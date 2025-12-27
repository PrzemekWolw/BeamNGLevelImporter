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

  texture_length = float(data.get('textureLength', 5.0) or 5.0)
  break_angle_deg = float(data.get('breakAngle', 3.0) or 3.0)
  width_subdiv = max(0, int(data.get('widthSubdivisions', 0) or 0))
  min_seg = 1.0

  try:
    import numpy as np
    HAS_NP = True
  except Exception:
    HAS_NP = False

  if HAS_NP:
    # Convert inputs to numpy
    P = np.asarray([(float(n[0]), float(n[1]), float(n[2])) for n in nodes], dtype=np.float64)
    W = np.asarray([float(n[3]) for n in nodes], dtype=np.float64)
    D = np.asarray([float(n[4]) for n in nodes], dtype=np.float64)
    Nn = np.asarray([(float(n[5]), float(n[6]), float(n[7])) for n in nodes], dtype=np.float64)
    # Normalize N, replace zeros with (0,0,1)
    nlen = np.linalg.norm(Nn, axis=1)
    zero_mask = nlen <= 1e-12
    if np.any(zero_mask):
      Nn[zero_mask] = np.array([0.0, 0.0, 1.0])
      nlen[zero_mask] = 1.0
    Nn = Nn / nlen[:, None]

    def cr_vec(a0, a1, a2, a3, Ts):
      T = Ts[:, None]
      T2 = T * T
      T3 = T2 * T
      return 0.5 * (2.0*a1 + (-a0 + a2)*T + (2.0*a0 - 5.0*a1 + 4.0*a2 - a3)*T2 + (-a0 + 3.0*a1 - 3.0*a2 + a3)*T3)

    def cr_scalar(a0, a1, a2, a3, Ts):
      T2 = Ts * Ts
      T3 = T2 * Ts
      return 0.5 * (2.0*a1 + (-a0 + a2)*Ts + (2.0*a0 - 5.0*a1 + 4.0*a2 - a3)*T2 + (-a0 + 3.0*a1 - 3.0*a2 + a3)*T3)

    count = P.shape[0]
    # Vectorized sampling per segment (variable steps), then angle-based decimation loop
    pos_chunks = []
    wid_chunks = []
    dep_chunks = []
    nor_chunks = []
    last_flags = []  # True for last sample in each segment

    for i in range(1, count):
      n1, n2, n3, n4 = _mr_ids(i-1, count)
      chord = np.linalg.norm(P[i] - P[i-1])
      steps = max(1, int(math.ceil(chord / min_seg)))
      Ts = (np.arange(1, steps + 1, dtype=np.float64) / steps)

      pos_seg = cr_vec(P[n1], P[n2], P[n3], P[n4], Ts)            # (steps, 3)
      wid_seg = cr_scalar(W[n1], W[n2], W[n3], W[n4], Ts)         # (steps,)
      dep_seg = cr_scalar(D[n1], D[n2], D[n3], D[n4], Ts)         # (steps,)
      nor_seg = cr_vec(Nn[n1], Nn[n2], Nn[n3], Nn[n4], Ts)        # (steps, 3)

      # Normalize normals; replace zeros with (0,0,1)
      nl = np.linalg.norm(nor_seg, axis=1)
      bad = nl <= 1e-12
      if np.any(bad):
        nor_seg[bad] = np.array([0.0, 0.0, 1.0])
        nl[bad] = 1.0
      nor_seg = nor_seg / nl[:, None]

      pos_chunks.append(pos_seg)
      wid_chunks.append(wid_seg)
      dep_chunks.append(dep_seg)
      nor_chunks.append(nor_seg)
      lf = np.zeros(steps, dtype=bool)
      lf[-1] = True
      last_flags.append(lf)

    if len(pos_chunks) == 0:
      return None

    pos_all = np.vstack(pos_chunks)    # (M, 3)
    wid_all = np.concatenate(wid_chunks)
    dep_all = np.concatenate(dep_chunks)
    nor_all = np.vstack(nor_chunks)
    must_add = np.concatenate(last_flags)

    # Angle-based decimation (kept as a loop to preserve exact behavior)
    S_pos = []
    S_w = []
    S_d = []
    S_n = []

    last_break_pos = P[0].copy()
    last_break_dir = None
    S_pos.append(last_break_pos)
    S_w.append(W[0])
    S_d.append(D[0])
    S_n.append(Nn[0])

    cos_clamp = lambda x: max(-1.0, min(1.0, float(x)))

    for k in range(pos_all.shape[0]):
      pos = pos_all[k]
      to_vec = pos - last_break_pos
      dist = float(np.linalg.norm(to_vec))
      if dist <= 1e-6:
        continue
      to_dir = to_vec / dist
      add = False
      if last_break_dir is None:
        add = True
      else:
        d = cos_clamp(np.dot(to_dir, last_break_dir))
        ang = math.degrees(math.acos(d))
        if ang > break_angle_deg or must_add[k]:
          add = True
      if add:
        S_pos.append(pos)
        S_w.append(float(wid_all[k]))
        S_d.append(float(dep_all[k]))
        S_n.append(nor_all[k])
        last_break_pos = pos
        last_break_dir = to_dir

    rows = len(S_pos)
    if rows < 2:
      return None

    S_pos = np.asarray(S_pos, dtype=np.float64)  # (rows, 3)
    S_w = np.asarray(S_w, dtype=np.float64)      # (rows,)
    S_d = np.asarray(S_d, dtype=np.float64)      # (rows,)
    S_n = np.asarray(S_n, dtype=np.float64)      # (rows, 3)

    # Forward vectors (centered difference)
    F = np.empty_like(S_pos)
    F[0] = S_pos[1] - S_pos[0]
    F[-1] = S_pos[-1] - S_pos[-2]
    if rows > 2:
      F[1:-1] = S_pos[2:] - S_pos[:-2]
    fn = np.linalg.norm(F, axis=1)
    good = fn > 1e-12
    F[good] /= fn[good, None]
    F[~good] = np.array([1.0, 0.0, 0.0])

    # Right vectors: rv = fv x normal; fix degenerates; re-orthonormalize fv = normal x rv
    R = np.cross(F, S_n)
    rn = np.linalg.norm(R, axis=1)
    rgood = rn > 1e-12

    if not np.all(rgood):
      bad_idx = np.where(~rgood)[0]
      if bad_idx.size > 0:
        # Choose alt axis per row to avoid collinearity
        alt = np.tile(np.array([1.0, 0.0, 0.0]), (rows, 1))
        use_y = (np.abs(S_n[:, 0]) >= 0.9)
        alt[use_y] = np.array([0.0, 1.0, 0.0])
        R_alt = np.cross(S_n, alt)
        R[~rgood] = R_alt[~rgood]
        rn = np.linalg.norm(R, axis=1)
        rgood = rn > 1e-12

    R[rgood] /= rn[rgood, None]
    if np.any(~rgood):
      R[~rgood] = np.array([1.0, 0.0, 0.0])

    F = np.cross(S_n, R)
    fn2 = np.linalg.norm(F, axis=1)
    fgood = fn2 > 1e-12
    F[fgood] /= fn2[fgood, None]
    if np.any(~fgood):
      F[~fgood] = np.array([1.0, 0.0, 0.0])

    # Left/right edges and bottoms
    half = (S_w * 0.5)[:, None]                 # (rows, 1)
    p0 = S_pos - R * half                       # left
    p2 = S_pos + R * half                       # right
    pb0 = p0 - S_n * S_d[:, None]               # bottom-left
    pb2 = p2 - S_n * S_d[:, None]               # bottom-right

    # V rows (accum texture V)
    diffs = np.diff(S_pos, axis=0)
    seglen = np.linalg.norm(diffs, axis=1)
    v_rows = np.concatenate(([0.0], np.cumsum(seglen) / max(1e-6, texture_length)))

    # Build top grid
    cols_top = width_subdiv + 2
    tcols = np.linspace(0.0, 1.0, cols_top, dtype=np.float64)  # 0..1
    top_pts = p0[:, None, :] + (p2 - p0)[:, None, :] * tcols[None, :, None]  # (rows, cols_top, 3)
    top_verts = top_pts.reshape(-1, 3)
    top_U = (1.0 - tcols)[None, :].repeat(rows, axis=0).reshape(-1)
    top_V = v_rows[:, None].repeat(cols_top, axis=1).reshape(-1)
    top_uvs = np.stack([top_U, top_V], axis=1)

    # Bottom strip: [pb2, pb0] per row
    bot_pts = np.stack([pb2, pb0], axis=1)  # (rows, 2, 3)
    bot_verts = bot_pts.reshape(-1, 3)
    bot_U = np.tile(np.array([0.0, 1.0]), rows)
    bot_V = np.repeat(v_rows, 2)
    bot_uvs = np.stack([bot_U, bot_V], axis=1)

    # Left strip: [p0, pb0]
    left_pts = np.stack([p0, pb0], axis=1)  # (rows, 2, 3)
    left_verts = left_pts.reshape(-1, 3)
    left_U = np.tile(np.array([1.0, 0.0]), rows)
    left_V = np.repeat(v_rows, 2)
    left_uvs = np.stack([left_U, left_V], axis=1)

    # Right strip: [p2, pb2]
    right_pts = np.stack([p2, pb2], axis=1)  # (rows, 2, 3)
    right_verts = right_pts.reshape(-1, 3)
    right_U = np.tile(np.array([1.0, 0.0]), rows)
    right_V = np.repeat(v_rows, 2)
    right_uvs = np.stack([right_U, right_V], axis=1)

    # Concatenate verts and uvs in the same order as original
    verts_arr = np.vstack([top_verts, bot_verts, left_verts, right_verts])
    uvs_arr = np.vstack([top_uvs, bot_uvs, left_uvs, right_uvs])

    # Faces
    faces = []
    # Top grid faces
    base_top = 0
    colsp1 = cols_top
    rr = np.repeat(np.arange(rows - 1), cols_top - 1)
    cc = np.tile(np.arange(cols_top - 1), rows - 1)
    a = base_top + rr * colsp1 + cc
    b = a + 1
    d = a + colsp1
    e = d + 1
    faces_top = np.stack([a, b, e, d], axis=1)

    # Bottom faces
    base_bottom = verts_arr.shape[0] - (rows * 2 + rows * 2 + rows * 2)  # start of bottom in concat
    base_bottom = top_verts.shape[0]
    j = np.arange(rows - 1)
    a = base_bottom + j * 2 + 0
    b = base_bottom + j * 2 + 1
    d = base_bottom + (j + 1) * 2 + 0
    e = base_bottom + (j + 1) * 2 + 1
    faces_bottom = np.stack([a, b, e, d], axis=1)

    # Left faces
    base_left = base_bottom + rows * 2
    a = base_left + j * 2 + 0
    b = base_left + j * 2 + 1
    d = base_left + (j + 1) * 2 + 0
    e = base_left + (j + 1) * 2 + 1
    faces_left = np.stack([a, b, e, d], axis=1)

    # Right faces
    base_right = base_left + rows * 2
    a = base_right + j * 2 + 0
    b = base_right + j * 2 + 1
    d = base_right + (j + 1) * 2 + 0
    e = base_right + (j + 1) * 2 + 1
    faces_right = np.stack([a, b, e, d], axis=1)

    # Caps
    def top_idx(rw, cl): return base_top + rw * cols_top + cl
    def bot_idx(rw, cl): return base_bottom + rw * 2 + cl
    cap0 = np.array([top_idx(0, 0), top_idx(0, cols_top - 1), bot_idx(0, 1), bot_idx(0, 0)], dtype=np.int32)
    lr = rows - 1
    cap1 = np.array([top_idx(lr, 0), bot_idx(lr, 0), bot_idx(lr, 1), top_idx(lr, cols_top - 1)], dtype=np.int32)

    faces_all = np.vstack([faces_top, faces_bottom, faces_left, faces_right, cap0[None, :], cap1[None, :]])
    faces = [tuple(map(int, row)) for row in faces_all]

    # Convert verts/uvs to lists of tuples
    verts = [tuple(map(float, v)) for v in verts_arr.tolist()]
    uvs = [tuple(map(float, uv)) for uv in uvs_arr.tolist()]

  else:
    # Fallback: original scalar implementation
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

  rows = int(round(len(verts) / ( (width_subdiv + 2) + 2 + 2 + 2 )))  # safe only if NumPy path used; but counts below don't rely on this
  cols_top = width_subdiv + 2
  top_faces = (rows - 1) * (cols_top - 1) if rows >= 2 else 0
  bottom_faces = (rows - 1) if rows >= 2 else 0
  side_left = (rows - 1) if rows >= 2 else 0
  side_right = (rows - 1) if rows >= 2 else 0
  idx = 0
  num_slots = len(me.materials)
  def safe_set(mat_idx):
    return min(mat_idx, max(0, num_slots - 1))
  if num_slots > 0 and len(me.polygons) > 0:
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