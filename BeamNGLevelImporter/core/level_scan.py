# ##### BEGIN LICENSE BLOCK #####
#
# This program is licensed under The MIT License:
# see LICENSE for the full license text
#
# ##### END LICENSE BLOCK #####

from __future__ import annotations

import os
import re
import shutil
import zipfile
import hashlib
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .sjson import decode_sjson_text

# Regex to find .../levels/<level>/info.json in any case
INFO_JSON_RE = re.compile(r'(^|.*/)levels/([^/]+)/info\.json$', re.IGNORECASE)

# Cache for last level scan
_LAST_SCAN: Dict[str, "LevelInfo"] = {}
_SCAN_KEY: Tuple[Optional[str], Optional[str]] = (None, None)

# Cache for last global assets scan
_LAST_ASSETS: Optional["AssetIndex"] = None
_ASSETS_KEY: Tuple[Optional[str], Optional[str]] = (None, None)

# Cache for last file index scan
_LAST_FILE_INDEX: Optional["FileIndex"] = None
_FILE_INDEX_KEY: Tuple[Optional[str], Optional[str]] = (None, None)

# Level ID mapping (ASCII-safe identifiers for Blender EnumProperty)
_LEVEL_TO_ID: dict[str, str] = {}
_ID_TO_LEVEL: dict[str, str] = {}


# --------------------------
# Data types
# --------------------------
@dataclass
class Provider:
  # Source category (priority order highest->lowest):
  # 'dir-unpacked', 'zip-unpacked', 'dir-game', 'zip-game'
  kind: str
  # Folder providers: base dir of the tree (resolved case)
  dir_root: Optional[Path] = None
  # Zip providers: zip file and member prefix (e.g. "levels/foo/", "art/", "assets/")
  zip_path: Optional[Path] = None
  inner_prefix: Optional[str] = None
  source_name: Optional[str] = None  # mod folder or zip filename


@dataclass
class LevelInfo:
  name: str
  title: str
  providers: List[Provider]


@dataclass
class AssetIndex:
  # providers in priority order: user unpacked -> user zips -> game unpacked -> game zips
  art: List[Provider]
  assets: List[Provider]


@dataclass
class FileEntry:
  # Virtual path (posix, relative, preserve original case found)
  virtual_path: str
  # Provider (where the file is located)
  provider: Provider
  # 'dir' or 'zip'
  kind: str
  # For dir: absolute path to file; For zip: zip member name (original case)
  abs_path: Optional[Path] = None
  zip_member: Optional[str] = None
  size: Optional[int] = None


@dataclass
class FileIndex:
  # map from lowercased virtual path -> list of FileEntry in priority order
  files: Dict[str, List[FileEntry]]
  # Optional: quick stat counters
  total_files: int = 0
  zip_count: int = 0
  dir_count: int = 0

def _decode_text_best(data: bytes) -> str:
  """
  Try common encodings (BOM-aware UTF-8 first, then UTF-8 strict, then Windows/Latin fallbacks).
  Returns a proper str; last resort returns UTF-8 with ignore.
  """
  for enc in ('utf-8-sig', 'utf-8', 'cp1250', 'cp1252', 'iso-8859-2', 'latin-1'):
    try:
      return data.decode(enc)
    except Exception:
      continue
  return data.decode('utf-8', errors='ignore')

def _normalize_title(s: str) -> str:
  try:
    return unicodedata.normalize('NFC', s).strip()
  except Exception:
    return (s or '').strip()


def _make_level_id(level_name: str) -> str:
  # short, ASCII, stable id
  h = hashlib.sha1(level_name.encode('utf-8', errors='ignore')).hexdigest()[:16]
  return f"lvl_{h}"

def _rebuild_level_id_maps(levels: dict[str, 'LevelInfo']):
  _LEVEL_TO_ID.clear()
  _ID_TO_LEVEL.clear()
  for lvl in levels.keys():
    lid = _make_level_id(lvl)
    if lid in _ID_TO_LEVEL and _ID_TO_LEVEL[lid] != lvl:
      for extra in range(1, 1000):
        lid2 = f"{lid}_{extra}"
        if lid2 not in _ID_TO_LEVEL:
          lid = lid2
          break
    _LEVEL_TO_ID[lvl] = lid
    _ID_TO_LEVEL[lid] = lvl

def level_id_for(name: str) -> str:
  return _LEVEL_TO_ID.get(name) or _make_level_id(name)

def level_name_from_id(id_str: str) -> str | None:
  return _ID_TO_LEVEL.get(id_str)


# --------------------------
# Case-insensitive FS helpers
# --------------------------
def _find_child_case_insensitive(root: Path, name: str) -> Optional[Path]:
  try:
    for entry in os.listdir(root):
      if entry.lower() == name.lower():
        return root / entry
  except Exception:
    pass
  return None


def _iterdir_dirs(root: Path) -> List[Path]:
  try:
    out = []
    for entry in os.listdir(root):
      p = root / entry
      if p.is_dir():
        out.append(p)
    return out
  except Exception:
    return []


def _posix(s: str) -> str:
  return s.replace("\\", "/")


def _virt_norm(rel: str) -> str:
  # Normalize to posix, strip leading slashes, minimal ./ cleanup
  s = _posix(rel).lstrip("/")
  while s.startswith("./"):
    s = s[2:]
  return s


# --------------------------
# Read info.json title
# --------------------------
def _read_info_title_from_dir(level_dir: Path) -> Optional[str]:
  p = _find_child_case_insensitive(level_dir, "info.json")
  if not p or not p.exists():
    return None
  try:
    with open(p, "rb") as f:
      text = _decode_text_best(f.read())
    data = decode_sjson_text(text)
    if isinstance(data, dict):
      raw = data.get("title") or data.get("name") or ""
      if isinstance(raw, str) and raw.strip():
        return _normalize_title(raw)
  except Exception:
    pass
  return None


def _read_info_title_from_zip(zf: zipfile.ZipFile, info_member: str) -> Optional[str]:
  try:
    with zf.open(info_member, "r") as fp:
      data_bytes = fp.read()
    text = _decode_text_best(data_bytes)
    data = decode_sjson_text(text)
    if isinstance(data, dict):
      raw = data.get("title") or data.get("name") or ""
      if isinstance(raw, str) and raw.strip():
        return _normalize_title(raw)
  except Exception:
    pass
  return None


# --------------------------
# Walk zips recursively (depth-limited)
# --------------------------
def _iter_zip_files(root: Path, max_depth: Optional[int]) -> List[Path]:
  """
  Return list of *.zip under root, recursively.
  If max_depth is not None, limit recursion depth (0 = root only).
  """
  out: List[Path] = []
  if not root or not root.exists():
    return out
  root = root.resolve()
  base_parts = len(root.parts)
  for cur, dirs, files in os.walk(root):
    cur_parts = len(Path(cur).parts)
    depth = cur_parts - base_parts
    # Collect zip files
    for fn in files:
      if fn.lower().endswith(".zip"):
        out.append(Path(cur) / fn)
    # Prune deeper traversal if limited
    if max_depth is not None and depth >= max_depth:
      dirs[:] = []
  return out


# --------------------------
# Level scanners (case-insensitive)
# --------------------------
def _scan_levels_in_dir(root: Path, source_kind: str, source_name: Optional[str]) -> Dict[str, Tuple[str, Provider]]:
  out: Dict[str, Tuple[str, Provider]] = {}
  levels_dir = _find_child_case_insensitive(root, "levels")
  if not levels_dir or not levels_dir.exists():
    return out
  for lvl_dir in _iterdir_dirs(levels_dir):
    title = _read_info_title_from_dir(lvl_dir) or lvl_dir.name
    lvl_name = lvl_dir.name
    prov = Provider(kind=source_kind, dir_root=lvl_dir, source_name=source_name)
    out[lvl_name] = (title, prov)
  return out


def _scan_levels_in_unpacked_mods(unpacked_root: Path) -> Dict[str, List[Tuple[str, Provider]]]:
  out: Dict[str, List[Tuple[str, Provider]]] = {}
  if not unpacked_root.exists():
    return out
  for mod_dir in _iterdir_dirs(unpacked_root):
    levels_dir = _find_child_case_insensitive(mod_dir, "levels")
    if not levels_dir:
      continue
    for lvl_dir in _iterdir_dirs(levels_dir):
      title = _read_info_title_from_dir(lvl_dir) or lvl_dir.name
      lvl_name = lvl_dir.name
      prov = Provider(kind="dir-unpacked", dir_root=lvl_dir, source_name=mod_dir.name)
      out.setdefault(lvl_name, []).append((title, prov))
  return out


def _scan_levels_in_zip(zip_path: Path, source_kind: str) -> Dict[str, Tuple[str, Provider]]:
  out: Dict[str, Tuple[str, Provider]] = {}
  try:
    with zipfile.ZipFile(zip_path, "r") as zf:
      info_candidates = []
      for name in zf.namelist():
        m = INFO_JSON_RE.match(_posix(name))
        if m:
          level_name = m.group(2)
          info_candidates.append((level_name, name))
      for level_name, info_member in info_candidates:
        title = _read_info_title_from_zip(zf, info_member) or level_name
        inner_prefix = f"levels/{level_name}/"
        prov = Provider(kind=source_kind, zip_path=zip_path, inner_prefix=inner_prefix, source_name=zip_path.name)
        out[level_name] = (title, prov)
  except Exception:
    pass
  return out


def _scan_levels_in_zip_tree(root: Path, source_kind: str, max_depth: Optional[int]) -> Dict[str, List[Tuple[str, Provider]]]:
  out: Dict[str, List[Tuple[str, Provider]]] = {}
  for z in _iter_zip_files(root, max_depth):
    zmap = _scan_levels_in_zip(z, source_kind)
    for lvl, (title, prov) in zmap.items():
      out.setdefault(lvl, []).append((title, prov))
  return out


def scan_levels(game_install: Optional[Path], user_folder: Optional[Path]) -> Dict[str, LevelInfo]:
  result: Dict[str, LevelInfo] = {}

  # 1) user unpacked mods
  user_unpacked = user_folder and (user_folder / "current" / "mods" / "unpacked")
  if user_unpacked:
    unpacked_found = _scan_levels_in_unpacked_mods(user_unpacked)
    for lvl, entries in unpacked_found.items():
      for title, prov in entries:
        info = result.get(lvl)
        if not info:
          info = LevelInfo(name=lvl, title=title, providers=[])
          result[lvl] = info
        info.providers.append(prov)
        if not info.title:
          info.title = title

  # 2) user zips (scan recursively under current/mods; unlimited depth)
  user_zips_dir = user_folder and (user_folder / "current" / "mods")
  if user_zips_dir:
    zips_found = _scan_levels_in_zip_tree(user_zips_dir, "zip-unpacked", max_depth=None)
    for lvl, entries in zips_found.items():
      for title, prov in entries:
        info = result.get(lvl)
        if not info:
          info = LevelInfo(name=lvl, title=title, providers=[])
          result[lvl] = info
        info.providers.append(prov)
        if not info.title:
          info.title = title

  # 3) game unpacked
  if game_install:
    dir_found = _scan_levels_in_dir(game_install, "dir-game", str(game_install))
    for lvl, (title, prov) in dir_found.items():
      info = result.get(lvl)
      if not info:
        info = LevelInfo(name=lvl, title=title, providers=[])
        result[lvl] = info
      info.providers.append(prov)
      if not info.title:
        info.title = title

  # 4) game zips (scan recursively up to 6 levels)
  if game_install:
    game_zips = _scan_levels_in_zip_tree(game_install, "zip-game", max_depth=6)
    for lvl, entries in game_zips.items():
      for title, prov in entries:
        info = result.get(lvl)
        if not info:
          info = LevelInfo(name=lvl, title=title, providers=[])
          result[lvl] = info
        info.providers.append(prov)
        if not info.title:
          info.title = title

  return result


def remember_scan(game_install: Optional[Path], user_folder: Optional[Path], result: Dict[str, LevelInfo]) -> None:
  global _LAST_SCAN, _SCAN_KEY
  _LAST_SCAN.clear()
  _LAST_SCAN.update(result)
  _SCAN_KEY = (str(game_install) if game_install else None, str(user_folder) if user_folder else None)
  _rebuild_level_id_maps(_LAST_SCAN)


def last_scan() -> Dict[str, LevelInfo]:
  return dict(_LAST_SCAN)


# --------------------------
# Asset scanning (art/ and assets/)
# --------------------------
def _dir_has_child(root: Path, child_names: List[str]) -> Dict[str, Path]:
  found: Dict[str, Path] = {}
  for want in child_names:
    p = _find_child_case_insensitive(root, want)
    if p and p.exists() and p.is_dir():
      found[want.lower()] = p
  return found


def _zip_has_root_prefix(zf: zipfile.ZipFile, root_name: str) -> bool:
  root_l = f"{root_name.strip('/').lower()}/"
  for name in zf.namelist():
    n = _posix(name).lstrip("/")
    if n.lower().startswith(root_l):
      parts = n.split("/")
      if len(parts) >= 2 and parts[0].lower() == root_name.lower():
        return True
  return False


def _scan_assets_in_unpacked_mods(unpacked_root: Path) -> Tuple[List[Provider], List[Provider]]:
  arts: List[Provider] = []
  assets: List[Provider] = []
  if not unpacked_root.exists():
    return arts, assets
  for mod_dir in _iterdir_dirs(unpacked_root):
    kids = _dir_has_child(mod_dir, ["art", "assets"])
    if "art" in kids:
      arts.append(Provider(kind="dir-unpacked", dir_root=kids["art"], source_name=mod_dir.name))
    if "assets" in kids:
      assets.append(Provider(kind="dir-unpacked", dir_root=kids["assets"], source_name=mod_dir.name))
  return arts, assets


def _scan_assets_in_zip_tree(root: Path, source_kind: str, max_depth: Optional[int]) -> Tuple[List[Provider], List[Provider]]:
  arts: List[Provider] = []
  assets: List[Provider] = []
  for z in _iter_zip_files(root, max_depth):
    try:
      with zipfile.ZipFile(z, "r") as zf:
        if _zip_has_root_prefix(zf, "art"):
          arts.append(Provider(kind=source_kind, zip_path=z, inner_prefix="art/", source_name=z.name))
        if _zip_has_root_prefix(zf, "assets"):
          assets.append(Provider(kind=source_kind, zip_path=z, inner_prefix="assets/", source_name=z.name))
    except Exception:
      continue
  return arts, assets


def _scan_assets_in_game_dir(game_install: Path, source_kind: str) -> Tuple[List[Provider], List[Provider]]:
  arts: List[Provider] = []
  assets: List[Provider] = []
  if not game_install or not game_install.exists():
    return arts, assets
  kids = _dir_has_child(game_install, ["art", "assets"])
  if "art" in kids:
    arts.append(Provider(kind=source_kind, dir_root=kids["art"], source_name=str(game_install)))
  if "assets" in kids:
    assets.append(Provider(kind=source_kind, dir_root=kids["assets"], source_name=str(game_install)))
  return arts, assets


def scan_assets(game_install: Optional[Path], user_folder: Optional[Path]) -> AssetIndex:
  art_prov: List[Provider] = []
  assets_prov: List[Provider] = []

  # 1) user unpacked mods (direct subfolders in 'unpacked')
  user_unpacked = user_folder and (user_folder / "current" / "mods" / "unpacked")
  if user_unpacked:
    a1, s1 = _scan_assets_in_unpacked_mods(user_unpacked)
    art_prov.extend(a1)
    assets_prov.extend(s1)

  # 2) user zip mods (scan recursively under current/mods; unlimited depth)
  user_zips = user_folder and (user_folder / "current" / "mods")
  if user_zips:
    a2, s2 = _scan_assets_in_zip_tree(user_zips, "zip-unpacked", max_depth=None)
    art_prov.extend(a2)
    assets_prov.extend(s2)

  # 3) game unpacked
  if game_install:
    a3, s3 = _scan_assets_in_game_dir(game_install, "dir-game")
    art_prov.extend(a3)
    assets_prov.extend(s3)

  # 4) game zips (scan recursively up to 6 levels)
  if game_install:
    a4, s4 = _scan_assets_in_zip_tree(game_install, "zip-game", max_depth=6)
    art_prov.extend(a4)
    assets_prov.extend(s4)

  return AssetIndex(art=art_prov, assets=assets_prov)


def remember_assets(game_install: Optional[Path], user_folder: Optional[Path], assets: AssetIndex) -> None:
  global _LAST_ASSETS, _ASSETS_KEY
  _LAST_ASSETS = assets
  _ASSETS_KEY = (str(game_install) if game_install else None, str(user_folder) if user_folder else None)


def last_assets() -> Optional[AssetIndex]:
  return _LAST_ASSETS


# --------------------------
# Overlay builders (levels and assets)
# --------------------------
def _ensure_dirs_case(dst_root: Path, rel_dir_posix: str, dir_map: Dict[str, Path]) -> Path:
  """
  Ensure destination subdir exists using case-insensitive canonicalization.
  If a conflicting file exists where a directory is needed, remove it and create the directory.
  """
  if not rel_dir_posix or rel_dir_posix == ".":
    return dst_root
  parts = [p for p in rel_dir_posix.split("/") if p]
  acc = ""
  cur = dst_root
  for part in parts:
    acc = f"{acc}/{part.lower()}" if acc else part.lower()
    if acc in dir_map and dir_map[acc].exists():
      # If it exists but is a file, replace with directory
      if dir_map[acc].is_file():
        try:
          dir_map[acc].unlink()
        except Exception:
          pass
        try:
          dir_map[acc].mkdir(parents=False, exist_ok=True)
        except Exception:
          pass
      cur = dir_map[acc]
      continue
    found = _find_child_case_insensitive(cur, part)
    if found:
      if found.is_file():
        # replace file with directory
        try:
          found.unlink()
        except Exception:
          pass
        found = cur / part
        try:
          found.mkdir(parents=False, exist_ok=True)
        except Exception:
          pass
    else:
      found = cur / part
      try:
        found.mkdir(parents=False, exist_ok=True)
      except Exception:
        pass
    dir_map[acc] = found
    cur = found
  return cur


def _dest_path_for_file(dst_root: Path, rel_posix: str, dir_map: Dict[str, Path], file_map: Dict[str, Path]) -> Path:
  rel_posix = rel_posix.lstrip("/")
  dir_part, _, base_name = rel_posix.rpartition("/")
  dir_path = _ensure_dirs_case(dst_root, dir_part, dir_map)
  key = rel_posix.lower()
  if key in file_map and file_map[key].exists():
    return file_map[key]
  try:
    for entry in os.listdir(dir_path):
      if entry.lower() == base_name.lower():
        p = dir_path / entry
        file_map[key] = p
        return p
  except Exception:
    pass
  p = dir_path / base_name
  file_map[key] = p
  return p


def _copy_dir_case_insensitive(src_dir: Path, dst_root: Path, dir_map: Dict[str, Path], file_map: Dict[str, Path]):
  for root, _, files in os.walk(src_dir):
    rel = os.path.relpath(root, src_dir).replace("\\", "/")
    if rel == ".":
      rel = ""
    _ensure_dirs_case(dst_root, rel, dir_map)
    for fn in files:
      rel_file = f"{rel}/{fn}" if rel else fn
      dst_file = _dest_path_for_file(dst_root, rel_file, dir_map, file_map)
      try:
        dst_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(Path(root) / fn, dst_file)
      except Exception:
        pass


def _split_path_posix(s: str) -> List[str]:
  return [p for p in s.replace("\\", "/").split("/") if p]


def _rel_after_prefix_case_insensitive(full_path: str, prefix_lower: str) -> Optional[str]:
  fparts = _split_path_posix(full_path)
  pparts = [p for p in prefix_lower.split("/") if p]
  if len(pparts) > len(fparts):
    return None
  i = 0
  while i < len(pparts):
    if fparts[i].lower() != pparts[i]:
      return None
    i += 1
  return "/".join(fparts[i:])


def _copy_zip_prefix_case_insensitive(zip_path: Path, inner_prefix: str, dst_root: Path, dir_map: Dict[str, Path], file_map: Dict[str, Path]):
  """
  Copy all members under inner_prefix (case-insensitive) from a zip into dst_root,
  creating directories and files case-insensitively. Properly handles directory
  entries even if the zip uses no trailing slash.
  """
  pref_l = inner_prefix.replace("\\", "/").lower().lstrip("/")
  try:
    with zipfile.ZipFile(zip_path, "r") as zf:
      for info in zf.infolist():
        name = info.filename  # original case as stored in zip
        rel = _rel_after_prefix_case_insensitive(_posix(name), pref_l)
        if rel is None:
          continue
        # Directory entry?
        if getattr(info, "is_dir", None) and info.is_dir():
          _ensure_dirs_case(dst_root, rel, dir_map)
          continue
        # Some zips represent dirs as entries without trailing slash; detect by zero size and children
        if rel == "" or rel.endswith("/"):
          _ensure_dirs_case(dst_root, rel, dir_map)
          continue
        # Regular file
        dst_file = _dest_path_for_file(dst_root, rel, dir_map, file_map)
        try:
          dst_file.parent.mkdir(parents=True, exist_ok=True)
          with zf.open(info, "r") as src, open(dst_file, "wb") as out:
            shutil.copyfileobj(src, out)
        except Exception:
          pass
  except Exception:
    pass


def build_overlay_for_level(level_name: str, overlay_root: Path, providers: List[Provider]) -> Path:
  dir_map: Dict[str, Path] = {}
  file_map: Dict[str, Path] = {}

  levels_dir = _ensure_dirs_case(overlay_root, "levels", dir_map)
  target_level_dir = _ensure_dirs_case(levels_dir, level_name, dir_map)

  for prov in providers:
    if prov.dir_root:
      _copy_dir_case_insensitive(prov.dir_root, target_level_dir, dir_map, file_map)
    elif prov.zip_path and prov.inner_prefix:
      _copy_zip_prefix_case_insensitive(prov.zip_path, prov.inner_prefix, target_level_dir, dir_map, file_map)

  return target_level_dir


def build_overlay_for_assets(overlay_root: Path, assets: AssetIndex) -> Tuple[Optional[Path], Optional[Path]]:
  art_dir: Optional[Path] = None
  assets_dir: Optional[Path] = None

  if assets.art:
    dir_map_a: Dict[str, Path] = {}
    file_map_a: Dict[str, Path] = {}
    art_dir = _ensure_dirs_case(overlay_root, "art", dir_map_a)
    for prov in assets.art:
      if prov.dir_root:
        _copy_dir_case_insensitive(prov.dir_root, art_dir, dir_map_a, file_map_a)
      elif prov.zip_path and prov.inner_prefix:
        _copy_zip_prefix_case_insensitive(prov.zip_path, prov.inner_prefix, art_dir, dir_map_a, file_map_a)

  if assets.assets:
    dir_map_s: Dict[str, Path] = {}
    file_map_s: Dict[str, Path] = {}
    assets_dir = _ensure_dirs_case(overlay_root, "assets", dir_map_s)
    for prov in assets.assets:
      if prov.dir_root:
        _copy_dir_case_insensitive(prov.dir_root, assets_dir, dir_map_s, file_map_s)
      elif prov.zip_path and prov.inner_prefix:
        _copy_zip_prefix_case_insensitive(prov.zip_path, prov.inner_prefix, assets_dir, dir_map_s, file_map_s)

  return art_dir, assets_dir


# --------------------------
# Full-file index (all files) with deep zip search
# --------------------------
def _add_index_entry(idx: FileIndex, entry: FileEntry):
  key = entry.virtual_path.lower()
  arr = idx.files.get(key)
  if arr is None:
    idx.files[key] = [entry]
    idx.total_files += 1
    if entry.kind == 'zip': idx.zip_count += 1
    else: idx.dir_count += 1
    return
  # Avoid duplicate from exact same provider+member/path
  if entry.kind == 'zip':
    same = any(e.kind == 'zip' and e.provider.zip_path == entry.provider.zip_path and (e.zip_member or "").lower() == (entry.zip_member or "").lower() for e in arr)
  else:
    same = any(e.kind == 'dir' and (e.abs_path or "") == (entry.abs_path or "") for e in arr)
  if not same:
    arr.append(entry)
    idx.total_files += 1
    if entry.kind == 'zip': idx.zip_count += 1
    else: idx.dir_count += 1


def _walk_dir_index(idx: FileIndex, base: Path, provider: Provider):
  base = base.resolve()
  try:
    for root, _, files in os.walk(base):
      for fn in files:
        full = Path(root) / fn
        rel = os.path.relpath(full, base)
        virt = _virt_norm(rel)
        _add_index_entry(idx, FileEntry(
          virtual_path=virt,
          provider=provider,
          kind='dir',
          abs_path=full,
          zip_member=None,
          size=None
        ))
  except Exception:
    pass


def _index_zip(idx: FileIndex, zip_path: Path, provider: Provider):
  try:
    with zipfile.ZipFile(zip_path, "r") as zf:
      for info in zf.infolist():
        n = _posix(info.filename)
        if getattr(info, "is_dir", None) and info.is_dir():
          continue
        if n.endswith("/"):
          continue
        virt = _virt_norm(n)  # keep full path inside zip as virtual path
        _add_index_entry(idx, FileEntry(
          virtual_path=virt,
          provider=provider,
          kind='zip',
          abs_path=None,
          zip_member=info.filename,
          size=getattr(info, 'file_size', None)
        ))
  except Exception:
    pass


def _scan_zip_tree_for_index(idx: FileIndex, where: Path, source_kind: str, max_depth: Optional[int]):
  if not where or not where.exists():
    return
  for z in _iter_zip_files(where, max_depth):
    prov = Provider(kind=source_kind, zip_path=z, inner_prefix=None, source_name=z.name)
    _index_zip(idx, z, prov)


def scan_file_index(game_install: Optional[Path], user_folder: Optional[Path]) -> FileIndex:
  """
  Build a global, case-insensitive index of every file in:
  - user/current/mods/unpacked/* (all files)
  - user/current/mods/** (all *.zip at any depth)
  - game_install (all files)
  - game_install/** (all *.zip up to 6 directories deep)
  Priority in returned candidate lists: user unpacked, user zips, game dir, game zips.
  """
  idx = FileIndex(files={})

  # 1) user unpacked (direct children of 'unpacked')
  unpacked = user_folder and (user_folder / "current" / "mods" / "unpacked")
  if unpacked and unpacked.exists():
    for mod_dir in _iterdir_dirs(unpacked):
      prov = Provider(kind="dir-unpacked", dir_root=mod_dir, source_name=mod_dir.name)
      _walk_dir_index(idx, mod_dir, prov)

  # 2) user zips (scan recursively under current/mods; unlimited depth)
  user_mods = user_folder and (user_folder / "current" / "mods")
  if user_mods and user_mods.exists():
    _scan_zip_tree_for_index(idx, user_mods, "zip-unpacked", max_depth=None)

  # 3) game install dir
  if game_install and game_install.exists():
    prov = Provider(kind="dir-game", dir_root=game_install, source_name=str(game_install))
    _walk_dir_index(idx, game_install, prov)

  # 4) game zips (scan recursively up to 6 levels)
  if game_install and game_install.exists():
    _scan_zip_tree_for_index(idx, game_install, "zip-game", max_depth=6)

  return idx


def remember_file_index(game_install: Optional[Path], user_folder: Optional[Path], index: FileIndex) -> None:
  global _LAST_FILE_INDEX, _FILE_INDEX_KEY
  _LAST_FILE_INDEX = index
  _FILE_INDEX_KEY = (str(game_install) if game_install else None, str(user_folder) if user_folder else None)


def last_file_index() -> Optional[FileIndex]:
  return _LAST_FILE_INDEX


def find_file_candidates(virtual_path: str) -> List[FileEntry]:
  """
  Return all candidates for a virtual path (case-insensitive), in priority order.
  virtual_path example: 'art/textures/foo.dds', 'levels/mylevel/main/mis.json', ...
  """
  idx = _LAST_FILE_INDEX
  if not idx:
    return []
  key = _virt_norm(virtual_path).lower()
  return list(idx.files.get(key, []))


def find_file_first(virtual_path: str) -> Optional[FileEntry]:
  """Return best-match FileEntry for virtual_path (highest priority) or None."""
  c = find_file_candidates(virtual_path)
  return c[0] if c else None
