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
from ..utils.bpy_helpers import ensure_collection, pick_highest_lod
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
  Behavior intentionally mirrors shapes/collada.py:
    - before/after object sets
    - pick_best via pick_highest_lod
    - delete non-best
    - hide & link best to ShapesLib
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

  # Optional transform apply (same pattern as Collada)
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

  # Pick best LOD and delete others (mirrors shapes/collada.py)
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
    return None

  best.name = key

  # Ensure linked to ShapesLib and hidden (mirrors shapes/collada.py)
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

  return best


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