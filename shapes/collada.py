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
from ..core.paths import resolve_any_beamng_path
from ..utils.bpy_helpers import ensure_collection, pick_highest_lod
from .beamng_collada.collada_import import import_collada_file_to_blender
from .common import shape_key
from .dts import _import_dts_from_exact_path


def _virtual_dae_from_shape(shape_virt_path: str) -> str:
  """
  Given a shape virtual path (possibly with any ext or none),
  construct a virtual .dae path with the same base.
  Example:
    'vehicles/foo/car.dts' -> 'vehicles/foo/car.dae'
    'art/shapes/tree'      -> 'art/shapes/tree.dae'
  """
  s = shape_virt_path.replace("\\", "/")
  if "." in os.path.basename(s):
    base = s.rsplit(".", 1)[0]
  else:
    base = s
  return f"{base}.dae"


def import_collada_shapes(ctx):
  shapes_lib = ensure_collection('ShapesLib')
  for shp in ctx.shapes:
    ctx.progress.update(f"Resolving model: {os.path.basename(shp)}", step=1)

    key = shape_key(shp)
    if bpy.data.objects.get(key):
      ctx.progress.update(f"Skipping already imported base: {key}", step=1)
      continue

    virt_dae = _virtual_dae_from_shape(shp)

    dae_path = resolve_any_beamng_path(virt_dae, ctx.config.level_path)
    dae_file = Path(dae_path) if dae_path else None
    if not dae_file or not dae_file.exists():
      base_no_ext = virt_dae.rsplit(".", 1)[0]
      for ext in (".cdae", ".dts", ".cached.dts"):
        cand_virt = base_no_ext + ext
        cand_path = resolve_any_beamng_path(cand_virt, ctx.config.level_path)
        cand_file = Path(cand_path) if cand_path else None
        if cand_file and cand_file.exists():
          obj = _import_dts_from_exact_path(cand_file, shp)
          if obj:
            break
      else:
        print(f"INFO: No .dae/.cdae/.dts/.cached.dts found for shape: {shp}")
      continue

    ctx.progress.update(f"Importing Collada: {os.path.basename(str(dae_file))}", step=1)

    before = set(bpy.data.objects)
    try:
      import_collada_file_to_blender(str(dae_file), shapes_lib, up_axis='Z_UP', ignore_node_scale=False)
    except Exception as e:
      print(f"WARN: Collada custom import failed: {dae_file} ({e})")
      base_no_ext = virt_dae.rsplit(".", 1)[0]
      for ext in (".cdae", ".dts", ".cached.dts"):
        cand_virt = base_no_ext + ext
        cand_path = resolve_any_beamng_path(cand_virt, ctx.config.level_path)
        cand_file = Path(cand_path) if cand_path else None
        if cand_file and cand_file.exists():
          obj = _import_dts_from_exact_path(cand_file, shp)
          if obj:
            break
      continue

    after = set(bpy.data.objects)
    imported = [o for o in (after - before) if o is not None]
    if not imported:
      print(f"WARN: No objects detected as imported for {dae_file}")
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
    except Exception:
      pass
