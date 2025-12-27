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

  user_sw      = bool(data.get('useShrinkwrap', True))
  shrink_name  = data.get('shrinkwrapTarget')
  apply_sw     = bool(data.get('applyShrinkwrap', False))
  target_obj   = bpy.data.objects.get(shrink_name) if isinstance(shrink_name, str) else None

  use_shrinkwrap = (not include_obj) and user_sw and (target_obj is not None)

  try:
    import numpy as np
    HAS_NP = True
  except Exception:
    HAS_NP = False

  # Convert input nodes
  if HAS_NP:
    P = np.asarray([(float(n[0]), float(n[1]), float(n[2])) for n in nodes], dtype=np.float64)
    W = np.asarray([float(n[3]) for n in nodes], dtype=np.float64)
  else:
    P = [mathutils.Vector((float(n[0]), float(n[1]), float(n[2]))) for n in nodes]
    W = [float(n[3]) for n in nodes]

  ncnt = len(nodes)
  if HAS_NP:
    # Build sampled positions and widths (vectorized across t per segment)
    if improved:
      i_start = 0
      i_end = ncnt - 1 if looped else ncnt - 2
      s = smoothness
      # Precompute t arrays: interior (skip t=0) and last (include t=0..1)
      t_interior = np.arange(1, steps_per + 1, dtype=np.float64) / steps_per
      t_full = np.arange(0, steps_per + 1, dtype=np.float64) / steps_per
      pos_list = []
      wid_list = []
      for i in range(i_start, i_end + 1):
        n1, n2, n3, n4 = _dr_node_ids(i, ncnt, looped)
        c0 = P[n2]
        c1 = s * (P[n3] - P[n1])
        c2 = 2*s*P[n1] + (s - 3)*P[n2] + (3 - 2*s)*P[n3] - s*P[n4]
        c3 = -s*P[n1] + (2 - s)*P[n2] + (s - 2)*P[n3] + s*P[n4]
        w0, w1, w2, w3 = W[n1], W[n2], W[n3], W[n4]
        sw_c0 = w1
        sw_c1 = s * (w2 - w0)
        sw_c2 = 2*s*w0 + (s - 3)*w1 + (3 - 2*s)*w2 - s*w3
        sw_c3 = -s*w0 + (2 - s)*w1 + (s - 2)*w2 + s*w3

        Ts = t_full if (i == i_end) else t_interior
        tcol = Ts[:, None]
        pos_seg = c0 + c1 * tcol + c2 * (tcol * tcol) + c3 * (tcol * tcol * tcol)
        t2 = Ts * Ts; t3 = t2 * Ts
        wid_seg = sw_c0 + sw_c1 * Ts + sw_c2 * t2 + sw_c3 * t3

        pos_list.append(pos_seg)
        wid_list.append(wid_seg)

      S_pos = np.vstack(pos_list)
      S_w = np.concatenate(wid_list)
    else:
      # Linear interpolation
      t_interior = np.arange(1, steps_per + 1, dtype=np.float64) / steps_per
      t_full = np.arange(0, steps_per + 1, dtype=np.float64) / steps_per
      pos_list = []
      wid_list = []
      for i in range(ncnt - 1):
        p1, p2 = P[i], P[i+1]
        w1, w2 = W[i], W[i+1]
        Ts = t_full if (i == ncnt - 2) else t_interior
        tcol = Ts[:, None]
        pos_seg = p1 + (p2 - p1) * tcol
        wid_seg = (1.0 - Ts) * w1 + Ts * w2
        pos_list.append(pos_seg); wid_list.append(wid_seg)
      S_pos = np.vstack(pos_list)
      S_w = np.concatenate(wid_list)

    if S_pos.shape[0] < 2:
      return None

    # v_acc (accumulated length / tex_len)
    diffs = np.diff(S_pos, axis=0)
    seglen = np.linalg.norm(diffs, axis=1)
    v_acc = np.concatenate(([0.0], np.cumsum(seglen) / max(1e-6, tex_len)))

    # Forward vectors
    rows = S_pos.shape[0]
    up_vec = np.array([0.0, 0.0, 1.0], dtype=np.float64)
    F = np.empty_like(S_pos)
    F[0] = S_pos[1] - S_pos[0]
    F[-1] = S_pos[-1] - S_pos[-2]
    if rows > 2:
      F[1:-1] = S_pos[2:] - S_pos[:-2]
    fnorm = np.linalg.norm(F, axis=1)
    safe = fnorm > 1e-12
    F[safe] /= fnorm[safe, None]
    F[~safe] = np.array([1.0, 0.0, 0.0], dtype=np.float64)

    # Right vectors (cross with up)
    R = np.cross(F, up_vec[None, :])
    rnorm = np.linalg.norm(R, axis=1)
    rsafe = rnorm > 1e-12
    R[rsafe] /= rnorm[rsafe, None]
    R[~rsafe] = np.array([1.0, 0.0, 0.0], dtype=np.float64)

    # Grid build
    cols = max(2, int(width_segments))
    u_norm = np.linspace(0.0, 1.0, cols + 1, dtype=np.float64)
    lateral = (u_norm - 0.5)[None, :] * S_w[:, None]  # rows x (cols+1)
    centers = S_pos[:, None, :]  # rows x 1 x 3
    rshift = R[:, None, :] * lateral[..., None]  # rows x (cols+1) x 3
    Pgrid = centers + rshift

    # Z offset for shrinkwrap or decals
    if use_shrinkwrap:
      Pgrid[..., 2] += float(up_clearance)
    else:
      Pgrid[..., 2] += float(decal_bias + surface_bias + layer_offset)

    verts = [tuple(map(float, v)) for v in Pgrid.reshape(-1, 3)]
    Us = np.broadcast_to(u_norm[None, :], (rows, cols + 1)).reshape(-1)
    Vs = np.broadcast_to(v_acc[:, None], (rows, cols + 1)).reshape(-1)
    uvs = list(zip(Us.tolist(), Vs.tolist()))

    # Faces
    colsp1 = cols + 1
    rr = np.repeat(np.arange(rows - 1), cols)
    cc = np.tile(np.arange(cols), rows - 1)
    a = rr * colsp1 + cc
    faces = np.stack([a, a + 1, a + 1 + colsp1, a + colsp1], axis=1).tolist()

    if looped and rows > 2:
      c = np.arange(cols)
      a2 = (rows - 1) * colsp1 + c
      faces2 = np.stack([a2, a2 + 1, c + 1, c], axis=1).tolist()
      faces.extend(faces2)

    faces = [tuple(map(int, f)) for f in faces]

  else:
    P = [mathutils.Vector((float(n[0]), float(n[1]), float(n[2]))) for n in nodes]
    W = [float(n[3]) for n in nodes]
    S_pos, S_w = [], []

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
        if use_shrinkwrap:
          best_z = p.z + float(up_clearance)
        else:
          best_z = p.z + float(decal_bias + surface_bias + layer_offset)

        z_row.append(best_z)
      z_row = _dr_fill_row_holes(z_row)
      for idx, (u_norm, px, py) in enumerate(row_xy):
        z = z_row[idx]
        if z is None:
          z = center.z + (float(up_clearance) if use_shrinkwrap else 0.0)
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

  if use_shrinkwrap:
    mod = obj.modifiers.new("DR_Shrinkwrap", type='SHRINKWRAP')
    mod.wrap_method = 'PROJECT'
    mod.use_project_x = False
    mod.use_project_y = False
    mod.use_project_z = True
    mod.use_positive_direction = False
    mod.use_negative_direction = True
    mod.cull_face = 'OFF'
    mod.project_limit = float(up_clearance + max_down)
    mod.offset = float(decal_bias + surface_bias + layer_offset)
    mod.target = target_obj
    if apply_sw:
      try:
        dg = bpy.context.evaluated_depsgraph_get()
        obj_eval = obj.evaluated_get(dg)
        tmp = obj_eval.to_mesh()
        try:
          new_me = bpy.data.meshes.new(me.name + "_sw")
          new_me.from_mesh(tmp)
          obj.modifiers.clear()
          obj.data = new_me
        finally:
          obj_eval.to_mesh_clear()
      except Exception:
        pass
  else:
    if shrink_name and not target_obj:
      print(f"[DecalRoad] Shrinkwrap target '{shrink_name}' not found for '{name}'. Skipping shrinkwrap.")

  return obj