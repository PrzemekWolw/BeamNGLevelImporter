# ##### BEGIN LICENSE BLOCK #####
#
# This program is licensed under The MIT License:
# see LICENSE for the full license text
#
# ##### END LICENSE BLOCK #####

from __future__ import annotations
import bpy
import os
from pathlib import Path

from .core.types import ImportConfig, ImportContext
from .core.progress import ProgressHelper, force_redraw
from .core.paths import extract_zip_level_root, resolve_beamng_path, resolve_any_beamng_path
from .core.import_sources import (
  load_main_records, load_forest_records, load_decal_sets, load_terrain_meta,
  scan_material_json_packs, scan_material_cs_packs, load_forest_item_db,
  scan_material_packs_in_zip,
)
from .core.normalize import normalize_records, normalize_forest
from .materials.common import ensure_uv_layers_named
from .materials.v15 import build_pbr_v15_material
from .materials.v0 import build_pbr_v0_material
from .materials.terrain_v15 import build_terrain_material_v15
from .materials.terrain_v0 import build_terrain_material_v0
from .shapes.collada import import_collada_shapes
from .objects.mission import build_mission_objects
from .objects.forest import build_forest_objects
from .objects.decals import build_decal_objects
from .utils.bpy_helpers import ensure_collection, delete_object_if_exists, dedupe_materials
from .core import ts_parser
from .core.sjson import read_json_records
from .core.level_scan import last_scan, build_overlay_for_level, last_assets

def _info(op, msg):
  if op: op.report({'INFO'}, msg)
  print(msg)

def import_level(scene, props, operator=None):
  def info(msg): _info(operator, msg)
  temp_path = Path(bpy.app.tempdir or ".").resolve()
  level_path: Path | None = None

  # Preferred: scanner/overlay
  if getattr(props, "use_scanner", False):
    selected_name = None
    if getattr(props, "levels", None) and 0 <= props.levels_index < len(props.levels):
      selected_name = props.levels[props.levels_index].name
    elif getattr(props, "selected_level", ""):
      selected_name = props.selected_level

    if selected_name:
      scan_data = last_scan()
      lvl_info = scan_data.get(selected_name)
      if not lvl_info:
        raise RuntimeError("Selected level is not available. Please run Scan Levels again.")

      overlay_root = (temp_path / f"beamng_level_overlay_{selected_name}").resolve()
      try:
        import shutil
        if overlay_root.exists():
          shutil.rmtree(overlay_root)
      except Exception:
        pass

      providers = list(lvl_info.providers or [])
      if not getattr(props, "overlay_patches", True) and providers:
        providers = [providers[0]]

      level_dir = build_overlay_for_level(lvl_info.name, overlay_root, providers)
      level_path = level_dir
      props.levelpath = str(level_dir)

  if not level_path:
    # Manual/zip fallback
    level_path = Path(props.levelpath).resolve() if props.levelpath else None
    if getattr(props, "enable_zip", False) and getattr(props, "zippath", ""):
      root = extract_zip_level_root(Path(props.zippath), temp_path)
      if not root or not root.exists():
        raise RuntimeError("Failed to extract level from zip")
      level_path = root
      props.levelpath = str(root)

  if not level_path or not level_path.exists():
    raise RuntimeError("Level path not set or not found")

  level_data  = load_main_records(level_path)
  forest_data = load_forest_records(level_path)
  terrain_meta = load_terrain_meta(level_path)
  materials_packs = scan_material_json_packs(level_path) + scan_material_cs_packs(level_path)
  forest_items = load_forest_item_db(level_path)
  forest_names = {}
  shapes = []
  terrain_mats = []
  decals_defs, decal_instances = load_decal_sets(level_path)

  def _offset_nodes(nodes, dpos):
    if not isinstance(nodes, list):
      return nodes
    out = []
    for n in nodes:
      if isinstance(n, dict):
        nn = dict(n)
        p = nn.get('point') or nn.get('position') or nn.get('pos')
        if isinstance(p, (list, tuple)) and len(p) == 3:
          nn['point'] = [p[0] + dpos[0], p[1] + dpos[1], p[2] + dpos[2]]
        out.append(nn)
      else:
        out.append(n)
    return out

  prefabs_expanded = []
  prefab_roots = []
  to_remove = []
  for rec in list(level_data):
    if not isinstance(rec, dict) or rec.get('class') != 'Prefab':
      continue
    prefab_fn = rec.get('filename')
    if not prefab_fn:
      continue
    prefab_real = resolve_any_beamng_path(prefab_fn, level_path) or resolve_beamng_path(prefab_fn, level_path)
    if not prefab_real or not Path(prefab_real).exists():
      info(f"Prefab file not found: {prefab_fn} -> {prefab_real}")
      continue
    prefab_path = Path(prefab_real)

    prefab_name = rec.get('name') or rec.get('internalName') or prefab_path.stem
    prefab_parent = rec.get('__parent') or 'MissionGroup'
    prefab_pos = rec.get('position') or [0, 0, 0]
    if not isinstance(prefab_pos, (list, tuple)) or len(prefab_pos) != 3:
      prefab_pos = [0, 0, 0]
    prefab_roots.append({'class': 'SimGroup', 'name': prefab_name, '__parent': prefab_parent})
    prefab_records = []
    try:
      prefab_records = read_json_records(prefab_path)
    except Exception:
      prefab_records = []
    if not prefab_records:
      try:
        txt = prefab_path.read_text(encoding='utf-8', errors='ignore')
        prefab_records = ts_parser.parse_torque_file(txt)
      except Exception:
        prefab_records = []
    group_name_map = {}
    for r in prefab_records:
      if isinstance(r, dict) and r.get('class') == 'SimGroup':
        old = r.get('name') or 'Group'
        group_name_map[old] = f"{prefab_name}_{old}"
    for r in prefab_records:
      if not isinstance(r, dict):
        continue
      r2 = dict(r)
      cls = r2.get('class')
      pos = r2.get('position')
      if isinstance(pos, (list, tuple)) and len(pos) == 3:
        r2['position'] = [pos[0] + prefab_pos[0], pos[1] + prefab_pos[1], pos[2] + prefab_pos[2]]
      if 'nodes' in r2:
        r2['nodes'] = _offset_nodes(r2.get('nodes'), prefab_pos)
      parent = r2.get('__parent')
      if cls == 'SimGroup':
        oldname = r2.get('name') or 'Group'
        r2['name'] = group_name_map.get(oldname, f"{prefab_name}_{oldname}")
        r2['__parent'] = group_name_map.get(parent, prefab_name)
      else:
        r2['__parent'] = group_name_map.get(parent, prefab_name)
      prefabs_expanded.append(r2)
    to_remove.append(rec)
  if prefabs_expanded or prefab_roots:
    level_data.extend(prefab_roots)
    level_data.extend(prefabs_expanded)
    for r in to_remove:
      try:
        level_data.remove(r)
      except ValueError:
        pass

  # Normalize
  normalize_records(level_data)
  normalize_forest(forest_data)

  # Ensure collections for SimGroups
  for i in level_data:
    if i.get('class') == 'SimGroup':
      ensure_collection(i.get('name') or 'SimGroup')

  # Collect shape files to import
  for i in level_data:
    if i.get('class') == 'TSStatic':
      shape = i.get('shapeName')
      if shape and shape not in shapes:
        shapes.append(shape)

  for key, item in (forest_items or {}).items():
    shape = (item or {}).get('shapeFile')
    name = (item or {}).get('name') or (item or {}).get('internalName')
    if shape and shape not in shapes:
      shapes.append(shape)
    if name:
      forest_names[name] = os.path.split(shape)[1] if shape else name

  cfg = ImportConfig(
    level_path=level_path,
    enable_zip=bool(getattr(props, "enable_zip", False)),
    zip_path=Path(props.zippath) if getattr(props, "zippath", "") else None
  )

  ctx = ImportContext(
    config=cfg,
    progress=ProgressHelper(),
    level_data=level_data,
    forest_data=forest_data,
    terrain_meta=terrain_meta,
    materials_packs=materials_packs,
    forest_items=forest_items,
    forest_names=forest_names,
    shapes=shapes,
    terrain_mats=terrain_mats,
    decal_defs=decals_defs,
    decal_instances=decal_instances
  )

  # Terrain material mode and world size
  texture_sets = {}
  for pack in ctx.materials_packs:
    if isinstance(pack, dict):
      for k, v in pack.items():
        if isinstance(v, dict) and v.get('class') == 'TerrainMaterialTextureSet':
          ts_name = v.get('name') or k
          if ts_name:
            texture_sets[ts_name] = v

  terrain_texset_name = None
  for rec in ctx.level_data:
    if rec.get('class') == 'TerrainBlock':
      ts = rec.get('materialTextureSet')
      if ts and ts in texture_sets:
        terrain_texset_name = ts
        break

  use_v15_terrain = bool(terrain_texset_name)

  terrain_world_size = None
  try:
    tb = next(rec for rec in ctx.level_data if rec.get('class') == 'TerrainBlock')
    sq = float(tb.get('squareSize') or 1.0)
    ter_meta = next((m for m in ctx.terrain_meta if isinstance(m, dict) and 'size' in m), None)
    ter_size = int(ter_meta.get('size')) if ter_meta else None
    if ter_size and ter_size > 1:
      terrain_world_size = (ter_size - 1) * sq
  except Exception:
    terrain_world_size = None

  materials_count = sum(len(p) for p in ctx.materials_packs if isinstance(p, dict))
  total_steps = max(1, len(shapes)) + max(1, len(level_data)) + max(1, len(forest_data)) + max(1, materials_count) + 10

  try:
    ctx.progress.begin(total_steps, "BeamNG: preparing import...")

    for pack in ctx.materials_packs:
      if not isinstance(pack, dict):
        continue
      for _, v in pack.items():
        if not isinstance(v, dict):
          continue
        if v.get('class') == "TerrainMaterial":
          if use_v15_terrain:
            build_terrain_material_v15(ctx.config.level_path, v, ctx.terrain_mats, terrain_world_size=terrain_world_size)
          else:
            build_terrain_material_v0(ctx.config.level_path, v, ctx.terrain_mats, terrain_world_size=terrain_world_size)
        elif v.get('mapTo') and v.get('version') == 1.5:
          name = v['mapTo'] if v['mapTo'] != 'unmapped_mat' else v.get('name')
          build_pbr_v15_material(name, v, ctx.config.level_path)
        elif v.get('mapTo') and (v.get('version') == 0 or not v.get('version')):
          name = v['mapTo'] if v['mapTo'] != 'unmapped_mat' else v.get('name')
          build_pbr_v0_material(name, v, ctx.config.level_path)
        ctx.progress.update(step=1)

    # 2) Extra materials from all /art providers (skip existing)
    assets_idx = last_assets()
    if assets_idx and assets_idx.art:
      extra_packs: list[dict] = []
      # Gather packs
      for prov in assets_idx.art:
        if prov.dir_root and prov.dir_root.exists():
          extra_packs.extend(scan_material_json_packs(prov.dir_root))
          extra_packs.extend(scan_material_cs_packs(prov.dir_root))
        elif prov.zip_path and prov.zip_path.exists():
          extra_packs.extend(scan_material_packs_in_zip(prov.zip_path))
      # Build only missing materials
      for pack in extra_packs:
        if not isinstance(pack, dict):
          continue
        for _, v in pack.items():
          if not isinstance(v, dict):
            continue
          cls = v.get('class')
          if cls == "TerrainMaterial":
            nm = v.get('internalName') or v.get('name')
            if nm and bpy.data.materials.get(nm):
              continue
            if use_v15_terrain:
              build_terrain_material_v15(ctx.config.level_path, v, ctx.terrain_mats, terrain_world_size=terrain_world_size)
            else:
              build_terrain_material_v0(ctx.config.level_path, v, ctx.terrain_mats, terrain_world_size=terrain_world_size)
          elif cls == "Material" or (v.get('mapTo') and (v.get('version') in (None, 0, 1.5))):
            name = v.get('mapTo') if v.get('mapTo') not in (None, 'unmapped_mat') else v.get('name')
            if not name:
              continue
            if bpy.data.materials.get(name):
              continue
            if v.get('version') == 1.5:
              build_pbr_v15_material(name, v, ctx.config.level_path)
            else:
              build_pbr_v0_material(name, v, ctx.config.level_path)
        ctx.progress.update(step=1)

    # Shapes
    import_collada_shapes(ctx)
    for obj in bpy.data.objects:
      if obj.type == 'MESH' and obj.data:
        ensure_uv_layers_named(obj.data, "UVMap", "UVMap2")
    for d in ("Cube", "Light", "Lamp", "Camera"):
      delete_object_if_exists(d)
    dedupe_materials()

    for i in ctx.level_data:
      if i.get('class') == 'SimGroup':
        name = i.get('name'); parent = i.get('__parent')
        if name and parent:
          c = bpy.data.collections.get(name); p = bpy.data.collections.get(parent)
          if c and p and c.name not in [ch.name for ch in p.children]:
            p.children.link(c)

    build_mission_objects(ctx)
    build_forest_objects(ctx)

    build_decal_objects(ctx)

    force_redraw()
    info("BeamNG Import finished")
  finally:
    ctx.progress.end()