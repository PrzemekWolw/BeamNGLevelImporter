# ##### BEGIN LICENSE BLOCK #####
#
# This program is licensed under The MIT License:
# see LICENSE for the full license text
#
# ##### END LICENSE BLOCK #####

import bpy
import mathutils

from .common import _normalize_scale, make_matrix, fast_link

try:
  import numpy as np
  HAS_NUMPY = True
except Exception:
  HAS_NUMPY = False


def _gn_add_io_socket(node_group, *, in_out: str, name: str, socket_type: str):
  """
  Blender 4.x+: node_group.interface.new_socket(...)
  Blender 3.6:  node_group.inputs.new(...) / node_group.outputs.new(...)
  """
  if hasattr(node_group, "interface"):
    node_group.interface.new_socket(name=name, in_out=in_out, socket_type=socket_type)
    return

  # Blender 3.6 fallback
  if in_out == 'INPUT':
    # signature: inputs.new(type, name)
    node_group.inputs.new(socket_type, name)
  else:
    node_group.outputs.new(socket_type, name)


def _node_output_socket(node, preferred_name: str):
  """Return node.outputs[preferred_name] if it exists else first output."""
  s = node.outputs.get(preferred_name)
  if s:
    return s
  if node.outputs:
    return node.outputs[0]
  return None


def _node_input_socket(node, preferred_name: str):
  """Return node.inputs[preferred_name] if it exists else first input."""
  s = node.inputs.get(preferred_name)
  if s:
    return s
  if node.inputs:
    return node.inputs[0]
  return None


def build_tsstatic_instancers(ts_groups, progress=None):
  """
  Build TSStatic instancers.
  Creates one point-cloud object per (inst_name, parent_coll) with attributes for rotation/scale,
  then a GN modifier that instances the mesh object by name.
  Falls back to empties if the source object isn't found.
  """
  rot_attr_name = 'ts_rot'
  scl_attr_name = 'ts_scale'
  processed = 0

  for (inst_name, parent_coll), items in ts_groups.items():
    try:
      lib_obj = bpy.data.objects.get(inst_name)
      if not lib_obj or lib_obj.type != 'MESH':
        for it in items:
          empty = bpy.data.objects.new(inst_name, None)
          empty.empty_display_type = 'ARROWS'
          empty.matrix_world = make_matrix(it['pos'], it['rot_euler'], it['scale'])
          fast_link(empty, parent_coll)
          processed += 1
          if progress and (processed % 64) == 0:
            progress.update(step=1)
        continue

      mesh_name = f"TSPoints_{inst_name}"
      mesh = bpy.data.meshes.new(mesh_name)
      n_pts = len(items)

      if HAS_NUMPY:
        co = np.empty((n_pts, 3), dtype=np.float32)
        rot = np.empty((n_pts, 3), dtype=np.float32)
        scl = np.empty((n_pts, 3), dtype=np.float32)
        for i, it in enumerate(items):
          p = it['pos']
          e = it['rot_euler']
          s = _normalize_scale(it['scale'])
          co[i] = (float(p[0]), float(p[1]), float(p[2]))
          rot[i] = (float(e.x), float(e.y), float(e.z))
          scl[i] = (float(s[0]), float(s[1]), float(s[2]))
        mesh.from_pydata(co.tolist(), [], [])
      else:
        positions = [it['pos'] for it in items]
        rotations = [(it['rot_euler'].x, it['rot_euler'].y, it['rot_euler'].z) for it in items]
        scales = [_normalize_scale(it['scale']) for it in items]
        mesh.from_pydata(positions, [], [])

      mesh.update()

      rotation_attr = mesh.attributes.new(name=rot_attr_name, type='FLOAT_VECTOR', domain='POINT')
      scale_attr    = mesh.attributes.new(name=scl_attr_name, type='FLOAT_VECTOR', domain='POINT')
      if HAS_NUMPY:
        rotation_attr.data.foreach_set("vector", rot.ravel())
        scale_attr.data.foreach_set("vector", scl.ravel())
      else:
        rot_flat = []
        scl_flat = []
        for r in rotations:
          rot_flat.extend((float(r[0]), float(r[1]), float(r[2])))
        for s in scales:
          scl_flat.extend((float(s[0]), float(s[1]), float(s[2])))
        rotation_attr.data.foreach_set("vector", rot_flat)
        scale_attr.data.foreach_set("vector", scl_flat)

      inst_obj_name = f"TSStatic_{inst_name}"
      inst_obj = bpy.data.objects.new(inst_obj_name, mesh)
      fast_link(inst_obj, parent_coll)

      mod = inst_obj.modifiers.new(name="TSStaticInstances", type='NODES')
      node_group_name = f"TSStaticInstancer_{inst_name}"
      node_group = bpy.data.node_groups.new(name=node_group_name, type='GeometryNodeTree')

      input_node = node_group.nodes.new('NodeGroupInput')
      output_node = node_group.nodes.new('NodeGroupOutput')

      # Add group sockets (3.6 compatible)
      _gn_add_io_socket(node_group, in_out='INPUT',  name='Geometry', socket_type='NodeSocketGeometry')
      _gn_add_io_socket(node_group, in_out='OUTPUT', name='Geometry', socket_type='NodeSocketGeometry')

      object_info_node = node_group.nodes.new('GeometryNodeObjectInfo')
      object_info_node.inputs['Object'].default_value = lib_obj
      if hasattr(object_info_node, "transform_space"):
        object_info_node.transform_space = 'ORIGINAL'

      instance_node = node_group.nodes.new('GeometryNodeInstanceOnPoints')

      rot_attr_node = node_group.nodes.new('GeometryNodeInputNamedAttribute')
      rot_attr_node.inputs['Name'].default_value = rot_attr_name
      if hasattr(rot_attr_node, "data_type"):
        rot_attr_node.data_type = 'FLOAT_VECTOR'

      scl_attr_node = node_group.nodes.new('GeometryNodeInputNamedAttribute')
      scl_attr_node.inputs['Name'].default_value = scl_attr_name
      if hasattr(scl_attr_node, "data_type"):
        scl_attr_node.data_type = 'FLOAT_VECTOR'

      # Wire: Group Input Geometry -> Instance on Points Points
      node_group.links.new(
        _node_output_socket(input_node, 'Geometry'),
        _node_input_socket(instance_node, 'Points')
      )

      # Wire: Object Info -> Instance
      node_group.links.new(
        _node_output_socket(object_info_node, 'Geometry'),
        _node_input_socket(instance_node, 'Instance')
      )

      # Wire: rot/scale attrs
      node_group.links.new(
        _node_output_socket(rot_attr_node, 'Attribute'),
        _node_input_socket(instance_node, 'Rotation')
      )
      node_group.links.new(
        _node_output_socket(scl_attr_node, 'Attribute'),
        _node_input_socket(instance_node, 'Scale')
      )

      # Wire: Instance output -> Group Output Geometry
      out_sock = _node_input_socket(output_node, 'Geometry')
      inst_out = (
        instance_node.outputs.get('Instances') or
        instance_node.outputs.get('Geometry') or
        (instance_node.outputs[0] if instance_node.outputs else None)
      )
      if inst_out and out_sock:
        node_group.links.new(inst_out, out_sock)

      mod.node_group = node_group

      processed += n_pts
      if progress and (processed % 64) == 0:
        progress.update(step=1)

    except Exception as e:
      print(f"Error building TSStatic instancer for {inst_name}: {e}")
      import traceback
      traceback.print_exc()
      for it in items:
        empty = bpy.data.objects.new(inst_name, None)
        empty.empty_display_type = 'ARROWS'
        empty.matrix_world = make_matrix(it['pos'], it['rot_euler'], it['scale'])
        fast_link(empty, parent_coll)
        processed += 1
        if progress and (processed % 64) == 0:
          progress.update(step=1)