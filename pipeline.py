# ##### BEGIN LICENSE BLOCK #####
#
# This program is licensed under The MIT License:
# see LICENSE for the full license text
#
# ##### END LICENSE BLOCK #####

import bpy
import os
from pathlib import Path

from .core.types import ImportConfig, ImportContext
from .core.progress import ProgressHelper, force_redraw
from .core.paths import extract_zip_level_root, resolve_beamng_path
from .core.sjson import read_json_records, decode_sjson_file
from .materials.v15 import build_pbr_v15_material
from .materials.v0 import build_pbr_v0_material
from .materials.terrain_v15 import build_terrain_material_v15
from .materials.terrain_v0 import build_terrain_material_v0
from .shapes.collada import import_collada_shapes
from .objects.mission import build_mission_objects
from .objects.forest import build_forest_objects
from .utils.bpy_helpers import ensure_collection, delete_object_if_exists, dedupe_materials

def import_level(scene, props, operator=None):
  def info(msg):
    if operator: operator.report({'INFO'}, msg)
    print(msg)

  temp_path = Path(bpy.app.tempdir or ".").resolve()
  level_path = Path(props.levelpath).resolve() if props.levelpath else None

  if props.enable_zip and props.zippath:
    root = extract_zip_level_root(Path(props.zippath), temp_path)
    if not root or not root.exists():
      raise RuntimeError("Failed to extract level from zip")
    level_path = root
    props.levelpath = str(root)

  if not level_path or not level_path.exists():
    raise RuntimeError("Level path not set or not found")

  import_path = (level_path / 'main').resolve()
  forest_path = (level_path / 'forest').resolve()
  managed_item_data = (level_path / 'art' / 'forest').resolve()
  managed_decal_data = (level_path / 'art' / 'decals').resolve()

  level_data = []
  forest_data = []
  terrain_meta = []
  materials_packs = []
  forest_items = {}
  forest_names = {}
  shapes = []
  terrain_mats = []
  decals_defs = {}
  decal_instances = {}

  if import_path.exists():
    for subdir, dirs, files in os.walk(import_path):
      for file in files:
        if file.endswith('.json'):
          level_data.extend(read_json_records(Path(subdir) / file))

  if forest_path.exists():
    for subdir, dirs, files in os.walk(forest_path):
      for file in files:
        if file.endswith('.json'):
          forest_data.extend(read_json_records(Path(subdir) / file))

  for file in level_path.glob('*.terrain.json'):
    terrain_meta.extend(read_json_records(file))

  for subdir, dirs, files in os.walk(level_path):
    for file in files:
      if file.endswith('materials.json'):
        try:
          materials_packs.append(decode_sjson_file(Path(subdir) / file))
        except Exception:
          pass

  if managed_item_data.exists():
    for file in managed_item_data.glob('*.json'):
      try:
        data = decode_sjson_file(file)
        if isinstance(data, dict):
          forest_items = data
      except Exception:
        pass

  if managed_decal_data.exists():
    for file in managed_decal_data.glob('*managedDecalData.json'):
      try:
        data = decode_sjson_file(file)
        if isinstance(data, dict):
          for k, v in data.items():
            if isinstance(v, dict) and v.get('class') == 'DecalData':
              decals_defs[k] = v
      except Exception:
        pass

  for file in level_path.glob('*.decals.json'):
    try:
      data = decode_sjson_file(file)
      if isinstance(data, dict) and isinstance(data.get('instances'), dict):
        for dec_name, inst_list in data['instances'].items():
          if isinstance(inst_list, list):
            decal_instances.setdefault(dec_name, []).extend(inst_list)
    except Exception:
      pass

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
  to_remove_prefab_records = []
  for rec in list(level_data):
    if not isinstance(rec, dict) or rec.get('class') != 'Prefab':
      continue
    prefab_fn = rec.get('filename')
    if not prefab_fn:
      continue
    prefab_path = resolve_beamng_path(prefab_fn, level_path)
    if not prefab_path.exists():
      info(f"Prefab file not found: {prefab_fn} -> {prefab_path}")
      continue

    prefab_name = rec.get('name') or rec.get('internalName') or prefab_path.stem
    prefab_parent = rec.get('__parent') or 'MissionGroup'
    prefab_pos = rec.get('position') or [0, 0, 0]
    if not isinstance(prefab_pos, (list, tuple)) or len(prefab_pos) != 3:
      prefab_pos = [0, 0, 0]

    prefab_roots.append({
      'class': 'SimGroup',
      'name': prefab_name,
      '__parent': prefab_parent
    })

    try:
      prefab_records = read_json_records(prefab_path)
    except Exception as e:
      info(f"Failed to read prefab {prefab_path}: {e}")
      continue

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
        if parent in group_name_map:
          r2['__parent'] = group_name_map[parent]
        else:
          r2['__parent'] = prefab_name
      else:
        if parent in group_name_map:
          r2['__parent'] = group_name_map[parent]
        else:
          r2['__parent'] = prefab_name

      prefabs_expanded.append(r2)

    to_remove_prefab_records.append(rec)

  if prefabs_expanded or prefab_roots:
    level_data.extend(prefab_roots)
    level_data.extend(prefabs_expanded)
    for r in to_remove_prefab_records:
      try:
        level_data.remove(r)
      except ValueError:
        pass

  for i in level_data:
    if i.get('class') == 'SimGroup':
      ensure_collection(i.get('name') or 'SimGroup')

  for i in level_data:
    if i.get('class') == 'TSStatic':
      shape = i.get('shapeName')
      if shape and shape not in shapes:
        shapes.append(shape)

  for key, item in (forest_items or {}).items():
    shape = (item or {}).get('shapeFile')
    name = (item or {}).get('name')
    if not shape:
      continue
    if shape not in shapes:
      shapes.append(shape)
    if name:
      forest_names[name] = os.path.split(shape)[1]

  cfg = ImportConfig(
    level_path=level_path,
    enable_zip=bool(props.enable_zip),
    zip_path=Path(props.zippath) if props.zippath else None
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

        # Terrain materials
        if v.get('class') == "TerrainMaterial":
          if use_v15_terrain:
            build_terrain_material_v15(ctx.config.level_path, v, ctx.terrain_mats, terrain_world_size=terrain_world_size)
          else:
            build_terrain_material_v0(ctx.config.level_path, v, ctx.terrain_mats, terrain_world_size=terrain_world_size)

        #unmapped_mats are used often for materials that are applied to procedural objects
        elif v.get('mapTo') and v.get('version') == 1.5:
          if not v['mapTo'] == 'unmapped_mat':
            build_pbr_v15_material(v['mapTo'], v, ctx.config.level_path)
          else:
            build_pbr_v15_material(v['name'], v, ctx.config.level_path)
        elif v.get('mapTo') and (v.get('version') == 0 or not v.get('version')):
          if not v['mapTo'] == 'unmapped_mat':
            build_pbr_v0_material(v['mapTo'], v, ctx.config.level_path)
          else:
            build_pbr_v0_material(v['name'], v, ctx.config.level_path)
        ctx.progress.update(step=1)

    import_collada_shapes(ctx)

    for d in ("Cube", "Light", "Lamp", "Camera"):
      delete_object_if_exists(d)
    dedupe_materials()

    for i in ctx.level_data:
      if i.get('class') == 'SimGroup':
        name = i.get('name')
        parent_name = i.get('__parent')
        if name and parent_name:
          c = bpy.data.collections.get(name)
          p = bpy.data.collections.get(parent_name)
          if c and p and c.name not in [ch.name for ch in p.children]:
            p.children.link(c)

    build_mission_objects(ctx)
    build_forest_objects(ctx)

    from .objects.decals import build_decal_objects
    build_decal_objects(ctx)

    force_redraw()
    info("BeamNG Import finished")
  finally:
    ctx.progress.end()