# ##### BEGIN LICENSE BLOCK #####
#
# This program is licensed under The MIT License:
# see LICENSE for the full license text
#
# ##### END LICENSE BLOCK #####

import bpy, time, struct
from .tsshape import TSShape
from . import import_common as C

# ======================================================
# Version detection (DTS/CDAE)
# ======================================================
def _detect_version(filepath: str) -> int:
  with open(filepath, "rb") as f:
    data = f.read(4)
  if len(data) != 4:
    raise ValueError("File too small to detect DTS/CDAE version")
  ver_full = struct.unpack("<i", data)[0]
  return ver_full & 0xFF

# ======================================================
# DTS import
# ======================================================
def read_dts_file(file, filepath, merge_verts: bool = True):
  shape = TSShape()
  shape.read_from_path(filepath)
  C._create_scene_from_shape(shape, merge_verts=merge_verts)

def load_dts(filepath, context, merge_verts: bool = True):
  print("Importing DTS: %r..." % (filepath))
  t0 = time.perf_counter()
  with open(filepath, "rb"):
    pass
  read_dts_file(None, filepath, merge_verts=merge_verts)
  print(" done in %.4f sec." % (time.perf_counter() - t0))

# ======================================================
# Unified loader
# ======================================================
def load(operator, context, filepath: str = "", merge_verts: bool = True):
  try:
    ver = _detect_version(filepath)
  except Exception as e:
    operator.report({"ERROR"}, f"Cannot detect DTS/CDAE version: {e}")
    return {"CANCELLED"}

  # allow operator to override merge_verts if it has the property
  if hasattr(operator, "merge_verts"):
    try:
      merge_verts = bool(getattr(operator, "merge_verts"))
    except Exception:
      pass

  if ver == 30:
    operator.report({"ERROR"}, "Version 30 files are not supported.")
    return {"CANCELLED"}

  if ver >= 31:
    from . import import_cdae
    import_cdae.load_cdae(filepath, context, merge_verts=merge_verts)
    return {"FINISHED"}
  elif ver >= 19:
    load_dts(filepath, context, merge_verts=merge_verts)
    return {"FINISHED"}
  else:
    operator.report({"ERROR"}, f"Unsupported DTS/CDAE version {ver} (too old).")
    return {"CANCELLED"}