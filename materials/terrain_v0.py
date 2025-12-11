# ##### BEGIN LICENSE BLOCK #####
#
# This program is licensed under The MIT License:
# see LICENSE for the full license text
#
# ##### END LICENSE BLOCK #####

import bpy
from pathlib import Path
from .common import (
  sample_tiled_img, value_node, saturate_socket
)

def _get(v,k,d=None): return v.get(k,d) if isinstance(v,dict) else d
def _getf(v,k,d=None):
  try: return float(v.get(k)) if (isinstance(v,dict) and v.get(k) is not None) else d
  except: return d

def build_terrain_material_v0(level_dir: Path, v: dict, out_list: list[str], terrain_world_size: float | None = None):
  name = f"{_get(v,'internalName','Terrain')}-{_get(v,'persistentId','')}"
  mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
  mat.use_nodes = True
  nt = mat.node_tree
  for n in list(nt.nodes): nt.nodes.remove(n)
  out = nt.nodes.new('ShaderNodeOutputMaterial'); out.location=(1100,0)
  bsdf = nt.nodes.new('ShaderNodeBsdfPrincipled'); bsdf.location=(800,0)
  nt.links.new(bsdf.outputs[0], out.inputs[0])
  out_list.append(name)

  try: bsdf.inputs['Base Color'].default_value = (0.5, 0.5, 0.5, 1.0)
  except KeyError: pass

  cam = nt.nodes.new('ShaderNodeCameraData')
  pixel_dist = cam.outputs.get('View Z Depth') or (cam.outputs[1] if len(cam.outputs) > 1 else cam.outputs[0])

  diff   = _get(v,'diffuseMap'); diffSize = _getf(v,'diffuseSize', 1.0)
  det    = _get(v,'detailMap');  detSize  = _getf(v,'detailSize', 2.0)
  mac    = _get(v,'macroMap');   macSize  = _getf(v,'macroSize', 60.0)
  macStr = _getf(v,'macroStrength', 0.5)
  macDist= _getf(v,'macroDistance', 500.0)
  nrm    = _get(v,'normalMap')

  world_w = float(terrain_world_size) if (terrain_world_size and terrain_world_size > 0) else 1.0
  uv_name = 'UV_TERRAIN01'

  def _fade_by_distance(maxDist):
    inv = nt.nodes.new('ShaderNodeMath'); inv.operation='DIVIDE'
    nt.links.new(pixel_dist, inv.inputs[0]); inv.inputs[1].default_value = max(1e-6, float(maxDist))
    sub = nt.nodes.new('ShaderNodeMath'); sub.operation='SUBTRACT'; sub.inputs[0].default_value=1.0
    nt.links.new(inv.outputs[0], sub.inputs[1])
    return saturate_socket(nt, sub.outputs[0])

  def _to_srgb(sock):
    g = nt.nodes.new('ShaderNodeGamma'); g.inputs[1].default_value = 1.0/2.2
    nt.links.new(sock, g.inputs[0]); return g.outputs[0]

  def _to_linear(sock):
    g = nt.nodes.new('ShaderNodeGamma'); g.inputs[1].default_value = 2.2
    nt.links.new(sock, g.inputs[0]); return g.outputs[0]

  def _softlight_gamma(base_lin, over_lin, fac_scalar):
    base_srgb = _to_srgb(base_lin); over_srgb = _to_srgb(over_lin)
    mix = nt.nodes.new('ShaderNodeMixRGB'); mix.blend_type='SOFT_LIGHT'; mix.use_clamp=True
    nt.links.new(fac_scalar, mix.inputs[0]); nt.links.new(base_srgb, mix.inputs[1]); nt.links.new(over_srgb, mix.inputs[2])
    return _to_linear(mix.outputs[0])

  def _sample_per_meter(path, tex_size, label, colorspace='sRGB'):
    if not path: return None
    size_eff = (float(tex_size)/world_w) if world_w > 0 else float(tex_size)
    img,_ = sample_tiled_img(nt, path, level_dir, size_meters=size_eff, colorspace=colorspace, invert_y=True, uv_name=uv_name, label=label)
    return img

  col = None
  if det:
    dimg = _sample_per_meter(det, detSize, 'Detail (Base)', 'sRGB')
    col = dimg.outputs[0] if dimg else None
  elif diff:
    dimg,_ = sample_tiled_img(nt, diff, level_dir, size_meters=1.0, colorspace='sRGB', invert_y=True, uv_name=uv_name, label='Diffuse (Base)')
    col = dimg.outputs[0] if dimg else None
  else:
    rgb = nt.nodes.new('ShaderNodeRGB'); rgb.outputs[0].default_value = (0.5,0.5,0.5,1.0)
    col = rgb.outputs[0]

  if det and diff and col:
    dimg2,_ = sample_tiled_img(nt, diff, level_dir, size_meters=1.0, colorspace='sRGB', invert_y=True, uv_name=uv_name, label='Diffuse (SoftLight)')
    fac0 = value_node(nt, 1)
    col = _softlight_gamma(col, dimg2.outputs[0], fac0.outputs[0])

  if mac and col:
    mimg = _sample_per_meter(mac, macSize, 'Macro', 'sRGB')
    if mimg:
      fade_c = _fade_by_distance(macDist)
      facMul = nt.nodes.new('ShaderNodeMath'); facMul.operation='MULTIPLY'
      mfac = value_node(nt, macStr)
      nt.links.new(fade_c, facMul.inputs[0]); nt.links.new(mfac.outputs[0], facMul.inputs[1])
      safety = value_node(nt, 0.8)
      facSafe = nt.nodes.new('ShaderNodeMath'); facSafe.operation='MULTIPLY'
      nt.links.new(facMul.outputs[0], facSafe.inputs[0]); nt.links.new(safety.outputs[0], facSafe.inputs[1])
      col = _softlight_gamma(col, mimg.outputs[0], facSafe.outputs[0])

  if col:
    try: nt.links.new(col, bsdf.inputs['Base Color'])
    except KeyError: pass

  if nrm:
    nimg = _sample_per_meter(nrm, detSize if det else 2.0, 'Normal', 'Non-Color')
    if nimg:
      nmap = nt.nodes.new('ShaderNodeNormalMap'); nmap.inputs['Strength'].default_value = 1.0
      nt.links.new(nimg.outputs[0], nmap.inputs['Color'])
      nt.links.new(nmap.outputs['Normal'], bsdf.inputs['Normal'])

  try: bsdf.inputs['Roughness'].default_value = 1.0
  except KeyError: pass

  return mat
