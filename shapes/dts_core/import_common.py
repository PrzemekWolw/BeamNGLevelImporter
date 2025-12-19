# ##### BEGIN LICENSE BLOCK #####
#
# This program is licensed under The MIT License:
# see LICENSE for the full license text
#
# ##### END LICENSE BLOCK #####

import bpy, mathutils, bmesh
from .tsshape import *
from .tsmesh import TSMesh, TSSkinnedMesh, TSNullMesh, TSMeshFlags

def triangle_strip_to_list(strip, clockwise):
  triangle_list = []
  for v in range(len(strip) - 2):
    if clockwise:
      triangle_list.extend([strip[v + 1], strip[v], strip[v + 2]])
    else:
      triangle_list.extend([strip[v], strip[v + 1], strip[v + 2]])
    clockwise = not clockwise
  return triangle_list

def create_material(material_name):
  mtl = bpy.data.materials.get(material_name)
  if mtl is None:
    mtl = bpy.data.materials.new(name=material_name)
    mtl.diffuse_color = (1.0, 1.0, 1.0, 1.0)
    mtl.specular_intensity = 0
    mtl.use_nodes = True
    mtl.use_backface_culling = True
  return mtl

def translate_uv(uv):
  return (uv[0], 1.0 - uv[1])

def translate_vert(vert):
  return (vert[0], vert[1], vert[2])

def _is_collision_name(lname: str) -> bool:
  return lname.startswith(("colmesh", "colbox", "colsphere", "colcapsule"))

def _is_pure_empty_object_name(lname: str) -> bool:
  if (lname.startswith("base") and lname[4:].isdigit()) or (lname.startswith("start") and lname[5:].isdigit()):
    return True
  if (lname.startswith("abase") and lname[5:].isdigit()) or (lname.startswith("astart") and lname[6:].isdigit()):
    return True
  if lname == "bb_autobillboard":
    return True
  if lname.startswith("bb_"):
    return True
  if lname.startswith("nulldetail"):
    return True
  return False

# Quaternion helpers
def _quat16_to_blender_quat(q16: TQuaternion16, is_cdae: bool):
  qf = q16.to_quat_f()
  x = qf.x * (-1.0 if not is_cdae else 1.0)  # DTS legacy: flip X; CDAE: no flip
  return mathutils.Quaternion((qf.w, x, qf.y, qf.z))

def _node_local_matrix(node: ShapeNode, is_cdae: bool) -> mathutils.Matrix:
  q = _quat16_to_blender_quat(node.rotation, is_cdae)
  R = q.to_matrix().to_4x4()
  M = R.copy()
  M.translation = mathutils.Vector(node.translation)
  return M

def _compute_world_mats(shape: TSShape, is_cdae: bool):
  nodes = shape.nodes
  cache = {}
  def get(i):
    if i in cache:
      return cache[i]
    node = nodes[i]
    M_local = _node_local_matrix(node, is_cdae)
    if node.parent_index >= 0:
      M = get(node.parent_index) @ M_local
    else:
      M = M_local
    cache[i] = M
    return M
  return [get(i) for i in range(len(nodes))]

# ======================================================
# IMPORT (shared)
# ======================================================
def apply_node_transform_to_object(shape_node, ob, is_cdae=False):
  ob.location = translate_vert(shape_node.translation)
  rotation_quaternion = _quat16_to_blender_quat(shape_node.rotation, is_cdae=is_cdae)
  ob.rotation_mode = 'QUATERNION'
  ob.rotation_quaternion = rotation_quaternion

def create_dummy_object_from_shape_object(shape, shape_object, name_override=None):
  scn = bpy.context.scene
  shape_node = shape.nodes[shape_object.node_index]
  base_name = shape.names[shape_object.name_index]
  name = name_override if name_override else base_name
  is_cdae = getattr(shape, "_from_cdae", False)
  ob = bpy.data.objects.new(name, None)
  apply_node_transform_to_object(shape_node, ob, is_cdae=is_cdae)
  scn.collection.objects.link(ob)
  return ob

def _create_detail_empties(shape: TSShape):
  if not hasattr(shape, "details") or not shape.details:
    return
  scn = bpy.context.scene
  parent = bpy.data.objects.get("Details")
  if parent is None:
    parent = bpy.data.objects.new("Details", None)
    scn.collection.objects.link(parent)
  object_name_set = set()
  for obj in shape.objects:
    if 0 <= obj.name_index < len(shape.names):
      object_name_set.add(shape.names[obj.name_index])
  for det in shape.details:
    if not (0 <= det.name_index < len(shape.names)):
      continue
    name = shape.names[det.name_index]
    lname = name.lower()
    if lname in object_name_set:
      continue
    if _is_collision_name(lname):
      continue
    if lname == "bb_autobillboard" or lname.startswith("bb_") or lname.startswith("nulldetail"):
      empty = bpy.data.objects.new(name, None)
      empty["detail_size"] = float(getattr(det, "size", 0.0))
      empty["subshape"] = int(getattr(det, "sub_shape_num", -1))
      if getattr(det, "sub_shape_num", -1) < 0 or lname.startswith("bb_"):
        empty["bb_dimension"] = int(getattr(det, "billboard_dimension", 0))
        empty["bb_detail_level"] = int(getattr(det, "billboard_detail_level", 0))
        empty["bb_equator_steps"] = int(getattr(det, "billboard_equator_steps", 0))
        empty["bb_polar_steps"] = int(getattr(det, "billboard_polar_steps", 0))
        empty["bb_polar_angle"] = float(getattr(det, "billboard_polar_angle", 0.0))
        empty["bb_include_poles"] = int(getattr(det, "billboard_include_poles", 0))
      scn.collection.objects.link(empty)
      empty.parent = parent

def _ensure_action(arm_obj, name):
  act = bpy.data.actions.get(name)
  if not act:
    act = bpy.data.actions.new(name=name)
  arm_obj.animation_data_create()
  arm_obj.animation_data.action = act
  return act

def _set_key_quat(act, pb, frame, quat):
  pb.rotation_mode = 'QUATERNION'
  pb.rotation_quaternion = quat
  pb.keyframe_insert(data_path="rotation_quaternion", frame=frame)

def _set_key_loc(act, pb, frame, loc):
  pb.location = loc
  pb.keyframe_insert(data_path="location", frame=frame)

def _set_key_scale(act, pb, frame, sca):
  pb.scale = sca
  pb.keyframe_insert(data_path="scale", frame=frame)

# ======================================================
# UPDATED: key animation as delta relative to node rest (rotation + translation)
# ======================================================
def build_actions_from_sequences(shape: TSShape, arm_obj: bpy.types.Object, fps: float = 30.0):
  if not getattr(shape, "_sequences", None):
    return
  is_cdae = getattr(shape, "_from_cdae", False)
  node_names = [
    shape.names[n.name_index] if 0 <= n.name_index < len(shape.names) else f"bone_{i}"
    for i, n in enumerate(shape.nodes)
  ]
  for seq in shape._sequences:
    seq_name = shape.names[seq.name_index] if 0 <= seq.name_index < len(shape.names) else "Seq"
    act_name = f"TS_{seq_name}"
    act = _ensure_action(arm_obj, act_name)
    for f in list(act.fcurves):
      act.fcurves.remove(f)
    nkeys = max(1, seq.num_keyframes)
    duration = max(0.0, seq.duration)
    def frame_for_key(k: int) -> int:
      if nkeys <= 1:
        return 1
      return int(round(k * (duration / max(1, nkeys - 1)) * fps) + 1)
    rot_vec = getattr(shape, "_anim_node_rotations", [])
    trn_vec = getattr(shape, "_anim_node_translations", [])
    us_vec  = getattr(shape, "_anim_node_uniform_scales", [])
    as_vec  = getattr(shape, "_anim_node_aligned_scales", [])
    arbS_vec = getattr(shape, "_anim_node_arbitrary_scale_factors", [])
    for node_idx, bone_name in enumerate(node_names):
      pb = arm_obj.pose.bones.get(bone_name)
      if not pb:
        continue
      rest_quat = _quat16_to_blender_quat(shape.nodes[node_idx].rotation, is_cdae)
      rest_tran = shape.nodes[node_idx].translation
      rot_matters = (seq.rotation_matters.values and ((seq.rotation_matters.values[node_idx // 32] >> (node_idx % 32)) & 1))
      trn_matters = (seq.translation_matters.values and ((seq.translation_matters.values[node_idx // 32] >> (node_idx % 32)) & 1))
      scl_matters = (seq.scale_matters.values and ((seq.scale_matters.values[node_idx // 32] >> (node_idx % 32)) & 1))
      rot_num = seq.rotation_matters.rank(node_idx) if rot_matters else None
      trn_num = seq.translation_matters.rank(node_idx) if trn_matters else None
      scl_num = seq.scale_matters.rank(node_idx)    if scl_matters else None
      for k in range(nkeys):
        f = frame_for_key(k)
        if rot_num is not None:
          idx = seq.base_rotation + rot_num * nkeys + k
          if 0 <= idx < len(rot_vec):
            anim_quat = _quat16_to_blender_quat(rot_vec[idx], is_cdae)
          else:
            anim_quat = rest_quat
        else:
          anim_quat = rest_quat
        rot_delta = rest_quat.inverted() @ anim_quat
        if trn_num is not None:
          idx = seq.base_translation + trn_num * nkeys + k
          if 0 <= idx < len(trn_vec):
            anim_tran = trn_vec[idx]
          else:
            anim_tran = rest_tran
        else:
          anim_tran = rest_tran
        loc_delta = (anim_tran[0] - rest_tran[0],
               anim_tran[1] - rest_tran[1],
               anim_tran[2] - rest_tran[2])
        if scl_num is not None:
          if seq.flags & SequenceFlags.UniformScale and us_vec:
            idx = seq.base_scale + scl_num * nkeys + k
            s = (us_vec[idx] if 0 <= idx < len(us_vec) else 1.0)
            sca = (s, s, s)
          elif seq.flags & SequenceFlags.AlignedScale and as_vec:
            idx = seq.base_scale + scl_num * nkeys + k
            if 0 <= idx < len(as_vec):
              sx, sy, sz = as_vec[idx]
              sca = (sx, sy, sz)
            else:
              sca = (1.0, 1.0, 1.0)
          elif seq.flags & SequenceFlags.ArbitraryScale and arbS_vec:
            idx = seq.base_scale + scl_num * nkeys + k
            if 0 <= idx < len(arbS_vec):
              sx, sy, sz = arbS_vec[idx]
              sca = (sx, sy, sz)
            else:
              sca = (1.0, 1.0, 1.0)
          else:
            sca = (1.0, 1.0, 1.0)
        else:
          sca = (1.0, 1.0, 1.0)
        _set_key_loc(act, pb, f, loc_delta)
        _set_key_quat(act, pb, f, rot_delta)
        _set_key_scale(act, pb, f, sca)
    arm_obj.animation_data_create()
    nla = arm_obj.animation_data.nla_tracks.get(act.name)
    if nla is None:
      nla = arm_obj.animation_data.nla_tracks.new()
      nla.name = act.name
    if not any(strip.action == act for strip in nla.strips):
      strip = nla.strips.new(act.name, 1, act)
      strip.frame_end = max(2, round(duration * fps) + 1)

# ======================================================
# Armature creation
# ======================================================
def build_armature_from_shape(shape: TSShape) -> bpy.types.Object:
  scn = bpy.context.scene
  arm_data = bpy.data.armatures.new("TS_Armature")
  arm_obj = bpy.data.objects.new("TS_Armature", arm_data)
  scn.collection.objects.link(arm_obj)
  bpy.context.view_layer.objects.active = arm_obj
  bpy.ops.object.mode_set(mode='EDIT')
  is_cdae = getattr(shape, "_from_cdae", False)
  world_mats = _compute_world_mats(shape, is_cdae)
  ebones = {}
  for i, node in enumerate(shape.nodes):
    name = shape.names[node.name_index] if 0 <= node.name_index < len(shape.names) else f"bone_{i}"
    b = arm_data.edit_bones.new(name)
    M = world_mats[i]
    b.head = M.translation
    dirv = (M.to_3x3() @ mathutils.Vector((0.0, 0.05, 0.0)))
    if dirv.length < 1e-6:
      dirv = mathutils.Vector((0.0, 0.05, 0.0))
    b.tail = b.head + dirv
    ebones[i] = b
  for i, node in enumerate(shape.nodes):
    if node.parent_index >= 0:
      ebones[i].parent = ebones.get(node.parent_index)
  bpy.ops.object.mode_set(mode='OBJECT')
  return arm_obj

def _apply_skin_to_object(ob: bpy.types.Object, shape: TSShape, ts_mesh, arm_obj: bpy.types.Object):
  if not isinstance(ts_mesh, TSSkinnedMesh) or arm_obj is None:
    return
  mod = ob.modifiers.new("Armature", 'ARMATURE')
  mod.object = arm_obj
  bone_slot_to_name = {}
  for bi, node_idx in enumerate(ts_mesh.node_index):
    if 0 <= node_idx < len(shape.nodes):
      ni = shape.nodes[node_idx].name_index
      bone_slot_to_name[bi] = shape.names[ni] if 0 <= ni < len(shape.names) else f"bone_{node_idx}"
  for name in set(bone_slot_to_name.values()):
    if name not in ob.vertex_groups:
      ob.vertex_groups.new(name=name)
  per_vert = {}
  for vi, bi, w in zip(ts_mesh.vertex_index, ts_mesh.bone_index, ts_mesh.weight):
    if w <= 0.0:
      continue
    vname = bone_slot_to_name.get(bi)
    if not vname:
      continue
    per_vert.setdefault(int(vi), []).append((vname, float(w)))
  for vindex, pairs in per_vert.items():
    for vname, w in pairs:
      vg = ob.vertex_groups.get(vname)
      if vg:
        vg.add([vindex], w, 'ADD')

# ======================================================
# Scene composition
# ======================================================
def _create_scene_from_shape(shape: TSShape, merge_verts: bool = True):
  scn = bpy.context.scene
  is_cdae = getattr(shape, "_from_cdae", False)
  has_skin = any(isinstance(m, TSSkinnedMesh) for m in shape.meshes)
  has_sequences = bool(getattr(shape, "_sequences", []))
  arm_obj = None
  if has_skin or has_sequences:
    arm_obj = build_armature_from_shape(shape)
  hierarchy = {}
  created = []  # (ob, ts_mesh)
  for obj_index, shape_object in enumerate(shape.objects):
    base_name = shape.names[shape_object.name_index]
    lname = base_name.lower()
    shape_node = shape.nodes[shape_object.node_index]
    parent_obj = None
    if shape_node.parent_index >= 0:
      parent_obj = hierarchy.get(shape_node.parent_index)
    if _is_pure_empty_object_name(lname):
      empty = create_dummy_object_from_shape_object(shape, shape_object, name_override=base_name)
      if parent_obj is not None and empty is not None:
        empty.parent = parent_obj
        empty.matrix_parent_inverse = parent_obj.matrix_world.inverted()
      hierarchy[shape_object.node_index] = empty
      continue
    if shape_object.num_meshes <= 0:
      fallback = create_dummy_object_from_shape_object(shape, shape_object, name_override=base_name)
      if parent_obj is not None and fallback is not None:
        fallback.parent = parent_obj
        fallback.matrix_parent_inverse = parent_obj.matrix_world.inverted()
      hierarchy[shape_object.node_index] = fallback
      continue
    subshape_index = shape.get_sub_shape_for_object(obj_index)
    subshape_details = shape.get_sub_shape_details(subshape_index) if subshape_index >= 0 else []
    detail_by_object_detail = {}
    for det in subshape_details:
      if det.sub_shape_num == subshape_index and det.object_detail_num >= 0:
        detail_by_object_detail[det.object_detail_num] = det
    created_any = False
    for j in range(shape_object.num_meshes):
      global_mesh_idx = shape_object.start_mesh_index + j
      if global_mesh_idx >= len(shape.meshes):
        continue
      mesh = shape.meshes[global_mesh_idx]
      if not isinstance(mesh, (TSMesh, TSSkinnedMesh)) or not getattr(mesh, "vertices", []):
        continue
      prefix = ""
      if isinstance(mesh, TSMesh) and (mesh.flags & TSMeshFlags.BillboardZAxis) != 0:
        prefix = "bbz_"
      elif isinstance(mesh, TSMesh) and (mesh.flags & TSMeshFlags.Billboard) != 0:
        prefix = "bb_"
      det = detail_by_object_detail.get(j)
      suffix = ""
      if det and getattr(det, "size", None) is not None and det.size >= 10:
        suffix = f"_a{int(round(det.size))}"
      name_override = prefix + base_name + suffix
      ob = create_mesh_object_from_shape_object(shape, shape_object, j, name_override=name_override, merge_verts=merge_verts)
      if ob is not None:
        created_any = True
        if parent_obj is not None and not isinstance(mesh, TSSkinnedMesh):
          ob.parent = parent_obj
          ob.matrix_parent_inverse = parent_obj.matrix_world.inverted()
        ob["ts_flags"] = int(mesh.flags) if hasattr(mesh, "flags") else 0
        if not isinstance(mesh, TSSkinnedMesh):
          hierarchy[shape_object.node_index] = ob
        created.append((ob, mesh))
    if not created_any:
      fallback = create_dummy_object_from_shape_object(shape, shape_object, name_override=base_name)
      if parent_obj is not None and fallback is not None:
        fallback.parent = parent_obj
        fallback.matrix_parent_inverse = parent_obj.matrix_world.inverted()
      hierarchy[shape_object.node_index] = fallback
  if arm_obj is not None:
    for ob, ts_mesh in created:
      _apply_skin_to_object(ob, shape, ts_mesh, arm_obj)
    if has_sequences:
      build_actions_from_sequences(shape, arm_obj, fps=30.0)
  _create_detail_empties(shape)

def create_mesh_object_from_shape_object(shape, shape_object, shape_mesh_index, name_override=None, merge_verts: bool = True):
  scn = bpy.context.scene
  shape_node = shape.nodes[shape_object.node_index]
  base_name = shape.names[shape_object.name_index]
  shape_object_name = name_override if name_override else base_name
  shape_mesh = shape.meshes[shape_object.start_mesh_index + shape_mesh_index]
  is_cdae = getattr(shape, "_from_cdae", False)
  material_remap = {}
  me = bpy.data.meshes.new('DTSMesh' + str(shape_object.start_mesh_index + shape_mesh_index))
  bm = bmesh.new()
  bm.from_mesh(me)
  uv_layer = None
  uv2_layer = None
  vc_layer = None
  if len(shape_mesh.tvertices) == len(shape_mesh.vertices):
    uv_layer = bm.loops.layers.uv.new()
  if len(shape_mesh.t2vertices) == len(shape_mesh.vertices):
    uv2_layer = bm.loops.layers.uv.new()
  if len(shape_mesh.colors) == len(shape_mesh.vertices):
    vc_layer = bm.loops.layers.color.new()
  ob = bpy.data.objects.new(shape_object_name, me)
  scn.collection.objects.link(ob)
  if not isinstance(shape_mesh, TSSkinnedMesh):
    apply_node_transform_to_object(shape_node, ob, is_cdae=is_cdae)
  else:
    ob.location = (0.0, 0.0, 0.0)
    ob.rotation_mode = 'QUATERNION'
    ob.rotation_quaternion = mathutils.Quaternion((1.0, 0.0, 0.0, 0.0))
    ob.scale = (1.0, 1.0, 1.0)
  poly_prim_idx = []
  poly_mat_idx = []
  def ensure_material_slot(prim):
    key = prim.material_index
    if key in material_remap:
      return material_remap[key]
    if 0 <= key < len(shape.materials):
      mname = shape.materials[key].name
    else:
      mname = f"Mat_{key}"
    slot = len(material_remap)
    material_remap[key] = slot
    ob.data.materials.append(create_material(mname))
    return slot
  mesh_indices = shape_mesh.indices
  verts = shape_mesh.vertices
  norms = getattr(shape_mesh, "normals", [])
  use_merge = bool(merge_verts) and norms and (len(norms) == len(verts))
  if use_merge:
    vert_remap = {}
    remapped_verts = []
    merged_normals = []
    def get_merged_index(vidx: int) -> int:
      key = (verts[vidx], norms[vidx])
      idx = vert_remap.get(key)
      if idx is None:
        idx = len(remapped_verts)
        vert_remap[key] = idx
        remapped_verts.append(bm.verts.new(translate_vert(verts[vidx])))
        merged_normals.append(norms[vidx])
      return idx
    def add_face_from_indices(i0, i1, i2, mat_slot, prim_i):
      i0m = get_merged_index(i0)
      i1m = get_merged_index(i1)
      i2m = get_merged_index(i2)
      if i0m == i1m or i1m == i2m or i2m == i0m:
        return
      v0 = remapped_verts[i0m]
      v1 = remapped_verts[i1m]
      v2 = remapped_verts[i2m]
      if v0 is v1 or v1 is v2 or v0 is v2:
        return
      try:
        face = bm.faces.new((v0, v1, v2))
        if uv_layer is not None:
          face.loops[0][uv_layer].uv = translate_uv(shape_mesh.tvertices[i0])
          face.loops[1][uv_layer].uv = translate_uv(shape_mesh.tvertices[i1])
          face.loops[2][uv_layer].uv = translate_uv(shape_mesh.tvertices[i2])
        if uv2_layer is not None:
          face.loops[0][uv2_layer].uv = translate_uv(shape_mesh.t2vertices[i0])
          face.loops[1][uv2_layer].uv = translate_uv(shape_mesh.t2vertices[i1])
          face.loops[2][uv2_layer].uv = translate_uv(shape_mesh.t2vertices[i2])
        if vc_layer is not None:
          face.loops[0][vc_layer] = shape_mesh.colors[i0]
          face.loops[1][vc_layer] = shape_mesh.colors[i1]
          face.loops[2][vc_layer] = shape_mesh.colors[i2]
        face.material_index = mat_slot
        face.smooth = True
        poly_prim_idx.append(prim_i)
        poly_mat_idx.append(face.material_index)
      except ValueError:
        pass
      except Exception as e:
        print("Face add error:", e)
  else:
    vertices = [bm.verts.new(translate_vert(v)) for v in verts]
    def add_face_from_indices(i0, i1, i2, mat_slot, prim_i):
      # Skip degenerate triangles
      if i0 == i1 or i1 == i2 or i2 == i0:
        return
      v0 = vertices[i0]
      v1 = vertices[i1]
      v2 = vertices[i2]
      # Skip if all the same BMVert (can happen in bad data)
      if v0 is v1 or v1 is v2 or v0 is v2:
        return
      try:
        face = bm.faces.new((v0, v1, v2))
        if uv_layer is not None:
          face.loops[0][uv_layer].uv = translate_uv(shape_mesh.tvertices[i0])
          face.loops[1][uv_layer].uv = translate_uv(shape_mesh.tvertices[i1])
          face.loops[2][uv_layer].uv = translate_uv(shape_mesh.tvertices[i2])
        if uv2_layer is not None:
          face.loops[0][uv2_layer].uv = translate_uv(shape_mesh.t2vertices[i0])
          face.loops[1][uv2_layer].uv = translate_uv(shape_mesh.t2vertices[i1])
          face.loops[2][uv2_layer].uv = translate_uv(shape_mesh.t2vertices[i2])
        if vc_layer is not None:
          face.loops[0][vc_layer] = shape_mesh.colors[i0]
          face.loops[1][vc_layer] = shape_mesh.colors[i1]
          face.loops[2][vc_layer] = shape_mesh.colors[i2]
        face.smooth = True
        face.material_index = mat_slot
        poly_prim_idx.append(prim_i)
        poly_mat_idx.append(face.material_index)
      except ValueError:
        # bmesh will raise if it detects a duplicate vert; just skip that triangle
        pass
      except Exception as e:
        print("Face add error:", e)
  for prim_i, prim in enumerate(shape_mesh.primitives):
    mat_slot = ensure_material_slot(prim)
    if prim.type == TSDrawPrimitiveType.Triangles:
      prim_indices = mesh_indices[prim.start:prim.start + prim.num_elements]
      if is_cdae:
        for x in range(0, len(prim_indices), 3):
          i0 = prim_indices[x + 0]
          i1 = prim_indices[x + 1]
          i2 = prim_indices[x + 2]
          add_face_from_indices(i0, i1, i2, mat_slot, prim_i)
      else:
        for x in range(0, len(prim_indices), 3):
          i0 = prim_indices[x + 2]
          i1 = prim_indices[x + 1]
          i2 = prim_indices[x + 0]
          add_face_from_indices(i0, i1, i2, mat_slot, prim_i)
    elif prim.type == TSDrawPrimitiveType.Strip:
      strip_indices = mesh_indices[prim.start:prim.start + prim.num_elements]
      prim_indices = triangle_strip_to_list(strip_indices, False)
      if is_cdae:
        for x in range(0, len(prim_indices), 3):
          i0 = prim_indices[x + 0]
          i1 = prim_indices[x + 1]
          i2 = prim_indices[x + 2]
          add_face_from_indices(i0, i1, i2, mat_slot, prim_i)
      else:
        for x in range(0, len(prim_indices), 3):
          i0 = prim_indices[x + 2]
          i1 = prim_indices[x + 1]
          i2 = prim_indices[x + 0]
          add_face_from_indices(i0, i1, i2, mat_slot, prim_i)
    else:
      print(f"Unsupported prim type {prim.type}, ignoring.")
  if is_cdae:
    try:
      bmesh.ops.reverse_faces(bm, faces=bm.faces)
    except Exception:
      for f in bm.faces:
        try:
          f.normal_flip()
        except Exception:
          pass
  bm.normal_update()
  bm.to_mesh(me)
  bm.free()
  if getattr(shape_mesh, "normals", None) and len(shape_mesh.normals) == len(shape_mesh.vertices):
    try:
      ln = []
      if use_merge:
        for loop in me.loops:
          vi = loop.vertex_index
          nx, ny, nz = merged_normals[vi]
          ln.append((nx, ny, nz))
      else:
        for loop in me.loops:
          vi = loop.vertex_index
          nx, ny, nz = shape_mesh.normals[vi]
          ln.append((nx, ny, nz))
      try:
        ns = me.normals_split_custom_set
        me.normals_split_custom_set(ln)
        if hasattr(me, "use_auto_smooth"):
          me.use_auto_smooth = True
        else:
          ns_settings = getattr(me, "normals", None)
          if ns_settings and hasattr(ns_settings, "use_auto_smooth"):
            ns_settings.use_auto_smooth = True
      except Exception as e:
        print("Failed to set custom split normals:", e)
    except Exception as e:
      print("Failed to build custom split normals list:", e)
  try:
    if poly_prim_idx and len(poly_prim_idx) == len(me.polygons):
      attr_p = me.attributes.get("ts_prim_index")
      if attr_p is None:
        attr_p = me.attributes.new("ts_prim_index", type='INT', domain='FACE')
      for i, poly in enumerate(me.polygons):
        attr_p.data[i].value = int(poly_prim_idx[i])
    if poly_mat_idx and len(poly_mat_idx) == len(me.polygons):
      attr_m = me.attributes.get("ts_mat_index")
      if attr_m is None:
        attr_m = me.attributes.new("ts_mat_index", type='INT', domain='FACE')
      for i, poly in enumerate(me.polygons):
        attr_m.data[i].value = int(poly_mat_idx[i])
  except Exception as e:
    print("Failed to write primitive/material face attributes:", e)
  if isinstance(shape_mesh, TSMesh) and not isinstance(shape_mesh, TSSkinnedMesh):
    num_frames = getattr(shape_mesh, "num_frames", 1)
    base_count = len(shape_mesh.vertices)
    if num_frames and num_frames > 1:
      total = len(shape_mesh.vertices)
      if total == base_count * num_frames:
        if not me.shape_keys:
          ob.shape_key_add(name="Basis", from_mix=False)
        for fi in range(1, num_frames):
          key = ob.shape_key_add(name=f"frame_{fi}", from_mix=False)
          start = fi * base_count
          for vi in range(base_count):
            key.data[vi].co = mathutils.Vector(translate_vert(shape_mesh.vertices[start + vi]))
  return ob
