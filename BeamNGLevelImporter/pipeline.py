# ##### BEGIN LICENSE BLOCK #####
#
# This program is licensed under The MIT License:
# see LICENSE for the full license text
#
# ##### END LICENSE BLOCK #####

from __future__ import annotations
import bpy
import os
import time
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
from .shapes.dts import import_dts_shape
from .shapes.common import shape_key
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

def _set_view_clip_planes(clip_start=0.1, clip_end=50000.0):
  try:
    for window in bpy.context.window_manager.windows:
      screen = window.screen
      if not screen:
        continue
      for area in screen.areas:
        if area.type != 'VIEW_3D':
          continue
        for space in area.spaces:
          if space.type == 'VIEW_3D':
            space.clip_start = float(clip_start)
            space.clip_end = float(clip_end)
  except Exception:
    pass

def import_level(scene, props, operator=None):
  def _elapsed(start):
    return time.perf_counter() - start
  def info(msg): _info(operator, msg)

  overall_start = time.perf_counter()

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

  load_start = time.perf_counter()

  level_data  = load_main_records(level_path)
  forest_data = load_forest_records(level_path)
  terrain_meta = load_terrain_meta(level_path)
  packs_with_dirs = scan_material_json_packs(level_path) + scan_material_cs_packs(level_path)
  materials_packs = [p for (p, _d) in packs_with_dirs]
  material_pack_dirs = {id(p): d for (p, d) in packs_with_dirs}
  forest_items = load_forest_item_db(level_path)
  forest_names = {}
  shapes = []
  terrain_mats = []
  decals_defs, decal_instances = load_decal_sets(level_path)

  info(
    f"Loaded main: {len(level_data)} records, "
    f"forest: {len(forest_data)} items, "
    f"terrain meta: {len(terrain_meta)} entries, "
    f"materials files: {len(materials_packs)}, "
    f"forest item DB: {len(forest_items)}, "
    f"decal defs: {len(decals_defs)}, "
    f"decal instances: {sum(len(v) for v in decal_instances.values()) if decal_instances else 0} "
    f"(in {_elapsed(load_start):.2f}s)"
  )

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
    info(
      f"Expanded prefabs: {len(prefab_roots)} roots, "
      f"{len(prefabs_expanded)} objects (remaining level records: {len(level_data)})"
    )

  # Normalize
  normalize_records(level_data)
  normalize_forest(forest_data)
  norm_start = time.perf_counter()
  normalize_records(level_data)
  normalize_forest(forest_data)
  info(f"Normalized {len(level_data)} level records and {len(forest_data)} forest items in {_elapsed(norm_start):.2f}s")

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
    decal_instances=decal_instances,
    material_pack_dirs=material_pack_dirs,
  )

  info(
    f"Collected shapes: {len(shapes)} unique shape paths "
    f"(from TSStatic + forest item DB)"
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

  materials_count = sum(len(p) for p in ctx.materials_packs if isinstance(p, dict))
  info(
    f"Terrain materials: {'v1.5' if use_v15_terrain else 'v0'}, "
    f"Terrain world size: {terrain_world_size if terrain_world_size is not None else 'unknown'}, "
    f"Material in level data: {materials_count}"
  )

  try:
    ctx.progress.begin(total_steps, "BeamNG: preparing import...")

    mats_start = time.perf_counter()
    built_terrain = 0
    built_pbr = 0


    for pack in ctx.materials_packs:
      if not isinstance(pack, dict):
        continue
      mat_dir = ctx.material_pack_dirs.get(id(pack))
      for _, v in pack.items():
        if not isinstance(v, dict):
          continue
        if v.get('class') == "TerrainMaterial":
          if use_v15_terrain:
            build_terrain_material_v15(ctx.config.level_path, v, ctx.terrain_mats, terrain_world_size=terrain_world_size, mat_dir=mat_dir)
          else:
            build_terrain_material_v0(ctx.config.level_path, v, ctx.terrain_mats, terrain_world_size=terrain_world_size, mat_dir=mat_dir)
          built_terrain += 1
        elif v.get('mapTo') and v.get('version') == 1.5:
          name = v['mapTo'] if v['mapTo'] != 'unmapped_mat' else v.get('name')
          build_pbr_v15_material(name, v, ctx.config.level_path, mat_dir=mat_dir)
          built_pbr += 1
        elif v.get('mapTo') and (v.get('version') == 0 or not v.get('version')):
          name = v['mapTo'] if v['mapTo'] != 'unmapped_mat' else v.get('name')
          build_pbr_v0_material(name, v, ctx.config.level_path, mat_dir=mat_dir)
          built_pbr += 1
        ctx.progress.update(step=1)

    info(
      f"Built materials from level data: "
      f"{built_pbr} PBR, {built_terrain} terrain in {_elapsed(mats_start):.2f}s"
    )

    extra_mats_start = time.perf_counter()
    extra_pbr = 0
    extra_terrain = 0
    extra_scanned_packs = 0

    # 2) Extra materials from all /art providers (skip existing)
    assets_idx = last_assets()
    if assets_idx and assets_idx.art:
      extra_packs_with_dirs: list[tuple[dict, Path]] = []
      for prov in assets_idx.art:
        if prov.dir_root and prov.dir_root.exists():
          extra_packs_with_dirs.extend(scan_material_json_packs(prov.dir_root))
          extra_packs_with_dirs.extend(scan_material_cs_packs(prov.dir_root))
        elif prov.zip_path and prov.zip_path.exists():
          extra_packs_with_dirs.extend(scan_material_packs_in_zip(prov.zip_path))
      extra_scanned_packs = len(extra_packs_with_dirs)
      # Build only missing materials
      for pack, pack_dir in extra_packs_with_dirs:
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
              build_terrain_material_v15(ctx.config.level_path, v, ctx.terrain_mats, terrain_world_size=terrain_world_size, mat_dir=pack_dir)
            else:
              build_terrain_material_v0(ctx.config.level_path, v, ctx.terrain_mats, terrain_world_size=terrain_world_size, mat_dir=pack_dir)
            extra_terrain += 1
          elif cls == "Material" or (v.get('mapTo') and (v.get('version') in (None, 0, 1.5))):
            name = v.get('mapTo') if v.get('mapTo') not in (None, 'unmapped_mat') else v.get('name')
            if not name or bpy.data.materials.get(name):
              continue
            if v.get('version') == 1.5:
              build_pbr_v15_material(name, v, ctx.config.level_path, mat_dir=pack_dir)
            else:
              build_pbr_v0_material(name, v, ctx.config.level_path, mat_dir=pack_dir)
            extra_pbr += 1
        ctx.progress.update(step=1)

    if extra_scanned_packs:
      info(
        f"Common /art data: scanned {extra_scanned_packs} data, "
        f"built {extra_pbr} common PBR and {extra_terrain} common terrain materials "
        f"in {_elapsed(extra_mats_start):.2f}s"
      )

    # Shapes
    shapes_start = time.perf_counter()
    import_collada_shapes(ctx)

    for shp in ctx.shapes:
      key = shape_key(shp)
      if bpy.data.objects.get(key):
        continue
      obj = import_dts_shape(shp, ctx.config.level_path)
      if not obj:
        print(f"WARN: No importer found for shape: {shp}")
    info(
      f"Imported shapes: {len(ctx.shapes)} "
      f"in {_elapsed(shapes_start):.2f}s"
    )

    for obj in bpy.data.objects:
      if obj.type == 'MESH' and obj.data:
        ensure_uv_layers_named(obj.data, "UVMap", "UVMap2")
    for d in ("Cube", "Light", "Lamp", "Camera"):
      delete_object_if_exists(d)
    dedupe_materials()

    mission_start = time.perf_counter()
    for i in ctx.level_data:
      if i.get('class') == 'SimGroup':
        name = i.get('name')
        parent = i.get('__parent')
        if not (name and parent):
          continue

        c = bpy.data.collections.get(name)
        p = bpy.data.collections.get(parent)
        if not (c and p):
          continue

        if name not in p.children:
          try:
            p.children.link(c)
          except RuntimeError:
            pass

        for other in bpy.data.collections:
          if other is p:
            continue
          if name in other.children:
            try:
              other.children.unlink(c)
            except RuntimeError:
              pass

        for scene in bpy.data.scenes:
          root = scene.collection
          if root is p:
            continue
          if name in root.children:
            try:
              root.children.unlink(c)
            except RuntimeError:
              pass

    build_mission_objects(ctx)
    info(f"Built mission objects in {_elapsed(mission_start):.2f}s")

    forest_start = time.perf_counter()
    build_forest_objects(ctx)
    info(f"Built forest instances in {_elapsed(forest_start):.2f}s")

    decals_start = time.perf_counter()
    build_decal_objects(ctx)
    info(f"Built decals in {_elapsed(decals_start):.2f}s")
    _set_view_clip_planes(clip_start=1.0, clip_end=10000.0)
    force_redraw()
    total_time = _elapsed(overall_start)
    info(f"BeamNG import finished in {total_time:.2f}s")
    info("BeamNG Import finished")
  finally:
    ctx.progress.end()