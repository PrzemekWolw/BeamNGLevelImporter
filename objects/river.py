# ##### BEGIN LICENSE BLOCK #####
#
# This program is licensed under The MIT License:
# see LICENSE for the full license text
#
# ##### END LICENSE BLOCK #####

import bpy
import math
import mathutils

from .bvh import _dr_build_bvh_targets, _dr_bvh_ray_down
from .common import _smooth_all_polys, fast_link

def _cr_float(a0, a1, a2, a3, t: float) -> float:
  t2 = t * t
  t3 = t2 * t
  return 0.5 * ((2.0*a1) + (-a0 + a2)*t + (2.0*a0 - 5.0*a1 + 4.0*a2 - a3)*t2 + (-a0 + 3.0*a1 - 3.0*a2 + a3)*t3)

def _cr_vec(v0, v1, v2, v3, t: float):
  return mathutils.Vector((
    _cr_float(v0.x, v1.x, v2.x, v3.x, t),
    _cr_float(v0.y, v1.y, v2.y, v3.y, t),
    _cr_float(v0.z, v1.z, v2.z, v3.z, t),
  ))

def make_river_from_nodes_catmull(name, nodes, subdivide_len, parent_coll, material_builder, level_dir):
  if not isinstance(nodes, list) or len(nodes) < 2:
    return None
  P = [mathutils.Vector((float(n[0]), float(n[1]), float(n[2]))) for n in nodes]
  W = [float(n[3]) for n in nodes]
  subdivide_len = max(1e-3, float(subdivide_len or 1.0))

  S_pos = []
  S_w = []
  count = len(P)
  for i in range(count - 1):
    p0 = P[i-1] if i-1 >= 0 else P[i]
    p1 = P[i]
    p2 = P[i+1]
    p3 = P[i+2] if (i+2) < count else P[i+1]
    w0 = W[i-1] if i-1 >= 0 else W[i]
    w1 = W[i]; w2 = W[i+1]
    w3 = W[i+2] if (i+2) < count else W[i+1]
    chord = (p2 - p1).length
    steps = max(1, math.ceil(chord / subdivide_len))
    for s in range(steps + 1):
      t = s / steps
      if i > 0 and s == 0:
        continue
      pos = _cr_vec(p0, p1, p2, p3, t)
      wid = _cr_float(w0, w1, w2, w3, t)
      S_pos.append(pos); S_w.append(wid)
  if len(S_pos) < 2:
    return None

  bvh_targets = _dr_build_bvh_targets(include_objects=True)
  decal_bias = 0.01
  up = mathutils.Vector((0.0, 0.0, 1.0))
  verts = []
  rows = len(S_pos)
  for j in range(rows):
    if j == 0:
      fwd = (S_pos[1] - S_pos[0]).normalized()
    elif j == rows - 1:
      fwd = (S_pos[-1] - S_pos[-2]).normalized()
    else:
      fwd = (S_pos[j+1] - S_pos[j-1]).normalized()
    if fwd.length_squared == 0.0:
      fwd = mathutils.Vector((1.0, 0.0, 0.0))
    rvec = fwd.cross(up)
    if rvec.length_squared == 0.0:
      rvec = up.orthogonal()
    rvec.normalize()
    half = S_w[j] * 0.5
    L = S_pos[j] - rvec * half
    R = S_pos[j] + rvec * half
    zL = _dr_bvh_ray_down(L + up, 5000.0, bvh_targets)
    zR = _dr_bvh_ray_down(R + up, 5000.0, bvh_targets)
    if zL is not None: L.z = zL + decal_bias
    if zR is not None: R.z = zR + decal_bias
    verts.append((L.x, L.y, L.z))
    verts.append((R.x, R.y, R.z))

  faces = []
  for j in range(rows - 1):
    a = 2*j; b = a + 1; c = a + 3; d = a + 2
    faces.append((a, b, c, d))

  me = bpy.data.meshes.new(f"River_{name}")
  me.from_pydata(verts, [], faces)
  me.update()
  obj = bpy.data.objects.new(name, me)
  fast_link(obj, parent_coll)
  _smooth_all_polys(me)

  try:
    wmat = material_builder(name, {'class': 'River'}, level_dir)
    if len(me.materials):
      me.materials[0] = wmat
    else:
      me.materials.append(wmat)
  except Exception as e:
    print(f"River material error for {name}: {e}")
  return obj