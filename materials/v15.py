# ##### BEGIN LICENSE BLOCK #####
#
# This program is licensed under The MIT License:
# see LICENSE for the full license text
#
# ##### END LICENSE BLOCK #####

from __future__ import annotations
import bpy
from pathlib import Path
from .common import (
  try_get, ensure_principled, get_bsdf_input, find_uv_name_for_material,
  img_node, value_node, rgb_node, make_separate_r, clamp_01, connect_img,
  set_material_blend_shadow, get_scalar, get_map, use_uv2
)

def new_frame(nt, label, color=(0.2, 0.2, 0.2), loc=(0, 0)):
  f = nt.nodes.new('NodeFrame')
  f.label = label
  f.use_custom_color = True
  f.color = color
  f.location = loc
  return f

def new_node(nt, bl_idname, label=None, name=None, loc=(0, 0), parent=None):
  n = nt.nodes.new(bl_idname)
  if label: n.label = label
  if name: n.name = name
  n.location = loc
  if parent: n.parent = parent
  return n

def place(n, x, y, parent=None, label=None):
  n.location = (x, y)
  if parent: n.parent = parent
  if label: n.label = label
  return n

def link(links, a_out, b_in):
  links.new(a_out, b_in)
  return b_in

def color_for_layer(idx: int):
  # pleasant distinct-ish colors for frames
  palette = [
    (0.18, 0.20, 0.32),
    (0.22, 0.32, 0.18),
    (0.32, 0.18, 0.20),
    (0.28, 0.24, 0.14),
  ]
  return palette[idx % len(palette)]

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

  BSDF_X, BSDF_Y = (1200, 150)
  LAYER_X_START = -1400
  LAYER_X_STEP = 540
  COL_BASE = 0         # y row for base color chain
  COL_ALPHA = -200
  COL_MR = -420        # metallic/roughness
  COL_NORMAL = -640
  COL_EMISSIVE = -860
  COL_COAT = -1080

  bsdf.location = (BSDF_X, 100)

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
  top_frame = new_frame(nt, f'{mat_name} (PBR v1.5)', color=(0.12, 0.12, 0.12), loc=(LAYER_X_START-80, COL_BASE+200))

  for idx, layer in enumerate(stages_iter):
    layer_x = LAYER_X_START + idx * LAYER_X_STEP
    fcol = color_for_layer(idx)
    frame = new_frame(nt, f'Layer {idx+1}', color=fcol, loc=(layer_x-40, COL_BASE+140))
    summary = new_node(nt, 'NodeReroute', label='Layer Outputs', loc=(layer_x+300, COL_BASE+60), parent=frame)
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

    bc_factor = rgb_node(nt, (baseColorFactor[0], baseColorFactor[1], baseColorFactor[2], baseColorFactor[3]), f'BaseFactor L{idx}')
    place(bc_factor, layer_x, COL_BASE, frame, label='Base Color Factor')
    this_color = bc_factor.outputs['Color']

    if bc_path:
      bc_img = connect_img(nt, bc_path, level_dir, 'sRGB', bc_uv2, uv2_name, uv1_name, label=f'BaseColor L{idx}')
      place(bc_img, layer_x-220, COL_BASE, frame)
      mul = new_node(nt, 'ShaderNodeMixRGB', label='Base * Tex', loc=(layer_x+180, COL_BASE), parent=frame)
      mul.blend_type = 'MULTIPLY'; mul.inputs['Fac'].default_value=1.0
      link(links, bc_factor.outputs['Color'], mul.inputs['Color1'])
      link(links, bc_img.outputs['Color'], mul.inputs['Color2'])
      this_color = mul.outputs['Color']

    if useVertColor:
      vcol = new_node(nt, 'ShaderNodeAttribute', label='Vertex Color', loc=(layer_x-220, COL_BASE-60), parent=frame)
      vcol.attribute_name = 'Col'
      mul2 = new_node(nt, 'ShaderNodeMixRGB', label='Base * VCol', loc=(layer_x+380, COL_BASE-60), parent=frame)
      mul2.blend_type='MULTIPLY'; mul2.inputs['Fac'].default_value=1.0
      link(links, this_color, mul2.inputs['Color1'])
      link(links, vcol.outputs['Color'], mul2.inputs['Color2'])
      this_color = mul2.outputs['Color']

    if ao_path:
      ao_img = connect_img(nt, ao_path, level_dir, 'Non-Color', ao_uv2, uv2_name, uv1_name, label=f'AO L{idx}')
      place(ao_img, layer_x-220, COL_BASE-120, frame)
      ao_mul = new_node(nt, 'ShaderNodeMixRGB', label='Base * AO', loc=(layer_x+580, COL_BASE-120), parent=frame)
      ao_mul.blend_type='MULTIPLY'; ao_mul.inputs['Fac'].default_value=1.0
      link(links, this_color, ao_mul.inputs['Color1'])
      link(links, ao_img.outputs['Color'], ao_mul.inputs['Color2'])
      this_color = ao_mul.outputs['Color']

    if det_col_path and abs(detailBaseFac) > 1e-6:
      det_img = connect_img(nt, det_col_path, level_dir, 'sRGB', det_col_uv2, uv2_name, uv1_name, label=f'DetailCol L{idx}', scale=detScale)
      place(det_img, layer_x-220, COL_BASE-180, frame)
      vm_mul2 = new_node(nt, 'ShaderNodeVectorMath', label='(Detail*2)', loc=(layer_x, COL_BASE-180), parent=frame)
      vm_mul2.operation='MULTIPLY'
      link(links, det_img.outputs['Color'], vm_mul2.inputs[0])
      c2 = new_node(nt, 'ShaderNodeCombineXYZ', label='Vec(2,2,2)', loc=(layer_x-60, COL_BASE-240), parent=frame)
      c2.inputs[0].default_value=2.0; c2.inputs[1].default_value=2.0; c2.inputs[2].default_value=2.0
      link(links, c2.outputs[0], vm_mul2.inputs[1])
      vm_addn1 = new_node(nt, 'ShaderNodeVectorMath', label='(x-1)', loc=(layer_x+180, COL_BASE-180), parent=frame)
      vm_addn1.operation='ADD'
      link(links, vm_mul2.outputs[0], vm_addn1.inputs[0])
      cn1 = new_node(nt, 'ShaderNodeCombineXYZ', label='Vec(-1,-1,-1)', loc=(layer_x+120, COL_BASE-240), parent=frame)
      cn1.inputs[0].default_value=-1.0; cn1.inputs[1].default_value=-1.0; cn1.inputs[2].default_value=-1.0
      link(links, cn1.outputs[0], vm_addn1.inputs[1])
      det_fac_vec = new_node(nt, 'ShaderNodeCombineXYZ', label=f'DetailFactor {detailBaseFac:.2f}', loc=(layer_x+360, COL_BASE-240), parent=frame)
      det_fac_vec.inputs[0].default_value = detailBaseFac
      det_fac_vec.inputs[1].default_value = detailBaseFac
      det_fac_vec.inputs[2].default_value = detailBaseFac
      vm_detscale = new_node(nt, 'ShaderNodeVectorMath', label='Scaled Detail', loc=(layer_x+420, COL_BASE-180), parent=frame)
      vm_detscale.operation='MULTIPLY'
      link(links, vm_addn1.outputs[0], vm_detscale.inputs[0])
      link(links, det_fac_vec.outputs[0], vm_detscale.inputs[1])
      add_det = new_node(nt, 'ShaderNodeMixRGB', label='Add Detail', loc=(layer_x+640, COL_BASE-180), parent=frame)
      add_det.blend_type='ADD'; add_det.use_clamp=True
      link(links, this_color, add_det.inputs['Color1'])
      link(links, vm_detscale.outputs[0], add_det.inputs['Color2'])
      this_color = add_det.outputs['Color']

    layer_opacity_val = value_node(nt, opacityFactor, f'Opacity L{idx}')
    place(layer_opacity_val, layer_x, COL_ALPHA, frame, label=f'Opacity Factor {opacityFactor:.2f}')
    if op_path:
      op_img = connect_img(nt, op_path, level_dir, 'Non-Color', op_uv2, uv2_name, uv1_name, label=f'Opacity L{idx}')
      place(op_img, layer_x-220, COL_ALPHA, frame)
      sep, rname = make_separate_r(nt); place(sep, layer_x, COL_ALPHA-60, frame, label='Opacity R')
      link(links, op_img.outputs['Color'], sep.inputs[0])
      op_mul = new_node(nt, 'ShaderNodeMath', label='Opacity * TexR', loc=(layer_x+180, COL_ALPHA-30), parent=frame)
      op_mul.operation='MULTIPLY'
      link(links, layer_opacity_val.outputs[0], op_mul.inputs[0])
      link(links, sep.outputs[rname], op_mul.inputs[1])
      layer_opacity_val = op_mul
    cl = clamp_01(nt, links, layer_opacity_val.outputs[0])
    place(cl, layer_x+380, COL_ALPHA-30, frame, label='Opacity Clamp')
    layer_alpha = cl.outputs['Result']

    if base_col_chain is None:
      base_col_chain = this_color
    else:
      mix_layer = new_node(nt, 'ShaderNodeMixRGB', label='Layer Mix (alpha)', loc=(layer_x+860, COL_BASE-60), parent=frame)
      mix_layer.blend_type='MIX'
      link(links, layer_alpha, mix_layer.inputs['Fac'])
      link(links, base_col_chain, mix_layer.inputs['Color1'])
      link(links, this_color, mix_layer.inputs['Color2'])
      base_col_chain = mix_layer.outputs['Color']

    one_minus = new_node(nt, 'ShaderNodeMath', label='(1 - alpha)', loc=(layer_x+580, COL_ALPHA-30), parent=frame)
    one_minus.operation='SUBTRACT'
    one_minus.inputs[0].default_value = 1.0
    link(links, layer_alpha, one_minus.inputs[1])
    mul_prev = new_node(nt, 'ShaderNodeMath', label='prev*(1-a)', loc=(layer_x+760, COL_ALPHA-30), parent=frame)
    mul_prev.operation='MULTIPLY'
    link(links, alpha_prev, mul_prev.inputs[0])
    link(links, one_minus.outputs['Value'], mul_prev.inputs[1])
    add_alpha = new_node(nt, 'ShaderNodeMath', label='accum + a', loc=(layer_x+940, COL_ALPHA-30), parent=frame)
    add_alpha.operation='ADD'
    link(links, mul_prev.outputs['Value'], add_alpha.inputs[0])
    link(links, layer_alpha, add_alpha.inputs[1])
    alpha_prev = add_alpha.outputs['Value']

    if met_path:
      met_img = connect_img(nt, met_path, level_dir, 'Non-Color', met_uv2, uv2_name, uv1_name, label=f'Metallic L{idx}')
      place(met_img, layer_x-220, COL_MR, frame)
      sep, rname = make_separate_r(nt); place(sep, layer_x, COL_MR, frame, label='Metallic R')
      link(links, met_img.outputs['Color'], sep.inputs[0])
      met_val = sep.outputs[rname]
      if abs(metallicFactor - 0.0) > 1e-6:
        mfac = value_node(nt, metallicFactor, f'MetallicFac L{idx}')
        place(mfac, layer_x+180, COL_MR, frame, label=f'Metallic Fac {metallicFactor:.2f}')
        mmul = new_node(nt, 'ShaderNodeMath', label='Metallic * Fac', loc=(layer_x+360, COL_MR), parent=frame)
        mmul.operation = 'MULTIPLY'
        link(links, met_val, mmul.inputs[0])
        link(links, mfac.outputs[0], mmul.inputs[1])
        met_val = mmul.outputs['Value']
      metallic_stack = met_val
    else:
      if abs(metallicFactor - 0.0) > 1e-6:
        mnode = value_node(nt, metallicFactor, f'MetallicFac L{idx}')
        place(mnode, layer_x, COL_MR, frame, label=f'Metallic {metallicFactor:.2f}')
        metallic_stack = mnode.outputs[0]
    if rou_path:
      rou_img = connect_img(nt, rou_path, level_dir, 'Non-Color', rou_uv2, uv2_name, uv1_name, label=f'Roughness L{idx}')
      place(rou_img, layer_x-220, COL_MR-80, frame)
      sep, rname = make_separate_r(nt); place(sep, layer_x, COL_MR-80, frame, label='Roughness R')
      link(links, rou_img.outputs['Color'], sep.inputs[0])
      rou_val = sep.outputs[rname]
      if abs(roughnessFactor - 1.0) > 1e-6:
        facn = value_node(nt, roughnessFactor, f'RoughnessFac L{idx}')
        place(facn, layer_x+180, COL_MR-80, frame, label=f'Roughness Fac {roughnessFactor:.2f}')
        rou_mul = new_node(nt, 'ShaderNodeMath', label='Rough * Fac', loc=(layer_x+360, COL_MR-80), parent=frame)
        rou_mul.operation='MULTIPLY'
        link(links, rou_val, rou_mul.inputs[0])
        link(links, facn.outputs[0], rou_mul.inputs[1])
        rou_val = rou_mul.outputs['Value']
      roughness_stack = rou_val
    else:
      if abs(roughnessFactor - 1.0) > 1e-6:
        rnode = value_node(nt, roughnessFactor, f'RoughnessFac L{idx}')
        place(rnode, layer_x, COL_MR-80, frame, label=f'Roughness {roughnessFactor:.2f}')
        roughness_stack = rnode.outputs[0]

    base_normal = None
    if nor_path:
      nor_img = connect_img(nt, nor_path, level_dir, 'Non-Color', nor_uv2, uv2_name, uv1_name, label=f'Normal L{idx}')
      place(nor_img, layer_x-220, COL_NORMAL, frame)
      nrm_base = new_node(nt, 'ShaderNodeNormalMap', label=f'Normal Base (str {normalStrength:.2f})', loc=(layer_x, COL_NORMAL), parent=frame)
      nrm_base.inputs['Strength'].default_value = float(normalStrength)
      link(links, nor_img.outputs['Color'], nrm_base.inputs['Color'])
      base_normal = nrm_base.outputs['Normal']

    if det_nrm_path and abs(detailNormFac) > 1e-6:
      det_img = connect_img(nt, det_nrm_path, level_dir, 'Non-Color', det_nrm_uv2, uv2_name, uv1_name, label=f'DetailNorm L{idx}', scale=detScale)
      place(det_img, layer_x-220, COL_NORMAL-100, frame)
      nrm_det = new_node(nt, 'ShaderNodeNormalMap', label=f'Detail Normal (str {detailNormFac:.2f})', loc=(layer_x, COL_NORMAL-100), parent=frame)
      nrm_det.inputs['Strength'].default_value = float(detailNormFac)
      link(links, det_img.outputs['Color'], nrm_det.inputs['Color'])
      det_minus_001 = new_node(nt, 'ShaderNodeVectorMath', label='Detail + (0,0,-1)', loc=(layer_x+180, COL_NORMAL-100), parent=frame)
      det_minus_001.operation='ADD'
      cn1 = new_node(nt, 'ShaderNodeCombineXYZ', label='Vec(0,0,-1)', loc=(layer_x+120, COL_NORMAL-160), parent=frame)
      cn1.inputs[2].default_value=-1.0
      link(links, nrm_det.outputs['Normal'], det_minus_001.inputs[0])
      link(links, cn1.outputs[0], det_minus_001.inputs[1])
      if base_normal is None:
        base_normal = det_minus_001.outputs[0]
      else:
        nrm_add = new_node(nt, 'ShaderNodeVectorMath', label='Base + Detail', loc=(layer_x+360, COL_NORMAL-100), parent=frame)
        nrm_add.operation='ADD'
        link(links, base_normal, nrm_add.inputs[0])
        link(links, det_minus_001.outputs[0], nrm_add.inputs[1])
        nrm_norm = new_node(nt, 'ShaderNodeVectorMath', label='Normalize', loc=(layer_x+540, COL_NORMAL-100), parent=frame)
        nrm_norm.operation='NORMALIZE'
        link(links, nrm_add.outputs[0], nrm_norm.inputs[0])
        base_normal = nrm_norm.outputs[0]

    if base_normal is not None:
      normal_out = base_normal

    if emi_path or (emissiveFactor and any(abs(c) > 1e-6 for c in emissiveFactor)):
      emi_col = rgb_node(nt, (emissiveFactor[0], emissiveFactor[1], emissiveFactor[2], 1.0))
      place(emi_col, layer_x, COL_EMISSIVE, frame, label='Emissive Factor')
      emi_socket = emi_col.outputs['Color']
      if emi_path:
        emi_img = connect_img(nt, emi_path, level_dir, 'sRGB', emi_uv2, uv2_name, uv1_name, label=f'Emissive L{idx}')
        place(emi_img, layer_x-220, COL_EMISSIVE, frame)
        emi_mul = new_node(nt, 'ShaderNodeMixRGB', label='Emit * Tex', loc=(layer_x+180, COL_EMISSIVE), parent=frame)
        emi_mul.blend_type='MULTIPLY'; emi_mul.inputs['Fac'].default_value=1.0
        link(links, emi_socket, emi_mul.inputs['Color1'])
        link(links, emi_img.outputs['Color'], emi_mul.inputs['Color2'])
        emi_socket = emi_mul.outputs['Color']
      emissive_stack = emi_socket

    if cc_path or abs(clearCoatFactor) > 1e-6:
      cc_val_node = value_node(nt, clearCoatFactor, f'ClearCoatFac L{idx}')
      place(cc_val_node, layer_x, COL_COAT, frame, label=f'Coat Factor {clearCoatFactor:.2f}')
      cc_val = cc_val_node.outputs[0]
      if cc_path:
        cc_img = connect_img(nt, cc_path, level_dir, 'Non-Color', cc_uv2, uv2_name, uv1_name, label=f'ClearCoat L{idx}')
        place(cc_img, layer_x-220, COL_COAT, frame)
        sep, rname = make_separate_r(nt); place(sep, layer_x+160, COL_COAT, frame, label='Coat R')
        link(links, cc_img.outputs['Color'], sep.inputs[0])
        cc_mul = new_node(nt, 'ShaderNodeMath', label='Coat * TexR', loc=(layer_x+340, COL_COAT), parent=frame)
        cc_mul.operation='MULTIPLY'
        link(links, cc_val, cc_mul.inputs[0])
        link(links, sep.outputs[rname], cc_mul.inputs[1])
        coat_stack = cc_mul.outputs['Value']
      else:
        coat_stack = cc_val

    if ccr_path or abs(clearCoatRoughnessFactor) > 1e-6:
      ccr_val_node = value_node(nt, clearCoatRoughnessFactor, f'ClearCoatRoughFac L{idx}')
      place(ccr_val_node, layer_x, COL_COAT-100, frame, label=f'Coat Rough {clearCoatRoughnessFactor:.2f}')
      ccr_val = ccr_val_node.outputs[0]
      if ccr_path:
        ccr_img = connect_img(nt, ccr_path, level_dir, 'Non-Color', ccr_uv2, uv2_name, uv1_name, label=f'ClearCoatRou L{idx}')
        place(ccr_img, layer_x-220, COL_COAT-100, frame)
        sep, rname = make_separate_r(nt); place(sep, layer_x+160, COL_COAT-100, frame, label='CoatRough R')
        link(links, ccr_img.outputs['Color'], sep.inputs[0])
        ccr_mul = new_node(nt, 'ShaderNodeMath', label='CoatRough * TexR', loc=(layer_x+340, COL_COAT-100), parent=frame)
        ccr_mul.operation='MULTIPLY'
        link(links, ccr_val, ccr_mul.inputs[0])
        link(links, sep.outputs[rname], ccr_mul.inputs[1])
        coat_rough_stack = ccr_mul.outputs['Value']
      else:
        coat_rough_stack = ccr_val

    if isinstance(summary, bpy.types.Node):
      try:
        pass
      except Exception:
        pass

  if base_col_chain is not None:
    link(links, base_col_chain, bsdf.inputs['Base Color'])
  if metallic_stack is not None:
    link(links, metallic_stack, bsdf.inputs['Metallic'])
  if roughness_stack is not None:
    link(links, roughness_stack, bsdf.inputs['Roughness'])
    try:
      diff_rough_in = get_bsdf_input(bsdf, ['Diffuse Roughness'])
      link(links, roughness_stack, diff_rough_in)
    except KeyError:
      pass
  if normal_out is not None:
    link(links, normal_out, bsdf.inputs['Normal'])
  if emissive_stack is not None:
    try:
      emission_input = get_bsdf_input(bsdf, ['Emission Color', 'Emission'])
      link(links, emissive_stack, emission_input)
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
      link(links, coat_stack, cc_in)
    except KeyError:
      pass
  if coat_rough_stack is not None:
    try:
      ccr_in = get_bsdf_input(bsdf, ['Coat Roughness', 'Clearcoat Roughness'])
      link(links, coat_rough_stack, ccr_in)
    except KeyError:
      pass

  link(links, alpha_prev, bsdf.inputs['Alpha'])
  alphaTest = try_get(matdef, 'alphaTest', None)
  alphaRef = try_get(matdef, 'alphaRef', None)
  is_translucent = bool(try_get(matdef, 'translucent', False))
  translucent_zwrite = bool(try_get(matdef, 'translucentZWrite', False))

  if alphaTest and isinstance(alphaRef, int):
    set_material_blend_shadow(mat, blend_mode='CLIP', alpha_threshold=(alphaRef/255.0))
  elif is_translucent or translucent_zwrite:
    set_material_blend_shadow(mat, blend_mode='BLEND')
    try:
      mat.shadow_method = 'NONE'  # Disable shadow casting for translucent
    except Exception:
      pass
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
