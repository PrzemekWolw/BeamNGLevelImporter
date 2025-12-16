# ##### BEGIN LICENSE BLOCK #####
#
# This program is licensed under The MIT License:
# see LICENSE for the full license text
#
# ##### END LICENSE BLOCK #####

import os
import zipfile
from pathlib import Path

# Import link resolver at module scope (avoids importlib KeyError on dynamic import)
from .linking import resolve_virtual_with_links, ensure_local_file


def resolve_case_insensitive_path(path):
  parts = os.path.normpath(str(path)).split(os.sep)
  if os.path.isabs(str(path)):
    current = os.sep
    parts = parts[1:]
  else:
    current = '.'
  for part in parts:
    try:
      entries = os.listdir(current)
      lookup = {e.lower(): e for e in entries}
    except (FileNotFoundError, NotADirectoryError):
      return None
    match = lookup.get(part.lower())
    if not match:
      return None
    current = os.path.join(current, match)
  return current

def exists_insensitive(p: Path) -> bool:
  if p.exists():
    return True
  real = resolve_case_insensitive_path(p)
  return bool(real and os.path.exists(real))

def get_real_case_path(p: Path) -> Path:
  if p.exists():
    return p
  real = resolve_case_insensitive_path(p)
  if real:
    return Path(real)
  return p

def extract_zip_level_root(zip_path: Path, tmp_dir: Path) -> Path | None:
  if not zip_path or not zip_path.exists():
    return None
  with zipfile.ZipFile(zip_path, 'r') as zf:
    info_json_rel = None
    for name in zf.namelist():
      p = Path(name)
      if p.name.lower() == 'info.json':
        info_json_rel = p
        break
    zf.extractall(tmp_dir)
    if info_json_rel:
      return (tmp_dir / info_json_rel.parent).resolve()
    roots = [p for p in tmp_dir.iterdir() if p.is_dir()]
    return roots[0] if roots else tmp_dir

def is_virtual_levels_path(s: str) -> bool:
  s_norm = s.replace('\\', '/').lstrip()
  return s_norm.lower().startswith('/levels/') or s_norm.lower().startswith('levels/')

def strip_levels_prefix(s: str) -> str:
  s_norm = s.replace('\\', '/').lstrip('/')
  if s_norm.lower().startswith('levels/'):
    s_norm = s_norm[7:]
  return s_norm

def resolve_beamng_path(rel: str, level_dir: Path | None, extra_roots: list[Path] | None = None) -> Path:
  if not rel:
    return level_dir if level_dir else Path('.')
  s = rel.replace('\\', '/')
  s_stripped = s.lstrip('/')
  if Path(s).is_absolute() and not s.lower().startswith('/levels/'):
    return Path(s)
  base_candidates: list[Path] = []
  if is_virtual_levels_path(s):
    if level_dir:
      base_candidates.append(level_dir.parent)
    if extra_roots:
      base_candidates.extend(extra_roots)
    suffix = strip_levels_prefix(s)
    for base in base_candidates:
      cand = (base / suffix)
      if exists_insensitive(cand):
        return get_real_case_path(cand)
    return (base_candidates[0] / suffix) if base_candidates else Path('/' + s_stripped)
  else:
    root = level_dir if level_dir else Path('.')
    cand = (root / s_stripped)
    if exists_insensitive(cand):
      return get_real_case_path(cand)
    alt = (root.parent / s_stripped)
    if exists_insensitive(alt):
      return get_real_case_path(alt)
    return cand


# Link-aware resolver using global file index + cache extraction
def resolve_any_beamng_path(rel: str, level_dir: Path | None) -> Path | None:
  """
  Resolve a path to a local filesystem file:
  - If a real file exists on disk (overlay), return it.
  - Otherwise, use the global file index and .link resolution to find the file
    across mods/game (zip or dir). Zip members are extracted to a temp cache.
  """
  if not rel:
    return None

  # Try the existing on-disk logic first (overlay or real)
  p = resolve_beamng_path(rel, level_dir, None)
  if exists_insensitive(p) and p.is_file():
    return get_real_case_path(p)

  # Build a virtual path; if rel is absolute virtual (/levels/.. or /art/..), use it as-is
  s = rel.replace("\\", "/")
  if s.startswith("/"):
    virt = s.lstrip("/")
    entry = resolve_virtual_with_links(virt, base_dir_virt=None)
  else:
    # Relative to current level virtual base: "levels/<levelname>/"
    base_virt = None
    try:
      if level_dir:
        lvl_name = level_dir.name
        base_virt = f"levels/{lvl_name}"
    except Exception:
      base_virt = None
    entry = resolve_virtual_with_links(s, base_dir_virt=base_virt)

  if not entry:
    return None
  return ensure_local_file(entry)


def try_resolve_image_path(rel: str, level_dir: Path | None) -> Path | None:
  """
  Try resolve with link support and common image suffixes (both directions).
  """
  # Attempt as-is
  p = resolve_any_beamng_path(rel, level_dir)
  if p and p.exists():
    return p
  # Try suffixes from base name (strip either .png, .dds, .jpg, etc.)
  if "." in rel:
    base = rel.rsplit(".", 1)[0]
  else:
    base = rel
  for ext in (".png", ".dds", ".jpg", ".jpeg", ".tga", ".bmp"):
    p2 = resolve_any_beamng_path(base + ext, level_dir)
    if p2 and p2.exists():
      return p2
  return None


# Model path resolver with extension fallbacks
def resolve_model_path(rel: str, level_dir: Path | None) -> tuple[Path | None, str | None]:
  """
  Resolve a model path with extension fallbacks and .link support.
  Returns (path, resolved_ext) or (None, None).
  Order tried:
    - exact rel
    - base.dae
    - base.cdae
    - base.dts
    - base.cached.dts
  """
  # Try exact
  p = resolve_any_beamng_path(rel, level_dir)
  if p and p.exists():
    rl = rel.lower()
    if rl.endswith(".cached.dts"):
      return p, ".cached.dts"
    return p, (Path(rel).suffix.lower() or None)

  # Build base without extension (handle .cached.dts)
  rl = rel
  rll = rl.lower()
  if rll.endswith(".cached.dts"):
    base = rl[:-12]
  elif "." in rl:
    base = rl.rsplit(".", 1)[0]
  else:
    base = rl

  exts = [".dae", ".cdae", ".dts", ".cached.dts"]
  for ext in exts:
    cand = base + ext
    p2 = resolve_any_beamng_path(cand, level_dir)
    if p2 and p2.exists():
      return p2, ext
  return None, None
