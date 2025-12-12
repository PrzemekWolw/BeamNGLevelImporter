# ##### BEGIN LICENSE BLOCK #####
#
# This program is licensed under The MIT License:
# see LICENSE for the full license text
#
# ##### END LICENSE BLOCK #####

import bpy
import os
from ..core.paths import resolve_beamng_path, exists_insensitive, get_real_case_path
from ..utils.bpy_helpers import ensure_collection, pick_highest_lod
from .beamng_collada.collada_import import import_collada_file_to_blender

def import_collada_shapes(ctx):
  shapes_lib = ensure_collection('ShapesLib')
  for shp in ctx.shapes:
    if not shp.lower().endswith('.dae'):
      ctx.progress.update(f"Skipping non-DAE: {os.path.basename(shp)}", step=1)
      continue
    ctx.progress.update(f"Importing BeamNG Collada: {os.path.basename(shp)}", step=1)
    p = resolve_beamng_path(shp, ctx.config.level_path, None)
    if not exists_insensitive(p):
      print(f"WARN: Collada file not found: {p}")
      continue
    p = get_real_case_path(p)
    try:
      import_collada_file_to_blender(str(p), shapes_lib, up_axis='Z_UP', ignore_node_scale=False)
    except Exception as e:
      print(f"WARN: Collada custom import failed: {p} ({e})")
      continue

    imported = list(bpy.context.selected_objects)
    if not imported:
      continue

    for o in imported:
      try:
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
      except Exception:
        pass

    best = pick_highest_lod(imported)
    for o in imported:
      if o == best:
        continue
      try:
        for c in list(o.users_collection):
          c.objects.unlink(o)
        bpy.data.objects.remove(o, do_unlink=True)
      except Exception:
        pass

    if best:
      model = os.path.split(shp)
      best.name = model[1]
      if best.name not in shapes_lib.objects:
        shapes_lib.objects.link(best)
      best.location = (0, 0, -1000)
