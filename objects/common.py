# ##### BEGIN LICENSE BLOCK #####
#
# This program is licensed under The MIT License:
# see LICENSE for the full license text
#
# ##### END LICENSE BLOCK #####

import bpy
import math
import mathutils

try:
  import numpy as np
  HAS_NUMPY = True
except Exception:
  HAS_NUMPY = False

def get_euler_from_rotlist(rot):
  if rot and len(rot) == 9:
    return mathutils.Matrix([[rot[0], rot[1], rot[2]],
                             [rot[3], rot[4], rot[5]],
                             [rot[6], rot[7], rot[8]]]).transposed().to_euler()
  return mathutils.Euler((0.0, 0.0, 0.0))

def make_matrix(loc, rot_euler, scale=(1,1,1)):
  loc_m = mathutils.Matrix.Translation(mathutils.Vector(loc))
  rot_m = rot_euler.to_matrix().to_4x4()
  sca_m = mathutils.Matrix.Diagonal((scale[0], scale[1], scale[2], 1.0))
  return loc_m @ rot_m @ sca_m

_cached_meshes = {"PLANE2": None, "CUBE2": None}

def get_unit_plane_mesh():
  if _cached_meshes["PLANE2"]:
    return _cached_meshes["PLANE2"]
  me = bpy.data.meshes.new("BLK_Plane2")
  verts = [(-1,-1,0), (1,-1,0), (1,1,0), (-1,1,0)]
  faces = [(0,1,2,3)]
  me.from_pydata(verts, [], faces)
  me.update()
  _cached_meshes["PLANE2"] = me
  return me

def get_unit_cube_mesh():
  if _cached_meshes["CUBE2"]:
    return _cached_meshes["CUBE2"]
  me = bpy.data.meshes.new("BLK_Cube2")
  v = [-1, 1]
  verts = [(x,y,z) for x in v for y in v for z in v]
  faces = [
    (0,1,3,2), (4,6,7,5),
    (0,2,6,4), (1,5,7,3),
    (0,4,5,1), (2,3,7,6),
  ]
  me.from_pydata(verts, [], faces)
  me.update()
  _cached_meshes["CUBE2"] = me
  return me

def fast_link(obj, coll_name_or_coll):
  if isinstance(coll_name_or_coll, str):
    coll = bpy.data.collections.get(coll_name_or_coll)
  else:
    coll = coll_name_or_coll
  try:
    if coll:
      coll.objects.link(obj)
    else:
      bpy.context.scene.collection.objects.link(obj)
  except RuntimeError:
    pass

_coll_cache = {}
def get_parent_collection(parent_name):
  if not parent_name:
    return None
  if parent_name in _coll_cache:
    return _coll_cache[parent_name]
  c = bpy.data.collections.get(parent_name)
  _coll_cache[parent_name] = c
  return c

def _normalize_scale(scale):
  if isinstance(scale, (int, float)):
    s = float(scale)
    return (s, s, s)
  if isinstance(scale, (list, tuple)):
    if len(scale) == 1:
      s = float(scale[0]); return (s, s, s)
    if len(scale) >= 3:
      return (float(scale[0]), float(scale[1]), float(scale[2]))
    s = list(scale) + [1.0] * (3 - len(scale))
    return (float(s[0]), float(s[1]), float(s[2]))
  return (1.0, 1.0, 1.0)

def _np_flat32(seq2d):
  if not HAS_NUMPY:
    flat = []
    for t in seq2d:
      if len(t) == 2:
        flat.extend((float(t[0]), float(t[1])))
      else:
        flat.extend((float(t[0]), float(t[1]), float(t[2])))
    return flat
  arr = np.asarray(seq2d, dtype=np.float32)
  if arr.ndim != 2:
    arr = np.reshape(arr, (-1, arr.shape[-1]))
  return np.ravel(arr, order='C')

def _np_full_bool(n, val=True):
  if HAS_NUMPY:
    return np.full(n, bool(val), dtype=np.bool_)
  return [bool(val)] * n

def _assign_uvs_from_vertex_uvs(me, uv_name, uvs):
  try:
    uv_layer = me.uv_layers.new(name=uv_name)
    if not uv_layer:
      return
    n_loops = len(me.loops)
    if n_loops == 0:
      return
    if HAS_NUMPY:
      vi = np.empty(n_loops, dtype=np.int32)
      me.loops.foreach_get('vertex_index', vi)
      uv_arr = np.asarray(uvs, dtype=np.float32)
      uv_flat = uv_arr[vi].ravel()
      uv_layer.data.foreach_set('uv', uv_flat)
    else:
      vi = [0] * n_loops
      me.loops.foreach_get('vertex_index', vi)
      uv_flat = []
      for i in range(n_loops):
        u, v = uvs[vi[i]]
        uv_flat.extend((u, v))
      uv_layer.data.foreach_set('uv', uv_flat)
  except Exception:
    pass

def _smooth_all_polys(me):
  try:
    n = len(me.polygons)
    if n:
      me.polygons.foreach_set("use_smooth", _np_full_bool(n, True))
  except Exception:
    pass

def _set_modifier_object_input(mod, socket_name, obj):
  try:
    iface = mod.node_group.interface
    idx = None
    count = 0
    for it in iface.items_tree:
      if getattr(it, 'in_out', 'INPUT') == 'INPUT':
        count += 1
        if it.name == socket_name:
          idx = count
          break
    if idx is not None:
      mod[f"Input_{idx}"] = obj
      return True
  except Exception:
    pass
  return False
