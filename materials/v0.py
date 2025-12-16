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
  palette = [
    (0.18, 0.20, 0.32),
    (0.22, 0.32, 0.18),
    (0.32, 0.18, 0.20),
    (0.28, 0.24, 0.14),
  ]
  return palette[idx % len(palette)]

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

  BSDF_X, BSDF_Y = (1200, 150)
  LAYER_X_START = -1400
  LAYER_X_STEP = 520

  COL_BASE = 0        # base color / overlays / palette / vcol / detail color
  COL_ALPHA = -240    # opacity
  COL_SPEC = -460     # specular + roughness
  COL_REFL = -540     # reflectivity
  COL_NORMAL = -760   # base normal
  COL_DNORM = -860    # detail normal

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
  roughness_stack = None
  normal_out = None
  top_frame = new_frame(nt, f'{mat_name} (v0)', color=(0.12, 0.12, 0.12), loc=(LAYER_X_START-80, COL_BASE+200))

  for idx, layer in enumerate(stages_iter):
    layer_x = LAYER_X_START + idx * LAYER_X_STEP
    fcol = color_for_layer(idx)
    frame = new_frame(nt, f'Layer {idx+1}', color=fcol, loc=(layer_x-40, COL_BASE+140))
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
    pal_path  = get_map(layer, ['colorPaletteMap'])

    bc_uv2   = use_uv2(layer, ['diffuseMapUseUV'])
    ov_uv2   = use_uv2(layer, ['overlayMapUseUV'])
    det_uv2  = use_uv2(layer, ['detailMapUseUV'])
    nor_uv2  = use_uv2(layer, ['normalMapUseUV'])
    detn_uv2 = use_uv2(layer, ['normalDetailMapUseUV'])
    op_uv2   = use_uv2(layer, ['opacityMapUseUV'])
    sp_uv2   = use_uv2(layer, ['specularMapUseUV'])
    rf_uv2   = use_uv2(layer, ['reflectivityMapUseUV'])
    pal_uv2  = use_uv2(layer, ['colorPaletteMapUseUV'])

    bc_factor = rgb_node(nt, (baseColorFactor[0], baseColorFactor[1], baseColorFactor[2], baseColorFactor[3]), f'BaseFactor L{idx}')
    place(bc_factor, layer_x, COL_BASE, frame, label='Base Color Factor')
    this_color = bc_factor.outputs['Color']

    if bc_path:
      bc_img = connect_img(nt, bc_path, level_dir, 'sRGB', bc_uv2, uv2_name, uv1_name, label=f'Diffuse L{idx}')
      place(bc_img, layer_x-220, COL_BASE, frame)
      mul = new_node(nt, 'ShaderNodeMixRGB', label='Base * Diffuse', loc=(layer_x+180, COL_BASE), parent=frame)
      mul.blend_type='MULTIPLY'; mul.inputs['Fac'].default_value=1.0
      link(links, bc_factor.outputs['Color'], mul.inputs['Color1'])
      link(links, bc_img.outputs['Color'], mul.inputs['Color2'])
      this_color = mul.outputs['Color']

    if pal_path:
      pal_img = connect_img(nt, pal_path, level_dir, 'sRGB', pal_uv2, uv2_name, uv1_name, label=f'Palette L{idx}')
      place(pal_img, layer_x-220, COL_BASE-60, frame)
      pal_mul = new_node(nt, 'ShaderNodeMixRGB', label='Base * Palette', loc=(layer_x+180, COL_BASE-60), parent=frame)
      pal_mul.blend_type='MULTIPLY'; pal_mul.inputs['Fac'].default_value=1.0
      link(links, this_color, pal_mul.inputs['Color1'])
      link(links, pal_img.outputs['Color'], pal_mul.inputs['Color2'])
      this_color = pal_mul.outputs['Color']

    if overlay:
      ov_img = connect_img(nt, overlay, level_dir, 'sRGB', ov_uv2, uv2_name, uv1_name, label=f'Overlay L{idx}')
      place(ov_img, layer_x-220, COL_BASE-120, frame)
      mix = new_node(nt, 'ShaderNodeMixRGB', label='Overlay Mix', loc=(layer_x+180, COL_BASE-120), parent=frame)
      mix.blend_type='MIX'
      sep, rname = make_separate_r(nt); place(sep, layer_x, COL_BASE-180, frame, label='Overlay R')
      link(links, ov_img.outputs['Color'], sep.inputs[0])
      fac_socket = ov_img.outputs.get('Alpha') or sep.outputs[rname]
      link(links, fac_socket, mix.inputs['Fac'])
      link(links, this_color, mix.inputs['Color1'])
      link(links, ov_img.outputs['Color'], mix.inputs['Color2'])
      this_color = mix.outputs['Color']

    if useVertColor:
      vcol = new_node(nt, 'ShaderNodeAttribute', label='Vertex Color', loc=(layer_x-220, COL_BASE-240), parent=frame)
      vcol.attribute_name = 'Col'
      mul2 = new_node(nt, 'ShaderNodeMixRGB', label='Base * VCol', loc=(layer_x+180, COL_BASE-240), parent=frame)
      mul2.blend_type='MULTIPLY'; mul2.inputs['Fac'].default_value=1.0
      link(links, this_color, mul2.inputs['Color1'])
      link(links, vcol.outputs['Color'], mul2.inputs['Color2'])
      this_color = mul2.outputs['Color']

    if detail and abs(detailBaseFac) > 1e-6:
      det_img = connect_img(nt, detail, level_dir, 'sRGB', det_uv2, uv2_name, uv1_name, label=f'DetailCol L{idx}', scale=detScale)
      place(det_img, layer_x-220, COL_BASE-300, frame)
      scale2 = new_node(nt, 'ShaderNodeVectorMath', label='Detail * 2', loc=(layer_x, COL_BASE-300), parent=frame)
      scale2.operation='MULTIPLY'
      c2 = new_node(nt, 'ShaderNodeCombineXYZ', label='Vec(2,2,2)', loc=(layer_x-60, COL_BASE-360), parent=frame)
      c2.inputs[0].default_value=2.0; c2.inputs[1].default_value=2.0; c2.inputs[2].default_value=2.0
      link(links, det_img.outputs['Color'], scale2.inputs[0])
      link(links, c2.outputs[0], scale2.inputs[1])
      sub1 = new_node(nt, 'ShaderNodeVectorMath', label='(x - 1)', loc=(layer_x+180, COL_BASE-300), parent=frame)
      sub1.operation='ADD'
      cn1 = new_node(nt, 'ShaderNodeCombineXYZ', label='Vec(-1,-1,-1)', loc=(layer_x+120, COL_BASE-360), parent=frame)
      cn1.inputs[0].default_value=-1.0; cn1.inputs[1].default_value=-1.0; cn1.inputs[2].default_value=-1.0
      link(links, scale2.outputs[0], sub1.inputs[0])
      link(links, cn1.outputs[0], sub1.inputs[1])
      dvec = new_node(nt, 'ShaderNodeCombineXYZ', label=f'Detail Fac {detailBaseFac:.2f}', loc=(layer_x+360, COL_BASE-360), parent=frame)
      dvec.inputs[0].default_value = detailBaseFac
      dvec.inputs[1].default_value = detailBaseFac
      dvec.inputs[2].default_value = detailBaseFac
      vmul = new_node(nt, 'ShaderNodeVectorMath', label='Scaled Detail', loc=(layer_x+420, COL_BASE-300), parent=frame)
      vmul.operation='MULTIPLY'
      link(links, sub1.outputs[0], vmul.inputs[0])
      link(links, dvec.outputs[0], vmul.inputs[1])
      add_det = new_node(nt, 'ShaderNodeMixRGB', label='Add Detail', loc=(layer_x+640, COL_BASE-300), parent=frame)
      add_det.blend_type='ADD'; add_det.use_clamp=True
      link(links, this_color, add_det.inputs['Color1'])
      link(links, vmul.outputs[0], add_det.inputs['Color2'])
      this_color = add_det.outputs['Color']

    layer_opacity_val = value_node(nt, opacityFactor, f'Opacity L{idx}')
    place(layer_opacity_val, layer_x, COL_ALPHA, frame, label=f'Opacity Fac {opacityFactor:.2f}')
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
    # Multiply layer opacity by diffuse/base color alpha if present
    if bc_path:
      # bc_img exists from the Base Color block above
      bc_alpha = bc_img.outputs.get('Alpha')
      if bc_alpha is not None:
        op_mul_bc = new_node(nt, 'ShaderNodeMath', label='Opacity * DiffuseA', loc=(layer_x+360, COL_ALPHA-30), parent=frame)
        op_mul_bc.operation = 'MULTIPLY'
        link(links, layer_opacity_val.outputs[0], op_mul_bc.inputs[0])
        link(links, bc_alpha, op_mul_bc.inputs[1])
        layer_opacity_val = op_mul_bc
    # Clamp after combining all alpha contributions
    cl = clamp_01(nt, links, layer_opacity_val.outputs[0])
    place(cl, layer_x+560, COL_ALPHA-30, frame, label='Opacity Clamp')  # moved a bit to the right
    place(cl, layer_x+380, COL_ALPHA-30, frame, label='Opacity Clamp')
    layer_alpha = cl.outputs['Result']

    if base_col_chain is None:
      base_col_chain = this_color
    else:
      mix_layer = new_node(nt, 'ShaderNodeMixRGB', label='Layer Mix (alpha)', loc=(layer_x+820, COL_BASE-80), parent=frame)
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

    if spec_path:
      sp_img = connect_img(nt, spec_path, level_dir, 'Non-Color', sp_uv2, uv2_name, uv1_name, label=f'Specular L{idx}')
      place(sp_img, layer_x-220, COL_SPEC, frame)
      sep_sp, rname_sp = make_separate_r(nt); place(sep_sp, layer_x, COL_SPEC, frame, label='Spec R')
      link(links, sp_img.outputs['Color'], sep_sp.inputs[0])
      gloss_socket = sp_img.outputs.get('Alpha')
      inv = new_node(nt, 'ShaderNodeMath', label='1 - gloss', loc=(layer_x+180, COL_SPEC+10), parent=frame)
      inv.operation='SUBTRACT'; inv.inputs[0].default_value=1.0
      link(links, (gloss_socket or sep_sp.outputs[rname_sp]), inv.inputs[1])
      rough_val = inv.outputs['Value']
      if abs(roughnessFactor - 1.0) > 1e-6:
        rf_fac = value_node(nt, roughnessFactor, f'RoughnessFac L{idx}')
        place(rf_fac, layer_x+340, COL_SPEC+10, frame, label=f'Rough Fac {roughnessFactor:.2f}')
        rf_mul = new_node(nt, 'ShaderNodeMath', label='Rough * Fac', loc=(layer_x+520, COL_SPEC+10), parent=frame)
        rf_mul.operation='MULTIPLY'
        link(links, rough_val, rf_mul.inputs[0])
        link(links, rf_fac.outputs[0], rf_mul.inputs[1])
        rough_val = rf_mul.outputs['Value']
      if roughness_stack is None:
        roughness_stack = rough_val

      spec_lum = new_node(nt, 'ShaderNodeRGBToBW', label='Spec Luminance', loc=(layer_x+180, COL_SPEC-60), parent=frame)
      link(links, sp_img.outputs['Color'], spec_lum.inputs['Color'])
      try:
        sp_in = get_bsdf_input(bsdf, ['Specular', 'Specular IOR Level'])
        link(links, spec_lum.outputs['Val'], sp_in)
      except KeyError:
        pass

    if refl_path:
      rf_img = connect_img(nt, refl_path, level_dir, 'Non-Color', rf_uv2, uv2_name, uv1_name, label=f'Reflectivity L{idx}')
      place(rf_img, layer_x-220, COL_REFL, frame)
      rf_bw = new_node(nt, 'ShaderNodeRGBToBW', label='Reflectivity BW', loc=(layer_x+0, COL_REFL), parent=frame)
      rf_bw.parent = frame; rf_bw.location = (layer_x+0, COL_REFL)
      link(links, rf_img.outputs['Color'], rf_bw.inputs['Color'])
      try:
        sp_in = get_bsdf_input(bsdf, ['Specular', 'Specular IOR Level'])
        addn = new_node(nt, 'ShaderNodeMath', label='Spec + Refl', loc=(layer_x+180, COL_REFL), parent=frame)
        addn.operation='ADD'
        addn.inputs[0].default_value = 0.25
        link(links, rf_bw.outputs['Val'], addn.inputs[1])
        link(links, addn.outputs['Value'], sp_in)
      except KeyError:
        pass

    base_normal = None
    if nor_path:
      nor_img = connect_img(nt, nor_path, level_dir, 'Non-Color', nor_uv2, uv2_name, uv1_name, label=f'Normal L{idx}')
      place(nor_img, layer_x-220, COL_NORMAL, frame)
      nrm_base = new_node(nt, 'ShaderNodeNormalMap', label=f'Normal (str {normalStrength:.2f})', loc=(layer_x, COL_NORMAL), parent=frame)
      nrm_base.inputs['Strength'].default_value = float(normalStrength)
      link(links, nor_img.outputs['Color'], nrm_base.inputs['Color'])
      base_normal = nrm_base.outputs['Normal']

    if det_nrm and abs(detailNormFac) > 1e-6:
      det_img = connect_img(nt, det_nrm, level_dir, 'Non-Color', detn_uv2, uv2_name, uv1_name, label=f'DetailNorm L{idx}', scale=detScale)
      place(det_img, layer_x-220, COL_DNORM, frame)
      nrm_det = new_node(nt, 'ShaderNodeNormalMap', label=f'Detail Normal (str {detailNormFac:.2f})', loc=(layer_x, COL_DNORM), parent=frame)
      nrm_det.inputs['Strength'].default_value = float(detailNormFac)
      link(links, det_img.outputs['Color'], nrm_det.inputs['Color'])
      det_minus_001 = new_node(nt, 'ShaderNodeVectorMath', label='Detail + (0,0,-1)', loc=(layer_x+180, COL_DNORM), parent=frame)
      det_minus_001.operation='ADD'
      cn1 = new_node(nt, 'ShaderNodeCombineXYZ', label='Vec(0,0,-1)', loc=(layer_x+120, COL_DNORM-60), parent=frame)
      cn1.inputs[2].default_value=-1.0
      link(links, nrm_det.outputs['Normal'], det_minus_001.inputs[0])
      link(links, cn1.outputs[0], det_minus_001.inputs[1])
      if base_normal is None:
        base_normal = det_minus_001.outputs[0]
      else:
        nrm_add = new_node(nt, 'ShaderNodeVectorMath', label='Base + Detail', loc=(layer_x+360, COL_DNORM), parent=frame)
        nrm_add.operation='ADD'
        link(links, base_normal, nrm_add.inputs[0])
        link(links, det_minus_001.outputs[0], nrm_add.inputs[1])
        nrm_norm = new_node(nt, 'ShaderNodeVectorMath', label='Normalize', loc=(layer_x+540, COL_DNORM), parent=frame)
        nrm_norm.operation='NORMALIZE'
        link(links, nrm_add.outputs[0], nrm_norm.inputs[0])
        base_normal = nrm_norm.outputs[0]

    if base_normal is not None:
      normal_out = base_normal

  if base_col_chain is not None:
    link(links, base_col_chain, bsdf.inputs['Base Color'])
  if roughness_stack is not None:
    link(links, roughness_stack, bsdf.inputs['Roughness'])
  if normal_out is not None:
    link(links, normal_out, bsdf.inputs['Normal'])

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
      mat.shadow_method = 'NONE'
    except Exception:
      pass
  else:
    set_material_blend_shadow(mat, blend_mode='OPAQUE')
  if hasattr(mat, 'use_backface_culling'):
    dbl = try_get(matdef, 'doubleSided', False)
    mat.use_backface_culling = not bool(dbl)

