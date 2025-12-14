# ##### BEGIN LICENSE BLOCK #####
#
# This program is licensed under The MIT License:
# see LICENSE for the full license text
#
# ##### END LICENSE BLOCK #####

import bpy
import mathutils

from .common import make_matrix, get_unit_plane_mesh, get_unit_cube_mesh, fast_link

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

def make_light_fast(kind, name, loc, rot_euler, scale, energy, color, parent_coll, angle=None):
  lamp = bpy.data.lights.new(name=name, type=kind)
  if energy is not None:
    lamp.energy = float(energy)
  if color is not None:
    lamp.color = (float(color[0]), float(color[1]), float(color[2]))
  if angle is not None and kind == 'SPOT':
    lamp.spot_size = angle
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