# ##### BEGIN LICENSE BLOCK #####
#
# This program is licensed under The MIT License:
# see LICENSE for the full license text
#
# ##### END LICENSE BLOCK #####

import bpy

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

def is_collision_object_name(name: str) -> bool:
  if not name:
    return False
  n = name.lower()
  if "colmesh" in n or "collision" in n:
    return True
  if n.startswith("col_") or n.startswith("colmesh_") or n.startswith("collision_"):
    return True
  if n.startswith("ucx_") or n.startswith("ubx_") or n.startswith("ucd_"):
    return True
  if n.startswith("colmesh-") or n.startswith("col-"):
    return True
  return False

def _parse_trailing_number_from_object(o: bpy.types.Object):
  name = o.name or ""
  if not name:
    return name, None
  i = len(name)
  while i > 0 and name[i - 1].isdigit():
    i -= 1
  if i == len(name):
    return name, None
  base = name[:i]
  try:
    num = int(name[i:])
  except Exception:
    num = None
  return base, num

def pick_highest_lod(objects):
  mesh_objs = [o for o in objects if o and o.type == 'MESH' and o.data]
  if not mesh_objs:
    return None

  kept_meshes = []
  for o in mesh_objs:
    if is_collision_object_name(o.name):
      try:
        for c in list(o.users_collection):
          c.objects.unlink(o)
        bpy.data.objects.remove(o, do_unlink=True)
      except Exception:
        pass
    else:
      kept_meshes.append(o)

  if not kept_meshes:
    return None

  mesh_objs = kept_meshes

  groups_by_index = {}
  any_index = False
  for o in mesh_objs:
    base, num = _parse_trailing_number_from_object(o)
    if num is None:
      continue
    any_index = True
    groups_by_index.setdefault(num, []).append(o)

  if any_index and groups_by_index:
    best_index = max(groups_by_index.keys())
    candidates = groups_by_index[best_index]
    if len(candidates) == 1:
      return candidates[0]

    base_obj = candidates[0]
    to_join = [o for o in candidates[1:] if o is not base_obj]

    for o in bpy.context.selected_objects:
      try:
        o.select_set(False)
      except Exception:
        pass
    try:
      base_obj.select_set(True)
    except Exception:
      pass
    for o in to_join:
      try:
        o.select_set(True)
      except Exception:
        pass
    bpy.context.view_layer.objects.active = base_obj
    try:
      bpy.ops.object.join()
    except Exception:
      pass
    return base_obj

  if len(mesh_objs) == 1:
    return mesh_objs[0]

  base_obj = mesh_objs[0]
  to_join = mesh_objs[1:]

  for o in bpy.context.selected_objects:
    try:
      o.select_set(False)
    except Exception:
      pass
  try:
    base_obj.select_set(True)
  except Exception:
    pass
  for o in to_join:
    try:
      o.select_set(True)
    except Exception:
      pass
  bpy.context.view_layer.objects.active = base_obj
  try:
    bpy.ops.object.join()
  except Exception:
    pass
  return base_obj
