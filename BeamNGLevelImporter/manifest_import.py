# ##### BEGIN LICENSE BLOCK #####
#
# This program is licensed under The MIT License:
# see LICENSE for the full license text
#
# ##### END LICENSE BLOCK #####

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable

import bpy

from .core.level_scan import (
  last_file_index,
  scan_file_index,
  remember_file_index,
  find_file_candidates,
)
from .core.linking import ensure_local_file
from .core.import_sources import scan_material_json_packs, scan_material_cs_packs

from .materials.v15 import build_pbr_v15_material
from .materials.v0 import build_pbr_v0_material


# ----------------------------
# General helpers
# ----------------------------

def _virt_norm(s: str) -> str:
  s = (s or "").replace("\\", "/").strip()
  s = s.lstrip("/")
  while s.startswith("./"):
    s = s[2:]
  while "//" in s:
    s = s.replace("//", "/")
  return s


def _ensure_collection(name: str) -> bpy.types.Collection:
  c = bpy.data.collections.get(name)
  if not c:
    c = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(c)
  return c


def _ensure_link_to_collection(obj: bpy.types.Object, coll: bpy.types.Collection):
  if not obj:
    return
  if coll in obj.users_collection:
    return
  try:
    coll.objects.link(obj)
  except Exception:
    pass
  try:
    sc = bpy.context.scene.collection
    if sc in obj.users_collection and sc != coll:
      sc.objects.unlink(obj)
  except Exception:
    pass


# ----------------------------
# Transforms
# ----------------------------

def _apply_pos_scale_only(obj: bpy.types.Object, pos: dict | None, scale: dict | None):
  if pos:
    obj.location = (float(pos["x"]), float(pos["y"]), float(pos["z"]))


def _make_empty(name: str) -> bpy.types.Object:
  empty = bpy.data.objects.new(name or "Vehicle", None)
  empty.empty_display_type = 'PLAIN_AXES'
  bpy.context.scene.collection.objects.link(empty)
  return empty


def _parent_all_to_empty(empty: bpy.types.Object, objs: list[bpy.types.Object]):
  for o in objs:
    if not o or o == empty:
      continue
    try:
      o.parent = empty
      o.matrix_parent_inverse = empty.matrix_world.inverted_safe()
    except Exception:
      pass


# ----------------------------
# GLB import
# This needs to be moved later to shape handling code. We will support glb for level objects too.
# ----------------------------

def _import_glb(glb_path: Path) -> list[bpy.types.Object]:
  before = set(bpy.data.objects)
  bpy.ops.import_scene.gltf(filepath=str(glb_path))
  after = set(bpy.data.objects)
  return [o for o in (after - before) if o is not None]


# ----------------------------
# Material remapping (GLB -> BeamNG-built)
# ----------------------------

_COPY_SUFFIX_RE = re.compile(r"\.\d{3}$", re.IGNORECASE)

def _strip_copy_suffix(name: str) -> str:
  return _COPY_SUFFIX_RE.sub("", name or "")

def _normalize_mat_key(name: str) -> str:
  n = (name or "").strip()
  n = _strip_copy_suffix(n)
  for pref in ("Material_", "Mat_", "material_", "mat_"):
    if n.startswith(pref):
      n = n[len(pref):]
  low = n.lower()
  for suf in ("-material", "_material", " material"):
    if low.endswith(suf):
      n = n[:len(n) - len(suf)]
      low = n.lower()
  return n.strip()

def _find_best_beamng_material(glb_mat_name: str) -> bpy.types.Material | None:
  if not glb_mat_name:
    return None
  mats = bpy.data.materials

  m = mats.get(glb_mat_name)
  if m:
    return m

  base = _normalize_mat_key(glb_mat_name)
  if not base:
    return None

  m = mats.get(base)
  if m:
    return m

  base_l = base.lower()
  for cand in mats:
    if cand.name.lower() == base_l:
      return cand

  return None

def remap_imported_glb_materials(imported_objs: list[bpy.types.Object]) -> int:
  replaced = 0
  for obj in imported_objs:
    if not obj or obj.type != 'MESH':
      continue
    me = obj.data
    if not me or not hasattr(me, "materials"):
      continue
    for i, mat in enumerate(list(me.materials)):
      if not mat:
        continue
      target = _find_best_beamng_material(mat.name)
      if target and target != mat:
        try:
          me.materials[i] = target
          replaced += 1
        except Exception:
          pass
  return replaced


# ----------------------------
# VFS / index
# ----------------------------

def ensure_vfs_index(props):
  if last_file_index():
    return
  game = Path(props.game_install).resolve() if getattr(props, "game_install", "") else None
  user = Path(props.user_folder).resolve() if getattr(props, "user_folder", "") else None
  if not game and not user:
    raise RuntimeError("VFS index missing and Game Install/User Folder not set.")
  idx = scan_file_index(game, user)
  remember_file_index(game, user, idx)


# ----------------------------
# Vehicle materials preload (index-based, jbeam -> vehicles/<jbeam>)
# ----------------------------

def _collect_material_pack_files_under(prefix: str) -> list[Path]:
  """
  From file index, extract all **/materials.json and **/*.materials.cs under prefix.
  Works for zips & dirs.
  """
  idx = last_file_index()
  if not idx:
    return []
  pref = _virt_norm(prefix).lower().rstrip("/") + "/"

  out: list[Path] = []
  for key_l, entries in idx.files.items():
    if not key_l.startswith(pref):
      continue
    if not (key_l.endswith("materials.json") or key_l.endswith(".materials.cs")):
      continue
    if not entries:
      continue
    local = ensure_local_file(entries[0])
    if local and Path(local).exists():
      out.append(Path(local))
  return out


def _guess_vehicle_root_from_entry(v: dict) -> str | None:
  """
  No vehicleDir is present. Use jbeam name:
    jbeam: "agent_traffic_jp2" -> "vehicles/agent_traffic_jp2"
  """
  jb = v.get("jbeam")
  if isinstance(jb, str) and jb.strip():
    name = jb.strip()
    # if user ever provides a path, try to extract vehicles/<name>
    if "/" in name or "\\" in name:
      s = _virt_norm(name)
      parts = s.split("/")
      for i in range(len(parts) - 1):
        if parts[i].lower() == "vehicles" and parts[i+1]:
          return f"vehicles/{parts[i+1]}"
      return s
    return f"vehicles/{name}"
  return None


def _build_materials_from_files(base_dir: Path, files: list[Path]) -> int:
  # Scan each directory once
  seen_dirs: set[Path] = set()
  packs_with_dirs: list[tuple[dict, Path]] = []

  for fp in files:
    d = fp.parent
    if d in seen_dirs:
      continue
    seen_dirs.add(d)
    packs_with_dirs.extend(scan_material_json_packs(d))
    packs_with_dirs.extend(scan_material_cs_packs(d))

  built = 0
  for pack, pack_dir in packs_with_dirs:
    if not isinstance(pack, dict):
      continue
    for _, v in pack.items():
      if not isinstance(v, dict):
        continue
      if v.get("class") != "Material" and not v.get("mapTo"):
        continue

      name = v.get('mapTo') if v.get('mapTo') not in (None, 'unmapped_mat') else v.get('name')
      if not name:
        continue
      if bpy.data.materials.get(name):
        continue

      try:
        if v.get('version') == 1.5:
          build_pbr_v15_material(name, v, base_dir, mat_dir=pack_dir)
        else:
          build_pbr_v0_material(name, v, base_dir, mat_dir=pack_dir)
        built += 1
      except Exception:
        pass

  return built


def preload_vehicle_materials_from_vfs(manifest: dict, base_dir: Path | None) -> int:
  files: list[Path] = []

  # vehicles/common always
  files.extend(_collect_material_pack_files_under("vehicles/common"))

  # per vehicle via jbeam name
  for v in (manifest.get("vehicles") or []):
    if not isinstance(v, dict):
      continue
    root = _guess_vehicle_root_from_entry(v)
    if root:
      files.extend(_collect_material_pack_files_under(root))

  base = base_dir or Path(bpy.app.tempdir or ".").resolve()
  return _build_materials_from_files(base, files)


# ----------------------------
# Level import (scanner-based, reliable)
# ----------------------------

def _level_name_from_manifest_level(level_virtual: str) -> str:
  s = (level_virtual or "").replace("\\", "/").strip()
  s = s.strip("/")
  if not s.lower().startswith("levels/"):
    raise RuntimeError(f"Manifest level is not /levels/<name>: {level_virtual}")
  parts = [p for p in s.split("/") if p]
  if len(parts) < 2 or not parts[1]:
    raise RuntimeError(f"Manifest level is not specific enough: {level_virtual}")
  return parts[1]


def _ensure_level_scanned_and_listed(props):
  """
  Ensure props.levels list is populated. If empty, run scan pipeline.
  """
  if props.levels and len(props.levels) > 0:
    return

  from .core.level_scan import (
    scan_levels, remember_scan,
    scan_assets, remember_assets,
    scan_file_index, remember_file_index,
  )
  from .ops_scan import _rebuild_level_list

  game = Path(props.game_install).resolve() if getattr(props, "game_install", "") else None
  user = Path(props.user_folder).resolve() if getattr(props, "user_folder", "") else None
  if not game and not user:
    raise RuntimeError("Cannot scan levels: Game Install/User Folder not set.")

  lvl_result = scan_levels(game, user)
  remember_scan(game, user, lvl_result)

  assets_idx = scan_assets(game, user)
  remember_assets(game, user, assets_idx)

  fidx = scan_file_index(game, user)
  remember_file_index(game, user, fidx)

  _rebuild_level_list(props)


def import_level_from_manifest_virtual(level_virtual: str, operator=None):
  """
  Import using the normal scanner/overlay pipeline:
  - detect level name
  - ensure scan ran
  - select it in props.levels_index
  - call pipeline.import_level
  """
  from .pipeline import import_level
  props = bpy.context.scene.BeamNGLevelImporter

  lvl_name = _level_name_from_manifest_level(level_virtual)
  _ensure_level_scanned_and_listed(props)

  idx = -1
  for i, it in enumerate(props.levels):
    if (it.name or "").lower() == lvl_name.lower():
      idx = i
      break
  if idx < 0:
    raise RuntimeError(
      f"Level '{lvl_name}' not found in scanned levels. Run Scan Data and ensure the level exists."
    )

  old = (props.use_scanner, props.levels_index, props.overlay_patches)
  try:
    props.use_scanner = True
    props.levels_index = idx
    import_level(bpy.context.scene, props, operator)
  finally:
    props.use_scanner, props.levels_index, props.overlay_patches = old


# ----------------------------
# Main manifest import
# ----------------------------

def import_manifest(manifest_path: Path, *, import_level_too: bool, operator=None):
  props = bpy.context.scene.BeamNGLevelImporter
  ensure_vfs_index(props)

  if not manifest_path.exists():
    raise RuntimeError(f"Manifest not found: {manifest_path}")

  with open(manifest_path, "r", encoding="utf-8") as f:
    manifest = json.load(f)

  vehicles = manifest.get("vehicles") or []
  if not isinstance(vehicles, list) or not vehicles:
    raise RuntimeError("Manifest has no vehicles[]")

  # Preload vehicle materials first (works without level dir)
  built = preload_vehicle_materials_from_vfs(manifest, base_dir=None)
  print(f"[Manifest] Built vehicle materials: {built}")

  export_dir = manifest_path.parent
  veh_coll = _ensure_collection("BeamNG_ExportedVehicles")

  # Import vehicles
  for v in vehicles:
    if not isinstance(v, dict):
      continue

    rel = v.get("file") or ""
    if not isinstance(rel, str) or not rel:
      continue

    glb_path = Path(rel)
    if not glb_path.is_absolute():
      glb_path = export_dir / glb_path

    if not glb_path.exists():
      print(f"[Manifest] Missing GLB: {glb_path}")
      continue

    imported = _import_glb(glb_path)
    if not imported:
      print(f"[Manifest] Import produced no objects: {glb_path}")
      continue

    veh_name = (v.get("name") or glb_path.stem or "Vehicle").strip()
    empty = _make_empty(veh_name)

    _parent_all_to_empty(empty, imported)

    _ensure_link_to_collection(empty, veh_coll)
    for child in imported:
      _ensure_link_to_collection(child, veh_coll)

    _apply_pos_scale_only(empty, v.get("position"), v.get("scale"))

    replaced = remap_imported_glb_materials(imported)
    if replaced:
      print(f"[Manifest] Remapped {replaced} material slot(s) for {veh_name}")

  # Import level after vehicles using normal pipeline
  if import_level_too:
    lvl = manifest.get("level")
    if isinstance(lvl, str) and lvl.strip():
      import_level_from_manifest_virtual(lvl, operator=operator)
    else:
      raise RuntimeError("Manifest has no 'level' string to import.")
