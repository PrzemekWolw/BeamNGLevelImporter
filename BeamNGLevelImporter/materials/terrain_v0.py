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
  sample_tiled_img, value_node, saturate_socket
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

def _get(v,k,d=None): return v.get(k,d) if isinstance(v,dict) else d
def _getf(v,k,d=None):
  try: return float(v.get(k)) if (isinstance(v,dict) and v.get(k) is not None) else d
  except: return d

def build_terrain_material_v0(level_dir: Path, v: dict, out_list: list[str], terrain_world_size: float | None = None, mat_dir: Path | None = None):
  name = f"{_get(v,'internalName','Terrain')}-{_get(v,'persistentId','')}"
  mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
  mat.use_nodes = True
  nt = mat.node_tree
  links = nt.links
  for n in list(nt.nodes): nt.nodes.remove(n)

  X_OUT, X_BSDF = 1100, 800
  X_DIST = -900
  X_COLOR = -500
  X_NORMAL = 50
  ROW0 = 0

  out = nt.nodes.new('ShaderNodeOutputMaterial'); place(out, X_OUT, ROW0)
  bsdf = nt.nodes.new('ShaderNodeBsdfPrincipled'); place(bsdf, X_BSDF, ROW0, label='Principled BSDF')
  link(links, bsdf.outputs[0], out.inputs[0])
  out_list.append(name)

  try: bsdf.inputs['Base Color'].default_value = (0.5, 0.5, 0.5, 1.0)
  except KeyError: pass
  try: bsdf.inputs['Roughness'].default_value = 1.0
  except KeyError: pass

  frame_top   = new_frame(nt, f'{name} (Terrain v0)', color=(0.12,0.12,0.12), loc=(X_DIST-80, ROW0+250))
  frame_dist  = new_frame(nt, 'Distance Fade', color=(0.16,0.16,0.24), loc=(X_DIST-40, ROW0+140))
  frame_color = new_frame(nt, 'Base Color Stack', color=(0.20,0.16,0.16), loc=(X_COLOR-40, ROW0+140))
  frame_nrm   = new_frame(nt, 'Normal', color=(0.16,0.18,0.22), loc=(X_NORMAL-40, ROW0+140))

  cam = nt.nodes.new('ShaderNodeCameraData')
  place(cam, X_DIST, ROW0, frame_dist, label='Camera Data')
  pixel_dist = cam.outputs.get('View Z Depth') or (cam.outputs[1] if len(cam.outputs) > 1 else cam.outputs[0])

  diff   = _get(v,'diffuseMap'); diffSize = _getf(v,'diffuseSize', 1.0)
  det    = _get(v,'detailMap');  detSize  = _getf(v,'detailSize', 2.0)
  mac    = _get(v,'macroMap');   macSize  = _getf(v,'macroSize', 60.0)
  macStr = _getf(v,'macroStrength', 0.5)
  macDist= _getf(v,'macroDistance', 500.0)
  nrm    = _get(v,'normalMap')

  world_w = float(terrain_world_size) if (terrain_world_size and terrain_world_size > 0) else 1.0
  uv_name = 'UV_TERRAIN01'

  def _to_srgb(sock, x, y, parent):
    g = nt.nodes.new('ShaderNodeGamma'); g.inputs[1].default_value = 1.0/2.2
    place(g, x, y, parent, 'to sRGB (γ=1/2.2)')
    link(links, sock, g.inputs[0]); return g.outputs[0]

  def _to_linear(sock, x, y, parent):
    g = nt.nodes.new('ShaderNodeGamma'); g.inputs[1].default_value = 2.2
    place(g, x, y, parent, 'to Linear (γ=2.2)')
    link(links, sock, g.inputs[0]); return g.outputs[0]

  def _softlight_gamma(base_lin, over_lin, fac_scalar, x, y, parent):
    base_srgb = _to_srgb(base_lin, x, y, parent)
    over_srgb = _to_srgb(over_lin, x, y-80, parent)
    mix = nt.nodes.new('ShaderNodeMixRGB'); mix.blend_type='SOFT_LIGHT'; mix.use_clamp=True
    place(mix, x+220, y-40, parent, 'Soft Light (sRGB)')
    link(links, fac_scalar, mix.inputs[0])
    link(links, base_srgb, mix.inputs[1])
    link(links, over_srgb, mix.inputs[2])
    return _to_linear(mix.outputs[0], x+420, y-40, parent)

  def _sample_per_meter(path, tex_size, label, colorspace='sRGB', x=X_COLOR-240, y=ROW0, parent=frame_color, mat_dir: Path | None = None):
    if not path: return None
    size_eff = (float(tex_size)/world_w) if world_w > 0 else float(tex_size)
    img,_ = sample_tiled_img(nt, path, level_dir, size_meters=size_eff, colorspace=colorspace, invert_y=True, uv_name=uv_name, label=label, mat_dir=mat_dir)
    if img: place(img, x, y, parent, label)
    return img

  fade_c = None
  if mac and macDist and macDist > 0:
    inv = nt.nodes.new('ShaderNodeMath'); inv.operation='DIVIDE'
    place(inv, X_DIST+220, ROW0, frame_dist, label='dist / maxDist')
    link(links, pixel_dist, inv.inputs[0]); inv.inputs[1].default_value = max(1e-6, float(macDist))

    sub = nt.nodes.new('ShaderNodeMath'); sub.operation='SUBTRACT'
    place(sub, X_DIST+420, ROW0, frame_dist, label='1 - x')
    sub.inputs[0].default_value = 1.0
    link(links, inv.outputs[0], sub.inputs[1])

    fade_c = saturate_socket(nt, sub.outputs[0])
    try:
      fade_c.node.label = 'Saturate [0,1]'
      fade_c.node.parent = frame_dist
      fade_c.node.location = (X_DIST+620, ROW0)
    except Exception:
      pass

  col = None
  if det:
    dimg = _sample_per_meter(det, detSize, 'Detail (Base)', 'sRGB', x=X_COLOR-240, y=ROW0, parent=frame_color, mat_dir=mat_dir)
    col = dimg.outputs[0] if dimg else None
  elif diff:
    dimg,_ = sample_tiled_img(nt, diff, level_dir, size_meters=1.0, colorspace='sRGB', invert_y=True, uv_name=uv_name, label='Diffuse (Base)', mat_dir=mat_dir)
    if dimg: place(dimg, X_COLOR-240, ROW0, frame_color, 'Diffuse (Base)')
    col = dimg.outputs[0] if dimg else None
  else:
    rgb = nt.nodes.new('ShaderNodeRGB'); rgb.outputs[0].default_value = (0.5,0.5,0.5,1.0)
    place(rgb, X_COLOR-240, ROW0, frame_color, 'Fallback Color')
    col = rgb.outputs[0]

  if det and diff and col:
    dimg2,_ = sample_tiled_img(nt, diff, level_dir, size_meters=1.0, colorspace='sRGB', invert_y=True, uv_name=uv_name, label='Diffuse (SoftLight)', mat_dir=mat_dir)
    if dimg2: place(dimg2, X_COLOR-240, ROW0-120, frame_color, 'Diffuse (SoftLight)')
    fac0 = value_node(nt, 1.0); place(fac0, X_COLOR-20, ROW0-120, frame_color, 'Fac 1.0')
    col = _softlight_gamma(col, dimg2.outputs[0], fac0.outputs[0], X_COLOR+80, ROW0-120, frame_color)

  if mac and col:
    mimg = _sample_per_meter(mac, macSize, 'Macro', 'sRGB', x=X_COLOR-240, y=ROW0-260, parent=frame_color, mat_dir=mat_dir)
    if mimg:
      mfac = value_node(nt, macStr); place(mfac, X_COLOR-20, ROW0-300, frame_color, f'Macro Strength {macStr:.2f}')
      facMul = nt.nodes.new('ShaderNodeMath'); facMul.operation='MULTIPLY'
      place(facMul, X_COLOR+140, ROW0-300, frame_color, 'fade * strength')
      if fade_c:
        link(links, fade_c, facMul.inputs[0])
      else:
        fac1 = value_node(nt, 1.0); place(fac1, X_COLOR+40, ROW0-300, frame_color, 'No fade (1)')
        link(links, fac1.outputs[0], facMul.inputs[0])
      link(links, mfac.outputs[0], facMul.inputs[1])
      safety = value_node(nt, 0.8); place(safety, X_COLOR+280, ROW0-300, frame_color, 'Safety 0.8')
      facSafe = nt.nodes.new('ShaderNodeMath'); facSafe.operation='MULTIPLY'
      place(facSafe, X_COLOR+420, ROW0-300, frame_color, '*(safety)')
      link(links, facMul.outputs[0], facSafe.inputs[0]); link(links, safety.outputs[0], facSafe.inputs[1])
      col = _softlight_gamma(col, mimg.outputs[0], facSafe.outputs[0], X_COLOR+80, ROW0-260, frame_color)

  if col:
    try: link(links, col, bsdf.inputs['Base Color'])
    except KeyError: pass

  if nrm:
    nimg = _sample_per_meter(nrm, detSize if det else 2.0, 'Normal', 'Non-Color', x=X_NORMAL-240, y=ROW0, parent=frame_nrm, mat_dir=mat_dir)
    if nimg:
      nmap = nt.nodes.new('ShaderNodeNormalMap'); nmap.inputs['Strength'].default_value = 1.0
      place(nmap, X_NORMAL-20, ROW0, frame_nrm, 'Normal Map')
      link(links, nimg.outputs[0], nmap.inputs['Color'])
      link(links, nmap.outputs['Normal'], bsdf.inputs['Normal'])

  return mat
