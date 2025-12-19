# ##### BEGIN LICENSE BLOCK #####
#
# This program is licensed under The MIT License:
# see LICENSE for the full license text
#
# ##### END LICENSE BLOCK #####

import bpy
import mathutils
import xml.etree.ElementTree as ET
from math import pi
import numpy as np

from . import collada_util as U
from .collada_reader import SourceReader
from .collada_parse import (
  build_mesh_index, resolve_input_source, classify_inputs,
  read_source_reader_from_input, triangles_from_primitive_np
)
from .collada_materials import (
  get_first_bound_material_name, build_instance_material_bindings,
  ensure_empty_material, ensure_material_slot
)
from .collada_normals import apply_custom_normals

def import_collada_file_to_blender(path, collection, up_axis='Z_UP', ignore_node_scale=False):
  U._SOURCE_FLOAT_CACHE.clear()
  U._INPUT_SR_CACHE.clear()

  tree = ET.parse(path)
  root = tree.getroot()
  created_objs = []
  unit_scale = 1.0
  asset = root.find('.//{*}asset')
  if asset is not None:
    unit_el = asset.find('{*}unit')
    if unit_el is not None and unit_el.get('meter'):
      try:
        unit_scale = float(unit_el.get('meter'))
      except Exception:
        unit_scale = 1.0
    up_el = asset.find('{*}up_axis')
    if up_el is not None and up_el.text:
      up_axis = up_el.text.strip()

  root_parent = mathutils.Matrix.Identity(4)
  if unit_scale != 1.0:
    root_parent = root_parent @ mathutils.Matrix.Scale(unit_scale, 4, (1, 0, 0))
    root_parent = root_parent @ mathutils.Matrix.Scale(unit_scale, 4, (0, 1, 0))
    root_parent = root_parent @ mathutils.Matrix.Scale(unit_scale, 4, (0, 0, 1))
  if up_axis == 'X_UP':
    rot = mathutils.Matrix(((0, 0, 1, 0), (1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 0, 1)))
    root_parent = rot @ root_parent
  elif up_axis == 'Y_UP':
    rot = mathutils.Matrix(((-1, 0, 0, 0), (0, 0, 1, 0), (0, 1, 0, 0), (0, 0, 0, 1)))
    root_parent = rot @ root_parent

  geometries_by_id = {}
  controllers_by_id = {}
  nodes_by_id = {}
  for gg in root.findall('.//{*}geometry'):
    gid = gg.get('id')
    if gid:
      geometries_by_id[gid] = gg
  for cc in root.findall('.//{*}controller'):
    cid = cc.get('id')
    if cid:
      controllers_by_id[cid] = cc
  for nd in root.findall('.//{*}node'):
    nid = nd.get('id')
    if nid:
      nodes_by_id[nid] = nd

  def node_local_matrix(transform_elements):
    m = mathutils.Matrix.Identity(4)
    for el in transform_elements:
      t = U.tag_name(el)
      vals = U.parse_floats_np(el.text or '', dtype=np.float64)
      if t == 'translate':
        m = m @ mathutils.Matrix.Translation((vals[0], vals[1], vals[2]))
      elif t == 'scale':
        if ignore_node_scale:
          continue
        m = m @ mathutils.Matrix.Scale(vals[0], 4, (1, 0, 0))
        m = m @ mathutils.Matrix.Scale(vals[1], 4, (0, 1, 0))
        m = m @ mathutils.Matrix.Scale(vals[2], 4, (0, 0, 1))
      elif t == 'rotate':
        axis = mathutils.Vector((vals[0], vals[1], vals[2]))
        ang = -vals[3] * pi / 180.0
        m = m @ mathutils.Matrix.Rotation(ang, 4, axis)
      elif t == 'matrix':
        mx = mathutils.Matrix(((vals[0], vals[1], vals[2], vals[3]),
                               (vals[4], vals[5], vals[6], vals[7]),
                               (vals[8], vals[9], vals[10], vals[11]),
                               (vals[12], vals[13], vals[14], vals[15])))
        m = m @ mx
    return m

  def max_index_ok(idx, arr_size, stride, accessor_offset=0):
    if idx is None or arr_size == 0 or idx.size == 0:
      return True
    max_idx = int(idx.max())
    usable = arr_size - int(accessor_offset)
    if usable <= 0 or stride <= 0:
      return False
    return max_idx < (usable // stride)

  def ensure_armature(name):
    base = name or "Armature"
    existing_arms = {a.name for a in bpy.data.armatures}
    arm_name = U.make_valid_name(base + "_Armature", existing=existing_arms)
    arm = bpy.data.armatures.new(arm_name)

    existing_objs = {o.name for o in bpy.data.objects}
    arm_obj_name = U.make_valid_name(base + "_ArmatureObj", existing=existing_objs)
    arm_obj = bpy.data.objects.new(arm_obj_name, arm)
    collection.objects.link(arm_obj)
    return arm, arm_obj

  def build_material_map_for_instance(inst):
    symbol_to_matname = build_instance_material_bindings(inst, root)
    matname_to_bmat = {}
    for _, mname in symbol_to_matname.items():
      bmat = bpy.data.materials.get(mname)
      if bmat is None:
        bmat = ensure_empty_material(mname)
      matname_to_bmat[mname] = bmat
    return symbol_to_matname, matname_to_bmat

  def resolve_material_name_loose(sym):
    if not sym:
      return None

    for mm in root.findall('.//{*}material'):
      mid = (mm.get('id') or '')
      mname = (mm.get('name') or '')
      if mid == sym or mname == sym:
        return mname or mid or sym

    sym_l = sym.lower()
    candidates = [sym]
    for suf in ("-material-material", "-material"):
      if sym_l.endswith(suf):
        candidates.append(sym[:-len(suf)])

    for cand in candidates:
      for mm in root.findall('.//{*}material'):
        mid = (mm.get('id') or '')
        mname = (mm.get('name') or '')
        if mid == cand or mname == cand:
          return mname or mid or cand

    return None

  def build_geometry_for_mesh(geom_el, mesh, inst_like, world, invert_geom, obj_name_hint=None):
    mesh_index = build_mesh_index(mesh)
    prims = [p for p in mesh if U.tag_name(p) in ('triangles', 'tristrips', 'trifans', 'polylist', 'polygons')]
    if not prims:
      return None, None, False

    sym2matname, _ = build_material_map_for_instance(inst_like)
    prim_face_spans = []

    pi_list = []
    uv0_list = []
    uv1_list = []
    col_list = []
    ln_list = []
    prim_pos_srs = []
    prim_pos_offsets = []
    prim_pos_strides = []

    pos_src_id = None
    sr_pos_common = None
    pos_offsets = None
    pos_stride_common = None
    total_loops = 0
    mixed_position_sources = False

    pi_list_original = []

    for prim in prims:
      inputs = prim.findall('{*}input')
      buckets, offsets, max_off = classify_inputs(inputs)
      stride = max_off + 1

      sr_pos = read_source_reader_from_input(mesh, buckets['POSITION'], [['X', 'Y', 'Z']], 'POSITION')
      sr_nor = read_source_reader_from_input(mesh, buckets['NORMAL'], [['X', 'Y', 'Z']], 'NORMAL')

      sr_col = read_source_reader_from_input(
        mesh, buckets['COLOR'],
        [['R', 'G', 'B', 'A'], ['R', 'G', 'B'], ['X', 'Y', 'Z']],
        'COLOR'
      )

      sr_uv0 = read_source_reader_from_input(mesh, buckets['TEXCOORD_0'], [['S', 'T'], ['U', 'V'], ['X', 'Y']], 'TEXCOORD')
      sr_uv1 = read_source_reader_from_input(mesh, buckets['TEXCOORD_1'], [['S', 'T'], ['U', 'V'], ['X', 'Y']], 'TEXCOORD')

      tri_rows = triangles_from_primitive_np(prim, stride)
      if tri_rows.size == 0:
        continue

      pi = tri_rows[:, offsets.get('POSITION', 0)] if 'POSITION' in offsets else None
      ni = tri_rows[:, offsets['NORMAL']] if 'NORMAL' in offsets else None
      ci = tri_rows[:, offsets['COLOR']] if 'COLOR' in offsets else None
      u0i = tri_rows[:, offsets['TEXCOORD_0']] if 'TEXCOORD_0' in offsets else None
      u1i = tri_rows[:, offsets['TEXCOORD_1']] if 'TEXCOORD_1' in offsets else None

      pos_arr = sr_pos.float_array_np() if sr_pos else np.empty(0, np.float32)
      nor_arr = sr_nor.float_array_np() if sr_nor else np.empty(0, np.float32)
      col_arr = sr_col.float_array_np() if sr_col else np.empty(0, np.float32)
      uv0_arr = sr_uv0.float_array_np() if sr_uv0 else np.empty(0, np.float32)
      uv1_arr = sr_uv1.float_array_np() if sr_uv1 else np.empty(0, np.float32)

      if pi is None or pos_arr.size == 0:
        continue

      pos_stride = sr_pos.stride() if sr_pos else 0
      if not max_index_ok(pi, pos_arr.size, pos_stride, sr_pos.accessor_offset if sr_pos else 0):
        continue

      nor_stride = sr_nor.stride() if sr_nor else 0
      if ni is not None and (nor_arr.size == 0 or not max_index_ok(ni, nor_arr.size, nor_stride, sr_nor.accessor_offset if sr_nor else 0)):
        ni = None

      uv0_stride = sr_uv0.stride() if sr_uv0 else 0
      if u0i is not None and (uv0_arr.size == 0 or not max_index_ok(u0i, uv0_arr.size, uv0_stride, sr_uv0.accessor_offset if sr_uv0 else 0)):
        u0i = None

      uv1_stride = sr_uv1.stride() if sr_uv1 else 0
      if u1i is not None and (uv1_arr.size == 0 or not max_index_ok(u1i, uv1_arr.size, uv1_stride, sr_uv1.accessor_offset if sr_uv1 else 0)):
        u1i = None

      col_stride = sr_col.stride() if sr_col else 0
      if ci is not None and (col_arr.size == 0 or not max_index_ok(ci, col_arr.size, col_stride, sr_col.accessor_offset if sr_col else 0)):
        ci = None

      this_src_id = sr_pos.source.get('id') if (sr_pos and sr_pos.source is not None) else id(sr_pos)
      if pos_src_id is None:
        pos_src_id = this_src_id
        sr_pos_common = sr_pos
        pos_offsets = sr_pos.offsets or [0, 1, 2]
        pos_stride_common = pos_stride
      elif pos_src_id != this_src_id:
        mixed_position_sources = True

      this_faces = (pi.shape[0] // 3)
      prim_face_spans.append((total_loops // 3, this_faces, prim.get('material') or ''))

      pi_list_original.append(pi.astype(np.int64, copy=False))
      pi_list.append(pi.astype(np.int64, copy=False))
      prim_pos_srs.append(sr_pos)
      prim_pos_offsets.append(sr_pos.offsets or [0, 1, 2])
      prim_pos_strides.append(pos_stride)
      total_loops += pi.shape[0]

      def gather3(arr, idx, stride, o0, o1, o2, accessor_offset=0):
        base = accessor_offset + (idx.astype(np.int64, copy=False) * stride)
        return np.stack([
          arr[base + o0],
          arr[base + o1],
          arr[base + o2]
        ], axis=1).astype(np.float32, copy=False)

      def gather2(arr, idx, stride, o0, o1, accessor_offset=0):
        base = accessor_offset + (idx.astype(np.int64, copy=False) * stride)
        return np.stack([
          arr[base + o0],
          arr[base + o1]
        ], axis=1).astype(np.float32, copy=False)

      loop_n = None
      if ni is not None and nor_arr.size > 0 and sr_nor:
        no = sr_nor.offsets or [0, 1, 2]
        loop_n = gather3(
          nor_arr, ni, nor_stride,
          U.comp(no, 0, 0), U.comp(no, 1, 1), U.comp(no, 2, 2),
          sr_nor.accessor_offset
        )
        norms = np.linalg.norm(loop_n, axis=1, keepdims=True)
        norms[norms < 1e-8] = 1.0
        loop_n = loop_n / norms

      loop_c = None
      if ci is not None and col_arr.size and sr_col:
        co = sr_col.offsets or [0, 1, 2]
        base = sr_col.accessor_offset + (ci.astype(np.int64, copy=False) * col_stride)
        cr = col_arr[base + U.comp(co, 0, 0)]
        cg = col_arr[base + U.comp(co, 1, 1)]
        cb = col_arr[base + U.comp(co, 2, 2)]
        ca = np.ones_like(cr, dtype=np.float32)
        if col_stride >= 4 and (sr_col.offsets is not None) and len(sr_col.offsets) >= 4 and sr_col.offsets[3] is not None:
          ca = col_arr[base + int(sr_col.offsets[3])]
        loop_c = np.stack([cr, cg, cb, ca], axis=1).astype(np.float32, copy=False)

      loop_u0 = None
      if u0i is not None and uv0_arr.size and sr_uv0:
        uo = sr_uv0.offsets or [0, 1]
        loop_u0 = gather2(
          uv0_arr, u0i, uv0_stride,
          U.comp(uo, 0, 0), U.comp(uo, 1, 1),
          sr_uv0.accessor_offset
        )

      loop_u1 = None
      if u1i is not None and uv1_arr.size and sr_uv1:
        uo1 = sr_uv1.offsets or [0, 1]
        loop_u1 = gather2(
          uv1_arr, u1i, uv1_stride,
          U.comp(uo1, 0, 0), U.comp(uo1, 1, 1),
          sr_uv1.accessor_offset
        )

      uv0_list.append(loop_u0)
      uv1_list.append(loop_u1)
      col_list.append(loop_c)
      ln_list.append(loop_n)

    if total_loops == 0:
      return None, None, False

    pi_all = np.concatenate(pi_list, axis=0).astype(np.int32, copy=False)
    pi_all_orig = np.concatenate(pi_list_original, axis=0).astype(np.int64, copy=False)
    nloops = int(pi_all.shape[0])
    nfaces = nloops // 3

    use_shared_vertices = (sr_pos_common is not None) and not mixed_position_sources

    if use_shared_vertices:
      max_pi = int(pi_all.max()) if pi_all.size else -1
      nv = max_pi + 1
      pos_arr_all = sr_pos_common.float_array_np()
      o = pos_offsets or [0, 1, 2]
      s = pos_stride_common or 3
      idx_all = np.arange(nv, dtype=np.int64)
      base = sr_pos_common.accessor_offset + idx_all * s
      xs = pos_arr_all[base + U.comp(o, 0, 0)]
      ys = pos_arr_all[base + U.comp(o, 1, 1)]
      zs = pos_arr_all[base + U.comp(o, 2, 2)]
      verts_np = np.stack([xs, ys, zs], axis=1).astype(np.float32, copy=False)
    else:
      loop_pos_chunks = []
      for pi_chunk, sr_chunk, s_chunk, o_chunk in zip(pi_list, prim_pos_srs, prim_pos_strides, prim_pos_offsets):
        arr = sr_chunk.float_array_np() if sr_chunk else np.empty(0, np.float32)
        if arr.size and pi_chunk.size:
          base = sr_chunk.accessor_offset + (pi_chunk.astype(np.int64, copy=False) * s_chunk)
          xs = arr[base + U.comp(o_chunk, 0, 0)]
          ys = arr[base + U.comp(o_chunk, 1, 1)]
          zs = arr[base + U.comp(o_chunk, 2, 2)]
          loop_pos_chunks.append(np.stack([xs, ys, zs], axis=1))
        else:
          loop_pos_chunks.append(np.zeros((pi_chunk.shape[0], 3), dtype=np.float32))
      verts_np = np.concatenate(loop_pos_chunks, axis=0).astype(np.float32, copy=False)
      pi_all = np.arange(nloops, dtype=np.int32)

    if invert_geom:
      verts_np[:, 2] *= -1.0

    uv0_np = None
    if any(u is not None for u in uv0_list):
      uv0_np = np.concatenate(
        [u if u is not None else np.zeros((p.shape[0], 2), np.float32)
         for u, p in zip(uv0_list, pi_list)],
        axis=0
      ).astype(np.float32, copy=False)

    uv1_np = None
    if any(u is not None for u in uv1_list):
      uv1_np = np.concatenate(
        [u if u is not None else np.zeros((p.shape[0], 2), np.float32)
         for u, p in zip(uv1_list, pi_list)],
        axis=0
      ).astype(np.float32, copy=False)

    cols_np = None
    if any(c is not None for c in col_list):
      cols_np = np.concatenate(
        [c if c is not None else np.ones((p.shape[0], 4), np.float32)
         for c, p in zip(col_list, pi_list)],
        axis=0
      ).astype(np.float32, copy=False)

    geom_name = (
      geom_el.get('name') or
      geom_el.get('id') or
      mesh.get('name') or
      mesh.get('id') or
      'Mesh'
    )
    existing_meshes = {m.name for m in bpy.data.meshes}
    mesh_name = U.make_valid_name(geom_name, existing=existing_meshes)
    me = bpy.data.meshes.new(mesh_name)
    me.vertices.add(verts_np.shape[0])
    me.vertices.foreach_set("co", verts_np.ravel(order='C'))
    me.loops.add(nloops)
    me.loops.foreach_set("vertex_index", pi_all.astype(np.int32, copy=False))
    me.polygons.add(nfaces)
    me.polygons.foreach_set("loop_start", (np.arange(nfaces, dtype=np.int32) * 3))
    me.polygons.foreach_set("loop_total", np.full(nfaces, 3, dtype=np.int32))
    me.polygons.foreach_set("use_smooth", np.ones(nfaces, dtype=bool))

    symbol_to_matindex = {}
    for sym, mname in sym2matname.items():
      bmat = ensure_empty_material(mname)
      if bmat:
        symbol_to_matindex[sym] = ensure_material_slot(me, bmat)

    fallback_name = get_first_bound_material_name(inst_like, root) or "Default"
    fallback_mat = ensure_empty_material(fallback_name)
    fallback_index = ensure_material_slot(me, fallback_mat) if fallback_mat else 0

    instance_bound_names = list(sym2matname.values())
    single_bound_name = instance_bound_names[0] if len(set(instance_bound_names)) == 1 and instance_bound_names else None
    single_bound_index = None
    if single_bound_name:
      single_bound_mat = ensure_empty_material(single_bound_name)
      if single_bound_mat:
        single_bound_index = ensure_material_slot(me, single_bound_mat)

    face_material_indices = np.full(nfaces, fallback_index, dtype=np.int32)
    for fstart, fcount, sym in prim_face_spans:
      if fcount <= 0:
        continue

      midx = symbol_to_matindex.get(sym)

      if midx is None:
        mname2 = resolve_material_name_loose(sym)
        if mname2:
          bmat2 = ensure_empty_material(mname2)
          midx = ensure_material_slot(me, bmat2) if bmat2 else fallback_index
        elif single_bound_index is not None:
          midx = single_bound_index
        else:
          midx = fallback_index

      face_material_indices[fstart:fstart + fcount] = midx

    me.polygons.foreach_set("material_index", face_material_indices)

    if uv0_np is not None and uv0_np.size == nloops * 2:
      uv0_layer = me.uv_layers.new(name="UVMap")
      uv0_layer.data.foreach_set("uv", uv0_np.ravel(order='C'))
    if uv1_np is not None and uv1_np.size == nloops * 2:
      uv1_layer = me.uv_layers.new(name="UVMap2")
      uv1_layer.data.foreach_set("uv", uv1_np.ravel(order='C'))

    if cols_np is not None and cols_np.size == nloops * 4:
      vcol = me.color_attributes.new(name="Col", type='FLOAT_COLOR', domain='CORNER')
      vcol.data.foreach_set("color", cols_np.ravel(order='C'))
      try:
        me.color_attributes.active_color = vcol
      except Exception:
        pass

    try:
      me.validate(clean_customdata=True)
    except Exception:
      pass
    me.update(calc_edges=True)

    inst_name = (
      (inst_like.get('name') or inst_like.get('sid') or inst_like.get('symbol') or '').strip()
      if hasattr(inst_like, 'get') else ''
    )
    obj_base = inst_name or geom_name or mesh_name

    existing_objs = {o.name for o in bpy.data.objects}
    obj_name = U.make_valid_name(obj_base, existing=existing_objs)
    obj = bpy.data.objects.new(obj_name, me)
    obj.matrix_world = world
    collection.objects.link(obj)

    if any((n is not None) for n in ln_list):
      ln_np = np.concatenate(
        [n if n is not None else np.zeros((p.shape[0], 3), np.float32)
         for n, p in zip(ln_list, pi_list)],
        axis=0
      ).astype(np.float32, copy=False)
      if invert_geom:
        ln_np[:, 2] *= -1.0
      apply_custom_normals(me, ln_np)

    return obj, pi_all_orig, use_shared_vertices

  def process_skin_controller(ctrl_el, inst_ctrl, parent_world):
    skin = ctrl_el.find('{*}skin')
    if skin is None:
      return
    src_url = skin.find('{*}source').get('url') or ''
    if src_url.startswith('#'):
      src_url = src_url[1:]
    geom = geometries_by_id.get(src_url)
    if geom is None:
      return
    mesh = geom.find('{*}mesh')
    if mesh is None:
      return

    invert_geom = False
    ctrl_name = ctrl_el.get('name') or ctrl_el.get('id') or 'Skin'
    obj, pi_per_loop, use_shared = build_geometry_for_mesh(
      geom, mesh, inst_ctrl, parent_world, invert_geom,
      obj_name_hint=ctrl_name
    )
    if obj is None:
      return
    me = obj.data

    joints_el = skin.find('{*}joints')
    vw_el = skin.find('{*}vertex_weights')
    if joints_el is None or vw_el is None:
      return

    def sr_from_inputs(parent, sem, desired):
      for ip in parent.findall('{*}input'):
        if (ip.get('semantic') or '').upper() == sem:
          url = ip.get('source') or ''
          if url.startswith('#'):
            url = url[1:]
          src = None
          for s in skin.findall('{*}source'):
            if s.get('id') == url:
              src = s
              break
          if src is None:
            for s in skin.iter('{*}source'):
              if s.get('id') == url:
                src = s
                break
          if src is None:
            return None
          return SourceReader(src, desired)
      return None

    sr_joint_names = sr_from_inputs(joints_el, 'JOINT', ['JOINT'])
    sr_weights = sr_from_inputs(vw_el, 'WEIGHT', ['WEIGHT'])
    if sr_joint_names is None or sr_weights is None:
      return

    arm, arm_obj = ensure_armature(obj.name)
    arm_obj.matrix_world = mathutils.Matrix.Identity(4)
    bpy.context.view_layer.update()
    bpy.context.view_layer.objects.active = arm_obj
    bpy.ops.object.mode_set(mode='EDIT')
    joint_count = sr_joint_names.size()
    for j in range(joint_count):
      jname = sr_joint_names.getStringValue(j) or f"J{j}"
      eb = arm.edit_bones.new(jname)
      node = nodes_by_id.get(jname)
      head = mathutils.Vector((0, 0, 0))
      tail = mathutils.Vector((0, 0.1, 0))
      if node is not None:
        tx = [c for c in node if U.tag_name(c) in ('translate', 'rotate', 'scale', 'matrix', 'skew', 'lookat')]
        mat = node_local_matrix(tx)
        head = (parent_world @ mat).to_translation()
        tail = head + mathutils.Vector((0, 0.1, 0))
      eb.head = head
      eb.tail = tail
    bpy.ops.object.mode_set(mode='OBJECT')
    obj.parent = arm_obj
    arm_mod = obj.modifiers.new(name="Armature", type='ARMATURE')
    arm_mod.object = arm_obj

    for j in range(joint_count):
      jname = sr_joint_names.getStringValue(j) or f"J{j}"
      if jname not in obj.vertex_groups:
        obj.vertex_groups.new(name=jname)

    vcount_arr = U.parse_ints_np(vw_el.find('{*}vcount').text, dtype=np.int64)
    v_arr = U.parse_ints_np(vw_el.find('{*}v').text, dtype=np.int64)
    inputs = vw_el.findall('{*}input')
    offs = {}
    max_off = 0
    for ip in inputs:
      off = int(ip.get('offset') or 0)
      max_off = max(max_off, off)
      offs[(ip.get('semantic') or '').upper()] = off
    stride = max_off + 1

    idx = 0
    nv = len(me.vertices)
    weights_arr = sr_weights.float_array_np(dtype=np.float32)
    for vtx in range(vcount_arr.size):
      n_infl = int(vcount_arr[vtx])
      for _ in range(n_infl):
        j_idx = v_arr[idx + offs.get('JOINT', 0)]
        w_idx = v_arr[idx + offs.get('WEIGHT', 0)]
        idx += stride
        if j_idx < 0 or w_idx < 0:
          continue
        if j_idx >= sr_joint_names.size():
          continue
        w = float(weights_arr[sr_weights.accessor_offset + int(w_idx)])
        if w == 0.0:
          continue
        jname = sr_joint_names.getStringValue(int(j_idx)) or f"J{int(j_idx)}"
        vg = obj.vertex_groups.get(jname)
        if vg is None:
          continue
        if use_shared:
          target_vid = vtx if vtx < nv else (nv - 1)
          vg.add([target_vid], w, 'ADD')
        else:
          mask = (pi_per_loop == vtx)
          loop_indices = np.nonzero(mask)[0].astype(np.int32)
          for li in loop_indices:
            if li < nv:
              vg.add([int(li)], float(w), 'ADD')

  def process_morph_controller(ctrl_el, inst_ctrl, parent_world):
    morph = ctrl_el.find('{*}morph')
    if morph is None:
      return
    src_el = morph.find('{*}source')
    base_url = src_el.get('url') or ''
    if base_url.startswith('#'):
      base_url = base_url[1:]
    base_geom = geometries_by_id.get(base_url)
    if base_geom is None:
      return
    base_mesh = base_geom.find('{*}mesh')
    if base_mesh is None:
      return
    invert_geom = False
    ctrl_name = ctrl_el.get('name') or ctrl_el.get('id') or 'Morph'
    base_obj, pi_per_loop, use_shared = build_geometry_for_mesh(
      base_geom, base_mesh, inst_ctrl, parent_world, invert_geom,
      obj_name_hint=ctrl_name
    )
    if base_obj is None:
      return
    me = base_obj.data

    targets_el = morph.find('{*}targets')
    if targets_el is None:
      return

    def read_sr(parent, sem, desired):
      for ip in parent.findall('{*}input'):
        if (ip.get('semantic') or '').upper() == sem:
          url = ip.get('source') or ''
          if url.startswith('#'):
            url = url[1:]
          for s in morph.findall('{*}source'):
            if s.get('id') == url:
              return SourceReader(s, desired)
      return None

    sr_targets = read_sr(targets_el, 'MORPH_TARGET', ['JOINT'])
    if sr_targets is None:
      return

    if me.shape_keys is None:
      base_obj.shape_key_add(name="Basis", from_mix=False)

    tgt_count = sr_targets.size()
    for i in range(tgt_count):
      gid = sr_targets.getStringValue(i)
      tgeom = geometries_by_id.get(gid)
      if tgeom is None:
        for g in root.findall('.//{*}geometry'):
          if (g.get('id') or '') == gid:
            tgeom = g
            break
      if tgeom is None:
        continue
      tmesh = tgeom.find('{*}mesh')
      if tmesh is None:
        continue

      prims = [p for p in tmesh if U.tag_name(p) in ('triangles', 'polylist', 'polygons', 'tristrips', 'trifans')]
      if not prims:
        continue
      buckets, _, _ = classify_inputs(prims[0].findall('{*}input'))
      sr_pos = read_source_reader_from_input(tmesh, buckets['POSITION'], [['X', 'Y', 'Z']], 'POSITION')
      if sr_pos is None:
        continue
      tarr = sr_pos.float_array_np()
      s = sr_pos.stride()
      o = sr_pos.offsets or [0, 1, 2]
      count = sr_pos.size()
      idx_all = np.arange(count, dtype=np.int64)
      base = sr_pos.accessor_offset + idx_all * s
      tx = tarr[base + U.comp(o, 0, 0)]
      ty = tarr[base + U.comp(o, 1, 1)]
      tz = tarr[base + U.comp(o, 2, 2)]
      tpos = np.stack([tx, ty, tz], axis=1).astype(np.float32, copy=False)

      tname_raw = tgeom.get('name') or tgeom.get('id') or f"Target_{i}"
      existing_sk = {k.name for k in (me.shape_keys.key_blocks or [])}
      sk_name = U.make_valid_name(tname_raw, existing=existing_sk)
      key = base_obj.shape_key_add(name=sk_name, from_mix=False)
      co = np.zeros((len(me.vertices), 3), dtype=np.float32)
      if use_shared and len(me.vertices) <= tpos.shape[0]:
        co[:len(me.vertices), :] = tpos[:len(me.vertices), :]
      else:
        idx = np.clip(pi_per_loop, 0, tpos.shape[0] - 1)
        co = tpos[idx, :]
      if co.shape[0] != len(me.vertices):
        co = np.resize(co, (len(me.vertices), 3))
      key.data.foreach_set("co", co.ravel(order='C'))

  def process_node(dom_node, parent_world, parent_obj=None):
    tx_elems = [c for c in dom_node if U.tag_name(c) in ('translate', 'rotate', 'scale', 'matrix', 'skew', 'lookat')]
    local = node_local_matrix(tx_elems)
    world = parent_world @ local
    invert_geom = (U.mat_det(world) < 0.0)
    if invert_geom:
      world = world @ mathutils.Matrix.Scale(-1.0, 4, (0, 0, 1))

    inst_geoms = list(dom_node.findall('{*}instance_geometry'))
    inst_ctrls = list(dom_node.findall('{*}instance_controller'))

    this_parent_obj = parent_obj
    if not inst_geoms and not inst_ctrls:
      has_children = bool(dom_node.findall('{*}node') or dom_node.findall('{*}instance_node'))
      if has_children or tx_elems:
        nid = dom_node.get('id') or ''
        nname = dom_node.get('name') or nid or 'Empty'
        existing_objs = {o.name for o in bpy.data.objects}
        empty_name = U.make_valid_name(nname, existing=existing_objs)
        empty = bpy.data.objects.new(empty_name, None)
        empty.empty_display_type = 'PLAIN_AXES'
        empty.matrix_world = world
        collection.objects.link(empty)
        if parent_obj:
          empty.parent = parent_obj
        this_parent_obj = empty

    for inst in inst_geoms:
      url = inst.get('url', '')
      if url.startswith('#'):
        url = url[1:]
      geom = geometries_by_id.get(url)
      if geom is None:
        continue
      mesh = geom.find('{*}mesh')
      if mesh is None:
        continue
      obj, _, _ = build_geometry_for_mesh(geom, mesh, inst, world, invert_geom)
      if obj:
        if parent_obj:
          obj.parent = parent_obj
        created_objs.append(obj)

    for instc in inst_ctrls:
      curl = instc.get('url') or ''
      if curl.startswith('#'):
        curl = curl[1:]
      ctrl = controllers_by_id.get(curl)
      if ctrl is None:
        continue
      if ctrl.find('{*}skin') is not None:
        process_skin_controller(ctrl, instc, world)
      elif ctrl.find('{*}morph') is not None:
        process_morph_controller(ctrl, instc, world)

    for child in dom_node.findall('{*}node'):
      process_node(child, world, parent_obj=this_parent_obj)

    for instn in dom_node.findall('{*}instance_node'):
      ref = instn.get('url') or ''
      if ref.startswith('#'):
        ref = ref[1:]
      refnode = nodes_by_id.get(ref)
      if refnode is not None:
        process_node(refnode, world, parent_obj=this_parent_obj)

  for vscene in root.findall('.//{*}visual_scene'):
    for top_node in vscene.findall('{*}node'):
      process_node(top_node, root_parent, parent_obj=None)

  try:
    for o in bpy.context.selected_objects:
      o.select_set(False)
    for o in created_objs:
      o.select_set(True)
    if created_objs:
      bpy.context.view_layer.objects.active = created_objs[-1]
  except Exception:
    pass

  return created_objs
