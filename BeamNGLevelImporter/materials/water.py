# ##### BEGIN LICENSE BLOCK #####
#
# This program is licensed under The MIT License:
# see LICENSE for the full license text
#
# ##### END LICENSE BLOCK #####

from __future__ import annotations
import bpy
from math import sqrt
from pathlib import Path
from .common import (
  ensure_principled, img_node, set_material_blend_shadow, try_get
)

def _col255_to_rgba(col):
  if not isinstance(col, (list, tuple)) or len(col) < 3:
    return (0.1, 0.2, 0.3, 1.0)
  r = float(col[0]) / 255.0
  g = float(col[1]) / 255.0
  b = float(col[2]) / 255.0
  a = float(col[3]) / 255.0 if len(col) >= 4 else 1.0
  return (r, g, b, a)

def _first_valid_list_of_two(seq_list, default=(1.0, 1.0)):
  # Pick first [x,y] pair we find; fallback default
  if isinstance(seq_list, list):
    for item in seq_list:
      if isinstance(item, dict):
        sc = item.get('rippleTexScale') or item.get('foamTexScale')
        if isinstance(sc, (list, tuple)) and len(sc) >= 2:
          return (float(sc[0]) or 1.0, float(sc[1]) or 1.0)
  return default

def _avg_ripple_magnitude(ripples, overall=1.0):
  vals = []
  if isinstance(ripples, list):
    for r in ripples:
      mag = try_get(r, 'rippleMagnitude', None)
      if mag is None:
        continue
      try:
        vals.append(float(mag))
      except Exception:
        pass
  if not vals:
    return max(0.1, float(overall))
  return max(0.1, sum(vals) / len(vals) * float(overall))

def _spec_power_to_roughness(spec_power: float) -> float:
  if spec_power is None:
    return 0.08
  try:
    sp = max(1.0, float(spec_power))
  except Exception:
    sp = 64.0
  # Loose approximation of Blinn exponent to roughness (GGX-ish)
  rough = sqrt(2.0 / (sp + 2.0))
  # keep a reasonable range
  return max(0.02, min(0.8, rough))

def build_water_material_for_object(mat_name: str, data: dict, level_dir: Path | None) -> bpy.types.Material:
  """
  Builds a light-weight water material for Blender using the game data.
  Returns the material (existing or newly created).
  """
  name = f"Water_{mat_name}" if mat_name else "Water_Default"
  mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
  nt, bsdf, out = ensure_principled(mat)
  links = nt.links

  # Basic appearance
  base_color = _col255_to_rgba(try_get(data, 'baseColor', [64,128,200,255]))
  reflectivity = float(try_get(data, 'reflectivity', 0.4) or 0.4)
  spec_power = try_get(data, 'specularPower', 128.0)
  roughness = _spec_power_to_roughness(spec_power)

  # Some water definitions have 'clarity' used in basic lighting path.
  # We'll use it to drive alpha/transmission gently.
  clarity = float(try_get(data, 'clarity', 0.5) or 0.5)
  # Alpha: lower clarity -> more opaque; higher clarity -> slightly more transparent
  alpha = max(0.2, min(1.0, 1.0 - (clarity * 0.5)))
  # Eevee-friendly: avoid fully transparent water for SSR stability
  set_material_blend_shadow(mat, blend_mode='HASHED', alpha_threshold=0.0, shadow='NONE')

  # Principled setup
  bsdf.inputs['Base Color'].default_value = base_color
  # Specular ~ reflectivity (keep in sane range)
  try:
    spec_input = bsdf.inputs['Specular'] if 'Specular' in bsdf.inputs else bsdf.inputs['Specular IOR Level']
    spec_input.default_value = max(0.0, min(1.0, 0.25 + 0.6 * reflectivity))
  except Exception:
    pass
  bsdf.inputs['Roughness'].default_value = roughness
  bsdf.inputs['Metallic'].default_value = 1

  # Transmission + IOR for Cycles (and partially Eevee)
  if 'Transmission' in bsdf.inputs:
    bsdf.inputs['Transmission'].default_value = min(1.0, 0.6 + clarity * 0.4)
  if 'IOR' in bsdf.inputs:
    bsdf.inputs['IOR'].default_value = 1.333

  # Mildly use alpha so the surface isn’t fully opaque
  if 'Alpha' in bsdf.inputs:
    bsdf.inputs['Alpha'].default_value = alpha

  # Ripple normal from rippleTex
  ripple_tex = try_get(data, 'rippleTex', 'core/art/water/ripple.dds')
  overall_ripple = float(try_get(data, 'overallRippleMagnitude', 1.0) or 1.0)
  ripple_strength = _avg_ripple_magnitude(try_get(data, 'Ripples (texture animation)', []), overall_ripple)
  # pick first ripple tiling from list if any
  ripple_scale = _first_valid_list_of_two(try_get(data, 'Ripples (texture animation)', []), default=(4.0, 4.0))

  # Mapping for ripple
  texcoord = nt.nodes.new('ShaderNodeTexCoord'); texcoord.location = (-1400, -150)
  mapping = nt.nodes.new('ShaderNodeMapping'); mapping.vector_type = 'POINT'; mapping.location = (-1220, -150)
  mapping.inputs['Scale'].default_value[0] = float(ripple_scale[0]) *10
  mapping.inputs['Scale'].default_value[1] = float(ripple_scale[1]) *10
  mapping.inputs['Scale'].default_value[2] = 1.0

  ripple = img_node(nt, ripple_tex, level_dir, colorspace='Non-Color', label='Ripple (Normal)')
  ripple.location = (-1020, -150)
  normal = nt.nodes.new('ShaderNodeNormalMap'); normal.location = (-800, -150)
  normal.inputs['Strength'].default_value = ripple_strength/10
  normal.space = 'WORLD'

  links.new(texcoord.outputs['Object'], mapping.inputs['Vector'])
  links.new(mapping.outputs['Vector'], ripple.inputs['Vector'])
  links.new(ripple.outputs['Color'], normal.inputs['Color'])
  links.new(normal.outputs['Normal'], bsdf.inputs['Normal'])

  # Foam overlay (optional, add to base color)
  foam_tex = try_get(data, 'foamTex', None)
  if foam_tex:
    foam_scale = _first_valid_list_of_two(try_get(data, 'Foam', []), default=(2.0, 2.0))
    foam_map = nt.nodes.new('ShaderNodeMapping'); foam_map.vector_type='POINT'; foam_map.location = (-1220, -360)
    foam_map.inputs['Scale'].default_value[0] = float(foam_scale[0])
    foam_map.inputs['Scale'].default_value[1] = float(foam_scale[1])
    foam_map.inputs['Scale'].default_value[2] = 1.0
    foam_img = img_node(nt, foam_tex, level_dir, colorspace='sRGB', label='Foam')
    foam_img.location = (-1020, -360)

    foam_fac = float(try_get(data, 'overallFoamOpacity', 0.0) or 0.0)
    foam_mix = nt.nodes.new('ShaderNodeMixRGB'); foam_mix.location = (-420, 60)
    foam_mix.blend_type = 'ADD'
    foam_mix.use_clamp = True
    foam_mix.inputs['Fac'].default_value = min(1.0, max(0.0, foam_fac))

    # Chain: baseColor -> add foam color -> to BSDF base color
    const_base = nt.nodes.new('ShaderNodeRGB'); const_base.location = (-640, 180)
    const_base.outputs[0].default_value = base_color

    links.new(texcoord.outputs['Object'], foam_map.inputs['Vector'])
    links.new(foam_map.outputs['Vector'], foam_img.inputs['Vector'])
    links.new(const_base.outputs['Color'], foam_mix.inputs['Color1'])
    links.new(foam_img.outputs['Color'], foam_mix.inputs['Color2'])
    links.new(foam_mix.outputs['Color'], bsdf.inputs['Base Color'])

  # Make it render friendly in Eevee
  try:
    # Blender 3.x/4.x – if available:
    mat.use_backface_culling = False
  except Exception:
    pass

  # Enable Screen Space Refraction (if the property exists on this Blender)
  for attr in ("use_screen_refraction", "use_ssr", "use_screen_space_reflections"):
    if hasattr(mat, attr):
      try:
        setattr(mat, attr, True)
      except Exception:
        pass
  return mat
