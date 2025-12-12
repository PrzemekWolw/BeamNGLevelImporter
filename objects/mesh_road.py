# ##### BEGIN LICENSE BLOCK #####
#
# This program is licensed under The MIT License:
# see LICENSE for the full license text
#
# ##### END LICENSE BLOCK #####

import bpy
import math
import mathutils

from .common import _assign_uvs_from_vertex_uvs, _smooth_all_polys, fast_link

def _mr_cr_float(a0, a1, a2, a3, t: float) -> float:
  t2 = t * t
  t3 = t2 * t
  return 0.5 * ((2.0*a1) + (-a0 + a2)*t + (2.0*a0 - 5.0*a1 + 4.0*a2 - a3)*t2 + (-a0 + 3.0*a1 - 3.0*a2 + a3)*t3)

def _mr_cr_vec(v0, v1, v2, v3, t: float):
  return mathutils.Vector((
    _mr_cr_float(v0.x, v1.x, v2.x, v3.x, t),
    _mr_cr_float(v0.y, v1.y, v2.y, v3.y, t),
    _mr_cr_float(v0.z, v1.z, v2.z, v3.z, t),
  ))

def _mr_ids(i, count):
  n1 = max(i-1, 0); n2 = i; n3 = min(i+1, count-1); n4 = min(i+2, count-1)
  return n1, n2, n3, n4

def make_mesh_road(name, data, parent_coll):
  nodes = data.get('nodes') or []
  if not isinstance(nodes, list) or len(nodes) < 2:
    return None

  P = [mathutils.Vector((float(n[0]), float(n[1]), float(n[2]))) for n in nodes]
  W = [float(n[3]) for n in nodes]
  D = [float(n[4]) for n in nodes]
  N = []
  for n in nodes:
    nx, ny, nz = float(n[5]), float(n[6]), float(n[7])
    v = mathutils.Vector((nx, ny, nz))
    if v.length_squared == 0.0:
      v = mathutils.Vector((0, 0, 1))
    N.append(v.normalized())

  texture_length = float(data.get('textureLength', 5.0) or 5.0)
  break_angle_deg = float(data.get('breakAngle', 3.0) or 3.0)
  width_subdiv = max(0, int(data.get('widthSubdivisions', 0) or 0))
  min_seg = 1.0

  S_pos, S_w, S_d, S_n = [], [], [], []
  count = len(P)
  last_break_pos = P[0]
  last_break_dir = None
  S_pos.append(P[0]); S_w.append(W[0]); S_d.append(D[0]); S_n.append(N[0])
  for i in range(1, count):
    n1, n2, n3, n4 = _mr_ids(i-1, count)
    chord = (P[i] - P[i-1]).length
    steps = max(1, int(math.ceil(chord / min_seg)))
    for s in range(steps):
      t = (s + 1) / steps
      pos = _mr_cr_vec(P[n1], P[n2], P[n3], P[n4], t)
      wid = _mr_cr_float(W[n1], W[n2], W[n3], W[n4], t)
      dep = _mr_cr_float(D[n1], D[n2], D[n3], D[n4], t)
      nor = _mr_cr_vec(N[n1], N[n2], N[n3], N[n4], t)
      if nor.length_squared == 0.0:
        nor = mathutils.Vector((0, 0, 1))
      nor.normalize()
      to_vec = pos - last_break_pos
      if to_vec.length <= 1e-6:
        continue
      to_dir = to_vec.normalized()
      add = False
      if last_break_dir is None:
        add = True
      else:
        d = max(-1.0, min(1.0, to_dir.dot(last_break_dir)))
        ang = math.degrees(math.acos(d))
        if ang > break_angle_deg or s == steps - 1:
          add = True
      if add:
        S_pos.append(pos); S_w.append(wid); S_d.append(dep); S_n.append(nor)
        last_break_pos = pos
        last_break_dir = to_dir

  rows = len(S_pos)
  if rows < 2:
    return None

  u = [n for n in S_n]
  f = []
  r = []
  for j in range(rows):
    if j == 0:
      fv = (S_pos[1] - S_pos[0]).normalized()
    elif j == rows - 1:
      fv = (S_pos[-1] - S_pos[-2]).normalized()
    else:
      fv = (S_pos[j+1] - S_pos[j-1]).normalized()
    if fv.length_squared == 0.0:
      fv = mathutils.Vector((1, 0, 0))
    rv = fv.cross(u[j])
    if rv.length_squared == 0.0:
      rv = u[j].orthogonal()
    rv.normalize()
    fv = u[j].cross(rv).normalized()
    r.append(rv); f.append(fv)

  p0 = []
  p2 = []
  pb0 = []
  pb2 = []
  for j in range(rows):
    half = S_w[j] * 0.5
    left = S_pos[j] - r[j] * half
    right = S_pos[j] + r[j] * half
    p0.append(left); p2.append(right)
    pb0.append(left - u[j] * S_d[j])
    pb2.append(right - u[j] * S_d[j])

  v_rows = [0.0]
  for j in range(1, rows):
    v_rows.append(v_rows[-1] + (S_pos[j] - S_pos[j-1]).length / max(1e-6, texture_length))

  verts = []
  uvs = []
  faces = []

  cols_top = width_subdiv + 2
  def add_vtx(v): verts.append((v.x, v.y, v.z))
  def add_uv(uv): uvs.append(uv)

  for j in range(rows):
    v = v_rows[j]
    add_vtx(p0[j]); add_uv((1.0, v))
    for d_i in range(width_subdiv):
      t = (d_i + 1) / (width_subdiv + 1)
      add_vtx(p0[j].lerp(p2[j], t)); add_uv((1.0 - t, v))
    add_vtx(p2[j]); add_uv((0.0, v))

  def top_idx(rw, cl): return rw * cols_top + cl
  for j in range(rows - 1):
    for c in range(cols_top - 1):
      a = top_idx(j, c); b = top_idx(j, c + 1); e = top_idx(j + 1, c + 1); d = top_idx(j + 1, c)
      faces.append((a, b, e, d))

  base_bottom = len(verts)
  for j in range(rows):
    v = v_rows[j]
    add_vtx(pb2[j]); add_uv((0.0, v))
    add_vtx(pb0[j]); add_uv((1.0, v))

  def bot_idx(rw, cl): return base_bottom + rw * 2 + cl
  for j in range(rows - 1):
    a = bot_idx(j, 0); b = bot_idx(j, 1); e = bot_idx(j + 1, 1); d = bot_idx(j + 1, 0)
    faces.append((a, b, e, d))

  base_left = len(verts)
  for j in range(rows):
    v = v_rows[j]
    add_vtx(p0[j]);  add_uv((1.0, v))
    add_vtx(pb0[j]); add_uv((0.0, v))

  def left_idx(rw, cl): return base_left + rw * 2 + cl
  for j in range(rows - 1):
    a = left_idx(j, 0); b = left_idx(j, 1); e = left_idx(j + 1, 1); d = left_idx(j + 1, 0)
    faces.append((a, b, e, d))

  base_right = len(verts)
  for j in range(rows):
    v = v_rows[j]
    add_vtx(p2[j]);  add_uv((1.0, v))
    add_vtx(pb2[j]); add_uv((0.0, v))

  def right_idx(rw, cl): return base_right + rw * 2 + cl
  for j in range(rows - 1):
    a = right_idx(j, 0); b = right_idx(j, 1); e = right_idx(j + 1, 1); d = right_idx(j + 1, 0)
    faces.append((a, b, e, d))

  faces.append((top_idx(0, 0), top_idx(0, cols_top-1), bot_idx(0, 1), bot_idx(0, 0)))
  lr = rows - 1
  faces.append((top_idx(lr, 0), bot_idx(lr, 0), bot_idx(lr, 1), top_idx(lr, cols_top-1)))

  me = bpy.data.meshes.new(f"MeshRoad_{name}")
  me.from_pydata(verts, [], faces)
  me.update()

  _assign_uvs_from_vertex_uvs(me, "UVMap", uvs)
  _smooth_all_polys(me)
  obj = bpy.data.objects.new(name, me)
  fast_link(obj, parent_coll)

  top_mat = bpy.data.materials.get(data.get('topMaterial') or '')
  bottom_mat = bpy.data.materials.get(data.get('bottomMaterial') or '')
  side_mat = bpy.data.materials.get(data.get('sideMaterial') or '')

  mats = [top_mat, bottom_mat, side_mat]
  fallback = next((m for m in mats if m), None)
  final_slots = [(m if m else fallback) for m in mats]
  for m in final_slots:
    if m:
      me.materials.append(m)

  top_faces = (rows - 1) * (cols_top - 1)
  bottom_faces = (rows - 1)
  side_left = (rows - 1)
  side_right = (rows - 1)
  idx = 0
  num_slots = len(me.materials)
  def safe_set(mat_idx):
    return min(mat_idx, max(0, num_slots - 1))
  if num_slots > 0:
    for _ in range(top_faces):
      me.polygons[idx].material_index = safe_set(0); idx += 1
    for _ in range(bottom_faces):
      me.polygons[idx].material_index = safe_set(1); idx += 1
    for _ in range(side_left):
      me.polygons[idx].material_index = safe_set(2); idx += 1
    for _ in range(side_right):
      me.polygons[idx].material_index = safe_set(2); idx += 1
    if idx < len(me.polygons):
      me.polygons[idx].material_index = safe_set(2); idx += 1
    if idx < len(me.polygons):
      me.polygons[idx].material_index = safe_set(2)
  return obj