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
from .common import _assign_uvs_from_vertex_uvs, _smooth_all_polys, fast_link

def _dr_node_ids(i, count, looped):
  if looped:
    pm = lambda k: (k % count + count) % count
    return pm(i-1), pm(i), pm(i+1), pm(i+2)
  else:
    n1 = max(i-1, 0); n2 = i; n3 = min(i+1, count-1); n4 = min(i+2, count-1)
    return n1, n2, n3, n4

def _dr_fill_row_holes(z_row):
  n = len(z_row)
  last = None
  for i in range(n):
    if z_row[i] is None:
      z_row[i] = last
    else:
      last = z_row[i]
  last = None
  for i in range(n - 1, -1, -1):
    if z_row[i] is None:
      z_row[i] = last
    else:
      last = z_row[i]
  return z_row

def make_decal_road(name, data, parent_coll,
                    priority_step=0.002, priority_base=0.0,
                    width_segments=8,
                    up_clearance=50.0, max_down=20000.0,
                    surface_bias=0.03):
  nodes = data.get('nodes') or []
  if not isinstance(nodes, list) or len(nodes) < 2:
    return None
  P = [mathutils.Vector((float(n[0]), float(n[1]), float(n[2]))) for n in nodes]
  W = [float(n[3]) for n in nodes]
  improved    = bool(data.get('improvedSpline', True))
  looped      = bool(data.get('looped', False))
  smoothness  = float(data.get('smoothness', 0.5) or 0.5)
  detail      = float(data.get('detail', 0.1) or 0.1)
  steps_per   = max(1, int(1.0 / max(0.01, detail)) + 1)
  tex_len     = float(data.get('textureLength', 5.0) or 5.0)
  include_obj = bool(data.get('overObjects', False))
  decal_bias  = float(data.get('decalBias', 0.01) or 0.01)
  prio        = float(data.get('renderPriority', 10) or 10)
  layer_offset = priority_base + prio * float(priority_step)

  S_pos, S_w = [], []
  ncnt = len(P)
  if improved:
    i_start = 0
    i_end = ncnt - 1 if looped else ncnt - 2
    for i in range(i_start, i_end + 1):
      n1, n2, n3, n4 = _dr_node_ids(i, ncnt, looped)
      for s in range(steps_per + (1 if (i == i_end) else 0)):
        t = s / steps_per
        if i > 0 and s == 0:
          continue
        c0 = P[n2]
        c1 = smoothness * (P[n3] - P[n1])
        c2 = 2*smoothness*P[n1] + (smoothness - 3)*P[n2] + (3 - 2*smoothness)*P[n3] - smoothness*P[n4]
        c3 = -smoothness*P[n1] + (2 - smoothness)*P[n2] + (smoothness - 2)*P[n3] + smoothness*P[n4]
        pos = c0 + c1 * t + c2 * (t*t) + c3 * (t*t*t)
        w0, w1, w2, w3 = W[n1], W[n2], W[n3], W[n4]
        sw_c0 = w1
        sw_c1 = smoothness * (w2 - w0)
        sw_c2 = 2*smoothness*w0 + (smoothness - 3)*w1 + (3 - 2*smoothness)*w2 - smoothness*w3
        sw_c3 = -smoothness*w0 + (2 - smoothness)*w1 + (smoothness - 2)*w2 + smoothness*w3
        wid = sw_c0 + sw_c1 * t + sw_c2 * (t*t) + sw_c3 * (t*t*t)
        S_pos.append(pos); S_w.append(wid)
  else:
    for i in range(ncnt - 1):
      p1, p2 = P[i], P[i+1]
      w1, w2 = W[i], W[i+1]
      for s in range(steps_per + (1 if (i == ncnt - 2) else 0)):
        t = s / steps_per
        if i > 0 and s == 0:
          continue
        S_pos.append(p1.lerp(p2, t))
        S_w.append((1.0 - t) * w1 + t * w2)
  if len(S_pos) < 2:
    return None

  v_acc = [0.0]
  for j in range(1, len(S_pos)):
    v_acc.append(v_acc[-1] + (S_pos[j] - S_pos[j-1]).length / max(1e-6, tex_len))

  bvh_targets = _dr_build_bvh_targets(include_obj)
  up = mathutils.Vector((0.0, 0.0, 1.0))
  cols = max(2, int(width_segments))
  rows = len(S_pos)

  rvecs = []
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
    rvecs.append(rvec)

  verts = []
  uvs = []
  for j in range(rows):
    center = S_pos[j]
    width = S_w[j]
    rvec = rvecs[j]
    v = v_acc[j]
    row_xy = []
    z_row = []
    for c in range(cols + 1):
      u_norm = c / cols
      lateral = (u_norm - 0.5) * width
      p = center + rvec * lateral
      row_xy.append((u_norm, p.x, p.y))
      origin = mathutils.Vector((p.x, p.y, p.z + float(up_clearance)))
      best_z = _dr_bvh_ray_down(origin, max_down + up_clearance, bvh_targets)
      z_row.append(best_z)
    z_row = _dr_fill_row_holes(z_row)
    for idx, (u_norm, px, py) in enumerate(row_xy):
      z = z_row[idx]
      if z is None:
        z = center.z
      z += (decal_bias + layer_offset + surface_bias)
      verts.append((px, py, z))
      uvs.append((u_norm, v))

  faces = []
  def vidx(r, c): return r * (cols + 1) + c
  for r in range(rows - 1):
    for c in range(cols):
      a = vidx(r, c); b = vidx(r, c + 1); e = vidx(r + 1, c + 1); d = vidx(r + 1, c)
      faces.append((a, b, e, d))
  if looped and rows > 2:
    r = rows - 1; r0 = 0
    for c in range(cols):
      a = vidx(r, c); b = vidx(r, c + 1); e = vidx(r0, c + 1); d = vidx(r0, c)
      faces.append((a, b, e, d))

  me = bpy.data.meshes.new(f"DecalRoad_{name}")
  try:
    me.from_pydata(verts, [], faces)
  except Exception:
    me.from_pydata([], [], [])
  me.update()

  _assign_uvs_from_vertex_uvs(me, "UVMap", uvs)
  _smooth_all_polys(me)
  obj = bpy.data.objects.new(name, me)
  fast_link(obj, parent_coll)

  try:
    if hasattr(obj, "cycles_visibility"):
      obj.cycles_visibility.shadow = False
    if hasattr(obj, "visible_shadow"):
      obj.visible_shadow = False
    if hasattr(obj, "show_shadow"):
      obj.show_shadow = False
  except Exception:
    pass

  mat_name = data.get('material')
  if mat_name:
    mat = bpy.data.materials.get(mat_name)
    if mat:
      if me.materials:
        me.materials[0] = mat
      else:
        me.materials.append(mat)
  return obj