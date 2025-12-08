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
  val = try_get(layer, 'baseColorFactor', None)
  if val is None: val = try_get(layer, 'baseColor', None)
  if val is None: val = try_get(layer, 'diffuseColor', None)
  if isinstance(val, (list, tuple)) and len(val) >= 3:
    r = float(val[0]); g = float(val[1]); b = float(val[2])
    a = float(val[3]) if len(val) >= 4 else 1.0
    return (r, g, b, a)
  return (1.0, 1.0, 1.0, 1.0)

def get_emissive_factor(layer):
  val = try_get(layer, 'emissiveFactor', None)
  if isinstance(val, (list, tuple)) and len(val) >= 3:
    return [float(val[0]), float(val[1]), float(val[2])]
  return [0.0, 0.0, 0.0]

def layer_has_meaning(layer):
  if not isinstance(layer, dict) or not layer:
    return False
  if get_map(layer, ['baseColorMap','colorMap','diffuseMap','metallicMap','roughnessMap','normalMap',
                     'ambientOcclusionMap','emissiveMap','opacityMap',
                     'clearCoatMap','clearCoatRoughnessMap','baseColorDetailMap','detailMap',
                     'normalDetailMap','detailNormalMap']):
    return True
  bc = get_basecolor_factor(layer)
  if any(abs(bc[i]-1.0) > 1e-6 for i in range(3)): return True
  if abs(get_scalar(layer, 'opacityFactor', 'opacity', 1.0) - 1.0) > 1e-6: return True
  if abs(get_scalar(layer, 'metallicFactor', 'metallic', 1.0) - 1.0) > 1e-6: return True
  if abs(get_scalar(layer, 'roughnessFactor', 'roughness', 1.0) - 1.0) > 1e-6: return True
  if abs(get_scalar(layer, 'clearCoatFactor', 'clearCoat', 0.0)) > 1e-6: return True
  if abs(get_scalar(layer, 'clearCoatRoughnessFactor', 'clearCoatRoughness', 0.0)) > 1e-6: return True
  em = get_emissive_factor(layer)
  if any(abs(e) > 1e-6 for e in em): return True
  if layer.get('vertColor', False) or layer.get('vtxColorToBaseColor', False): return True
  return False

def build_pbr_v15_material(mat_name: str, matdef: dict, level_dir: Path|None):
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
  metallic_stack = None
  roughness_stack = None
  normal_out = None
  emissive_stack = None
  coat_stack = None
  coat_rough_stack = None
  any_opacity = False

  for idx, layer in enumerate(stages_iter):
    baseColorFactor = get_basecolor_factor(layer)
    emissiveFactor  = get_emissive_factor(layer)
    metallicFactor  = get_scalar(layer, 'metallicFactor', 'metallic', 0.0)
    roughnessFactor = get_scalar(layer, 'roughnessFactor', 'roughness', 1.0)
    opacityFactor   = get_scalar(layer, 'opacityFactor', 'opacity', 1.0)
    clearCoatFactor = get_scalar(layer, 'clearCoatFactor', 'clearCoat', 0.0)
    clearCoatRoughnessFactor = get_scalar(layer, 'clearCoatRoughnessFactor', 'clearCoatRoughness', 0.0)
    normalStrength  = get_scalar(layer, 'normalMapStrength', None, 1.0)
    detailBaseFac   = get_scalar(layer, 'detailBaseColorMapStrength', None, 0.0)
    detailNormFac   = get_scalar(layer, 'detailNormalMapStrength', None, 0.0)
    useVertColor    = bool(try_get(layer, "vertColor", False) or try_get(layer, "vtxColorToBaseColor", False))
    detScale        = try_get(layer, 'detailScale', None)

    bc_path  = get_map(layer, ['baseColorMap','colorMap','diffuseMap'])
    met_path = get_map(layer, ['metallicMap'])
    rou_path = get_map(layer, ['roughnessMap'])
    nor_path = get_map(layer, ['normalMap'])
    ao_path  = get_map(layer, ['ambientOcclusionMap','aoMap'])
    emi_path = get_map(layer, ['emissiveMap'])
    op_path  = get_map(layer, ['opacityMap'])
    cc_path  = get_map(layer, ['clearCoatMap'])
    ccr_path = get_map(layer, ['clearCoatRoughnessMap'])
    det_col_path = get_map(layer, ['baseColorDetailMap','detailMap'])
    det_nrm_path = get_map(layer, ['normalDetailMap','detailNormalMap'])

    bc_uv2  = use_uv2(layer, ['baseColorMapUseUV','diffuseMapUseUV'])
    met_uv2 = use_uv2(layer, ['metallicMapUseUV'])
    rou_uv2 = use_uv2(layer, ['roughnessMapUseUV'])
    nor_uv2 = use_uv2(layer, ['normalMapUseUV'])
    ao_uv2  = use_uv2(layer, ['ambientOcclusionMapUseUV','aoMapUseUV'])
    emi_uv2 = use_uv2(layer, ['emissiveMapUseUV'])
    op_uv2  = use_uv2(layer, ['opacityMapUseUV'])
    cc_uv2  = use_uv2(layer, ['clearCoatMapUseUV'])
    ccr_uv2 = use_uv2(layer, ['clearCoatRoughnessMapUseUV'])
    det_col_uv2 = use_uv2(layer, ['detailMapUseUV','baseColorDetailMapUseUV'])
    det_nrm_uv2 = use_uv2(layer, ['normalDetailMapUseUV','detailNormalMapUseUV'])

    if op_path or abs(opacityFactor - 1.0) > 1e-6:
      any_opacity = True

    bc_factor = rgb_node(nt, (baseColorFactor[0], baseColorFactor[1], baseColorFactor[2], baseColorFactor[3]), f'BaseFactor L{idx}')
    this_color = bc_factor.outputs['Color']

    if bc_path:
      bc_img = connect_img(nt, bc_path, level_dir, 'sRGB', bc_uv2, uv2_name, uv1_name, label=f'BaseColor L{idx}')
      mul = nt.nodes.new('ShaderNodeMixRGB'); mul.blend_type='MULTIPLY'; mul.inputs['Fac'].default_value=1.0
      links.new(bc_factor.outputs['Color'], mul.inputs['Color1'])
      links.new(bc_img.outputs['Color'], mul.inputs['Color2'])
      this_color = mul.outputs['Color']

    if useVertColor:
      vcol = nt.nodes.new('ShaderNodeAttribute'); vcol.attribute_name = 'Col'
      mul2 = nt.nodes.new('ShaderNodeMixRGB'); mul2.blend_type='MULTIPLY'; mul2.inputs['Fac'].default_value=1.0
      links.new(this_color, mul2.inputs['Color1'])
      links.new(vcol.outputs['Color'], mul2.inputs['Color2'])
      this_color = mul2.outputs['Color']

    if ao_path:
      ao_img = connect_img(nt, ao_path, level_dir, 'Non-Color', ao_uv2, uv2_name, uv1_name, label=f'AO L{idx}')
      ao_mul = nt.nodes.new('ShaderNodeMixRGB'); ao_mul.blend_type='MULTIPLY'; ao_mul.inputs['Fac'].default_value=1.0
      links.new(this_color, ao_mul.inputs['Color1'])
      links.new(ao_img.outputs['Color'], ao_mul.inputs['Color2'])
      this_color = ao_mul.outputs['Color']

    if det_col_path and abs(detailBaseFac) > 1e-6:
      det_img = connect_img(nt, det_col_path, level_dir, 'sRGB', det_col_uv2, uv2_name, uv1_name, label=f'DetailCol L{idx}', scale=detScale)
      vm_mul2 = nt.nodes.new('ShaderNodeVectorMath'); vm_mul2.operation='MULTIPLY'
      links.new(det_img.outputs['Color'], vm_mul2.inputs[0])
      c2 = nt.nodes.new('ShaderNodeCombineXYZ'); c2.inputs[0].default_value=2.0; c2.inputs[1].default_value=2.0; c2.inputs[2].default_value=2.0
      links.new(c2.outputs[0], vm_mul2.inputs[1])
      vm_addn1 = nt.nodes.new('ShaderNodeVectorMath'); vm_addn1.operation='ADD'
      links.new(vm_mul2.outputs[0], vm_addn1.inputs[0])
      cn1 = nt.nodes.new('ShaderNodeCombineXYZ'); cn1.inputs[0].default_value=-1.0; cn1.inputs[1].default_value=-1.0; cn1.inputs[2].default_value=-1.0
      links.new(cn1.outputs[0], vm_addn1.inputs[1])
      det_fac_vec = nt.nodes.new('ShaderNodeCombineXYZ')
      det_fac_vec.inputs[0].default_value = detailBaseFac
      det_fac_vec.inputs[1].default_value = detailBaseFac
      det_fac_vec.inputs[2].default_value = detailBaseFac
      vm_detscale = nt.nodes.new('ShaderNodeVectorMath'); vm_detscale.operation='MULTIPLY'
      links.new(vm_addn1.outputs[0], vm_detscale.inputs[0])
      links.new(det_fac_vec.outputs[0], vm_detscale.inputs[1])
      add_det = nt.nodes.new('ShaderNodeMixRGB'); add_det.blend_type='ADD'; add_det.use_clamp=True
      links.new(this_color, add_det.inputs['Color1'])
      links.new(vm_detscale.outputs[0], add_det.inputs['Color2'])
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
    cl = clamp_01(nt, links, layer_opacity_val.outputs[0])
    layer_alpha = cl.outputs['Result']

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
    links.new(alpha_prev, mul_prev.inputs[0])
    links.new(one_minus.outputs['Value'], mul_prev.inputs[1])
    add_alpha = nt.nodes.new('ShaderNodeMath'); add_alpha.operation='ADD'
    links.new(mul_prev.outputs['Value'], add_alpha.inputs[0])
    links.new(layer_alpha, add_alpha.inputs[1])
    alpha_prev = add_alpha.outputs['Value']

    if met_path:
      met_img = connect_img(nt, met_path, level_dir, 'Non-Color', met_uv2, uv2_name, uv1_name, label=f'Metallic L{idx}')
      sep, rname = make_separate_r(nt)
      links.new(met_img.outputs['Color'], sep.inputs[0])
      metallic_stack = sep.outputs[rname]
    if rou_path:
      rou_img = connect_img(nt, rou_path, level_dir, 'Non-Color', rou_uv2, uv2_name, uv1_name, label=f'Roughness L{idx}')
      sep, rname = make_separate_r(nt)
      links.new(rou_img.outputs['Color'], sep.inputs[0])
      rou_val = sep.outputs[rname]
      if abs(roughnessFactor - 1.0) > 1e-6:
        facn = value_node(nt, roughnessFactor, f'RoughnessFac L{idx}')
        rou_mul = nt.nodes.new('ShaderNodeMath'); rou_mul.operation='MULTIPLY'
        links.new(rou_val, rou_mul.inputs[0]); links.new(facn.outputs[0], rou_mul.inputs[1])
        rou_val = rou_mul.outputs['Value']
      roughness_stack = rou_val
    else:
      if abs(roughnessFactor - 1.0) > 1e-6:
        roughness_stack = value_node(nt, roughnessFactor, f'RoughnessFac L{idx}').outputs[0]

    base_normal = None
    if nor_path:
      nor_img = connect_img(nt, nor_path, level_dir, 'Non-Color', nor_uv2, uv2_name, uv1_name, label=f'Normal L{idx}')
      nrm_base = nt.nodes.new('ShaderNodeNormalMap')
      nrm_base.inputs['Strength'].default_value = float(normalStrength)
      links.new(nor_img.outputs['Color'], nrm_base.inputs['Color'])
      base_normal = nrm_base.outputs['Normal']

    if det_nrm_path and abs(detailNormFac) > 1e-6:
      det_img = connect_img(nt, det_nrm_path, level_dir, 'Non-Color', det_nrm_uv2, uv2_name, uv1_name, label=f'DetailNorm L{idx}', scale=detScale)
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

    if emi_path or (emissiveFactor and any(abs(c) > 1e-6 for c in emissiveFactor)):
      emi_col = rgb_node(nt, (emissiveFactor[0], emissiveFactor[1], emissiveFactor[2], 1.0))
      emi_socket = emi_col.outputs['Color']
      if emi_path:
        emi_img = connect_img(nt, emi_path, level_dir, 'sRGB', emi_uv2, uv2_name, uv1_name, label=f'Emissive L{idx}')
        emi_mul = nt.nodes.new('ShaderNodeMixRGB'); emi_mul.blend_type='MULTIPLY'; emi_mul.inputs['Fac'].default_value=1.0
        links.new(emi_socket, emi_mul.inputs['Color1'])
        links.new(emi_img.outputs['Color'], emi_mul.inputs['Color2'])
        emi_socket = emi_mul.outputs['Color']
      emissive_stack = emi_socket

    if cc_path or abs(clearCoatFactor) > 1e-6:
      cc_val = value_node(nt, clearCoatFactor, f'ClearCoatFac L{idx}').outputs[0]
      if cc_path:
        cc_img = connect_img(nt, cc_path, level_dir, 'Non-Color', cc_uv2, uv2_name, uv1_name, label=f'ClearCoat L{idx}')
        sep, rname = make_separate_r(nt)
        links.new(cc_img.outputs['Color'], sep.inputs[0])
        cc_mul = nt.nodes.new('ShaderNodeMath'); cc_mul.operation='MULTIPLY'
        links.new(cc_val, cc_mul.inputs[0]); links.new(sep.outputs[rname], cc_mul.inputs[1])
        coat_stack = cc_mul.outputs['Value']
      else:
        coat_stack = cc_val

    if ccr_path or abs(clearCoatRoughnessFactor) > 1e-6:
      ccr_val = value_node(nt, clearCoatRoughnessFactor, f'ClearCoatRoughFac L{idx}').outputs[0]
      if ccr_path:
        ccr_img = connect_img(nt, ccr_path, level_dir, 'Non-Color', ccr_uv2, uv2_name, uv1_name, label=f'ClearCoatRou L{idx}')
        sep, rname = make_separate_r(nt)
        links.new(ccr_img.outputs['Color'], sep.inputs[0])
        ccr_mul = nt.nodes.new('ShaderNodeMath'); ccr_mul.operation='MULTIPLY'
        links.new(ccr_val, ccr_mul.inputs[0]); links.new(sep.outputs[rname], ccr_mul.inputs[1])
        coat_rough_stack = ccr_mul.outputs['Value']
      else:
        coat_rough_stack = ccr_val

  if base_col_chain is not None:
    links.new(base_col_chain, bsdf.inputs['Base Color'])
  if metallic_stack is not None:
    links.new(metallic_stack, bsdf.inputs['Metallic'])
  if roughness_stack is not None:
    links.new(roughness_stack, bsdf.inputs['Roughness'])
    try:
      diff_rough_in = get_bsdf_input(bsdf, ['Diffuse Roughness'])
      links.new(roughness_stack, diff_rough_in)
    except KeyError:
      pass
  if normal_out is not None:
    links.new(normal_out, bsdf.inputs['Normal'])
  if emissive_stack is not None:
    try:
      emission_input = get_bsdf_input(bsdf, ['Emission Color', 'Emission'])
      links.new(emissive_stack, emission_input)
      try:
        emission_strength_input = get_bsdf_input(bsdf, ['Emission Strength'])
        emission_strength_input.default_value = 1.0
      except KeyError:
        pass
    except KeyError:
      pass
  if coat_stack is not None:
    try:
      cc_in = get_bsdf_input(bsdf, ['Coat Weight', 'Clearcoat'])
      links.new(coat_stack, cc_in)
    except KeyError:
      pass
  if coat_rough_stack is not None:
    try:
      ccr_in = get_bsdf_input(bsdf, ['Coat Roughness', 'Clearcoat Roughness'])
      links.new(coat_rough_stack, ccr_in)
    except KeyError:
      pass

  links.new(alpha_prev, bsdf.inputs['Alpha'])
  alphaTest = try_get(matdef, 'alphaTest', None)
  alphaRef = try_get(matdef, 'alphaRef', None)
  alphaTestValue = try_get(matdef, 'alphaTestValue', None) or try_get(matdef, 'AlphaTestValue', None)
  if alphaTest and isinstance(alphaRef, int):
    set_material_blend_shadow(mat, blend_mode='CLIP', alpha_threshold=(alphaRef/255.0))
  elif any_opacity:
    if alphaTestValue is not None:
      set_material_blend_shadow(mat, blend_mode='CLIP', alpha_threshold=alphaTestValue)
    else:
      set_material_blend_shadow(mat, blend_mode='BLEND')
  else:
    set_material_blend_shadow(mat, blend_mode='OPAQUE')

  if hasattr(mat, 'use_backface_culling'):
    dbl = try_get(matdef, 'doubleSided', False)
    mat.use_backface_culling = not bool(dbl)
  try:
    spec_sock = get_bsdf_input(bsdf, ['Specular', 'Specular IOR Level'])
    spec_sock.default_value = 0.5
  except KeyError:
    pass
