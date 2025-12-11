# ##### BEGIN LICENSE BLOCK #####
#
# This program is licensed under The MIT License:
# see LICENSE for the full license text
#
# ##### END LICENSE BLOCK #####
import bpy
from collections import defaultdict
from itertools import chain
from ..utils.bpy_helpers import ensure_collection, link_object_to_collection
from .mission import get_euler_from_rotlist

def _flatten_vec3_list(vecs):
  # vecs: iterable of (x,y,z) tuples
  return list(chain.from_iterable(vecs))


def _normalize_scale(scale):
  # Normalize scale to 3D vector
  if isinstance(scale, (int, float)):
    s = float(scale)
    return (s, s, s)
  if isinstance(scale, (list, tuple)):
    if len(scale) == 0:
      return (1.0, 1.0, 1.0)
    if len(scale) == 1:
      s = float(scale[0])
      return (s, s, s)
    # take first 3
    x, y, z = (float(scale[0]), float(scale[1]), float(scale[2] if len(scale) > 2 else 1.0))
    return (x, y, z)
  return (1.0, 1.0, 1.0)

def get_or_create_forest_marker():
  name = "_ForestMarker"
  obj = bpy.data.objects.get(name)
  if obj:
    return obj

  # Simple 3-axis cross as a tiny mesh
  mesh = bpy.data.meshes.new(name)
  verts = [
    (0.0, 0.0, 0.0),
    (0.2, 0.0, 0.0), (-0.2, 0.0, 0.0),
    (0.0, 0.2, 0.0), (0.0, -0.2, 0.0),
    (0.0, 0.0, 0.2), (0.0, 0.0, -0.2),
  ]
  edges = [
    (0, 1), (0, 2),
    (0, 3), (0, 4),
    (0, 5), (0, 6),
  ]
  mesh.from_pydata(verts, edges, [])
  mesh.update()

  obj = bpy.data.objects.new(name, mesh)
  helpers = ensure_collection('_ForestHelpers')
  # Only link the marker once
  helpers.objects.link(obj)
  obj.hide_render = True
  obj.hide_viewport = True
  return obj


def _build_point_geometry(name, positions, rotations, scales):
  rot_attr_name = 'forest_rot'
  scl_attr_name = 'forest_scale'
  n = len(positions)
  pos_flat = list(v for xyz in positions for v in xyz)
  rot_flat = list(v for xyz in rotations for v in xyz)
  scl_flat = list(v for xyz in scales for v in xyz)
  mesh = bpy.data.meshes.new(name)
  mesh.vertices.add(n)
  mesh.vertices.foreach_set("co", pos_flat)
  mesh.update()
  rot_attr = mesh.attributes.new(name=rot_attr_name, type='FLOAT_VECTOR', domain='POINT')
  scl_attr = mesh.attributes.new(name=scl_attr_name, type='FLOAT_VECTOR', domain='POINT')
  rot_attr.data.foreach_set("vector", rot_flat)
  scl_attr.data.foreach_set("vector", scl_flat)
  return mesh, rot_attr_name, scl_attr_name, False

def build_forest_objects(ctx):
  forest_coll = ensure_collection('ForestData')

  # Group forest items by type for efficient instancing
  items_by_type = defaultdict(list)
  for i in ctx.forest_data:
    type_name = i.get('type') or 'ForestItem'
    items_by_type[type_name].append(i)

  total_items = len(ctx.forest_data)
  processed = 0

  created_objects = []

  for type_name, items in items_by_type.items():
    try:
      if (processed % 64) == 0:
        ctx.progress.update(f"Forest: {processed}/{total_items}", step=1)

      # Resolve source object for this type
      model_name = ctx.forest_names.get(type_name)
      source_obj = None
      if model_name:
        source_obj = bpy.data.objects.get(model_name)
        if source_obj and source_obj.type != 'MESH':
          source_obj = None

      # Fallback: use a shared marker mesh instead of creating empties
      if not source_obj:
        source_obj = get_or_create_forest_marker()


      positions = []
      rotations_euler = []
      scales = []

      for i in items:
        pos = i.get('pos') or (0.0, 0.0, 0.0)
        rot = i.get('rotationMatrix')
        euler = get_euler_from_rotlist(rot)
        sca = _normalize_scale(i.get('scale'))

        positions.append((float(pos[0]), float(pos[1]), float(pos[2])))
        rotations_euler.append((float(euler.x), float(euler.y), float(euler.z)))
        scales.append((float(sca[0]), float(sca[1]), float(sca[2])))

      # Create point geometry with attributes in bulk
      geo_name = f"ForestPoints_{type_name}"
      datablock, rot_attr_name, scl_attr_name, is_pointcloud = _build_point_geometry(
        geo_name, positions, rotations_euler, scales
      )

      # Create object that holds the points
      obj = bpy.data.objects.new(f"Forest_{type_name}", datablock)
      link_object_to_collection(obj, forest_coll)
      obj.hide_viewport = True
      created_objects.append(obj)

      # Geometry Nodes modifier
      mod = obj.modifiers.new(name="ForestInstances", type='NODES')

      node_group_name = f"ForestInstancer_{type_name}"
      node_group = bpy.data.node_groups.new(name=node_group_name, type='GeometryNodeTree')

      # IO sockets
      input_node = node_group.nodes.new('NodeGroupInput')
      output_node = node_group.nodes.new('NodeGroupOutput')
      node_group.interface.new_socket(name='Geometry', in_out='INPUT', socket_type='NodeSocketGeometry')
      node_group.interface.new_socket(name='Geometry', in_out='OUTPUT', socket_type='NodeSocketGeometry')

      # Object Info -> instance source object
      object_info_node = node_group.nodes.new('GeometryNodeObjectInfo')
      object_info_node.inputs['Object'].default_value = source_obj
      if hasattr(object_info_node, "transform_space"):
        object_info_node.transform_space = 'ORIGINAL'  # keep original object transforms
      if hasattr(object_info_node, "as_instance"):
        # Some Blender versions expose this flag
        object_info_node.as_instance = True

      # Instance on Points
      instance_node = node_group.nodes.new('GeometryNodeInstanceOnPoints')

      # Named attributes for rotation and scale (point domain)
      rot_attr_node = node_group.nodes.new('GeometryNodeInputNamedAttribute')
      rot_attr_node.inputs['Name'].default_value = rot_attr_name
      if hasattr(rot_attr_node, "data_type"):
        rot_attr_node.data_type = 'FLOAT_VECTOR'

      scl_attr_node = node_group.nodes.new('GeometryNodeInputNamedAttribute')
      scl_attr_node.inputs['Name'].default_value = scl_attr_name
      if hasattr(scl_attr_node, "data_type"):
        scl_attr_node.data_type = 'FLOAT_VECTOR'

      # Wire the graph
      node_group.links.new(input_node.outputs['Geometry'], instance_node.inputs['Points'])
      node_group.links.new(object_info_node.outputs['Geometry'], instance_node.inputs['Instance'])
      node_group.links.new(rot_attr_node.outputs['Attribute'], instance_node.inputs['Rotation'])
      node_group.links.new(scl_attr_node.outputs['Attribute'], instance_node.inputs['Scale'])
      node_group.links.new(instance_node.outputs['Instances'], output_node.inputs['Geometry'])

      # Assign group to modifier
      mod.node_group = node_group

      processed += len(items)
      if (processed % 64) == 0:
        ctx.progress.update(f"Forest: {processed}/{total_items}", step=1)

    except Exception as e:
      print(f"Error processing forest type {type_name}: {e}")
      import traceback
      traceback.print_exc()
      # Fallback to empties on error
      for i in items:
        pos = i.get('pos') or (0.0, 0.0, 0.0)
        rot = i.get('rotationMatrix')
        euler = get_euler_from_rotlist(rot)
        empty = bpy.data.objects.new(type_name, None)
        empty.empty_display_type = 'ARROWS'
        empty.location = (float(pos[0]), float(pos[1]), float(pos[2]))
        empty.rotation_euler = (float(euler.x), float(euler.y), float(euler.z))
        link_object_to_collection(empty, forest_coll)
        empty.hide_viewport = True
        created_objects.append(empty)
        processed += 1

  for obj in created_objects:
    obj.hide_viewport = False

  ctx.progress.update(f"Forest: {total_items}/{total_items}", step=1)
