# ##### BEGIN LICENSE BLOCK #####
#
# This program is licensed under The MIT License:
# see LICENSE for the full license text
#
# ##### END LICENSE BLOCK #####

import bpy
from pathlib import Path
from .common import (
  try_get, ensure_principled, get_bsdf_input, find_uv_name_for_material,
  img_node, value_node, rgb_node, make_separate_r, clamp_01, connect_img,
  set_material_blend_shadow, get_scalar, get_map, use_uv2
)

def get_basecolor_factor(layer):
  val = try_get(layer, 'diffuseColor', None)
  if val is None: val = try_get(layer, 'baseColorFactor', None)
  if isinstance(val, (list, tuple)) and len(val) >= 3:
    r = float(val[0]); g = float(val[1]); b = float(val[2])
    a = float(val[3]) if len(val) >= 4 else 1.0
    return (r, g, b, a)
  return (1.0, 1.0, 1.0, 1.0)

def layer_has_meaning(layer):
  if not isinstance(layer, dict) or not layer:
    return False
  if get_map(layer, ['diffuseMap','colorMap','overlayMap','detailMap','normalMap','normalDetailMap','opacityMap',
                     'specularMap','reflectivityMap','colorPaletteMap']):
    return True
  bc = get_basecolor_factor(layer)
  if any(abs(bc[i]-1.0) > 1e-6 for i in range(3)): return True
  if abs(get_scalar(layer, 'opacityFactor', 'opacity', 1.0) - 1.0) > 1e-6: return True
  if abs(get_scalar(layer, 'roughnessFactor', None, 1.0) - 1.0) > 1e-6: return True
  if layer.get('vertColor', False) or layer.get('vtxColorToBaseColor', False): return True
  return False

def build_pbr_v0_material(mat_name: str, matdef: dict, level_dir: Path|None):
  if not mat_name or not isinstance(matdef, dict):
    return
  mat = bpy.data.materials.get(mat_name) or bpy.data.materials.new(mat_name)
  nt, bsdf, _ = ensure_principled(mat)
  links = nt.links
  stages = try_get(matdef, "Stages", [])
  if not isinstance(stages, list) or len(stages) == 0:
    return

  active_layers = try_get(matdef, 'activeLayers', None) or try_get(matdef, 'layerCount', None)
  if isinstance(active_layers, int) and active_layers >= 0:
    stages_iter = stages[:active_layers]
  else:
    stages_iter = stages[:1]
  stages_iter = [ly for ly in stages_iter if layer_has_meaning(ly)]
  stages_iter = stages_iter[:4]

  uv2_name = find_uv_name_for_material(mat, 1)
  uv1_name = find_uv_name_for_material(mat, 0)

  base_col_chain = None
  alpha_prev = value_node(nt, 0.0, 'AlphaPrev').outputs[0]
  roughness_stack = None
  normal_out = None
  any_opacity = False

  for idx, layer in enumerate(stages_iter):
    baseColorFactor = get_basecolor_factor(layer)
    roughnessFactor = get_scalar(layer, 'roughnessFactor', None, 1.0)
    opacityFactor   = get_scalar(layer, 'opacityFactor', 'opacity', 1.0)
    normalStrength  = get_scalar(layer, 'normalMapStrength', None, 1.0)
    detailBaseFac   = get_scalar(layer, 'detailBaseColorMapStrength', None, 0.0)
    detailNormFac   = get_scalar(layer, 'detailNormalMapStrength', None, 0.0)
    useVertColor    = bool(try_get(layer, "vertColor", False) or try_get(layer, "vtxColorToBaseColor", False))
    detScale        = try_get(layer, 'detailScale', None)

    bc_path   = get_map(layer, ['diffuseMap','colorMap','baseTex'])
    overlay   = get_map(layer, ['overlayMap'])
    detail    = get_map(layer, ['detailMap'])
    nor_path  = get_map(layer, ['normalMap','bumpTex'])
    det_nrm   = get_map(layer, ['normalDetailMap','detailNormalMap'])
    op_path   = get_map(layer, ['opacityMap'])
    spec_path = get_map(layer, ['specularMap'])
    refl_path = get_map(layer, ['reflectivityMap'])
    ao_path   = get_map(layer, ['ambientOcclusionMap'])
    pal_path  = get_map(layer, ['colorPaletteMap'])

    bc_uv2   = use_uv2(layer, ['diffuseMapUseUV'])
    ov_uv2   = use_uv2(layer, ['overlayMapUseUV'])
    det_uv2  = use_uv2(layer, ['detailMapUseUV'])
    nor_uv2  = use_uv2(layer, ['normalMapUseUV'])
    detn_uv2 = use_uv2(layer, ['normalDetailMapUseUV'])
    op_uv2   = use_uv2(layer, ['opacityMapUseUV'])
    sp_uv2   = use_uv2(layer, ['specularMapUseUV'])
    rf_uv2   = use_uv2(layer, ['reflectivityMapUseUV'])
    ao_uv2   = use_uv2(layer, ['ambientOcclusionMapUseUV'])
    pal_uv2  = use_uv2(layer, ['colorPaletteMapUseUV'])

    if op_path or abs(opacityFactor - 1.0) > 1e-6:
      any_opacity = True

    bc_factor = rgb_node(nt, (baseColorFactor[0], baseColorFactor[1], baseColorFactor[2], baseColorFactor[3]), f'BaseFactor L{idx}')
    this_color = bc_factor.outputs['Color']

    if bc_path:
      bc_img = connect_img(nt, bc_path, level_dir, 'sRGB', bc_uv2, uv2_name, uv1_name, label=f'Diffuse L{idx}')
      mul = nt.nodes.new('ShaderNodeMixRGB'); mul.blend_type='MULTIPLY'; mul.inputs['Fac'].default_value=1.0
      links.new(bc_factor.outputs['Color'], mul.inputs['Color1'])
      links.new(bc_img.outputs['Color'], mul.inputs['Color2'])
      this_color = mul.outputs['Color']

    if pal_path:
      pal_img = connect_img(nt, pal_path, level_dir, 'sRGB', pal_uv2, uv2_name, uv1_name, label=f'Palette L{idx}')
      pal_mul = nt.nodes.new('ShaderNodeMixRGB'); pal_mul.blend_type='MULTIPLY'; pal_mul.inputs['Fac'].default_value=1.0
      links.new(this_color, pal_mul.inputs['Color1'])
      links.new(pal_img.outputs['Color'], pal_mul.inputs['Color2'])
      this_color = pal_mul.outputs['Color']

    if overlay:
      ov_img = connect_img(nt, overlay, level_dir, 'sRGB', ov_uv2, uv2_name, uv1_name, label=f'Overlay L{idx}')
      mix = nt.nodes.new('ShaderNodeMixRGB'); mix.blend_type='MIX'
      sep, rname = make_separate_r(nt)
      links.new(ov_img.outputs['Color'], sep.inputs[0])
      fac_socket = ov_img.outputs.get('Alpha') or sep.outputs[rname]
      links.new(fac_socket, mix.inputs['Fac'])
      links.new(this_color, mix.inputs['Color1'])
      links.new(ov_img.outputs['Color'], mix.inputs['Color2'])
      this_color = mix.outputs['Color']

    if ao_path:
      ao_img = connect_img(nt, ao_path, level_dir, 'Non-Color', ao_uv2, uv2_name, uv1_name, label=f'AO L{idx}')
      ao_mul = nt.nodes.new('ShaderNodeMixRGB'); ao_mul.blend_type='MULTIPLY'; ao_mul.inputs['Fac'].default_value=1.0
      links.new(this_color, ao_mul.inputs['Color1'])
      links.new(ao_img.outputs['Color'], ao_mul.inputs['Color2'])
      this_color = ao_mul.outputs['Color']

    if useVertColor:
      vcol = nt.nodes.new('ShaderNodeAttribute'); vcol.attribute_name = 'Col'
      mul2 = nt.nodes.new('ShaderNodeMixRGB'); mul2.blend_type='MULTIPLY'; mul2.inputs['Fac'].default_value=1.0
      links.new(this_color, mul2.inputs['Color1'])
      links.new(vcol.outputs['Color'], mul2.inputs['Color2'])
      this_color = mul2.outputs['Color']

    if detail and abs(detailBaseFac) > 1e-6:
      det_img = connect_img(nt, detail, level_dir, 'sRGB', det_uv2, uv2_name, uv1_name, label=f'DetailCol L{idx}', scale=detScale)
      scale2 = nt.nodes.new('ShaderNodeVectorMath'); scale2.operation='MULTIPLY'
      c2 = nt.nodes.new('ShaderNodeCombineXYZ'); c2.inputs[0].default_value=2.0; c2.inputs[1].default_value=2.0; c2.inputs[2].default_value=2.0
      links.new(det_img.outputs['Color'], scale2.inputs[0]); links.new(c2.outputs[0], scale2.inputs[1])
      sub1 = nt.nodes.new('ShaderNodeVectorMath'); sub1.operation='ADD'
      cn1 = nt.nodes.new('ShaderNodeCombineXYZ'); cn1.inputs[0].default_value=-1.0; cn1.inputs[1].default_value=-1.0; cn1.inputs[2].default_value=-1.0
      links.new(scale2.outputs[0], sub1.inputs[0]); links.new(cn1.outputs[0], sub1.inputs[1])
      dvec = nt.nodes.new('ShaderNodeCombineXYZ')
      dvec.inputs[0].default_value = detailBaseFac
      dvec.inputs[1].default_value = detailBaseFac
      dvec.inputs[2].default_value = detailBaseFac
      vmul = nt.nodes.new('ShaderNodeVectorMath'); vmul.operation='MULTIPLY'
      links.new(sub1.outputs[0], vmul.inputs[0]); links.new(dvec.outputs[0], vmul.inputs[1])
      add_det = nt.nodes.new('ShaderNodeMixRGB'); add_det.blend_type='ADD'; add_det.use_clamp=True
      links.new(this_color, add_det.inputs['Color1'])
      links.new(vmul.outputs[0], add_det.inputs['Color2'])
      this_color = add_det.outputs['Color']

    layer_opacity_val = value_node(nt, opacityFactor, f'Opacity L{idx}')
    if op_path:
      op_img = connect_img(nt, op_path, level_dir, 'Non-Color', op_uv2, uv2_name, uv1_name, label=f'Opacity L{idx}')
      sep, rname = make_separate_r(nt)
      links.new(op_img.outputs['Color'], sep.inputs[0])
      op_mul = nt.nodes.new('ShaderNodeMath'); op_mul.operation='MULTIPLY'
      links.new(layer_opacity_val.outputs[0], op_mul.inputs[0])
      links.new(sep.outputs[rname], op_mul.inputs[1])
      layer_opacity_val = op_mul
    layer_alpha = clamp_01(nt, links, layer_opacity_val.outputs[0]).outputs['Result']

    if base_col_chain is None:
      base_col_chain = this_color
    else:
      mix_layer = nt.nodes.new('ShaderNodeMixRGB'); mix_layer.blend_type='MIX'
      links.new(layer_alpha, mix_layer.inputs['Fac'])
      links.new(base_col_chain, mix_layer.inputs['Color1'])
      links.new(this_color, mix_layer.inputs['Color2'])
      base_col_chain = mix_layer.outputs['Color']

    one_minus = nt.nodes.new('ShaderNodeMath'); one_minus.operation='SUBTRACT'
    one_minus.inputs[0].default_value = 1.0
    links.new(layer_alpha, one_minus.inputs[1])
    mul_prev = nt.nodes.new('ShaderNodeMath'); mul_prev.operation='MULTIPLY'
    links.new(alpha_prev, mul_prev.inputs[0]); links.new(one_minus.outputs['Value'], mul_prev.inputs[1])
    add_alpha = nt.nodes.new('ShaderNodeMath'); add_alpha.operation='ADD'
    links.new(mul_prev.outputs['Value'], add_alpha.inputs[0]); links.new(layer_alpha, add_alpha.inputs[1])
    alpha_prev = add_alpha.outputs['Value']

    if spec_path:
      sp_img = connect_img(nt, spec_path, level_dir, 'Non-Color', sp_uv2, uv2_name, uv1_name, label=f'Specular L{idx}')
      sep_sp, rname_sp = make_separate_r(nt)
      links.new(sp_img.outputs['Color'], sep_sp.inputs[0])
      gloss_socket = sp_img.outputs.get('Alpha')
      if gloss_socket:
        inv = nt.nodes.new('ShaderNodeMath'); inv.operation='SUBTRACT'; inv.inputs[0].default_value=1.0
        links.new(gloss_socket, inv.inputs[1])
        rough_val = inv.outputs['Value']
      else:
        inv = nt.nodes.new('ShaderNodeMath'); inv.operation='SUBTRACT'; inv.inputs[0].default_value=1.0
        links.new(sep_sp.outputs[rname_sp], inv.inputs[1])
        rough_val = inv.outputs['Value']
      if abs(roughnessFactor - 1.0) > 1e-6:
        rf_mul = nt.nodes.new('ShaderNodeMath'); rf_mul.operation='MULTIPLY'
        links.new(rough_val, rf_mul.inputs[0]); links.new(value_node(nt, roughnessFactor).outputs[0], rf_mul.inputs[1])
        rough_val = rf_mul.outputs['Value']
      if roughness_stack is None:
        roughness_stack = rough_val

      spec_lum = nt.nodes.new('ShaderNodeRGBToBW')
      links.new(sp_img.outputs['Color'], spec_lum.inputs['Color'])
      try:
        sp_in = get_bsdf_input(bsdf, ['Specular', 'Specular IOR Level'])
        links.new(spec_lum.outputs['Val'], sp_in)
      except KeyError:
        pass

    if refl_path:
      rf_img = connect_img(nt, refl_path, level_dir, 'Non-Color', rf_uv2, uv2_name, uv1_name, label=f'Reflectivity L{idx}')
      rf_bw = nt.nodes.new('ShaderNodeRGBToBW')
      links.new(rf_img.outputs['Color'], rf_bw.inputs['Color'])
      try:
        sp_in = get_bsdf_input(bsdf, ['Specular', 'Specular IOR Level'])
        addn = nt.nodes.new('ShaderNodeMath'); addn.operation='ADD'
        addn.inputs[0].default_value = 0.25
        links.new(rf_bw.outputs['Val'], addn.inputs[1])
        links.new(addn.outputs['Value'], sp_in)
      except KeyError:
        pass

    base_normal = None
    if nor_path:
      nor_img = connect_img(nt, nor_path, level_dir, 'Non-Color', nor_uv2, uv2_name, uv1_name, label=f'Normal L{idx}')
      nrm_base = nt.nodes.new('ShaderNodeNormalMap')
      nrm_base.inputs['Strength'].default_value = float(normalStrength)
      links.new(nor_img.outputs['Color'], nrm_base.inputs['Color'])
      base_normal = nrm_base.outputs['Normal']

    if det_nrm and abs(detailNormFac) > 1e-6:
      det_img = connect_img(nt, det_nrm, level_dir, 'Non-Color', detn_uv2, uv2_name, uv1_name, label=f'DetailNorm L{idx}', scale=detScale)
      nrm_det = nt.nodes.new('ShaderNodeNormalMap')
      nrm_det.inputs['Strength'].default_value = float(detailNormFac)
      links.new(det_img.outputs['Color'], nrm_det.inputs['Color'])
      det_minus_001 = nt.nodes.new('ShaderNodeVectorMath'); det_minus_001.operation='ADD'
      cn1 = nt.nodes.new('ShaderNodeCombineXYZ'); cn1.inputs[2].default_value=-1.0
      links.new(nrm_det.outputs['Normal'], det_minus_001.inputs[0])
      links.new(cn1.outputs[0], det_minus_001.inputs[1])
      if base_normal is None:
        base_normal = det_minus_001.outputs[0]
      else:
        nrm_add = nt.nodes.new('ShaderNodeVectorMath'); nrm_add.operation='ADD'
        links.new(base_normal, nrm_add.inputs[0])
        links.new(det_minus_001.outputs[0], nrm_add.inputs[1])
        nrm_norm = nt.nodes.new('ShaderNodeVectorMath'); nrm_norm.operation='NORMALIZE'
        links.new(nrm_add.outputs[0], nrm_norm.inputs[0])
        base_normal = nrm_norm.outputs[0]

    if base_normal is not None:
      normal_out = base_normal

  if base_col_chain is not None:
    links.new(base_col_chain, bsdf.inputs['Base Color'])
  if roughness_stack is not None:
    links.new(roughness_stack, bsdf.inputs['Roughness'])
  if normal_out is not None:
    links.new(normal_out, bsdf.inputs['Normal'])

  links.new(alpha_prev, bsdf.inputs['Alpha'])
  alphaTest = try_get(matdef, 'alphaTest', None)
  alphaRef = try_get(matdef, 'alphaRef', None)
  if alphaTest and isinstance(alphaRef, int):
    set_material_blend_shadow(mat, blend_mode='CLIP', alpha_threshold=(alphaRef/255.0))
  elif any_opacity:
    set_material_blend_shadow(mat, blend_mode='BLEND')
  else:
    set_material_blend_shadow(mat, blend_mode='OPAQUE')

  if hasattr(mat, 'use_backface_culling'):
    dbl = try_get(matdef, 'doubleSided', False)
    mat.use_backface_culling = not bool(dbl)
