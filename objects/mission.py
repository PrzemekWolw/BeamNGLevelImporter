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
from ..objects.groundcover import build_groundcover_objects, bake_groundcover_to_mesh
from ..materials.water import build_water_material_for_object
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

def _cr_float(a0, a1, a2, a3, t: float) -> float:
  t2 = t * t
  t3 = t2 * t
  return 0.5 * ((2.0*a1) + (-a0 + a2)*t + (2.0*a0 - 5.0*a1 + 4.0*a2 - a3)*t2 + (-a0 + 3.0*a1 - 3.0*a2 + a3)*t3)

def _cr_vec(v0, v1, v2, v3, t: float):
  # v* are mathutils.Vector
  return mathutils.Vector((
    _cr_float(v0.x, v1.x, v2.x, v3.x, t),
    _cr_float(v0.y, v1.y, v2.y, v3.y, t),
    _cr_float(v0.z, v1.z, v2.z, v3.z, t),
  ))

def make_river_from_nodes_catmull(name, nodes, subdivide_len, parent_coll, material_builder, level_dir):
  if not isinstance(nodes, list) or len(nodes) < 2:
    return None

  # Extract node attributes
  P = [mathutils.Vector((float(n[0]), float(n[1]), float(n[2]))) for n in nodes]
  W = [float(n[3]) for n in nodes]
  D = [float(n[4]) for n in nodes]
  N = []
  for n in nodes:
    v = mathutils.Vector((float(n[5]), float(n[6]), float(n[7])))
    if v.length_squared == 0.0:
      v = mathutils.Vector((0.0, 0.0, 1.0))
    N.append(v.normalized())

  subdivide_len = max(1e-3, float(subdivide_len or 1.0))

  # Resample with Catmull–Rom
  S_pos, S_w, S_d, S_n = [], [], [], []
  count = len(P)
  for i in range(count - 1):
    p0 = P[i-1] if i-1 >= 0 else P[i]
    p1 = P[i]
    p2 = P[i+1]
    p3 = P[i+2] if (i+2) < count else P[i+1]

    w0 = W[i-1] if i-1 >= 0 else W[i];   w1 = W[i];   w2 = W[i+1];   w3 = W[i+2] if (i+2) < count else W[i+1]
    d0 = D[i-1] if i-1 >= 0 else D[i];   d1 = D[i];   d2 = D[i+1];   d3 = D[i+2] if (i+2) < count else D[i+1]
    n0 = N[i-1] if i-1 >= 0 else N[i];   n1 = N[i];   n2 = N[i+1];   n3 = N[i+2] if (i+2) < count else N[i+1]

    chord_len = (p2 - p1).length
    steps = max(1, math.ceil(chord_len / subdivide_len))

    for s in range(steps + 1):
      t = s / steps
      if i > 0 and s == 0:
        continue  # avoid duplicate at segment joins
      pos = _cr_vec(p0, p1, p2, p3, t)
      wid = _cr_float(w0, w1, w2, w3, t)
      dep = _cr_float(d0, d1, d2, d3, t)
      nor = _cr_vec(n0, n1, n2, n3, t)
      if nor.length_squared == 0.0:
        nor = mathutils.Vector((0.0, 0.0, 1.0))
      nor.normalize()
      S_pos.append(pos); S_w.append(wid); S_d.append(dep); S_n.append(nor)

  # Build ribbon surface (top)
  verts = []
  for j in range(len(S_pos)):
    if j == 0:
      fwd = (S_pos[j+1] - S_pos[j]).normalized()
    elif j == len(S_pos) - 1:
      fwd = (S_pos[j] - S_pos[j-1]).normalized()
    else:
      fwd = (S_pos[j+1] - S_pos[j-1]).normalized()
    if fwd.length_squared == 0.0:
      fwd = mathutils.Vector((1.0, 0.0, 0.0))

    rvec = fwd.cross(S_n[j])
    if rvec.length_squared == 0.0:
      # fallback if parallel
      rvec = S_n[j].orthogonal()
    rvec.normalize()

    half = S_w[j] * 0.5
    L = S_pos[j] - rvec * half
    R = S_pos[j] + rvec * half
    verts.append((L.x, L.y, L.z))
    verts.append((R.x, R.y, R.z))

  faces = []
  for j in range(len(S_pos) - 1):
    a = 2*j
    b = a + 1
    c = a + 3
    d = a + 2
    faces.append((a, d, c, b))

  me = bpy.data.meshes.new(f"River_{name}")
  me.from_pydata(verts, [], faces)
  me.update()
  obj = bpy.data.objects.new(name, me)
  fast_link(obj, parent_coll)
  for poly in me.polygons:
    poly.use_smooth = True

  try:
    wmat = material_builder(name, {'class': 'River'}, level_dir)
    if len(me.materials):
      me.materials[0] = wmat
    else:
      me.materials.append(wmat)
  except Exception as e:
    print(f"River material error for {name}: {e}")

  return obj

def build_mission_objects(ctx):
  ctx.progress.update("Importing mission data...")

  # Collect TSStatic items for batched instancing
  ts_groups = defaultdict(list)
  groundcovers_present = False

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
      obj = make_cube_fast(name, sc, pz, rot_euler, parent_coll)
      try:
        wmat = build_water_material_for_object(name, i, ctx.config.level_path)
        if obj and obj.data:
          if len(obj.data.materials):
            obj.data.materials[0] = wmat
          else:
            obj.data.materials.append(wmat)
        if obj.data and hasattr(bpy.types.Mesh, "polygons"):
          for p in obj.data.polygons:
            p.use_smooth = True
      except Exception as e:
        print(f"WaterBlock material error for {name}: {e}")

    elif cls == 'WaterPlane':
      sc = (scl[0], scl[1], scl[2] / 2.0)
      pz = (pos[0], pos[1], pos[2] - sc[2])
      name = i.get('name') or 'WaterPlane'
      obj = make_plane_fast(name, 100000, pos, rot_euler, parent_coll)
      try:
        wmat = build_water_material_for_object(name, i, ctx.config.level_path)
        if obj and obj.data:
          if len(obj.data.materials):
            obj.data.materials[0] = wmat
          else:
            obj.data.materials.append(wmat)
        if obj.data and hasattr(bpy.types.Mesh, "polygons"):
          for p in obj.data.polygons:
            p.use_smooth = True
      except Exception as e:
        print(f"WaterPlane material error for {name}: {e}")

    elif cls == 'River':
      name = i.get('name') or 'River'
      nodes = i.get('nodes') or []
      subdiv_len = i.get('subdivideLength') or i.get('SubdivideLength') or 1.0
      make_river_from_nodes_catmull(
        name, nodes, float(subdiv_len),
        parent_coll, build_water_material_for_object, ctx.config.level_path
      )

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

    elif cls == 'GroundCover':
      groundcovers_present = True

    if (idx & 31) == 0:
      ctx.progress.update(step=1)
      if (idx & 127) == 0:
        force_redraw()

  # Build TSStatic instancers
  if ts_groups:
    _build_tsstatic_instancers(ts_groups, progress=ctx.progress)

  # Build GroundCover instancers
  if groundcovers_present:
    build_groundcover_objects(ctx)
    bake_groundcover_to_mesh(remove_particles=True)