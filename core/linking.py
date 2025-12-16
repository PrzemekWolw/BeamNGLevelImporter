# ##### BEGIN LICENSE BLOCK #####
#
# This program is licensed under The MIT License:
# see LICENSE for the full license text
#
# ##### END LICENSE BLOCK #####

from __future__ import annotations
import json
import hashlib
import os
from pathlib import Path
from typing import Optional

import bpy

from .level_scan import (
  last_file_index,
  find_file_first,
  find_file_candidates,
  FileEntry,
)

def _posix(s: str) -> str:
  return s.replace("\\", "/")

def _virt_norm(rel: str) -> str:
  s = _posix(rel).lstrip("/")
  while s.startswith("./"):
    s = s[2:]
  return s

def _virt_join(base_dir_virt: str, rel: str) -> str:
  base = _posix(base_dir_virt).strip("/")
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
  if entry.kind == "dir":
    return entry.abs_path if entry.abs_path and entry.abs_path.exists() else None
  if entry.kind == "zip":
    if not entry.provider.zip_path or not entry.zip_member:
      return None
    dest = _cache_path_for_zip_member(entry.provider.zip_path, entry.zip_member)
    if dest.exists() and dest.stat().st_size > 0:
      return dest
    # extract
    try:
      import zipfile, shutil
      with zipfile.ZipFile(entry.provider.zip_path, "r") as zf:
        with zf.open(entry.zip_member, "r") as src, open(dest, "wb") as out:
          shutil.copyfileobj(src, out)
      return dest if dest.exists() else None
    except Exception:
      return None
  return None

def _read_link_target_from_entry(entry: FileEntry) -> Optional[str]:
  """Read a .link file pointed to by entry and return the 'path' field."""
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

def resolve_virtual_with_links(virt_path: str, *, base_dir_virt: Optional[str] = None, max_depth: int = 8) -> Optional[FileEntry]:
  """
  Resolve a virtual path, following .link JSON indirections up to max_depth.
  virt_path and base_dir_virt are virtual paths (posix, no leading slash).
  Returns FileEntry or None.
  """
  idx = last_file_index()
  if not idx:
    return None

  # If base provided and virt is relative, anchor into base dir
  virt = _virt_norm(virt_path)
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

    # Absolute virtual?
    if target.startswith("/"):
      virt = _virt_norm(target)
      continue
    # Relative to link location
    # Base dir is directory of the link virtual path
    base_dir = _posix(link_entry.virtual_path).rsplit("/", 1)[0] if "/" in link_entry.virtual_path else ""
    virt = _virt_join(base_dir, target)

  return None
