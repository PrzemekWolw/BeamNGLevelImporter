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
  img_node, value_node, math_bin, saturate_socket,
  mix_val_scalar, rgb_to_bw_socket, sample_tiled_img, get_bsdf_input
)

def new_frame(nt, label, color=(0.18, 0.18, 0.18), loc=(0, 0)):
  f = nt.nodes.new('NodeFrame')
  f.label = label
  f.use_custom_color = True
  f.color = color
  f.location = loc
  return f

def place(n, x, y, parent=None, label=None):
  if n is None:
    return None
  n.location = (x, y)
  if parent:
    n.parent = parent
  if label is not None:
    n.label = label
  return n

def link(links, a_out, b_in):
  links.new(a_out, b_in)
  return b_in


def _get(v, k, d=None): return v.get(k, d) if isinstance(v, dict) else d
def _getf(v, k, d=None):
  try:
    val = _get(v, k, None)
    return float(val) if val is not None else d
  except Exception:
    return d
def _getv2(v, k, d=(1.0,1.0)):
  vv = _get(v, k, None)
  return (float(vv[0]), float(vv[1])) if isinstance(vv,(list,tuple)) and len(vv)>=2 else d
def _getv4(v, k, d=(0,0,0,0)):
  vv = _get(v, k, None)
  return tuple(float(x) for x in vv[:4]) if isinstance(vv,(list,tuple)) and len(vv)>=4 else d

def _vec_math(nt, op):
  n = nt.nodes.new('ShaderNodeVectorMath')
  n.operation = op
  return n

def _new_separate_rgb(nt):
  """Blender 5.0+: Separate Color; older: Separate RGB."""
  try:
    n = nt.nodes.new("ShaderNodeSeparateColor")
    n.mode = 'RGB'
    return n, ("Red", "Green", "Blue")
  except RuntimeError:
    n = nt.nodes.new("ShaderNodeSeparateRGB")
    return n, ("R", "G", "B")

def _new_combine_rgb(nt):
  """Blender 5.0+: Combine Color; older: Combine RGB."""
  try:
    n = nt.nodes.new("ShaderNodeCombineColor")
    n.mode = 'RGB'
    return n, ("Red", "Green", "Blue")
  except RuntimeError:
    n = nt.nodes.new("ShaderNodeCombineRGB")
    return n, ("R", "G", "B")

def _build_distance_factors(nt, pixel_dist, d0,d1,d2,d3):
  d0n = value_node(nt, d0); d1n = value_node(nt, d1); d2n = value_node(nt, d2); d3n = value_node(nt, d3)
  def satdiv(a, b):
    div = nt.nodes.new('ShaderNodeMath'); div.operation='DIVIDE'; div.label = 'SatDiv'
    link(nt.links, math_bin(nt,'SUBTRACT', pixel_dist, a.outputs[0]), div.inputs[0])
    link(nt.links, math_bin(nt,'SUBTRACT', b.outputs[0], a.outputs[0]), div.inputs[1])
    return saturate_socket(nt, div.outputs[0])
  nearF = satdiv(d0n, d1n); nearF.node.label = 'Near Factor'
  midF  = satdiv(d1n, d2n); midF.node.label = 'Mid Factor'
  farF  = satdiv(d2n, d3n); farF.node.label = 'Far Factor'
  return nearF, midF, farF

def _calc_strength(nt, nearF, midF, farF, atten_xy, strength_xy):
  a0,a1 = atten_xy; s0,s1 = strength_xy
  a0n = value_node(nt,a0); a1n = value_node(nt,a1); s0n = value_node(nt,s0); s1n = value_node(nt,s1)
  left  = mix_val_scalar(nt, math_bin(nt,'MULTIPLY', a0n.outputs[0], s0n.outputs[0]), s0n.outputs[0], nearF)
  right = mix_val_scalar(nt, s1n.outputs[0], math_bin(nt,'MULTIPLY', a1n.outputs[0], s1n.outputs[0]), farF)
  out = mix_val_scalar(nt, left, right, midF)
  try: out.node.label = 'Strength'
  except Exception: pass
  return out

def _gate_factor(nt, fac, pixel_dist, cutoff):
  lt = nt.nodes.new('ShaderNodeMath'); lt.operation='LESS_THAN'; lt.label = f'dist < {cutoff:.1f}'
  link(nt.links, pixel_dist, lt.inputs[0]); lt.inputs[1].default_value = float(cutoff)
  mul = nt.nodes.new('ShaderNodeMath'); mul.operation='MULTIPLY'; mul.label = 'Gated'
  link(nt.links, fac, mul.inputs[0]); link(nt.links, lt.outputs[0], mul.inputs[1])
  return mul.outputs[0]

def _center_vec(nt, col_socket):
  mul2 = _vec_math(nt, 'MULTIPLY'); mul2.label = 'x * 2'
  c2 = nt.nodes.new('ShaderNodeCombineXYZ'); c2.inputs[0].default_value = 2.0; c2.inputs[1].default_value = 2.0; c2.inputs[2].default_value = 2.0
  link(nt.links, col_socket, mul2.inputs[0]); link(nt.links, c2.outputs[0], mul2.inputs[1])
  sub1 = _vec_math(nt, 'SUBTRACT'); sub1.label = 'x - 1'
  one = nt.nodes.new('ShaderNodeCombineXYZ'); one.inputs[0].default_value = 1.0; one.inputs[1].default_value = 1.0; one.inputs[2].default_value = 1.0
  link(nt.links, mul2.outputs[0], sub1.inputs[0]); link(nt.links, one.outputs[0], sub1.inputs[1])
  return sub1.outputs[0]

def _sample_per_meter(nt, level_dir, path, tex_size_m, world_w, label, colorspace='sRGB', mat_dir: Path | None = None):
  if not path: return None
  size_eff = (float(tex_size_m)/float(world_w)) if (world_w and world_w > 0) else float(tex_size_m)
  img,_ = sample_tiled_img(nt, path, level_dir, size_meters=size_eff, colorspace=colorspace, invert_y=False, uv_name='UV_TERRAIN01', label=label, mat_dir=mat_dir)
  return img

def build_terrain_material_v15(level_dir: Path, v: dict, out_list: list[str], terrain_world_size: float | None = None, mat_dir: Path | None = None):
  name = f"{_get(v,'internalName','Terrain')}-{_get(v,'persistentId','')}"
  mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
  mat.use_nodes = True
  nt = mat.node_tree
  for n in list(nt.nodes): nt.nodes.remove(n)
  links = nt.links

  X_OUT = 1100
  X_BSDF = 800
  X_DIST = -1400
  X_COLOR = -950
  X_ROUGH = -420
  X_AO = -150
  X_NRM = 150
  ROW0 = 0

  out = nt.nodes.new('ShaderNodeOutputMaterial'); place(out, X_OUT, ROW0)
  bsdf = nt.nodes.new('ShaderNodeBsdfPrincipled'); place(bsdf, X_BSDF, ROW0, label='Principled BSDF')
  link(links, bsdf.outputs[0], out.inputs[0])
  out_list.append(name)

  try:
    get_bsdf_input(bsdf, ['Specular', 'Specular IOR Level']).default_value = 0.5
  except KeyError:
    pass

  frame_top   = new_frame(nt, f'{name} (Terrain v1.5)', color=(0.12,0.12,0.12), loc=(X_DIST-80, ROW0+250))
  frame_dist  = new_frame(nt, 'Distance & Strength', color=(0.16,0.16,0.24), loc=(X_DIST-40, ROW0+140))
  frame_color = new_frame(nt, 'Base Color Stack', color=(0.20,0.16,0.16), loc=(X_COLOR-40, ROW0+140))
  frame_rough = new_frame(nt, 'Roughness Stack', color=(0.16,0.20,0.16), loc=(X_ROUGH-40, ROW0+140))
  frame_ao    = new_frame(nt, 'AO Stack', color=(0.16,0.16,0.16), loc=(X_AO-40, ROW0+140))
  frame_nrm   = new_frame(nt, 'Normal Stack', color=(0.16,0.18,0.22), loc=(X_NRM-40, ROW0+140))

  cam = nt.nodes.new('ShaderNodeCameraData')
  place(cam, X_DIST, ROW0, frame_dist, label='Camera Data')
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

  # Distance factors and strength curves
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
    bimg,_ = sample_tiled_img(nt, col_base, level_dir, size_meters=1.0, colorspace='sRGB', invert_y=False, uv_name='UV_TERRAIN01', label='BaseColor Base', mat_dir=mat_dir)
    if bimg: place(bimg, X_COLOR-240, ROW0, frame_color, label='BaseColor Base')
    base_col = bimg.outputs[0] if bimg else None

  if col_macro and base_col:
    mimg = _sample_per_meter(nt, level_dir, col_macro, bmac_size, world_w, 'BaseColor Macro', 'Non-Color', mat_dir=mat_dir)
    if mimg:
      place(mimg, X_COLOR-240, ROW0-100, frame_color, label='BaseColor Macro')
      centered = _center_vec(nt, mimg.outputs[0]); centered.node.label = 'Center Macro'
      fac3 = nt.nodes.new('ShaderNodeCombineXYZ'); place(fac3, X_COLOR-120, ROW0-160, frame_color, 'Macro Fac -> Vec3')
      link(links, macF_col, fac3.inputs[0]); link(links, macF_col, fac3.inputs[1]); link(links, macF_col, fac3.inputs[2])
      scale = _vec_math(nt,'MULTIPLY'); place(scale, X_COLOR+80, ROW0-100, frame_color, 'Macro * Fac3')
      link(links, centered, scale.inputs[0]); link(links, fac3.outputs[0], scale.inputs[1])
      addn = nt.nodes.new('ShaderNodeMixRGB'); addn.blend_type='ADD'; addn.use_clamp=True
      place(addn, X_COLOR+280, ROW0-100, frame_color, 'Base + Macro')
      link(links, base_col, addn.inputs[1]); link(links, scale.outputs[0], addn.inputs[2])
      base_col = addn.outputs[0]

  if col_detail and base_col:
    dimg = _sample_per_meter(nt, level_dir, col_detail, bdet_size, world_w, 'BaseColor Detail', 'Non-Color', mat_dir=mat_dir)
    if dimg:
      place(dimg, X_COLOR-240, ROW0-220, frame_color, label='BaseColor Detail')
      centered = _center_vec(nt, dimg.outputs[0]); centered.node.label = 'Center Detail'
      fac3 = nt.nodes.new('ShaderNodeCombineXYZ'); place(fac3, X_COLOR-120, ROW0-280, frame_color, 'Detail Fac -> Vec3')
      link(links, detF_col, fac3.inputs[0]); link(links, detF_col, fac3.inputs[1]); link(links, detF_col, fac3.inputs[2])
      scale = _vec_math(nt,'MULTIPLY'); place(scale, X_COLOR+80, ROW0-220, frame_color, 'Detail * Fac3')
      link(links, centered, scale.inputs[0]); link(links, fac3.outputs[0], scale.inputs[1])
      addn = nt.nodes.new('ShaderNodeMixRGB'); addn.blend_type='ADD'; addn.use_clamp=True
      place(addn, X_COLOR+280, ROW0-220, frame_color, 'Base + Detail')
      link(links, base_col, addn.inputs[1]); link(links, scale.outputs[0], addn.inputs[2])
      base_col = addn.outputs[0]

  if base_col:
    link(links, base_col, bsdf.inputs['Base Color'])

  # Roughness stack
  if rgh_base:
    rb,_ = sample_tiled_img(nt, rgh_base, level_dir, size_meters=1.0, colorspace='Non-Color', invert_y=False, uv_name='UV_TERRAIN01', label='Rgh Base', mat_dir=mat_dir)
    if rb: place(rb, X_ROUGH-240, ROW0, frame_rough, label='Roughness Base')
    if rb:
      rough = rgb_to_bw_socket(nt, rb.outputs[0]); rough.node.label = 'Rgh BW'

      def add_r(path, size, fac, base_r, label):
        if not path or not base_r: return base_r
        img = _sample_per_meter(nt, level_dir, path, size, world_w, label, 'Non-Color', mat_dir=mat_dir)
        if not img: return base_r
        place(img, X_ROUGH-240, ROW0 - (100 if 'Macro' in label else 200), frame_rough, label=label)
        bw = rgb_to_bw_socket(nt, img.outputs[0]); bw.node.label = f'{label} BW'
        mul2 = nt.nodes.new('ShaderNodeMath'); mul2.operation='MULTIPLY'; mul2.label = 'x * 2'
        link(links, bw, mul2.inputs[0]); mul2.inputs[1].default_value = 2.0
        sub = nt.nodes.new('ShaderNodeMath'); sub.operation='SUBTRACT'; sub.label = 'x - 1'
        link(links, mul2.outputs[0], sub.inputs[0]); sub.inputs[1].default_value = 1.0
        scaled = nt.nodes.new('ShaderNodeMath'); scaled.operation='MULTIPLY'; scaled.label = '*(fac)'
        link(links, sub.outputs[0], scaled.inputs[0]); link(links, fac, scaled.inputs[1])
        addn = nt.nodes.new('ShaderNodeMath'); addn.operation='ADD'; addn.label = 'Add'
        link(links, base_r, addn.inputs[0]); link(links, scaled.outputs[0], addn.inputs[1])
        return saturate_socket(nt, addn.outputs[0])

      rough = add_r(rgh_macro, rmac_size, macF_rgh, rough, 'Rgh Macro')
      rough = add_r(rgh_detail, rdet_size, detF_rgh, rough, 'Rgh Detail')
      link(links, rough, bsdf.inputs['Roughness'])

  # AO base + macro/detail (Non-Color; not wired to Principled AO by default)
  if ao_base:
    ab,_ = sample_tiled_img(nt, ao_base, level_dir, size_meters=1.0, colorspace='Non-Color', invert_y=False, uv_name='UV_TERRAIN01', label='AO Base', mat_dir=mat_dir)
    if ab: place(ab, X_AO-240, ROW0, frame_ao, label='AO Base')
    if ab:
      ao_val = rgb_to_bw_socket(nt, ab.outputs[0]); ao_val.node.label = 'AO BW'

      def add_ao(path, size, fac, base_ao, label):
        if not path or not base_ao: return base_ao
        img = _sample_per_meter(nt, level_dir, path, size, world_w, label, 'Non-Color', mat_dir=mat_dir)
        if not img: return base_ao
        place(img, X_AO-240, ROW0 - (100 if 'Macro' in label else 200), frame_ao, label=label)
        bw = rgb_to_bw_socket(nt, img.outputs[0]); bw.node.label = f'{label} BW'
        mul2 = nt.nodes.new('ShaderNodeMath'); mul2.operation='MULTIPLY'; mul2.label = 'x * 2'
        link(links, bw, mul2.inputs[0]); mul2.inputs[1].default_value = 2.0
        sub = nt.nodes.new('ShaderNodeMath'); sub.operation='SUBTRACT'; sub.label = 'x - 1'
        link(links, mul2.outputs[0], sub.inputs[0]); sub.inputs[1].default_value = 1.0
        scaled = nt.nodes.new('ShaderNodeMath'); scaled.operation='MULTIPLY'; scaled.label = '*(fac)'
        link(links, sub.outputs[0], scaled.inputs[0]); link(links, fac, scaled.inputs[1])
        addn = nt.nodes.new('ShaderNodeMath'); addn.operation='ADD'; addn.label = 'Add'
        link(links, base_ao, addn.inputs[0]); link(links, scaled.outputs[0], addn.inputs[1])
        return saturate_socket(nt, addn.outputs[0])

      ao_val = add_ao(ao_macro, amac_size, macF_ao, ao_val, 'AO Macro')
      ao_val = add_ao(ao_detail, adet_size, detF_ao, ao_val, 'AO Detail')

  n_out = None
  if nrm_base:
    nb,_ = sample_tiled_img(nt, nrm_base, level_dir, size_meters=1.0, colorspace='Non-Color', invert_y=False, uv_name='UV_TERRAIN01', label='Normal Base', mat_dir=mat_dir)
    if nb: place(nb, X_NRM-240, ROW0, frame_nrm, label='Normal Base')
    if nb:
      nmap = nt.nodes.new('ShaderNodeNormalMap'); nmap.inputs['Strength'].default_value = 1.0
      place(nmap, X_NRM-40, ROW0, frame_nrm, label='Normal Base Map')
      link(links, nb.outputs[0], nmap.inputs['Color'])
      n_out = nmap.outputs[0]

  def nmap_from(path, size, label):
    img = _sample_per_meter(nt, level_dir, path, size, world_w, label, 'Non-Color', mat_dir=mat_dir)
    if not img: return None, None
    place(img, X_NRM-240, ROW0 - (100 if 'Macro' in label else 200), frame_nrm, label=label)
    nm = nt.nodes.new('ShaderNodeNormalMap'); nm.inputs['Strength'].default_value = 1.0
    place(nm, X_NRM-40, (ROW0 - (100 if 'Macro' in label else 200)), frame_nrm, label=f'{label} Map')
    link(links, img.outputs[0], nm.inputs['Color'])
    return img, nm.outputs[0]

  def _lerp_norm(nt_local, a_vec, b_vec, t_fac):
    # MixRGB expects color sockets, so convert Vector -> Color -> Vector
    mix = nt_local.nodes.new('ShaderNodeMixRGB'); mix.blend_type='MIX'
    place(mix, X_NRM+160, ROW0-300, frame_nrm, label='Lerp Normals')
    link(links, t_fac, mix.inputs[0])

    sep1 = nt_local.nodes.new('ShaderNodeSeparateXYZ'); place(sep1, X_NRM+80, ROW0-220, frame_nrm, 'Sep A')
    sep2 = nt_local.nodes.new('ShaderNodeSeparateXYZ'); place(sep2, X_NRM+80, ROW0-380, frame_nrm, 'Sep B')
    link(links, a_vec, sep1.inputs[0]); link(links, b_vec, sep2.inputs[0])

    comb1, (r1, g1, b1) = _new_combine_rgb(nt_local)
    place(comb1, X_NRM+120, ROW0-220, frame_nrm, 'Comb A')
    comb2, (r2, g2, b2) = _new_combine_rgb(nt_local)
    place(comb2, X_NRM+120, ROW0-380, frame_nrm, 'Comb B')

    link(links, sep1.outputs[0], comb1.inputs[r1])
    link(links, sep1.outputs[1], comb1.inputs[g1])
    link(links, sep1.outputs[2], comb1.inputs[b1])

    link(links, sep2.outputs[0], comb2.inputs[r2])
    link(links, sep2.outputs[1], comb2.inputs[g2])
    link(links, sep2.outputs[2], comb2.inputs[b2])

    link(links, comb1.outputs[0], mix.inputs[1])
    link(links, comb2.outputs[0], mix.inputs[2])

    sep3, (sr, sg, sb) = _new_separate_rgb(nt_local)
    place(sep3, X_NRM+320, ROW0-300, frame_nrm, 'Sep Mixed')
    link(links, mix.outputs[0], sep3.inputs[0])

    combN = nt_local.nodes.new('ShaderNodeCombineXYZ'); place(combN, X_NRM+480, ROW0-300, frame_nrm, 'To XYZ')
    link(links, sep3.outputs[sr], combN.inputs[0])
    link(links, sep3.outputs[sg], combN.inputs[1])
    link(links, sep3.outputs[sb], combN.inputs[2])

    norm = nt_local.nodes.new('ShaderNodeVectorMath'); norm.operation='NORMALIZE'
    place(norm, X_NRM+640, ROW0-300, frame_nrm, 'Normalize')
    link(links, combN.outputs[0], norm.inputs[0])
    return norm.outputs[0]

  if n_out and nrm_macro:
    _, nn = nmap_from(nrm_macro, nmac_size, 'Normal Macro')
    if nn:
      n_out = _lerp_norm(nt, n_out, nn, macF_nrm)

  if n_out and nrm_detail:
    _, nn = nmap_from(nrm_detail, ndet_size, 'Normal Detail')
    if nn:
      n_out = _lerp_norm(nt, n_out, nn, detF_nrm)

  if n_out:
    link(links, n_out, bsdf.inputs['Normal'])

  return mat
