# ##### BEGIN LICENSE BLOCK #####
#
# This program is licensed under The MIT License:
# see LICENSE for the full license text
#
# ##### END LICENSE BLOCK #####

from __future__ import annotations
import json
import hashlib
import posixpath
from pathlib import Path
from typing import Optional, Iterable

import bpy

from .level_scan import (
  last_file_index,
  find_file_first,
  FileEntry,
)

def _posix(s: str) -> str:
  return (s or "").replace("\\", "/")

def _virt_norm(rel: str) -> str:
  # normalize, strip leading '/', collapse ./ and ../
  s = _posix(rel).strip().lstrip("/")
  s = posixpath.normpath(s)
  if s == ".":
    return ""
  # clamp any leading ../
  while s.startswith("../"):
    s = s[3:]
  return s

def _virt_join(base_dir_virt: str, rel: str) -> str:
  base = _virt_norm(base_dir_virt)
  reln = _virt_norm(rel)
  if not base:
    return reln
  if not reln:
    return base
  return f"{base.rstrip('/')}/{reln}"

def _safe_json_loads(text: str):
  try:
    return json.loads(text)
  except Exception:
    return None

def _read_link_target_from_bytes(data: bytes) -> Optional[str]:
  try:
    text = data.decode("utf-8", errors="ignore")
  except Exception:
    return None
  obj = _safe_json_loads(text)
  if not isinstance(obj, dict):
    return None
  p = obj.get("path")
  if not isinstance(p, str) or not p.strip():
    return None
  return p.strip()

def _read_link_target_from_file(path: Path) -> Optional[str]:
  try:
    with open(path, "rb") as f:
      return _read_link_target_from_bytes(f.read())
  except Exception:
    return None

def _read_link_target_from_entry(entry: FileEntry) -> Optional[str]:
  if entry.kind == "dir":
    if not entry.abs_path:
      return None
    return _read_link_target_from_file(entry.abs_path)
  if entry.kind == "zip":
    try:
      import zipfile
      with zipfile.ZipFile(entry.provider.zip_path, "r") as zf:
        with zf.open(entry.zip_member, "r") as fp:
          data = fp.read()
      return _read_link_target_from_bytes(data)
    except Exception:
      return None
  return None


def _cache_root() -> Path:
  base = Path(bpy.app.tempdir or ".").resolve()
  p = base / "beamng_cache"
  p.mkdir(parents=True, exist_ok=True)
  return p

def _hash_str(s: str) -> str:
  return hashlib.sha1(s.encode("utf-8", errors="ignore")).hexdigest()[:16]

def _cache_path_for_zip_member(zip_path: Path, member: str) -> Path:
  root = _cache_root()
  zhash = _hash_str(str(zip_path))
  dest = root / "zip" / zhash / _posix(member).lstrip("/")
  dest.parent.mkdir(parents=True, exist_ok=True)
  return dest

def ensure_local_file(entry: FileEntry) -> Optional[Path]:
  """
  Given a FileEntry (from file index), return a local filesystem path:
  - dir entry -> absolute local path
  - zip entry -> extracted into temp cache, return cached path
  """
  if not entry:
    return None
  if entry.kind == "dir":
    return entry.abs_path if entry.abs_path and entry.abs_path.exists() else None
  if entry.kind == "zip":
    if not entry.provider.zip_path or not entry.zip_member:
      return None
    dest = _cache_path_for_zip_member(entry.provider.zip_path, entry.zip_member)
    try:
      if dest.exists() and dest.stat().st_size > 0:
        return dest
    except Exception:
      pass

    try:
      import zipfile, shutil
      with zipfile.ZipFile(entry.provider.zip_path, "r") as zf:
        # ensure member exists; fall back case-insensitive
        member = entry.zip_member
        try:
          info = zf.getinfo(member)
        except KeyError:
          ml = _posix(member).lower()
          found = None
          for nm in zf.namelist():
            if _posix(nm).lower() == ml:
              found = nm
              break
          if not found:
            return None
          info = zf.getinfo(found)
          member = found
        with zf.open(info, "r") as src, open(dest, "wb") as out:
          shutil.copyfileobj(src, out)
      return dest if dest.exists() else None
    except Exception:
      return None
  return None

_TYPED_SUFFIXES = (".color", ".normal", ".data")
_IMAGE_EXTS = (".dds", ".png", ".jpg", ".jpeg", ".tga", ".bmp")

def _split_last_ext(p: str) -> tuple[str, str]:
  if "." in p:
    b, e = p.rsplit(".", 1)
    return b, "." + e.lower()
  return p, ""

def _strip_typed_suffix(base_no_ext: str) -> tuple[str, str | None]:
  low = base_no_ext.lower()
  for suf in _TYPED_SUFFIXES:
    if low.endswith(suf):
      return base_no_ext[:-len(suf)], suf
  return base_no_ext, None

def _target_candidates(target: str) -> list[str]:
  """
  Given a link target path, generate fallback targets.
  This handles your packed-install case:
    foo.color.png -> foo.color.dds and also foo.dds
  """
  t = _posix(target).strip()
  if not t:
    return []

  # normalize to virtual-ish (strip leading / only for normalization; we will re-add if needed)
  abs_virtual = t.startswith("/")
  t_no_slash = t.lstrip("/")
  base_no_ext, _ext = _split_last_ext(t_no_slash)
  stem_no_typed, typed = _strip_typed_suffix(base_no_ext)

  out = [t_no_slash]

  if typed:
    # foo.color.dds etc
    for ext in _IMAGE_EXTS:
      out.append(base_no_ext + ext)
    # foo.dds etc
    for ext in _IMAGE_EXTS:
      out.append(stem_no_typed + ext)
  else:
    # normal extension swap
    for ext in _IMAGE_EXTS:
      out.append(base_no_ext + ext)

  # de-dup
  seen = set()
  ded = []
  for c in out:
    k = c.lower()
    if k in seen:
      continue
    seen.add(k)
    ded.append(("/" + c) if abs_virtual else c)
  return ded

def resolve_virtual_with_links(
  virt_path: str,
  *,
  base_dir_virt: Optional[str] = None,
  max_depth: int = 16
) -> Optional[FileEntry]:
  """
  Resolve a virtual path, following .link JSON indirections up to max_depth.
  Adds fallback attempts for link targets (png->dds and BeamNG typed suffixes).
  """
  idx = last_file_index()
  if not idx:
    return None

  virt = _virt_norm(virt_path)

  # Anchor relative paths into base if caller provided a level base
  if base_dir_virt and not virt.startswith(("levels/", "art/", "assets/", "core/", "vehicles/")):
    virt = _virt_join(base_dir_virt, virt)

  tried = set()
  for _ in range(max_depth):
    key = virt.lower()
    if key in tried:
      break
    tried.add(key)

    # Try direct file
    entry = find_file_first(virt)
    if entry:
      return entry

    # Try .link
    link_entry = find_file_first(virt + ".link")
    if not link_entry:
      return None

    target = _read_link_target_from_entry(link_entry)
    if not target:
      return None

    target = _posix(target).strip()

    # Build absolute virtual candidate(s) from target
    # If target is relative, resolve relative to the .link file's folder.
    if not target.startswith("/"):
      base_dir = _posix(link_entry.virtual_path).rsplit("/", 1)[0] if "/" in link_entry.virtual_path else ""
      target = "/" + _virt_join(base_dir, target)

    # IMPORTANT: Try target *and* fallback targets before giving up.
    for cand in _target_candidates(target):
      cand_virt = _virt_norm(cand)
      e2 = find_file_first(cand_virt)
      if e2:
        return e2

      # also allow chained links (cand.link)
      le2 = find_file_first(cand_virt + ".link")
      if le2:
        # follow chain by setting virt and restarting outer loop
        virt = cand_virt
        break
    else:
      # none of the candidates existed
      return None

    # continue outer loop with virt updated (either to cand_virt for chained links, or unchanged)
    continue

  return None
