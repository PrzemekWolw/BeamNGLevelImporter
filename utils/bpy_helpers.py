# ##### BEGIN LICENSE BLOCK #####
#
# This program is licensed under The MIT License:
# see LICENSE for the full license text
#
# ##### END LICENSE BLOCK #####

import bpy
import re
from typing import Iterable, Dict, List, Tuple, Optional

def ensure_collection(name: str):
  c = bpy.data.collections.get(name)
  if not c:
    c = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(c)
  return c

def link_object_to_collection(obj, coll_name_or_coll):
  if not obj:
    return
  if isinstance(coll_name_or_coll, str):
    coll = bpy.data.collections.get(coll_name_or_coll)
  else:
    coll = coll_name_or_coll
  target = coll or bpy.context.scene.collection
  if target in obj.users_collection:
    return
  for old_col in obj.users_collection[:]:
    old_col.objects.unlink(obj)
  try:
    target.objects.link(obj)
  except RuntimeError:
    pass

def delete_object_if_exists(name: str):
  obj = bpy.data.objects.get(name)
  if obj:
    for coll in list(obj.users_collection):
      coll.objects.unlink(obj)
    bpy.data.objects.remove(obj, do_unlink=True)

def dedupe_materials():
  mats = bpy.data.materials
  for mat in list(mats):
    original, _, ext = mat.name.rpartition(".")
    if ext.isnumeric() and original and mats.get(original):
      try:
        mat.user_remap(mats[original])
        mats.remove(mat)
      except Exception:
        pass


_COL_SUFFIX_RE = re.compile(r"-\d+$")
_BLENDER_COPY_RE = re.compile(r"\.\d+$")


def is_collision_object_name(name: str) -> bool:
  if not name:
    return False
  n = name.lower()

  if _COL_SUFFIX_RE.search(n) is not None:
    return True

  if "colmesh" in n or "collision" in n:
    return True
  if n.startswith("col_") or n.startswith("colmesh_") or n.startswith("collision_"):
    return True
  if n.startswith("ucx_") or n.startswith("ubx_") or n.startswith("ucd_"):
    return True
  if n.startswith("colmesh-") or n.startswith("col-"):
    return True
  return False


def _strip_blender_copy_suffix(name: str) -> str:
  if not name:
    return name
  return _BLENDER_COPY_RE.sub("", name)


def _parse_trailing_number(name: str) -> Optional[int]:

  if not name:
    return None
  base = _strip_blender_copy_suffix(name)
  i = len(base)
  while i > 0 and base[i - 1].isdigit():
    i -= 1
  if i == len(base):
    return None
  try:
    return int(base[i:])
  except Exception:
    return None


def pick_highest_lod_and_level(
  objects: Iterable[bpy.types.Object]
) -> Tuple[Optional[int], List[bpy.types.Object]]:

  objs = [o for o in objects if o is not None]
  if not objs:
    #print("pick_highest_lod_and_level: no objects")
    return None, []

  mesh_objs = [o for o in objs if o.type == 'MESH' and getattr(o, "data", None)]
  if not mesh_objs:
    #print("pick_highest_lod_and_level: no mesh objects in:", [o.name for o in objs])
    return None, []

  visible_meshes = [o for o in mesh_objs if not is_collision_object_name(o.name)]
  if not visible_meshes:
    #print("pick_highest_lod_and_level: only collision meshes found:",
    #      [o.name for o in mesh_objs])
    return None, []

  #print("pick_highest_lod_and_level: visible meshes:",
  #      [o.name for o in visible_meshes])

  by_index: Dict[int, List[bpy.types.Object]] = {}
  any_index = False

  for o in visible_meshes:
    idx = _parse_trailing_number(o.name)
    if idx is not None:
      any_index = True
      by_index.setdefault(idx, []).append(o)

  if not any_index:
    # No numbers at all -> LODs don't exist, keep all visible meshes
    #print("pick_highest_lod_and_level: no numeric suffixes, keeping all visible meshes")
    return None, list(visible_meshes)

  # We have numeric indices: highest number is highest LOD
  best_level = max(by_index.keys())
  best_objs = by_index[best_level]
  #print("pick_highest_lod_and_level: best LOD index:", best_level,
  #      "objects:", [o.name for o in best_objs])

  return best_level, best_objs


def pick_highest_lod(objects: Iterable[bpy.types.Object]) -> Optional[bpy.types.Object]:

  _level, best_objs = pick_highest_lod_and_level(objects)
  if not best_objs:
    return None
  return best_objs[0]
