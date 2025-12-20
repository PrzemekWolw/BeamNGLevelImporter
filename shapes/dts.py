# ##### BEGIN LICENSE BLOCK #####
#
# This program is licensed under The MIT License:
# see LICENSE for the full license text
#
# ##### END LICENSE BLOCK #####

from __future__ import annotations
import os
from pathlib import Path
import bpy

from .dts_core import import_dts as dts_loader
from ..core.paths import resolve_model_path
from ..utils.bpy_helpers import (
  ensure_collection,
  pick_highest_lod_and_level,
  is_collision_object_name,
)
from .common import shape_key


class _DummyOp:
  """Minimal operator-like object so dts_loader.load() can report."""

  merge_verts = True

  def report(self, _kind, msg):
    print(msg)


def _import_dts_from_exact_path(path: Path, shape_virt_path: str) -> bpy.types.Object | None:
  """
  Import a DTS/CDAE from an exact filesystem path (no extra resolution),
  then register the best object under the canonical key for shape_virt_path.
  Behavior mirrors shapes/collada.py:
    - before/after object sets
    - pick best LOD level via pick_highest_lod_and_level
    - delete non-best
    - join selected LOD meshes into one
    - hide & link main object to ShapesLib
  """
  if not path or not path.exists():
    return None

  ext_l = path.suffix.lower()
  if ext_l not in (".dts", ".cdae", ".cached.dts"):
    return None

  shapes_lib = ensure_collection("ShapesLib")
  key = shape_key(shape_virt_path)
  existing = bpy.data.objects.get(key)
  if existing and existing.type == "MESH":
    return existing

  path_str = str(path)
  print(f"Importing DTS/CDAE: {os.path.basename(path_str)}")

  before = set(bpy.data.objects)
  try:
    dts_loader.load(_DummyOp(), bpy.context, filepath=path_str, merge_verts=True)
  except Exception as e:
    print(f"WARN: DTS/CDAE import failed: {path} ({e})")
    return None

  after = set(bpy.data.objects)
  imported = [o for o in (after - before) if o is not None]
  if not imported:
    print(f"WARN: No objects detected as imported for {path}")
    return None

  #print("DTS imported objects:", [o.name for o in imported])

  mesh_imported = [o for o in imported if isinstance(getattr(o, "data", None), bpy.types.Mesh)]
  visible_meshes = [o for o in mesh_imported if not is_collision_object_name(o.name)]
  collision_meshes = [o for o in mesh_imported if is_collision_object_name(o.name)]

  #print("DTS mesh_imported:", [o.name for o in mesh_imported])
  #print("DTS visible_meshes:", [o.name for o in visible_meshes])
  #print("DTS collision_meshes:", [o.name for o in collision_meshes])

  candidates = visible_meshes or mesh_imported

  try:
    for o in imported:
      try:
        o.select_set(False)
      except Exception:
        pass
    if mesh_imported:
      for o in mesh_imported:
        try:
          o.select_set(True)
        except Exception:
          pass
      bpy.context.view_layer.objects.active = mesh_imported[0]
      bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
  except Exception as e:
    print("WARN: transform_apply failed (DTS):", e)
  finally:
    for o in imported:
      try:
        o.select_set(False)
      except Exception:
        pass

  best_level, best_objs = pick_highest_lod_and_level(candidates)

  if not best_objs:
    print("WARN: No best LOD set found for DTS shape:", shape_virt_path)
    for o in list(imported):
      try:
        for c in list(o.users_collection):
          c.objects.unlink(o)
        bpy.data.objects.remove(o, do_unlink=True)
      except Exception:
        pass
    return None

  best_set = set(best_objs)
  for o in list(imported):
    if o in best_set:
      continue
    try:
      for c in list(o.users_collection):
        c.objects.unlink(o)
      bpy.data.objects.remove(o, do_unlink=True)
    except Exception:
      pass

  # Join best_objs into a single object
  if len(best_objs) > 1:
    try:
      for o in bpy.context.selected_objects:
        try:
          o.select_set(False)
        except Exception:
          pass
      main_obj = best_objs[0]
      for o in best_objs:
        try:
          o.select_set(True)
        except Exception:
          pass
      bpy.context.view_layer.objects.active = main_obj
      bpy.ops.object.join()
    except Exception as e:
      print("WARN: join failed for DTS best LOD objects:", e)
      main_obj = best_objs[0]
  else:
    main_obj = best_objs[0]

  main_obj.name = key

  try:
    if shapes_lib and main_obj.name not in shapes_lib.objects:
      shapes_lib.objects.link(main_obj)
  except Exception:
    pass

  try:
    main_obj.hide_set(True)
    main_obj.hide_render = True
  except Exception:
    pass

  return main_obj


def import_dts_shape(shape_virt_path: str, level_dir: Path | None) -> bpy.types.Object | None:
  """
  Import a DTS/CDAE shape used by TSStatic, resolving via resolve_model_path.
  If you already have an exact filesystem path, call _import_dts_from_exact_path instead.
  """
  p, ext = resolve_model_path(shape_virt_path, level_dir)
  if not p or not p.exists():
    print(f"WARN: DTS/CDAE model not found (with fallbacks): {shape_virt_path}")
    return None

  ext_l = (ext or Path(p).suffix).lower()
  if ext_l not in (".dts", ".cdae", ".cached.dts"):
    # Non-DTS/CDAE is handled elsewhere (Collada, etc.)
    return None

  return _import_dts_from_exact_path(p, shape_virt_path)