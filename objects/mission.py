# ##### BEGIN LICENSE BLOCK #####
#
# This program is licensed under The MIT License:
# see LICENSE for the full license text
#
# ##### END LICENSE BLOCK #####

import bpy
import math
import os
from collections import defaultdict

from ..core.progress import force_redraw
from ..objects.terrainblock import import_terrain_block
from ..objects.groundcover import build_groundcover_objects, bake_groundcover_to_mesh
from ..materials.water import build_water_material_for_object

from .common import get_euler_from_rotlist, _normalize_scale, get_parent_collection, fast_link
from .primitives import (
  make_camera_fast, make_speaker_fast, make_light_fast, make_plane_fast, make_cube_fast
)
from .tsstatic import build_tsstatic_instancers
from .river import make_river_from_nodes_catmull
from .decal_road import make_decal_road
from .mesh_road import make_mesh_road

def _shape_key(shape_name: str | None) -> str:
  """
  Canonical key for TSStatic shapes.
  MUST match how shapes are named in shapes/collada.py.
  """
  s = (shape_name or "").replace("\\", "/").strip()
  base = os.path.basename(s) if s else ""
  return (base or "tsstatic").lower()

def _apply_custom_props(obj, data_dict):
  for k, v in data_dict.items():
    try:
      obj[k] = v
    except Exception as e:
      print(f"Could not store custom property {k} on {obj.name}: {e}")


def build_mission_objects(ctx):
  ctx.progress.update("Importing mission data...")
  # Collect TSStatic items for batched instancing
  ts_groups = defaultdict(list)
  groundcovers_present = False
  terrain_target_obj = None
  pending_decalroads = []

  for idx, i in enumerate(ctx.level_data):
    cls = i.get('class')
    parent_coll = get_parent_collection(i.get('__parent'))
    rot = i.get('rotationMatrix')
    rot_euler = get_euler_from_rotlist(rot)
    pos = i.get('position') or [0, 0, 0]
    scl = _normalize_scale(i.get('scale') or [1, 1, 1])

    handled = False  # track whether we did something specific for this class

    if cls == 'ScatterSky':
      handled = True
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
      handled = True
      name = i.get('internalName') or 'CameraBookmark'
      obj = make_camera_fast(name, pos, rot_euler, parent_coll)
      if obj:
        _apply_custom_props(obj, i)

    elif cls == 'SFXEmitter':
      handled = True
      name = i.get('name') or 'SFXEmitter'
      obj = make_speaker_fast(name, pos, rot_euler, scl, parent_coll)
      if obj:
        _apply_custom_props(obj, i)

    elif cls == 'SpotLight':
      handled = True
      name = i.get('name') or 'SpotLight'
      rot_euler_rot = rot_euler.copy()
      rot_euler_rot.rotate_axis('X', math.radians(90))
      brightness = float(i.get('brightness') or 1) * 100.0
      color = tuple((i.get('color') or [1, 1, 1])[:3])
      angle = float(i.get('outerAngle') or math.radians(45))
      obj = make_light_fast('SPOT', name, pos, rot_euler_rot, scl, brightness, color, parent_coll, angle)
      if obj:
        _apply_custom_props(obj, i)

    elif cls == 'PointLight':
      handled = True
      name = i.get('name') or 'PointLight'
      brightness = float(i.get('brightness') or 1) * 100.0
      color = tuple((i.get('color') or [1, 1, 1])[:3])
      obj = make_light_fast('POINT', name, pos, rot_euler, scl, brightness, color, parent_coll)
      if obj:
        _apply_custom_props(obj, i)

    elif cls == 'GroundPlane':
      handled = True
      obj = make_plane_fast('GroundPlane', 100000, pos, rot_euler, parent_coll)
      if obj:
        _apply_custom_props(obj, i)

    elif cls == 'WaterBlock':
      handled = True
      sc = (scl[0], scl[1], scl[2] / 2.0)
      pz = (pos[0], pos[1], pos[2] - sc[2])
      name = i.get('name') or 'WaterBlock'
      obj = make_cube_fast(name, sc, pz, rot_euler, parent_coll)
      if obj:
        _apply_custom_props(obj, i)
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
      handled = True
      sc = (scl[0], scl[1], scl[2] / 2.0)
      pz = (pos[0], pos[1], pos[2] - sc[2])
      name = i.get('name') or 'WaterPlane'
      obj = make_plane_fast(name, 100000, pos, rot_euler, parent_coll)
      if obj:
        _apply_custom_props(obj, i)
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
      handled = True
      name = i.get('name') or 'River'
      nodes = i.get('nodes') or []
      subdiv_len = i.get('subdivideLength') or i.get('SubdivideLength') or 1.0
      obj = make_river_from_nodes_catmull(
        name, nodes, float(subdiv_len),
        parent_coll, build_water_material_for_object, ctx.config.level_path
      )
      if obj:
        _apply_custom_props(obj, i)

    elif cls == 'DecalRoad':
      handled = True
      name = i.get('name') or 'DecalRoad'
      if terrain_target_obj is not None:
        i['useShrinkwrap'] = True
        i['shrinkwrapTarget'] = terrain_target_obj.name
        obj = make_decal_road(name, i, parent_coll)
        if obj:
          _apply_custom_props(obj, i)

      else:
        pending_decalroads.append((name, i.copy(), parent_coll))

    elif cls == 'MeshRoad':
      handled = True
      name = i.get('name') or 'MeshRoad'
      obj = make_mesh_road(name, i, parent_coll)
      if obj:
        _apply_custom_props(obj, i)

    elif cls == 'TerrainBlock':
      handled = True
      parent_coll = get_parent_collection(i.get('__parent'))
      terrain_obj = import_terrain_block(ctx, i)
      if terrain_obj:
        fast_link(terrain_obj, parent_coll)
        if terrain_target_obj is None and getattr(terrain_obj, "type", None) == 'MESH':
          terrain_target_obj = terrain_obj
        _apply_custom_props(terrain_obj, i)

    elif cls == 'TSStatic':
      handled = True
      shapeName = i.get('shapeName')
      inst_name = _shape_key(shapeName)
      # Collect for instancing
      ts_groups[(inst_name, parent_coll)].append({
        'pos': pos,
        'rot_euler': rot_euler,
        'scale': scl,
      })

    elif cls == 'GroundCover':
      handled = True
      groundcovers_present = True

    if not handled and cls and not cls == 'SimGroup':
      name = i.get('name') or i.get('internalName') or cls
      empty = bpy.data.objects.new(name, None)
      empty.empty_display_type = 'PLAIN_AXES'
      empty.location = pos
      empty.rotation_euler = rot_euler
      empty.scale = scl

      for k, v in i.items():
        try:
          empty[k] = v
        except Exception as e:
          print(f"Could not store custom property {k} on {name}: {e}")

      if parent_coll:
        parent_coll.objects.link(empty)

    if (idx & 31) == 0:
      ctx.progress.update(step=1)
      if (idx & 127) == 0:
        force_redraw()

  # Build GroundCover instancers
  if groundcovers_present:
    build_groundcover_objects(ctx)
    bake_groundcover_to_mesh(remove_particles=True)

  if pending_decalroads:
    if terrain_target_obj is not None:
      for name, data, coll in pending_decalroads:
        data['shrinkwrapTarget'] = terrain_target_obj.name
        obj = make_decal_road(name, data, coll)
        if obj:
          _apply_custom_props(obj, i)
    else:
      for name, data, coll in pending_decalroads:
        obj = make_decal_road(name, data, coll)
        if obj:
          _apply_custom_props(obj, i)

  # Build TSStatic instancers
  if ts_groups:
    build_tsstatic_instancers(ts_groups, progress=ctx.progress)