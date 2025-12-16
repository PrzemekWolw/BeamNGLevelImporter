# ##### BEGIN LICENSE BLOCK #####
#
# This program is licensed under The MIT License:
# see LICENSE for the full license text
#
# ##### END LICENSE BLOCK #####

import bpy
import os
from ..core.paths import resolve_model_path
from ..utils.bpy_helpers import ensure_collection, pick_highest_lod
from .beamng_collada.collada_import import import_collada_file_to_blender

def import_collada_shapes(ctx):
  shapes_lib = ensure_collection('ShapesLib')
  for shp in ctx.shapes:
    ctx.progress.update(f"Resolving model: {os.path.basename(shp)}", step=1)
    p, ext = resolve_model_path(shp, ctx.config.level_path)
    if not p or not p.exists():
      print(f"WARN: Model not found (with fallbacks): {shp}")
      continue

    # Only imort .dae for now
    if str(p).lower().endswith(".dae"):
      ctx.progress.update(f"Importing Collada: {os.path.basename(p)}", step=1)
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
        model = os.path.split(str(p))
        best.name = model[1]
        if best.name not in shapes_lib.objects:
          shapes_lib.objects.link(best)
        best.location = (0, 0, -1000)
    else:
      # Resolved to a non-DAE model; leave it for future importers
      print(f"INFO: Resolved model '{shp}' to '{p.name}' ({ext}); import not yet implemented for this type.")