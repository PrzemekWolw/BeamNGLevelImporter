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
from .core.paths import extract_zip_level_root
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

  level_data = []
  forest_data = []
  terrain_meta = []
  materials_packs = []
  forest_items = {}
  forest_names = {}
  shapes = []
  terrain_mats = []

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
    terrain_mats=terrain_mats
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

        elif v.get('mapTo') and v.get('version') == 1.5:
          build_pbr_v15_material(v['mapTo'], v, ctx.config.level_path)
        elif v.get('mapTo') and (v.get('version') == 0 or not v.get('version')):
          build_pbr_v0_material(v['mapTo'], v, ctx.config.level_path)
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

    force_redraw()
    info("BeamNG Import finished")
  finally:
    ctx.progress.end()