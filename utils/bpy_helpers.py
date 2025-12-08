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
  if coll:
    if obj.name not in coll.objects:
      coll.objects.link(obj)
  else:
    if obj.name not in bpy.context.scene.collection.objects:
      bpy.context.scene.collection.objects.link(obj)

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

def pick_highest_lod(objects):
  best = None
  best_lod = -1
  best_polys = -1
  for o in objects:
    if o.type != 'MESH':
      continue
    lod = -1
    name = o.name
    if '_a' in name:
      try:
        lod = int(name.split('_a')[-1])
      except Exception:
        lod = -1
    if '_L' in name:
      try:
        lod = int(name.split('_L')[-1])
      except Exception:
        lod = -1
    polys = len(o.data.polygons) if o.data else 0
    if lod > best_lod or (lod == best_lod and polys > best_polys):
      best = o
      best_lod = lod
      best_polys = polys
  if not best:
    for o in objects:
      if o.type != 'MESH' or not o.data:
        continue
      polys = len(o.data.polygons)
      if polys > best_polys:
        best_polys = polys
        best = o
  return best
