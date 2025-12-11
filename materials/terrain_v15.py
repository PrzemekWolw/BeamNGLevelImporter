# ##### BEGIN LICENSE BLOCK #####
#
# This program is licensed under The MIT License:
# see LICENSE for the full license text
#
# ##### END LICENSE BLOCK #####

import bpy
from pathlib import Path
from .common import (
  img_node, value_node, math_bin, saturate_socket,
  mix_val_scalar, rgb_to_bw_socket, sample_tiled_img, get_bsdf_input
)

def _get(v, k, d=None): return v.get(k, d) if isinstance(v, dict) else d
def _getf(v, k, d=None):
  try:
    val = _get(v,k,None)
    return float(val) if val is not None else d
  except Exception:
    return d
def _getv2(v, k, d=(1.0,1.0)):
  vv = _get(v,k,None)
  return (float(vv[0]), float(vv[1])) if isinstance(vv,(list,tuple)) and len(vv)>=2 else d
def _getv4(v, k, d=(0,0,0,0)):
  vv = _get(v,k,None)
  return tuple(float(x) for x in vv[:4]) if isinstance(vv,(list,tuple)) and len(vv)>=4 else d

def _vec_math(nt, op):
  n = nt.nodes.new('ShaderNodeVectorMath'); n.operation=op; return n

def _build_distance_factors(nt, pixel_dist, d0,d1,d2,d3):
  d0n=value_node(nt,d0); d1n=value_node(nt,d1); d2n=value_node(nt,d2); d3n=value_node(nt,d3)
  def satdiv(a,b):
    div = nt.nodes.new('ShaderNodeMath'); div.operation='DIVIDE'
    nt.links.new(math_bin(nt,'SUBTRACT',pixel_dist, a.outputs[0]), div.inputs[0])
    nt.links.new(math_bin(nt,'SUBTRACT',b.outputs[0], a.outputs[0]), div.inputs[1])
    return saturate_socket(nt, div.outputs[0])
  nearF = satdiv(d0n,d1n); midF = satdiv(d1n,d2n); farF = satdiv(d2n,d3n)
  return nearF, midF, farF

def _calc_strength(nt, nearF, midF, farF, atten_xy, strength_xy):
  a0,a1 = atten_xy; s0,s1 = strength_xy
  a0n=value_node(nt,a0); a1n=value_node(nt,a1); s0n=value_node(nt,s0); s1n=value_node(nt,s1)
  left  = mix_val_scalar(nt, math_bin(nt,'MULTIPLY', a0n.outputs[0], s0n.outputs[0]), s0n.outputs[0], nearF)
  right = mix_val_scalar(nt, s1n.outputs[0], math_bin(nt,'MULTIPLY', a1n.outputs[0], s1n.outputs[0]), farF)
  return mix_val_scalar(nt, left, right, midF)

def _gate_factor(nt, fac, pixel_dist, cutoff):
  lt = nt.nodes.new('ShaderNodeMath'); lt.operation='LESS_THAN'
  nt.links.new(pixel_dist, lt.inputs[0]); lt.inputs[1].default_value = float(cutoff)
  mul = nt.nodes.new('ShaderNodeMath'); mul.operation='MULTIPLY'
  nt.links.new(fac, mul.inputs[0]); nt.links.new(lt.outputs[0], mul.inputs[1])
  return mul.outputs[0]

def _center_vec(nt, col_socket):
  mul2 = _vec_math(nt,'MULTIPLY')
  c2 = nt.nodes.new('ShaderNodeCombineXYZ')
  c2.inputs[0].default_value = 2.0; c2.inputs[1].default_value = 2.0; c2.inputs[2].default_value = 2.0
  nt.links.new(col_socket, mul2.inputs[0]); nt.links.new(c2.outputs[0], mul2.inputs[1])
  sub1 = _vec_math(nt,'SUBTRACT')
  one = nt.nodes.new('ShaderNodeCombineXYZ')
  one.inputs[0].default_value = 1.0; one.inputs[1].default_value = 1.0; one.inputs[2].default_value = 1.0
  nt.links.new(mul2.outputs[0], sub1.inputs[0]); nt.links.new(one.outputs[0], sub1.inputs[1])
  return sub1.outputs[0]

def _sample_per_meter(nt, level_dir, path, tex_size_m, world_w, label, colorspace='sRGB'):
  """Single-UV workflow: use UV_TERRAIN01; per-meter tiling via size_eff = tex_size/world_w; invert_y=False."""
  if not path: return None
  size_eff = (float(tex_size_m)/float(world_w)) if (world_w and world_w > 0) else float(tex_size_m)
  img,_ = sample_tiled_img(nt, path, level_dir, size_meters=size_eff, colorspace=colorspace, invert_y=False, uv_name='UV_TERRAIN01', label=label)
  return img

def build_terrain_material_v15(level_dir: Path, v: dict, out_list: list[str], terrain_world_size: float | None = None):
  """v1.5 single-UV (UV_TERRAIN01), shader-faithful macro/detail mixing"""
  name = f"{_get(v,'internalName','Terrain')}-{_get(v,'persistentId','')}"
  mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
  mat.use_nodes = True
  nt = mat.node_tree
  for n in list(nt.nodes): nt.nodes.remove(n)
  out = nt.nodes.new('ShaderNodeOutputMaterial'); out.location=(1100,0)
  bsdf = nt.nodes.new('ShaderNodeBsdfPrincipled'); bsdf.location=(800,0)
  nt.links.new(bsdf.outputs[0], out.inputs[0])
  out_list.append(name)

  try:
    get_bsdf_input(bsdf, ['Specular', 'Specular IOR Level']).default_value = 0.5
  except KeyError:
    pass

  cam = nt.nodes.new('ShaderNodeCameraData')
  pixel_dist = cam.outputs.get('View Z Depth') or (cam.outputs[1] if len(cam.outputs) > 1 else cam.outputs[0])

  # Textures
  col_base   = _get(v,'baseColorBaseTex')
  col_macro  = _get(v,'baseColorMacroTex');  bmac_size = _getf(v,'baseColorMacroTexSize', 60.0)
  col_detail = _get(v,'baseColorDetailTex'); bdet_size = _getf(v,'baseColorDetailTexSize', 2.0)

  nrm_base   = _get(v,'normalBaseTex')
  nrm_macro  = _get(v,'normalMacroTex');     nmac_size = _getf(v,'normalMacroTexSize', 60.0)
  nrm_detail = _get(v,'normalDetailTex');    ndet_size = _getf(v,'normalDetailTexSize', 2.0)

  rgh_base   = _get(v,'roughnessBaseTex')
  rgh_macro  = _get(v,'roughnessMacroTex');  rmac_size = _getf(v,'roughnessMacroTexSize', 60.0)
  rgh_detail = _get(v,'roughnessDetailTex'); rdet_size = _getf(v,'roughnessDetailTexSize', 2.0)

  ao_base    = _get(v,'aoBaseTex')
  ao_macro   = _get(v,'aoMacroTex');         amac_size = _getf(v,'aoMacroTexSize', 60.0)
  ao_detail  = _get(v,'aoDetailTex');        adet_size = _getf(v,'aoDetailTexSize', 2.0)

  hgt_base   = _get(v,'heightBaseTex');      hgt_size  = _getf(v,'heightBaseTexSize', 2.0)

  dmac = _getv4(v,'macroDistances', (0,10,100,1000))
  ddet = _getv4(v,'detailDistances', (0,0,50,100))
  attn_mac = _getv2(v,'macroDistAtten', _getv2(v,'distanceAttenMacro', (0,1)))
  attn_det = _getv2(v,'detailDistAtten', _getv2(v,'distanceAttenDetail', (1,1)))

  col_mac_str = _getv2(v,'baseColorMacroStrength', (0.2,0.3))
  col_det_str = _getv2(v,'baseColorDetailStrength', (0.35,0.35))
  nrm_mac_str = _getv2(v,'normalMacroStrength', (0.2,0.3))
  nrm_det_str = _getv2(v,'normalDetailStrength', (0.7,0.15))
  rgh_mac_str = _getv2(v,'roughnessMacroStrength', (0.15,0.5))
  rgh_det_str = _getv2(v,'roughnessDetailStrength', (0.3,0.3))
  ao_mac_str  = _getv2(v,'aoMacroStrength', (0.0,0.0))
  ao_det_str  = _getv2(v,'aoDetailStrength', (0.0,0.0))

  world_w = float(terrain_world_size) if (terrain_world_size and terrain_world_size > 0) else 1.0

  nearM, midM, farM = _build_distance_factors(nt, pixel_dist, *dmac)
  nearD, midD, farD = _build_distance_factors(nt, pixel_dist, *ddet)

  macF_col = _calc_strength(nt, nearM, midM, farM, attn_mac, col_mac_str)
  detF_col = _calc_strength(nt, nearD, midD, farD, attn_det, col_det_str)
  macF_nrm = _calc_strength(nt, nearM, midM, farM, attn_mac, nrm_mac_str)
  detF_nrm = _calc_strength(nt, nearD, midD, farD, attn_det, nrm_det_str)
  macF_rgh = _calc_strength(nt, nearM, midM, farM, attn_mac, rgh_mac_str)
  detF_rgh = _calc_strength(nt, nearD, midD, farD, attn_det, rgh_det_str)
  macF_ao  = _calc_strength(nt, nearM, midM, farM, attn_mac, ao_mac_str)
  detF_ao  = _calc_strength(nt, nearD, midD, farD, attn_det, ao_det_str)

  mac_cut = min(1000.0, float(dmac[3]))
  det_cut = min(250.0,  float(ddet[3]))
  macF_col = _gate_factor(nt, macF_col, pixel_dist, mac_cut)
  detF_col = _gate_factor(nt, detF_col, pixel_dist, det_cut)
  macF_nrm = _gate_factor(nt, macF_nrm, pixel_dist, mac_cut)
  detF_nrm = _gate_factor(nt, detF_nrm, pixel_dist, det_cut)
  macF_rgh = _gate_factor(nt, macF_rgh, pixel_dist, mac_cut)
  detF_rgh = _gate_factor(nt, detF_rgh, pixel_dist, det_cut)
  macF_ao  = _gate_factor(nt, macF_ao,  pixel_dist, mac_cut)
  detF_ao  = _gate_factor(nt, detF_ao,  pixel_dist, det_cut)

  base_col = None
  if col_base:
    bimg,_ = sample_tiled_img(nt, col_base, level_dir, size_meters=1.0, colorspace='sRGB', invert_y=False, uv_name='UV_TERRAIN01', label='BaseColor Base')
    base_col = bimg.outputs[0] if bimg else None

  if col_macro and base_col:
    mimg = _sample_per_meter(nt, level_dir, col_macro, bmac_size, world_w, 'BaseColor Macro', 'Non-Color')
    if mimg:
      centered = _center_vec(nt, mimg.outputs[0])
      fac3 = nt.nodes.new('ShaderNodeCombineXYZ')
      nt.links.new(macF_col, fac3.inputs[0]); nt.links.new(macF_col, fac3.inputs[1]); nt.links.new(macF_col, fac3.inputs[2])
      scale = _vec_math(nt,'MULTIPLY')
      nt.links.new(centered, scale.inputs[0]); nt.links.new(fac3.outputs[0], scale.inputs[1])
      addn = nt.nodes.new('ShaderNodeMixRGB'); addn.blend_type='ADD'; addn.use_clamp=True
      nt.links.new(base_col, addn.inputs[1]); nt.links.new(scale.outputs[0], addn.inputs[2])
      base_col = addn.outputs[0]

  if col_detail and base_col:
    dimg = _sample_per_meter(nt, level_dir, col_detail, bdet_size, world_w, 'BaseColor Detail', 'Non-Color')
    if dimg:
      centered = _center_vec(nt, dimg.outputs[0])
      fac3 = nt.nodes.new('ShaderNodeCombineXYZ')
      nt.links.new(detF_col, fac3.inputs[0]); nt.links.new(detF_col, fac3.inputs[1]); nt.links.new(detF_col, fac3.inputs[2])
      scale = _vec_math(nt,'MULTIPLY')
      nt.links.new(centered, scale.inputs[0]); nt.links.new(fac3.outputs[0], scale.inputs[1])
      addn = nt.nodes.new('ShaderNodeMixRGB'); addn.blend_type='ADD'; addn.use_clamp=True
      nt.links.new(base_col, addn.inputs[1]); nt.links.new(scale.outputs[0], addn.inputs[2])
      base_col = addn.outputs[0]

  if base_col:
    nt.links.new(base_col, bsdf.inputs['Base Color'])

  if rgh_base:
    rb,_ = sample_tiled_img(nt, rgh_base, level_dir, size_meters=1.0, colorspace='Non-Color', invert_y=False, uv_name='UV_TERRAIN01', label='Rgh Base')
    if rb:
      rough = rgb_to_bw_socket(nt, rb.outputs[0])

      def add_r(path, size, fac, base_r, label):
        if not path or not base_r: return base_r
        img = _sample_per_meter(nt, level_dir, path, size, world_w, label, 'Non-Color')
        if not img: return base_r
        bw = rgb_to_bw_socket(nt, img.outputs[0])
        mul2 = nt.nodes.new('ShaderNodeMath'); mul2.operation='MULTIPLY'
        nt.links.new(bw, mul2.inputs[0]); mul2.inputs[1].default_value = 2.0
        sub = nt.nodes.new('ShaderNodeMath'); sub.operation='SUBTRACT'
        nt.links.new(mul2.outputs[0], sub.inputs[0]); sub.inputs[1].default_value = 1.0
        scaled = nt.nodes.new('ShaderNodeMath'); scaled.operation='MULTIPLY'
        nt.links.new(sub.outputs[0], scaled.inputs[0]); nt.links.new(fac, scaled.inputs[1])
        addn = nt.nodes.new('ShaderNodeMath'); addn.operation='ADD'
        nt.links.new(base_r, addn.inputs[0]); nt.links.new(scaled.outputs[0], addn.inputs[1])
        return saturate_socket(nt, addn.outputs[0])

      rough = add_r(rgh_macro, rmac_size, macF_rgh, rough, 'Rgh Macro')
      rough = add_r(rgh_detail, rdet_size, detF_rgh, rough, 'Rgh Detail')
      nt.links.new(rough, bsdf.inputs['Roughness'])

  # AO base + macro/detail (Non-Color; not wired to Principled AO by default)
  if ao_base:
    ab,_ = sample_tiled_img(nt, ao_base, level_dir, size_meters=1.0, colorspace='Non-Color', invert_y=False, uv_name='UV_TERRAIN01', label='AO Base')
    if ab:
      ao_val = rgb_to_bw_socket(nt, ab.outputs[0])

      def add_ao(path, size, fac, base_ao, label):
        if not path or not base_ao: return base_ao
        img = _sample_per_meter(nt, level_dir, path, size, world_w, label, 'Non-Color')
        if not img: return base_ao
        bw = rgb_to_bw_socket(nt, img.outputs[0])
        mul2 = nt.nodes.new('ShaderNodeMath'); mul2.operation='MULTIPLY'
        nt.links.new(bw, mul2.inputs[0]); mul2.inputs[1].default_value = 2.0
        sub = nt.nodes.new('ShaderNodeMath'); sub.operation='SUBTRACT'
        nt.links.new(mul2.outputs[0], sub.inputs[0]); sub.inputs[1].default_value = 1.0
        scaled = nt.nodes.new('ShaderNodeMath'); scaled.operation='MULTIPLY'
        nt.links.new(sub.outputs[0], scaled.inputs[0]); nt.links.new(fac, scaled.inputs[1])
        addn = nt.nodes.new('ShaderNodeMath'); addn.operation='ADD'
        nt.links.new(base_ao, addn.inputs[0]); nt.links.new(scaled.outputs[0], addn.inputs[1])
        return saturate_socket(nt, addn.outputs[0])

      ao_val = add_ao(ao_macro, amac_size, macF_ao, ao_val, 'AO Macro')
      ao_val = add_ao(ao_detail, adet_size, detF_ao, ao_val, 'AO Detail')

  n_out = None
  if nrm_base:
    nb,_ = sample_tiled_img(nt, nrm_base, level_dir, size_meters=1.0, colorspace='Non-Color', invert_y=False, uv_name='UV_TERRAIN01', label='Normal Base')
    if nb:
      nmap = nt.nodes.new('ShaderNodeNormalMap'); nmap.inputs['Strength'].default_value = 1.0
      nt.links.new(nb.outputs[0], nmap.inputs['Color'])
      n_out = nmap.outputs[0]

  def nmap_from(path, size, label):
    img = _sample_per_meter(nt, level_dir, path, size, world_w, label, 'Non-Color')
    if not img: return None
    nm = nt.nodes.new('ShaderNodeNormalMap'); nm.inputs['Strength'].default_value = 1.0
    nt.links.new(img.outputs[0], nm.inputs['Color'])
    return nm.outputs[0]

  def _lerp_norm(nt, a, b, t):
    mix = nt.nodes.new('ShaderNodeMixRGB'); mix.blend_type='MIX'
    nt.links.new(t, mix.inputs[0])
    sep1 = nt.nodes.new('ShaderNodeSeparateXYZ'); sep2 = nt.nodes.new('ShaderNodeSeparateXYZ')
    nt.links.new(a, sep1.inputs[0]); nt.links.new(b, sep2.inputs[0])
    comb1 = nt.nodes.new('ShaderNodeCombineRGB'); comb2 = nt.nodes.new('ShaderNodeCombineRGB')
    nt.links.new(sep1.outputs[0], comb1.inputs[0]); nt.links.new(sep1.outputs[1], comb1.inputs[1]); nt.links.new(sep1.outputs[2], comb1.inputs[2])
    nt.links.new(sep2.outputs[0], comb2.inputs[0]); nt.links.new(sep2.outputs[1], comb2.inputs[1]); nt.links.new(sep2.outputs[2], comb2.inputs[2])
    nt.links.new(comb1.outputs[0], mix.inputs[1]); nt.links.new(comb2.outputs[0], mix.inputs[2])
    sep3 = nt.nodes.new('ShaderNodeSeparateColor'); nt.links.new(mix.outputs[0], sep3.inputs[0])
    combN = nt.nodes.new('ShaderNodeCombineXYZ')
    nt.links.new(sep3.outputs[0], combN.inputs[0]); nt.links.new(sep3.outputs[1], combN.inputs[1]); nt.links.new(sep3.outputs[2], combN.inputs[2])
    norm = _vec_math(nt,'NORMALIZE'); nt.links.new(combN.outputs[0], norm.inputs[0])
    return norm.outputs[0]

  if n_out and nrm_macro:
    nn = nmap_from(nrm_macro, nmac_size, 'Normal Macro')
    if nn:
      n_out = _lerp_norm(nt, n_out, nn, macF_nrm)

  if n_out and nrm_detail:
    nn = nmap_from(nrm_detail, ndet_size, 'Normal Detail')
    if nn:
      n_out = _lerp_norm(nt, n_out, nn, detF_nrm)

  if n_out:
    nt.links.new(n_out, bsdf.inputs['Normal'])

  return mat
