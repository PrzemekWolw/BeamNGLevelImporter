# ##### BEGIN LICENSE BLOCK #####
#
# This program is licensed under The MIT License:
# see LICENSE for the full license text
#
# ##### END LICENSE BLOCK #####

import bpy
import math
import mathutils
from ..core.progress import force_redraw
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

def build_mission_objects(ctx):
  ctx.progress.update("Importing mission data...")
  for idx, i in enumerate(ctx.level_data):
    cls = i.get('class')
    parent_coll = get_parent_collection(i.get('__parent'))
    rot = i.get('rotationMatrix')
    rot_euler = get_euler_from_rotlist(rot)
    pos = i.get('position') or [0,0,0]
    scl = i.get('scale') or [1,1,1]

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

    #elif cls == 'TerrainBlock' and ctx.config.terrain_export and ctx.config.terrain_export.exists():
    #  res = 0
    #  tfile = i.get('terrainFile')
    #  for k in ctx.terrain_meta:
    #    if k.get('datafile') == tfile:
    #      res = k.get('size') or 0
    #      break
    #  if not res:
    #    continue
    #  offset = res / 2.0
    #  p2 = (pos[0] + offset, pos[1] + offset, pos[2])
    #  sqr = float(i.get('squareSize') or 1.0)
    #  final_xy = ((res/2.0)*sqr, (res/2.0)*sqr, 1.0)
    #  o = make_plane_fast('TerrainBlock', 2.0, p2, rot_euler, parent_coll)
    #  o.matrix_world = make_matrix(p2, rot_euler, final_xy)
    #
    #  sub = o.modifiers.new("SubsurfModifier", 'SUBSURF')
    #  sub.levels = 11
    #  sub.render_levels = 11
    #  sub.subdivision_type = 'SIMPLE'
    #  disp = o.modifiers.new("DisplaceModifier", 'DISPLACE')
    #  disp.texture_coords = 'UV'
    #  disp.mid_level = 0.0
    #  disp.strength = float(i.get('maxHeight') or 2048)
    #
    #  tex_file = None
    #  for f in ctx.config.terrain_export.iterdir():
    #    low = f.name.lower()
    #    if low in ('heightmap.png','heightmap.dds','heightmap.exr','heightmap.tif','heightmap.tiff'):
    #      tex_file = f
    #      break
    #  if tex_file:
    #    try:
    #      tex = bpy.data.textures.new(o.name + '_heightmap', 'IMAGE')
    #      tex.image = bpy.data.images.load(str(tex_file))
    #      try: tex.image.colorspace_settings.name = 'Non-Color'
    #      except Exception: pass
    #      disp.texture = tex
    #    except Exception:
    #      mat_t = o.active_material or bpy.data.materials.new('Terrain_Mat')
    #      o.active_material = mat_t
    #      mat_t.use_nodes = True
    #      ntm = mat_t.node_tree
    #      outm = ntm.nodes.get('Material Output') or ntm.nodes.new('ShaderNodeOutputMaterial')
    #      dispn = ntm.nodes.new('ShaderNodeDisplacement')
    #      img = ntm.nodes.new('ShaderNodeTexImage')
    #      img.image = bpy.data.images.load(str(tex_file))
    #      try: img.image.colorspace_settings.name = 'Non-Color'
    #      except Exception: pass
    #      ntm.links.new(dispn.inputs['Height'], img.outputs['Color'])
    #      ntm.links.new(outm.inputs['Displacement'], dispn.outputs['Displacement'])
    #      dispn.inputs['Scale'].default_value = float(i.get('maxHeight') or 2048)
    #
    #  for m in ctx.terrain_mats:
    #    mat_t = bpy.data.materials.get(m)
    #    if mat_t:
    #      o.data.materials.append(mat_t)
    #      o.active_material_index = len(o.data.materials) - 1
    #
    #  if o.data:
    #    for poly in o.data.polygons:
    #      poly.use_smooth = True
    #
    elif cls == 'TSStatic':
      shapeName = i.get('shapeName')
      inst_name = (shapeName and shapeName.split('/')[-1]) or 'TSStatic'
      empty = bpy.data.objects.new(inst_name, None)
      empty.empty_display_type = 'ARROWS'
      empty.matrix_world = make_matrix(pos, rot_euler, tuple(scl))
      fast_link(empty, parent_coll)
      lib_obj = bpy.data.objects.get(inst_name)
      if lib_obj and lib_obj.type == 'MESH':
        cp = bpy.data.objects.new(inst_name, lib_obj.data)
        fast_link(cp, parent_coll)
        cp.parent = empty

    if (idx & 31) == 0:
      ctx.progress.update(step=1)
      if (idx & 127) == 0:
        force_redraw()
