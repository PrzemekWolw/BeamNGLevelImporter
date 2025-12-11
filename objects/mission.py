# ##### BEGIN LICENSE BLOCK #####
#
# This program is licensed under The MIT License:
# see LICENSE for the full license text
#
# ##### END LICENSE BLOCK #####

import bpy
import math
import mathutils
from collections import defaultdict
from ..core.progress import force_redraw
from ..objects.terrainblock import import_terrain_block
from ..utils.bpy_helpers import ensure_collection, link_object_to_collection

def get_euler_from_rotlist(rot):
  if rot and len(rot) == 9:
    return mathutils.Matrix([[rot[0], rot[1], rot[2]],
                             [rot[3], rot[4], rot[5]],
                             [rot[6], rot[7], rot[8]]]).transposed().to_euler()
  return mathutils.Euler((0.0, 0.0, 0.0))

def make_matrix(loc, rot_euler, scale=(1,1,1)):
  loc_m = mathutils.Matrix.Translation(mathutils.Vector(loc))
  rot_m = rot_euler.to_matrix().to_4x4()
  sca_m = mathutils.Matrix.Diagonal((scale[0], scale[1], scale[2], 1.0))
  return loc_m @ rot_m @ sca_m

_cached_meshes = {"PLANE2": None, "CUBE2": None}

def get_unit_plane_mesh():
  if _cached_meshes["PLANE2"]:
    return _cached_meshes["PLANE2"]
  me = bpy.data.meshes.new("BLK_Plane2")
  verts = [(-1,-1,0), (1,-1,0), (1,1,0), (-1,1,0)]
  faces = [(0,1,2,3)]
  me.from_pydata(verts, [], faces)
  me.update()
  _cached_meshes["PLANE2"] = me
  return me

def get_unit_cube_mesh():
  if _cached_meshes["CUBE2"]:
    return _cached_meshes["CUBE2"]
  me = bpy.data.meshes.new("BLK_Cube2")
  v = [-1, 1]
  verts = [(x,y,z) for x in v for y in v for z in v]
  faces = [
    (0,1,3,2), (4,6,7,5),
    (0,2,6,4), (1,5,7,3),
    (0,4,5,1), (2,3,7,6),
  ]
  me.from_pydata(verts, [], faces)
  me.update()
  _cached_meshes["CUBE2"] = me
  return me

def fast_link(obj, coll_name_or_coll):
  if isinstance(coll_name_or_coll, str):
    coll = bpy.data.collections.get(coll_name_or_coll)
  else:
    coll = coll_name_or_coll
  if coll:
    if obj.name not in coll.objects:
      coll.objects.link(obj)
  else:
    if obj.name not in bpy.context.scene.collection.objects:
      bpy.context.scene.collection.objects.link(obj)

def make_camera_fast(name, loc, rot_euler, parent_coll):
  cam_data = bpy.data.cameras.new(name)
  obj = bpy.data.objects.new(name, cam_data)
  obj.matrix_world = make_matrix(loc, rot_euler, (1,1,1))
  fast_link(obj, parent_coll)
  return obj

def make_speaker_fast(name, loc, rot_euler, scale, parent_coll):
  spk = bpy.data.speakers.new(name)
  obj = bpy.data.objects.new(name, spk)
  obj.matrix_world = make_matrix(loc, rot_euler, scale or (1,1,1))
  fast_link(obj, parent_coll)
  return obj

def make_light_fast(kind, name, loc, rot_euler, scale, energy, color, parent_coll):
  lamp = bpy.data.lights.new(name=name, type=kind)
  if energy is not None:
    lamp.energy = float(energy)
  if color is not None:
    lamp.color = (float(color[0]), float(color[1]), float(color[2]))
  obj = bpy.data.objects.new(name, lamp)
  obj.matrix_world = make_matrix(loc, rot_euler, scale or (1,1,1))
  fast_link(obj, parent_coll)
  return obj

def make_plane_fast(name, size, loc, rot_euler, parent_coll):
  me = get_unit_plane_mesh()
  obj = bpy.data.objects.new(name, me)
  sc = float(size)/2.0 if size else 1.0
  obj.matrix_world = make_matrix(loc, rot_euler, (sc, sc, 1))
  fast_link(obj, parent_coll)
  return obj

def make_cube_fast(name, scale_xyz, loc, rot_euler, parent_coll):
  me = get_unit_cube_mesh()
  obj = bpy.data.objects.new(name, me)
  obj.matrix_world = make_matrix(loc, rot_euler, scale_xyz or (1,1,1))
  fast_link(obj, parent_coll)
  return obj

_coll_cache = {}
def get_parent_collection(parent_name):
  if not parent_name:
    return None
  if parent_name in _coll_cache:
    return _coll_cache[parent_name]
  c = bpy.data.collections.get(parent_name)
  _coll_cache[parent_name] = c
  return c

def _normalize_scale(scale):
  if isinstance(scale, (int, float)):
    return (float(scale), float(scale), float(scale))
  if isinstance(scale, (list, tuple)):
    if len(scale) == 1:
      return (float(scale[0]), float(scale[0]), float(scale[0]))
    if len(scale) >= 3:
      return (float(scale[0]), float(scale[1]), float(scale[2]))
    s = list(scale) + [1.0] * (3 - len(scale))
    return (float(s[0]), float(s[1]), float(s[2]))
  return (1.0, 1.0, 1.0)

def _build_tsstatic_instancers(ts_groups, progress=None):
  # ts_groups: dict with key=(inst_name, parent_coll) and value=list of dicts with pos, rot_euler, scale
  total_items = sum(len(v) for v in ts_groups.values())
  processed = 0

  rot_attr_name = 'ts_rot'
  scl_attr_name = 'ts_scale'

  for (inst_name, parent_coll), items in ts_groups.items():
    try:
      # Find source object to instance
      lib_obj = bpy.data.objects.get(inst_name)
      if not lib_obj or lib_obj.type != 'MESH':
        # Fallback to empties per-item
        for it in items:
          empty = bpy.data.objects.new(inst_name, None)
          empty.empty_display_type = 'ARROWS'
          empty.matrix_world = make_matrix(it['pos'], it['rot_euler'], it['scale'])
          fast_link(empty, parent_coll)
          processed += 1
          if progress and (processed % 64) == 0:
            progress.update(step=1)
        continue

      # Create point cloud mesh for this group
      mesh_name = f"TSPoints_{inst_name}"
      mesh = bpy.data.meshes.new(mesh_name)

      positions = [it['pos'] for it in items]
      rotations_euler = [it['rot_euler'] for it in items]
      scales = [it['scale'] for it in items]

      mesh.from_pydata(positions, [], [])
      mesh.update()

      # Attributes on point domain with non-conflicting names
      rotation_attr = mesh.attributes.new(name=rot_attr_name, type='FLOAT_VECTOR', domain='POINT')
      scale_attr = mesh.attributes.new(name=scl_attr_name, type='FLOAT_VECTOR', domain='POINT')

      for idx, (euler, sc) in enumerate(zip(rotations_euler, scales)):
        rotation_attr.data[idx].vector = (float(euler.x), float(euler.y), float(euler.z))
        scale_attr.data[idx].vector = (float(sc[0]), float(sc[1]), float(sc[2]))

      # Create instancer object
      inst_obj_name = f"TSStatic_{inst_name}"
      inst_obj = bpy.data.objects.new(inst_obj_name, mesh)
      fast_link(inst_obj, parent_coll)

      # Geometry Nodes modifier
      mod = inst_obj.modifiers.new(name="TSStaticInstances", type='NODES')
      node_group_name = f"TSStaticInstancer_{inst_name}"
      node_group = bpy.data.node_groups.new(name=node_group_name, type='GeometryNodeTree')

      # IO
      input_node = node_group.nodes.new('NodeGroupInput')
      output_node = node_group.nodes.new('NodeGroupOutput')
      node_group.interface.new_socket(name='Geometry', in_out='INPUT', socket_type='NodeSocketGeometry')
      node_group.interface.new_socket(name='Geometry', in_out='OUTPUT', socket_type='NodeSocketGeometry')

      # Object Info for the source geometry
      object_info_node = node_group.nodes.new('GeometryNodeObjectInfo')
      object_info_node.inputs['Object'].default_value = lib_obj
      if hasattr(object_info_node, "transform_space"):
        object_info_node.transform_space = 'ORIGINAL'

      # Instance on Points
      instance_node = node_group.nodes.new('GeometryNodeInstanceOnPoints')

      # Named attributes
      rot_attr_node = node_group.nodes.new('GeometryNodeInputNamedAttribute')
      rot_attr_node.inputs['Name'].default_value = rot_attr_name
      if hasattr(rot_attr_node, "data_type"):
        rot_attr_node.data_type = 'FLOAT_VECTOR'

      scl_attr_node = node_group.nodes.new('GeometryNodeInputNamedAttribute')
      scl_attr_node.inputs['Name'].default_value = scl_attr_name
      if hasattr(scl_attr_node, "data_type"):
        scl_attr_node.data_type = 'FLOAT_VECTOR'

      # Wire graph
      node_group.links.new(input_node.outputs['Geometry'], instance_node.inputs['Points'])
      node_group.links.new(object_info_node.outputs['Geometry'], instance_node.inputs['Instance'])
      node_group.links.new(rot_attr_node.outputs['Attribute'], instance_node.inputs['Rotation'])
      node_group.links.new(scl_attr_node.outputs['Attribute'], instance_node.inputs['Scale'])
      node_group.links.new(instance_node.outputs['Instances'], output_node.inputs['Geometry'])

      mod.node_group = node_group

      processed += len(items)
      if progress and (processed % 64) == 0:
        progress.update(step=1)

    except Exception as e:
      print(f"Error building TSStatic instancer for {inst_name}: {e}")
      import traceback
      traceback.print_exc()
      # Fallback to individual empties on error
      for it in items:
        empty = bpy.data.objects.new(inst_name, None)
        empty.empty_display_type = 'ARROWS'
        empty.matrix_world = make_matrix(it['pos'], it['rot_euler'], it['scale'])
        fast_link(empty, parent_coll)
        processed += 1
        if progress and (processed % 64) == 0:
          progress.update(step=1)

def build_mission_objects(ctx):
  ctx.progress.update("Importing mission data...")

  # Collect TSStatic items for batched instancing
  ts_groups = defaultdict(list)

  for idx, i in enumerate(ctx.level_data):
    cls = i.get('class')
    parent_coll = get_parent_collection(i.get('__parent'))
    rot = i.get('rotationMatrix')
    rot_euler = get_euler_from_rotlist(rot)
    pos = i.get('position') or [0,0,0]
    scl = _normalize_scale(i.get('scale') or [1,1,1])

    if cls == 'ScatterSky':
      world = bpy.context.scene.world
      if world and world.node_tree:
        nt = world.node_tree
        sky = nt.nodes.new("ShaderNodeTexSky")
        bg = nt.nodes.get("Background") or nt.nodes.new("ShaderNodeBackground")
        nt.links.new(bg.inputs["Color"], sky.outputs["Color"])
        sky.sky_type = 'NISHITA'
        sky.sun_disc = True
        try:
          sky.sun_elevation = math.radians(float(i.get('elevation', 40)))
        except Exception:
          sky.sun_elevation = math.radians(40)
        try:
          sky.sun_rotation = math.radians(float(i.get('azimuth', 60)))
        except Exception:
          sky.sun_rotation = math.radians(60)
        sky.sun_size = math.radians(1)
        sky.sun_intensity = 0.4

    elif cls == 'CameraBookmark':
      name = i.get('internalName') or 'CameraBookmark'
      make_camera_fast(name, pos, rot_euler, parent_coll)

    elif cls == 'SFXEmitter':
      name = i.get('name') or 'SFXEmitter'
      make_speaker_fast(name, pos, rot_euler, scl, parent_coll)

    elif cls == 'SpotLight':
      name = i.get('name') or 'SpotLight'
      rot_euler_rot = rot_euler.copy()
      rot_euler_rot.rotate_axis('X', math.radians(90))
      brightness = float(i.get('brightness') or 1) * 100.0
      color = tuple((i.get('color') or [1,1,1])[:3])
      make_light_fast('SPOT', name, pos, rot_euler_rot, scl, brightness, color, parent_coll)

    elif cls == 'PointLight':
      name = i.get('name') or 'PointLight'
      brightness = float(i.get('brightness') or 1) * 100.0
      color = tuple((i.get('color') or [1,1,1])[:3])
      make_light_fast('POINT', name, pos, rot_euler, scl, brightness, color, parent_coll)

    elif cls == 'GroundPlane':
      make_plane_fast('GroundPlane', 100000, pos, rot_euler, parent_coll)

    elif cls == 'WaterBlock':
      sc = (scl[0], scl[1], scl[2] / 2.0)
      pz = (pos[0], pos[1], pos[2] - sc[2])
      name = i.get('name') or 'WaterBlock'
      make_cube_fast(name, sc, pz, rot_euler, parent_coll)

    elif cls == 'TerrainBlock':
      parent_coll = get_parent_collection(i.get('__parent'))
      terrain_obj = import_terrain_block(ctx, i)
      if terrain_obj:
        fast_link(terrain_obj, parent_coll)

    elif cls == 'TSStatic':
      shapeName = i.get('shapeName')
      inst_name = (shapeName and shapeName.split('/')[-1]) or 'TSStatic'
      # Collect for instancing
      ts_groups[(inst_name, parent_coll)].append({
        'pos': pos,
        'rot_euler': rot_euler,
        'scale': scl,
      })

    if (idx & 31) == 0:
      ctx.progress.update(step=1)
      if (idx & 127) == 0:
        force_redraw()

  # Build TSStatic instancers
  if ts_groups:
    _build_tsstatic_instancers(ts_groups, progress=ctx.progress)