# ##### BEGIN LICENSE BLOCK #####
#
# This program is licensed under The MIT License:
# see LICENSE for the full license text
#
# ##### END LICENSE BLOCK #####

import bpy
import math
import mathutils
from mathutils import Vector, Matrix
from mathutils.bvhtree import BVHTree

from ..utils.bpy_helpers import ensure_collection, link_object_to_collection
from .common import get_unit_plane_mesh, _assign_uvs_from_vertex_uvs, _smooth_all_polys

def _build_uv_rects_for_decal(defn: dict):
  rects = []
  coords = defn.get('textureCoords')
  if isinstance(coords, list) and len(coords):
    for r in coords:
      try:
        u0, v0, du, dv = float(r[0]), float(r[1]), float(r[2]), float(r[3])
        rects.append((u0, v0, du, dv))
      except Exception:
        pass
    return rects
  rows = int(defn.get('texRows') or 1)
  cols = int(defn.get('texCols') or 1)
  if rows <= 1 and cols <= 1:
    return [(0.0, 0.0, 1.0, 1.0)]
  du = 1.0 / float(max(rows, 1))
  dv = 1.0 / float(max(cols, 1))
  for colId in range(cols):
    for rowId in range(rows):
      u0 = du * rowId
      v0 = dv * colId
      rects.append((u0, v0, du, dv))
  return rects

def _ensure_smooth_shading(me: bpy.types.Mesh) -> None:
  _smooth_all_polys(me)
  if hasattr(me, "use_auto_smooth"):
    try:
      me.use_auto_smooth = True
    except Exception:
      pass

def _make_uv_mapped_plane(name: str, uv_rect, flip_v=True):
  src = get_unit_plane_mesh()
  me = src.copy()
  me.name = name
  u0, v0, du, dv = uv_rect
  if flip_v:
    v0 = 1.0 - (v0 + dv)
  uvs = [
    (u0,        v0        ),  # (-1,-1)
    (u0 + du,   v0        ),  # ( 1,-1)
    (u0 + du,   v0 + dv   ),  # ( 1, 1)
    (u0,        v0 + dv   ),  # (-1, 1)
  ]
  _assign_uvs_from_vertex_uvs(me, "UVMap", uvs)
  _ensure_smooth_shading(me)
  return me

def _get_material_or_fallback(name: str):
  mat = bpy.data.materials.get(name)
  if mat:
    try:
      mat.blend_method = 'BLEND'
      if hasattr(mat, "shadow_method"):
        try:
          mat.shadow_method = 'NONE'
        except Exception:
          pass
      elif hasattr(mat, "shadow_mode"):
        try:
          mat.shadow_mode = 'NONE'
        except Exception:
          pass
      mat.use_backface_culling = True
      mat.show_transparent_back = False
    except Exception:
      pass
    return mat
  mat = bpy.data.materials.new(name=f"DecalMat_{name}")
  mat.use_nodes = True
  nt = mat.node_tree
  for n in list(nt.nodes):
    nt.nodes.remove(n)
  out = nt.nodes.new("ShaderNodeOutputMaterial")
  bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
  bsdf.inputs['Alpha'].default_value = 1.0
  nt.links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])
  mat.blend_method = 'BLEND'
  if hasattr(mat, "shadow_method"):
    try:
      mat.shadow_method = 'NONE'
    except Exception:
      pass
  elif hasattr(mat, "shadow_mode"):
    try:
      mat.shadow_mode = 'NONE'
    except Exception:
      pass
  mat.use_backface_culling = True
  mat.show_transparent_back = False
  return mat

def _matrix_from_nt(pos, normal, tangent, size):
  n = Vector(normal).normalized()
  t = Vector(tangent).normalized()
  f = n.cross(t).normalized()
  M = Matrix((
    (t.x, f.x, n.x, pos[0]),
    (t.y, f.y, n.y, pos[1]),
    (t.z, f.z, n.z, pos[2]),
    (0.0, 0.0, 0.0, 1.0),
  ))
  S = Matrix.Identity(4)
  S[0][0] = size
  S[1][1] = size
  S[2][2] = size
  return M @ S

def _ensure_child_collection(parent_coll, child_name: str):
  name = f"{parent_coll.name}_{child_name}"
  coll = bpy.data.collections.get(name)
  if not coll:
    coll = bpy.data.collections.new(name)
  if coll.name not in [c.name for c in parent_coll.children]:
    parent_coll.children.link(coll)
  return coll

class _SceneRaycaster:
  def __init__(self, depsgraph):
    self._entries = []
    self._build(depsgraph)

  def _build(self, depsgraph):
    for obj in bpy.data.objects:
      if obj.type != 'MESH':
        continue
      if any(c.name.startswith('Decals') for c in (obj.users_collection or [])):
        continue
      try:
        eval_obj = obj.evaluated_get(depsgraph)
        me = eval_obj.to_mesh(preserve_all_data_layers=False, depsgraph=depsgraph)
        if not me or not me.polygons:
          if eval_obj:
            eval_obj.to_mesh_clear()
          continue
        verts = [v.co.copy() for v in me.vertices]
        polys = [p.vertices[:] for p in me.polygons]
        bvh = BVHTree.FromPolygons(verts, polys, all_triangles=True)
        eval_obj.to_mesh_clear()
        if not bvh:
          continue
        Mw = obj.matrix_world.copy()
        Mi = Mw.inverted_safe()
        MiT = Mi.transposed()
        self._entries.append((bvh, Mw, Mi, MiT))
      except Exception:
        pass

  def raycast(self, origin_world: Vector, dir_world: Vector, max_dist: float):
    best = None
    best_dist = max_dist
    for bvh, Mw, Mi, MiT in self._entries:
      o_local = Mi @ origin_world
      d_local = (Mi.to_3x3() @ dir_world).normalized()
      loc, normal, idx, dist = bvh.ray_cast(o_local, d_local, best_dist)
      if loc is None:
        continue
      hit_world = Mw @ loc
      n_world = (MiT.to_3x3() @ normal).normalized()
      hit_dist = (hit_world - origin_world).length
      if hit_dist < best_dist:
        best = (hit_world, n_world, hit_dist)
        best_dist = hit_dist
    return best

def _build_clipped_decal_mesh_raycast(name, uv_rect, M_world, n_world, size, clip_angle_deg, raycaster: _SceneRaycaster, grid_res: int):
  u0, v0, du, dv = uv_rect
  flip_v = True
  N = max(1, int(grid_res))
  samples = []
  cos_thr = math.cos(math.radians(float(clip_angle_deg or 89.0)))
  nW = Vector(n_world).normalized()
  max_ray = size * 0.6 + 0.01
  start_offset = size * 0.6 + 0.01

  for j in range(N + 1):
    v_fac = j / N
    y = (v_fac - 0.5)
    for i in range(N + 1):
      u_fac = i / N
      x = (u_fac - 0.5)
      local = mathutils.Vector((x, y, 0.0, 1.0))
      world_pos = (M_world @ local).to_3d()
      o1 = world_pos + nW * start_offset
      d1 = -nW
      o2 = world_pos - nW * start_offset
      d2 = nW
      hit1 = raycaster.raycast(o1, d1, max_ray)
      hit2 = raycaster.raycast(o2, d2, max_ray)
      hit = hit1 if (hit1 and (not hit2 or hit1[2] <= hit2[2])) else hit2
      if hit:
        hpos, hnorm, _ = hit
        if nW.dot(hnorm) < cos_thr:
          samples.append({'hit': False})
          continue
        uu = u0 + du * (u_fac)
        vv = v0 + dv * (v_fac)
        if flip_v:
          vv = 1.0 - vv
        samples.append({'hit': True, 'pos': hpos, 'uv': (uu, vv)})
      else:
        samples.append({'hit': False})

  verts = []
  faces = []
  uvs = []

  def sample_idx(ii, jj):
    return jj * (N + 1) + ii

  for j in range(N):
    for i in range(N):
      idx00 = sample_idx(i, j)
      idx10 = sample_idx(i + 1, j)
      idx01 = sample_idx(i, j + 1)
      idx11 = sample_idx(i + 1, j + 1)
      s00, s10, s01, s11 = samples[idx00], samples[idx10], samples[idx01], samples[idx11]

      if s00.get('hit') and s10.get('hit') and s11.get('hit'):
        base = len(verts)
        verts.extend([s00['pos'], s10['pos'], s11['pos']])
        faces.append((base, base + 1, base + 2))
        uvs.extend([s00['uv'], s10['uv'], s11['uv']])

      if s00.get('hit') and s11.get('hit') and s01.get('hit'):
        base = len(verts)
        verts.extend([s00['pos'], s11['pos'], s01['pos']])
        faces.append((base, base + 1, base + 2))
        uvs.extend([s00['uv'], s11['uv'], s01['uv']])

  if not faces:
    return None

  me = bpy.data.meshes.new(name)
  me.from_pydata([tuple(v) for v in verts], [], faces)
  me.update()
  uv_layer = me.uv_layers.new(name="UVMap") if not me.uv_layers else me.uv_layers[0]
  me.uv_layers.active = uv_layer
  for li, luv in enumerate(uvs):
    uv_layer.data[li].uv = luv
  _ensure_smooth_shading(me)
  return me

def _adaptive_grid_res(size: float) -> int:
  if size <= 2.0:
    return 10
  if size <= 6.0:
    return 8
  if size <= 15.0:
    return 6
  if size <= 30.0:
    return 5
  return 4

def build_decal_objects(ctx):
  if not ctx.decal_instances:
    return

  parent_coll = ensure_collection('Decals')

  rects_cache = {}
  for name, defn in (ctx.decal_defs or {}).items():
    rects_cache[name] = _build_uv_rects_for_decal(defn or {})

  terrain_obj = None
  for obj in bpy.data.objects:
    if obj.type == 'MESH' and 'terrain' in obj.name.lower():
      terrain_obj = obj
      break

  depsgraph = bpy.context.evaluated_depsgraph_get()
  raycaster = _SceneRaycaster(depsgraph)

  total = sum(len(v) for v in ctx.decal_instances.values())
  done = 0

  for dec_name, instances in ctx.decal_instances.items():
    subcoll = _ensure_child_collection(parent_coll, dec_name)
    mat_name = (ctx.decal_defs.get(dec_name) or {}).get('material') if ctx.decal_defs else None
    mat = _get_material_or_fallback(mat_name or dec_name)
    rects = rects_cache.get(dec_name) or [(0.0, 0.0, 1.0, 1.0)]
    max_idx = len(rects) - 1
    clip_angle = (ctx.decal_defs.get(dec_name) or {}).get('clippingAngle', 89.0)

    for inst in instances:
      try:
        rect_idx = int(inst[0]) if len(inst) > 0 else 0
        size = float(inst[1]) if len(inst) > 1 else float((ctx.decal_defs.get(dec_name) or {}).get('size') or 1.0)
        px, py, pz = float(inst[3]), float(inst[4]), float(inst[5])
        nx, ny, nz = float(inst[6]), float(inst[7]), float(inst[8])
        tx, ty, tz = float(inst[9]), float(inst[10]), float(inst[11])
        rect_idx = max(0, min(rect_idx, max_idx))
        rect = rects[rect_idx]

        M = _matrix_from_nt((px, py, pz), (nx, ny, nz), (tx, ty, tz), size)

        use_shrinkwrap = (terrain_obj is not None and abs(nz) > 0.7)

        if not use_shrinkwrap:
          grid_res = _adaptive_grid_res(size)
          me = _build_clipped_decal_mesh_raycast(f"{dec_name}_decal", rect, M, (nx, ny, nz), size, clip_angle, raycaster, grid_res)
          if me:
            obj = bpy.data.objects.new(f"{dec_name}_decal", me)
            link_object_to_collection(obj, subcoll)
            if me.materials:
              me.materials[0] = mat
            else:
              me.materials.append(mat)
            obj.matrix_world = Matrix.Identity(4)
          else:
            me = _make_uv_mapped_plane(f"{dec_name}_decal", rect, flip_v=True)
            obj = bpy.data.objects.new(f"{dec_name}_decal", me)
            link_object_to_collection(obj, subcoll)
            obj.matrix_world = M @ mathutils.Matrix.Diagonal((0.5, 0.5, 0.5, 1.0))
            obj.location += Vector((nx, ny, nz)).normalized() * 0.002
            if me.materials:
              me.materials[0] = mat
            else:
              me.materials.append(mat)
        else:
          me = _make_uv_mapped_plane(f"{dec_name}_decal", rect, flip_v=True)
          obj = bpy.data.objects.new(f"{dec_name}_decal", me)
          link_object_to_collection(obj, subcoll)
          obj.matrix_world = M @ mathutils.Matrix.Diagonal((0.5, 0.5, 0.5, 1.0))
          obj.location += Vector((nx, ny, nz)).normalized() * 0.002
          if me.materials:
            me.materials[0] = mat
          else:
            me.materials.append(mat)
          sw = obj.modifiers.new("Shrinkwrap", type='SHRINKWRAP')
          sw.wrap_method = 'PROJECT'
          sw.wrap_mode = 'OUTSIDE'
          sw.use_negative_direction = True
          sw.use_positive_direction = True
          sw.target = terrain_obj
          sw.offset = 0.002

      except Exception as e:
        print(f"Decal import error for {dec_name}: {e}")

      done += 1
      if (done & 63) == 0:
        ctx.progress.update(f"Decals: {done}/{total}", step=1)

  ctx.progress.update(f"Decals: {total}/{total}", step=1)
