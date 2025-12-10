# ##### BEGIN LICENSE BLOCK #####
#
# This program is licensed under The MIT License:
# see LICENSE for the full license text
#
# ##### END LICENSE BLOCK #####
import bpy
from collections import defaultdict

from ..utils.bpy_helpers import ensure_collection, link_object_to_collection
from .mission import get_euler_from_rotlist


def build_forest_objects(ctx):
  forest_coll = ensure_collection('ForestData')

  # Group forest items by type for efficient instancing
  items_by_type = defaultdict(list)
  for i in ctx.forest_data:
    type_name = i.get('type') or 'ForestItem'
    items_by_type[type_name].append(i)

  total_items = len(ctx.forest_data)
  processed = 0

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

      # Fallback: no mesh found -> create empties so at least positions/rotations are visible
      if not source_obj:
        for i in items:
          position = i.get('pos') or [0, 0, 0]
          rot = i.get('rotationMatrix')
          rotationEuler = get_euler_from_rotlist(rot)

          empty = bpy.data.objects.new(type_name, None)
          empty.empty_display_type = 'ARROWS'
          empty.location = position
          empty.rotation_euler = rotationEuler
          link_object_to_collection(empty, forest_coll)
          processed += 1
        continue

      # Build a point mesh with one vertex per instance
      mesh_name = f"ForestPoints_{type_name}"
      mesh = bpy.data.meshes.new(mesh_name)

      positions = []
      rotations_euler = []
      scales = []

      for i in items:
        position = i.get('pos') or [0, 0, 0]
        rot = i.get('rotationMatrix')
        rotationEuler = get_euler_from_rotlist(rot)
        scale = i.get('scale') or [1, 1, 1]

        # Normalize scale to 3D vector
        if isinstance(scale, (int, float)):
          scale = (float(scale), float(scale), float(scale))
        elif isinstance(scale, (list, tuple)):
          if len(scale) == 1:
            scale = (float(scale[0]), float(scale[0]), float(scale[0]))
          elif len(scale) >= 3:
            scale = (float(scale[0]), float(scale[1]), float(scale[2]))
          else:
            s = list(scale) + [1.0] * (3 - len(scale))
            scale = (float(s[0]), float(s[1]), float(s[2]))
        else:
          scale = (1.0, 1.0, 1.0)

        positions.append(position)
        rotations_euler.append(rotationEuler)
        scales.append(scale)

      mesh.from_pydata(positions, [], [])
      mesh.update()

      # Store attributes on the POINT domain with non-conflicting names
      rot_attr_name = 'forest_rot'
      scl_attr_name = 'forest_scale'
      rotation_attr = mesh.attributes.new(name=rot_attr_name, type='FLOAT_VECTOR', domain='POINT')
      scale_attr = mesh.attributes.new(name=scl_attr_name, type='FLOAT_VECTOR', domain='POINT')

      for idx, (euler, scale) in enumerate(zip(rotations_euler, scales)):
        rotation_attr.data[idx].vector = (float(euler.x), float(euler.y), float(euler.z))
        scale_attr.data[idx].vector = (float(scale[0]), float(scale[1]), float(scale[2]))

      # Create object that holds the points
      obj = bpy.data.objects.new(f"Forest_{type_name}", mesh)
      link_object_to_collection(obj, forest_coll)

      # Geometry Nodes modifier
      mod = obj.modifiers.new(name="ForestInstances", type='NODES')

      # Unique node group per type
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
        position = i.get('pos') or [0, 0, 0]
        rot = i.get('rotationMatrix')
        rotationEuler = get_euler_from_rotlist(rot)
        empty = bpy.data.objects.new(type_name, None)
        empty.empty_display_type = 'ARROWS'
        empty.location = position
        empty.rotation_euler = rotationEuler
        link_object_to_collection(empty, forest_coll)
        processed += 1

  ctx.progress.update(f"Forest: {total_items}/{total_items}", step=1)