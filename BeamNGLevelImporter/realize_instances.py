# ##### BEGIN LICENSE BLOCK #####
#
# This program is licensed under The MIT License:
# see LICENSE for the full license text
#
# ##### END LICENSE BLOCK #####

import bpy
import mathutils


# Core: TSStatic realization

def realize_tsstatic_instances(
  only_selected_tsstatic=False,
  out_collection_name="TSStatic_Real_Instances",
  share_mesh_data=True,
  delete_tsstatic=True,
  delete_points_mesh=True,
):
  """
  Turn TSStatic instancers (TSStatic_*) built by build_tsstatic_instancers
  into separate real objects, one per point, with correct transforms.

  After realization, optionally delete:
    - TSStatic_* instancer objects (delete_tsstatic)
    - TSPoints_* meshes (delete_points_mesh)
  """

  if only_selected_tsstatic:
    tsstatic_objs = [
      o for o in bpy.context.selected_objects
      if o.name.startswith("TSStatic_")
    ]
  else:
    tsstatic_objs = [
      o for o in bpy.data.objects
      if o.name.startswith("TSStatic_")
    ]

  if not tsstatic_objs:
    print("BeamNG: no TSStatic_* objects found to realize.")
    return 0

  out_col = bpy.data.collections.get(out_collection_name)
  if out_col is None:
    out_col = bpy.data.collections.new(out_collection_name)
    bpy.context.scene.collection.children.link(out_col)

  total_created = 0
  points_meshes_to_delete = set()

  for inst_obj in tsstatic_objs:
    inst_name = inst_obj.name[len("TSStatic_"):]  # strip prefix

    points_mesh_name = f"TSPoints_{inst_name}"
    points_mesh = bpy.data.meshes.get(points_mesh_name)
    if points_mesh is None:
      print(f"[TSStatic] SKIP {inst_obj.name}: points mesh '{points_mesh_name}' not found.")
      continue

    points_meshes_to_delete.add(points_mesh)

    rot_attr_name = "ts_rot"
    scl_attr_name = "ts_scale"

    if rot_attr_name not in points_mesh.attributes or scl_attr_name not in points_mesh.attributes:
      print(f"[TSStatic] SKIP {inst_obj.name}: missing attributes '{rot_attr_name}' or '{scl_attr_name}'.")
      continue

    rot_attr = points_mesh.attributes[rot_attr_name]
    scl_attr = points_mesh.attributes[scl_attr_name]

    if rot_attr.domain != 'POINT' or scl_attr.domain != 'POINT':
      print(f"[TSStatic] SKIP {inst_obj.name}: attributes not on POINT domain.")
      continue

    verts = points_mesh.vertices
    if len(rot_attr.data) != len(verts) or len(scl_attr.data) != len(verts):
      print(f"[TSStatic] SKIP {inst_obj.name}: attribute length mismatch.")
      continue

    # Find GN modifier
    gn_mod = None
    for m in inst_obj.modifiers:
      if m.type == 'NODES' and m.name == "TSStaticInstances":
        gn_mod = m
        break

    if gn_mod is None or gn_mod.node_group is None:
      print(f"[TSStatic] SKIP {inst_obj.name}: TSStaticInstances GN modifier not found or missing node group.")
      continue

    # Source object from Object Info
    src_obj = None
    for node in gn_mod.node_group.nodes:
      if node.bl_idname == 'GeometryNodeObjectInfo':
        inp = node.inputs.get("Object", None)
        if inp is not None:
          src_obj = inp.default_value
        break

    if src_obj is None:
      print(f"[TSStatic] SKIP {inst_obj.name}: could not find source object from Object Info node.")
      continue

    if src_obj.type != 'MESH' or src_obj.data is None:
      print(f"[TSStatic] SKIP {inst_obj.name}: source object '{src_obj.name}' is not a valid MESH.")
      continue

    print(f"[TSStatic] Realizing {len(verts)} instances for {inst_obj.name} using source '{src_obj.name}'.")

    inst_mw = inst_obj.matrix_world
    created_here = 0

    for i, v in enumerate(verts):
      pos_local = v.co
      r = rot_attr.data[i].vector
      euler = mathutils.Euler((r.x, r.y, r.z), 'XYZ')
      s = scl_attr.data[i].vector

      mat_local = (
        mathutils.Matrix.Translation(pos_local) @
        euler.to_matrix().to_4x4() @
        mathutils.Matrix.Diagonal((s.x, s.y, s.z, 1.0))
      )

      mat_world = inst_mw @ mat_local

      if share_mesh_data:
        new_obj = bpy.data.objects.new(
          f"{src_obj.name}_inst_{inst_name}_{i:05d}",
          src_obj.data
        )
      else:
        new_mesh = src_obj.data.copy()
        new_obj = bpy.data.objects.new(
          f"{src_obj.name}_inst_{inst_name}_{i:05d}",
          new_mesh
        )

      new_obj.matrix_world = mat_world
      out_col.objects.link(new_obj)
      created_here += 1

    total_created += created_here
    print(f"[TSStatic] DONE {inst_obj.name}: created {created_here} objects.")

    if delete_tsstatic:
      for coll in list(inst_obj.users_collection):
        try:
          coll.objects.unlink(inst_obj)
        except Exception:
          pass
      try:
        bpy.data.objects.remove(inst_obj, do_unlink=True)
      except Exception:
        pass

  # Delete TSPoints_* meshes after all instancers processed
  if delete_points_mesh:
    for me in points_meshes_to_delete:
      try:
        if me.users == 0:
          bpy.data.meshes.remove(me, do_unlink=True)
      except Exception:
        pass

  print(f"BeamNG: TSStatic realize complete. Created {total_created} objects in '{out_collection_name}'.")
  return total_created


# Core: Forest realization

def realize_forest_instances(
  only_selected_forest=False,
  out_collection_name="Forest_Real_Instances",
  share_mesh_data=True,
  delete_forest_objects=True,
  delete_points_mesh=True,
):
  """
  Realize Forest_* instancers into separate real objects.

  After realization, optionally delete:
    - Forest_* instancer objects
    - ForestPoints_* meshes
  """

  if only_selected_forest:
    forest_objs = [o for o in bpy.context.selected_objects
             if o.name.startswith("Forest_")]
  else:
    forest_objs = [o for o in bpy.data.objects
             if o.name.startswith("Forest_")]

  if not forest_objs:
    print("BeamNG: no Forest_* objects found to realize.")
    return 0

  out_col = bpy.data.collections.get(out_collection_name)
  if out_col is None:
    out_col = bpy.data.collections.new(out_collection_name)
    bpy.context.scene.collection.children.link(out_col)

  total_created = 0
  points_meshes_to_delete = set()

  for inst_obj in forest_objs:
    type_name = inst_obj.name[len("Forest_"):]
    points_mesh_name = f"ForestPoints_{type_name}"
    points_mesh = bpy.data.meshes.get(points_mesh_name)
    if points_mesh is None:
      print(f"[Forest] SKIP {inst_obj.name}: points mesh '{points_mesh_name}' not found.")
      continue

    points_meshes_to_delete.add(points_mesh)

    rot_attr_name = "forest_rot"
    scl_attr_name = "forest_scale"

    if rot_attr_name not in points_mesh.attributes or scl_attr_name not in points_mesh.attributes:
      print(f"[Forest] SKIP {inst_obj.name}: missing attributes '{rot_attr_name}' or '{scl_attr_name}'.")
      continue

    rot_attr = points_mesh.attributes[rot_attr_name]
    scl_attr = points_mesh.attributes[scl_attr_name]

    if rot_attr.domain != 'POINT' or scl_attr.domain != 'POINT':
      print(f"[Forest] SKIP {inst_obj.name}: attributes not on POINT domain.")
      continue

    verts = points_mesh.vertices
    if len(rot_attr.data) != len(verts) or len(scl_attr.data) != len(verts):
      print(f"[Forest] SKIP {inst_obj.name}: attribute length mismatch.")
      continue

    gn_mod = None
    for m in inst_obj.modifiers:
      if m.type == 'NODES' and m.name == "ForestInstances":
        gn_mod = m
        break

    if gn_mod is None or gn_mod.node_group is None:
      print(f"[Forest] SKIP {inst_obj.name}: ForestInstances GN modifier not found or missing node group.")
      continue

    src_obj = None
    for node in gn_mod.node_group.nodes:
      if node.bl_idname == 'GeometryNodeObjectInfo':
        inp = node.inputs.get("Object", None)
        if inp is not None:
          src_obj = inp.default_value
        break

    if src_obj is None:
      print(f"[Forest] SKIP {inst_obj.name}: could not find source object from Object Info node.")
      continue

    if src_obj.type not in {'MESH', 'EMPTY'} or (src_obj.type == 'MESH' and src_obj.data is None):
      print(f"[Forest] SKIP {inst_obj.name}: source object '{src_obj.name}' is not usable.")
      continue

    print(f"[Forest] Realizing {len(verts)} instances for {inst_obj.name} using source '{src_obj.name}'.")

    inst_mw = inst_obj.matrix_world
    created_here = 0

    for i, v in enumerate(verts):
      pos_local = v.co
      r = rot_attr.data[i].vector
      euler = mathutils.Euler((r.x, r.y, r.z), 'XYZ')
      s = scl_attr.data[i].vector

      mat_local = (
        mathutils.Matrix.Translation(pos_local) @
        euler.to_matrix().to_4x4() @
        mathutils.Matrix.Diagonal((s.x, s.y, s.z, 1.0))
      )

      mat_world = inst_mw @ mat_local

      if src_obj.type == 'MESH':
        if share_mesh_data:
          new_obj = bpy.data.objects.new(
            f"{src_obj.name}_forest_{type_name}_{i:05d}",
            src_obj.data
          )
        else:
          new_mesh = src_obj.data.copy()
          new_obj = bpy.data.objects.new(
            f"{src_obj.name}_forest_{type_name}_{i:05d}",
            new_mesh
          )
      else:
        new_obj = src_obj.copy()
        new_obj.data = src_obj.data

      new_obj.matrix_world = mat_world
      out_col.objects.link(new_obj)
      created_here += 1

    total_created += created_here
    print(f"[Forest] DONE {inst_obj.name}: created {created_here} objects.")

    if delete_forest_objects:
      for coll in list(inst_obj.users_collection):
        try:
          coll.objects.unlink(inst_obj)
        except Exception:
          pass
      try:
        bpy.data.objects.remove(inst_obj, do_unlink=True)
      except Exception:
        pass

  # Delete ForestPoints_* meshes
  if delete_points_mesh:
    for me in points_meshes_to_delete:
      try:
        if me.users == 0:
          bpy.data.meshes.remove(me, do_unlink=True)
      except Exception:
        pass

  print(f"BeamNG: Forest realize complete. Created {total_created} objects in '{out_collection_name}'.")
  return total_created

class BEAMNG_OT_RealizeTSStaticInstances(bpy.types.Operator):
  bl_idname = "beamng.realize_tsstatic_instances"
  bl_label = "Realize TSStatic Instances"
  bl_description = "Convert TSStatic_* instancers into real objects and remove instancers"
  bl_options = {'REGISTER', 'UNDO'}

  only_selected: bpy.props.BoolProperty(
    name="Only Selected TSStatic",
    default=False,
    description="If enabled, only realize selected TSStatic_* objects"
  )

  def execute(self, context):
    created = realize_tsstatic_instances(
      only_selected_tsstatic=self.only_selected,
      out_collection_name="TSStatic_Real_Instances",
      share_mesh_data=True,
      delete_tsstatic=True,
      delete_points_mesh=True,
    )
    self.report({'INFO'}, f"Created {created} TSStatic instance object(s).")
    return {'FINISHED'}


class BEAMNG_OT_RealizeForestInstances(bpy.types.Operator):
  bl_idname = "beamng.realize_forest_instances"
  bl_label = "Realize Forest Instances"
  bl_description = "Convert Forest_* instancers into real objects and remove instancers"
  bl_options = {'REGISTER', 'UNDO'}

  only_selected: bpy.props.BoolProperty(
    name="Only Selected Forest",
    default=False,
    description="If enabled, only realize selected Forest_* objects"
  )

  def execute(self, context):
    created = realize_forest_instances(
      only_selected_forest=self.only_selected,
      out_collection_name="Forest_Real_Instances",
      share_mesh_data=True,
      delete_forest_objects=True,
      delete_points_mesh=True,
    )
    self.report({'INFO'}, f"Created {created} forest instance object(s).")
    return {'FINISHED'}


classes = (
  BEAMNG_OT_RealizeTSStaticInstances,
  BEAMNG_OT_RealizeForestInstances,
)


def register_realize_instances():
  for c in classes:
    bpy.utils.register_class(c)


def unregister_realize_instances():
  for c in reversed(classes):
    bpy.utils.unregister_class(c)