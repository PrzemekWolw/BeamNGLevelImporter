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

def _shape_key(shape_name: str) -> str:
  """
  Canonical key for a TSStatic shapeName. Must match mission-builder lookup.
  """
  s = (shape_name or "").replace("\\", "/").strip()
  return os.path.basename(s).lower()

def import_collada_shapes(ctx):
  shapes_lib = ensure_collection('ShapesLib')
  for shp in ctx.shapes:
    ctx.progress.update(f"Resolving model: {os.path.basename(shp)}", step=1)
    p, ext = resolve_model_path(shp, ctx.config.level_path)
    if not p or not p.exists():
      print(f"WARN: Model not found (with fallbacks): {shp}")
      continue

    # Only import .dae for now
    if not str(p).lower().endswith(".dae"):
      print(f"INFO: Resolved model '{shp}' to '{p.name}' ({ext}); import not yet implemented for this type.")
      continue

    key = _shape_key(shp)
    if bpy.data.objects.get(key):
      ctx.progress.update(f"Skipping already imported base: {key}", step=1)
      continue

    ctx.progress.update(f"Importing Collada: {os.path.basename(str(p))}", step=1)

    before = set(bpy.data.objects)
    try:
      import_collada_file_to_blender(str(p), shapes_lib, up_axis='Z_UP', ignore_node_scale=False)
    except Exception as e:
      print(f"WARN: Collada custom import failed: {p} ({e})")
      continue

    after = set(bpy.data.objects)
    imported = [o for o in (after - before) if o is not None]
    if not imported:
      print(f"WARN: No objects detected as imported for {p}")
      continue

    try:
      for o in imported:
        try:
          o.select_set(True)
        except Exception:
          pass
      bpy.context.view_layer.objects.active = imported[0]
      bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    except Exception:
      pass
    finally:
      for o in imported:
        try:
          o.select_set(False)
        except Exception:
          pass

    best = pick_highest_lod(imported)

    for o in list(imported):
      if o == best:
        continue
      try:
        for c in list(o.users_collection):
          c.objects.unlink(o)
        bpy.data.objects.remove(o, do_unlink=True)
      except Exception:
        pass

    if not best:
      continue

    best.name = key

    try:
      if shapes_lib and best.name not in shapes_lib.objects:
        shapes_lib.objects.link(best)
    except Exception:
      pass

    try:
      best.hide_set(True)
      best.hide_render = True
      if hasattr(best, "display_type"):
        best.display_type = 'BOUNDS'
    except Exception:
      pass
