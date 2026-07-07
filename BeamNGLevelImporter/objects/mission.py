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
from ..core.paths import resolve_any_beamng_path
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

LM_PER_W = 683.0
COOKIE_TEX_NODE = "BeamNG Cookie Texture"
COOKIE_COORD_NODE = "BeamNG Cookie Coordinates"

def lumens_to_watts(lm, lm_per_w=LM_PER_W):
  return float(lm) / float(lm_per_w)

def candela_to_watts(cd, lm_per_w=LM_PER_W):
  """
  Convert peak candela to watts:
    cd -> point-like luminous intensity, matching Blender spot light normalization.
  Blender spot lights use point-light energy with a cone mask, so the cone angle
  is not part of the energy conversion.
  """
  lumens = float(cd) * 4.0 * math.pi
  return lumens_to_watts(lumens, lm_per_w)

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

def _find_light_node(light, bl_idname):
  if not light or not light.node_tree:
    return None
  for node in light.node_tree.nodes:
    if node.bl_idname == bl_idname:
      return node
  return None

def _resolve_cookie_path(cookie, level_path):
  cookie_path = resolve_any_beamng_path(cookie, level_path)
  if cookie_path:
    return cookie_path

  value = str(cookie or "").strip()
  if not value:
    return None
  path = os.path.expanduser(value)
  if os.path.isabs(path) and os.path.exists(path):
    return path
  if value.startswith("/") and level_path:
    root = level_path.parent.parent
    path = root / value.lstrip("/")
    if path.exists():
      return path
  return None

def _apply_light_cookie_nodes(obj, cookie, level_path):
  light = getattr(obj, "data", None)
  cookie = str(cookie or "").strip()
  if not light or not cookie:
    return

  light.use_nodes = True
  nt = light.node_tree
  if not nt:
    return

  emission = _find_light_node(light, "ShaderNodeEmission") or nt.nodes.new("ShaderNodeEmission")
  output = _find_light_node(light, "ShaderNodeOutputLight") or nt.nodes.new("ShaderNodeOutputLight")
  tex = nt.nodes.get(COOKIE_TEX_NODE) or nt.nodes.new("ShaderNodeTexImage")
  coord = nt.nodes.get(COOKIE_COORD_NODE) or nt.nodes.new("ShaderNodeTexCoord")

  tex.name = COOKIE_TEX_NODE
  tex.label = "BeamNG Cookie"
  tex.extension = "CLIP"
  tex.location = (-560, 120)
  coord.name = COOKIE_COORD_NODE
  coord.label = "BeamNG Cookie Coordinates"
  coord.location = (-760, 120)

  cookie_path = _resolve_cookie_path(cookie, level_path)
  if cookie_path:
    try:
      tex.image = bpy.data.images.load(str(cookie_path), check_existing=True)
    except Exception as e:
      print(f"Could not load cookie texture {cookie} for light {obj.name}: {e}")
      tex.image = None
  else:
    tex.image = None

  emission.location = (-180, 0)
  output.location = (120, 0)
  if "Strength" in emission.inputs:
    emission.inputs["Strength"].default_value = 1.0

  for link in list(nt.links):
    if link.to_node == emission and link.to_socket == emission.inputs["Color"]:
      nt.links.remove(link)
    elif link.to_node == output and link.to_socket == output.inputs["Surface"]:
      nt.links.remove(link)

  if "UV" in coord.outputs and "Vector" in tex.inputs:
    nt.links.new(coord.outputs["UV"], tex.inputs["Vector"])
  nt.links.new(tex.outputs["Color"], emission.inputs["Color"])
  nt.links.new(emission.outputs["Emission"], output.inputs["Surface"])

def _apply_light_props(obj, data_dict, level_path):
  _apply_custom_props(obj, data_dict)
  if not obj or not getattr(obj, "data", None):
    return
  cookie = data_dict.get("cookie")
  if cookie:
    try:
      obj.data["cookie"] = cookie
    except Exception as e:
      print(f"Could not store cookie on light data {obj.name}: {e}")
    _apply_light_cookie_nodes(obj, cookie, level_path)


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
        try:
          sky.sky_type = 'MULTIPLE_SCATTERING'
        except Exception:
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
        sky.sun_intensity = 1.0

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

      # SpotLight intensity is candelas; brightness is the normalized editor value.
      intensity_cd = float(i.get('intensity')) if i.get('intensity') is not None else float(i.get('brightness') or 1.0) * 5000.0
      color = tuple((i.get('color') or [1, 1, 1])[:3])
      angle = math.radians(float(i.get('outerAngle') or 45.0))

      power_w = candela_to_watts(intensity_cd)

      obj = make_light_fast('SPOT', name, pos, rot_euler_rot, scl, power_w, color, parent_coll, angle)
      if obj:
        _apply_light_props(obj, i, ctx.config.level_path)

    elif cls == 'PointLight':
      handled = True
      name = i.get('name') or 'PointLight'

      # PointLight intensity is lumens; brightness is candelas normalized by LightRange.
      flux_lm = float(i.get('intensity')) if i.get('intensity') is not None else float(i.get('brightness') or 1.0) * 4.0 * math.pi * 5000.0
      color = tuple((i.get('color') or [1, 1, 1])[:3])

      power_w = lumens_to_watts(flux_lm)

      obj = make_light_fast('POINT', name, pos, rot_euler, scl, power_w, color, parent_coll)
      if obj:
        _apply_light_props(obj, i, ctx.config.level_path)

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