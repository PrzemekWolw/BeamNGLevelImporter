# ##### BEGIN LICENSE BLOCK #####
#
# This program is licensed under The MIT License:
# see LICENSE for the full license text
#
# ##### END LICENSE BLOCK #####

import os
import zipfile
from pathlib import Path

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
      if p.name == 'info.json':
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

def try_resolve_image_path(rel: str, level_dir: Path | None) -> Path | None:
  p = resolve_beamng_path(rel, level_dir)
  if exists_insensitive(p):
    return get_real_case_path(p)
  for alt in (p.with_suffix('.png'), p.with_suffix('.dds')):
    if exists_insensitive(alt):
      return get_real_case_path(alt)
  return None
