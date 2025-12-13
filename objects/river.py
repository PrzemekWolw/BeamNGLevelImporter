# ##### BEGIN LICENSE BLOCK #####
#
# This program is licensed under The MIT License:
# see LICENSE for the full license text
#
# ##### END LICENSE BLOCK #####

import bpy
import math
import mathutils

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

  subdivide_len = max(1e-3, float(subdivide_len or 1.0))

  try:
    import numpy as np
    HAS_NP = True
  except Exception:
    HAS_NP = False

  if HAS_NP:
    # Inputs to numpy
    P = np.asarray([(float(n[0]), float(n[1]), float(n[2])) for n in nodes], dtype=np.float64)
    W = np.asarray([float(n[3]) for n in nodes], dtype=np.float64)
    count = P.shape[0]

    # Catmull–Rom evaluators (vectorized over t)
    def cr_vec(a0, a1, a2, a3, Ts):
      T = Ts[:, None]
      T2 = T * T
      T3 = T2 * T
      return 0.5 * (2.0*a1 + (-a0 + a2)*T + (2.0*a0 - 5.0*a1 + 4.0*a2 - a3)*T2 + (-a0 + 3.0*a1 - 3.0*a2 + a3)*T3)

    def cr_scalar(a0, a1, a2, a3, Ts):
      T2 = Ts * Ts
      T3 = T2 * Ts
      return 0.5 * (2.0*a1 + (-a0 + a2)*Ts + (2.0*a0 - 5.0*a1 + 4.0*a2 - a3)*T2 + (-a0 + 3.0*a1 - 3.0*a2 + a3)*T3)

    pos_chunks = []
    wid_chunks = []

    # Cache t-arrays by step count to reduce allocations
    t_cache = {}

    for i in range(count - 1):
      # Control points with end clamping (same as original)
      p0 = P[i-1] if (i-1) >= 0 else P[i]
      p1 = P[i]
      p2 = P[i+1]
      p3 = P[i+2] if (i+2) < count else P[i+1]

      w0 = W[i-1] if (i-1) >= 0 else W[i]
      w1 = W[i]
      w2 = W[i+1]
      w3 = W[i+2] if (i+2) < count else W[i+1]

      chord = float(np.linalg.norm(p2 - p1))
      steps = max(1, int(math.ceil(chord / subdivide_len)))

      if steps not in t_cache:
        Ts_full = np.arange(0, steps + 1, dtype=np.float64) / steps    # 0..1 inclusive
        Ts_interior = Ts_full[1:]                                       # skip 0
        t_cache[steps] = (Ts_full, Ts_interior)
      else:
        Ts_full, Ts_interior = t_cache[steps]

      Ts = Ts_full if (i == 0) else Ts_interior

      pos_seg = cr_vec(p0, p1, p2, p3, Ts)            # (k, 3)
      wid_seg = cr_scalar(w0, w1, w2, w3, Ts)         # (k,)

      pos_chunks.append(pos_seg)
      wid_chunks.append(wid_seg)

    if not pos_chunks:
      return None

    S_pos = np.vstack(pos_chunks)       # (rows, 3)
    S_w = np.concatenate(wid_chunks)    # (rows,)

    rows = S_pos.shape[0]
    if rows < 2:
      return None

    # Forward vectors (centered difference), normalize, handle degenerates
    F = np.empty_like(S_pos)
    F[0] = S_pos[1] - S_pos[0]
    F[-1] = S_pos[-1] - S_pos[-2]
    if rows > 2:
      F[1:-1] = S_pos[2:] - S_pos[:-2]
    fn = np.linalg.norm(F, axis=1)
    good = fn > 1e-12
    F[good] /= fn[good, None]
    F[~good] = np.array([1.0, 0.0, 0.0])  # fallback

    # Right vectors: cross with up
    up = np.array([0.0, 0.0, 1.0], dtype=np.float64)
    Rv = np.cross(F, up[None, :])  # (rows, 3)
    rn = np.linalg.norm(Rv, axis=1)
    rsafe = rn > 1e-12
    Rv[rsafe] /= rn[rsafe, None]
    if np.any(~rsafe):
      Rv[~rsafe] = np.array([1.0, 0.0, 0.0])

    # Left/right points; force Z to center Z
    half = (S_w * 0.5)[:, None]
    L = S_pos - Rv * half
    R = S_pos + Rv * half
    L[:, 2] = S_pos[:, 2]
    R[:, 2] = S_pos[:, 2]

    # Vertices in [L0,R0, L1,R1, ...] order
    verts_arr = np.empty((rows * 2, 3), dtype=np.float64)
    verts_arr[0::2] = L
    verts_arr[1::2] = R
    verts = [tuple(map(float, v)) for v in verts_arr.tolist()]

    # Faces: (2j,2j+1,2j+3,2j+2)
    j = np.arange(rows - 1, dtype=np.int32)
    a = 2 * j
    b = a + 1
    c = a + 3
    d = a + 2
    faces = np.stack([a, b, c, d], axis=1).tolist()
    faces = [tuple(map(int, f)) for f in faces]

  else:
    P = [mathutils.Vector((float(n[0]), float(n[1]), float(n[2]))) for n in nodes]
    W = [float(n[3]) for n in nodes]

    S_pos = []
    S_w = []
    count = len(P)
    for i in range(count - 1):
      p0 = P[i-1] if i-1 >= 0 else P[i]
      p1 = P[i]
      p2 = P[i+1]
      p3 = P[i+2] if (i+2) < count else P[i+1]
      w0 = W[i-1] if i-1 >= 0 else W[i]
      w1 = W[i]
      w2 = W[i+1]
      w3 = W[i+2] if (i+2) < count else W[i+1]
      chord = (p2 - p1).length
      steps = max(1, math.ceil(chord / subdivide_len))
      for s in range(steps + 1):
        t = s / steps
        if i > 0 and s == 0:
          continue
        pos = _cr_vec(p0, p1, p2, p3, t)
        wid = _cr_float(w0, w1, w2, w3, t)
        S_pos.append(pos)
        S_w.append(wid)
    if len(S_pos) < 2:
      return None

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
      L.z = S_pos[j].z
      R.z = S_pos[j].z
      verts.append((L.x, L.y, L.z))
      verts.append((R.x, R.y, R.z))

    faces = []
    for j in range(rows - 1):
      a = 2*j
      b = a + 1
      c = a + 3
      d = a + 2
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