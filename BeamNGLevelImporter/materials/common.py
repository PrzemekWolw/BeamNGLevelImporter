# ##### BEGIN LICENSE BLOCK #####
#
# This program is licensed under The MIT License:
# see LICENSE for the full license text
#
# ##### END LICENSE BLOCK #####

import bpy
from pathlib import Path
from ..core.paths import try_resolve_image_path, resolve_texture_relative

def try_get(d, k, default=None):
  return d[k] if (isinstance(d, dict) and k in d) else default

def ensure_principled(mat):
  mat.use_nodes = True
  nt = mat.node_tree
  for n in list(nt.nodes):
    nt.nodes.remove(n)
  out = nt.nodes.new('ShaderNodeOutputMaterial'); out.location=(600,0)
  bsdf = nt.nodes.new('ShaderNodeBsdfPrincipled'); bsdf.location=(300,0)
  nt.links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])
  return nt, bsdf, out

def get_bsdf_input(bsdf, names):
  for n in names:
    if n in bsdf.inputs:
      return bsdf.inputs[n]
  raise KeyError(f"None of the inputs {names} exist on Principled BSDF")

def find_uv_name_for_material(mat, index=0):
  return "UVMap" if index == 0 else "UVMap2"

def img_for_relpath(relpath: str, level_dir: Path | None, mat_dir: Path | None = None):
  rel = resolve_texture_relative(relpath, mat_dir=mat_dir, level_dir=level_dir)
  p = try_resolve_image_path(rel, level_dir)
  if not p:
    return None
  try:
    return bpy.data.images.load(str(p), check_existing=True)
  except Exception:
    return None

def img_node(nt, relpath, level_dir, colorspace='sRGB', label='', mat_dir: Path | None = None):
  n = nt.nodes.new('ShaderNodeTexImage')
  n.label = label
  n.name = label if label else n.name
  n.interpolation = 'Smart'
  img = img_for_relpath(relpath, level_dir, mat_dir=mat_dir)
  if img:
    n.image = img
    try:
      n.image.colorspace_settings.name = 'sRGB' if colorspace == 'sRGB' else 'Non-Color'
      n.image.alpha_mode = 'STRAIGHT'
    except Exception:
      pass
  return n

def uv_node(nt, uv_name=None):
  uvn = nt.nodes.new('ShaderNodeUVMap')
  if uv_name: uvn.uv_map = uv_name
  return uvn

def value_node(nt, val=1.0, label=''):
  n = nt.nodes.new('ShaderNodeValue')
  n.outputs[0].default_value = float(val)
  if label: n.label = label
  return n

def rgb_node(nt, col=(1,1,1,1), label=''):
  n = nt.nodes.new('ShaderNodeRGB')
  n.outputs[0].default_value = col
  if label: n.label = label
  return n

def make_separate_r(nt):
  try:
    node = nt.nodes.new('ShaderNodeSeparateColor')
    node.mode = 'RGB'
    return node, 'Red'
  except RuntimeError:
    node = nt.nodes.new('ShaderNodeSeparateRGB')
    return node, 'R'

def clamp_01(nt, links, val_socket):
  cl = nt.nodes.new('ShaderNodeClamp')
  cl.inputs['Min'].default_value = 0.0
  cl.inputs['Max'].default_value = 1.0
  cl.clamp_type = 'MINMAX'
  links.new(val_socket, cl.inputs['Value'])
  return cl

def connect_img(nt, rel, level_dir, colorspace, use_uv2, uv2_name, uv1_name, label='', scale=None, mat_dir: Path | None = None):
  if not rel: return None
  img = img_node(nt, rel, level_dir, colorspace=colorspace, label=label, mat_dir=mat_dir)
  vector_in = img.inputs['Vector']
  need_mapping = isinstance(scale, (list, tuple)) and len(scale) >= 2 and (abs(scale[0]-1.0)>1e-6 or abs(scale[1]-1.0)>1e-6)
  if use_uv2 and uv2_name:
    if need_mapping:
      mapn = nt.nodes.new('ShaderNodeMapping'); mapn.vector_type='POINT'
      mapn.inputs['Scale'].default_value[0] = float(scale[0])
      mapn.inputs['Scale'].default_value[1] = float(scale[1])
      mapn.inputs['Scale'].default_value[2] = 1.0
      uvn = uv_node(nt, uv2_name)
      nt.links.new(uvn.outputs['UV'], mapn.inputs['Vector'])
      nt.links.new(mapn.outputs['Vector'], vector_in)
    else:
      uvn = uv_node(nt, uv2_name)
      nt.links.new(uvn.outputs['UV'], vector_in)
  else:
    if need_mapping:
      mapn = nt.nodes.new('ShaderNodeMapping'); mapn.vector_type='POINT'
      mapn.inputs['Scale'].default_value[0] = float(scale[0])
      mapn.inputs['Scale'].default_value[1] = float(scale[1])
      mapn.inputs['Scale'].default_value[2] = 1.0

      uvn = uv_node(nt, uv1_name) if uv1_name else nt.nodes.new('ShaderNodeTexCoord')
      uv_out = uvn.outputs['UV'] if 'UV' in uvn.outputs else uvn.outputs['UV']
      nt.links.new(uv_out, mapn.inputs['Vector'])
      nt.links.new(mapn.outputs['Vector'], vector_in)
    else:
      if uv1_name:
        uvn = uv_node(nt, uv1_name)
        nt.links.new(uvn.outputs['UV'], vector_in)
      else:
        texcoord = nt.nodes.new('ShaderNodeTexCoord')
        nt.links.new(texcoord.outputs['UV'], vector_in)
  return img

def set_material_blend_shadow(mat, *, blend_mode=None, alpha_threshold=None, shadow='AUTO'):
  if blend_mode:
    mat.blend_method = blend_mode
  shadow_prop = 'shadow_method' if hasattr(mat, 'shadow_method') else ('shadow_mode' if hasattr(mat, 'shadow_mode') else None)
  if shadow_prop:
    if shadow == 'AUTO':
      if blend_mode == 'CLIP':
        setattr(mat, shadow_prop, 'CLIP')
      elif blend_mode == 'BLEND':
        setattr(mat, shadow_prop, 'HASHED')
      else:
        setattr(mat, shadow_prop, 'OPAQUE')
    else:
      setattr(mat, shadow_prop, shadow)
  if alpha_threshold is not None and hasattr(mat, 'alpha_threshold'):
    mat.alpha_threshold = float(alpha_threshold)

def get_scalar(layer, new_key, old_key=None, default=1.0):
  v = layer.get(new_key, None)
  if v is None and old_key:
    v = layer.get(old_key, None)
  try:
    return float(v)
  except (TypeError, ValueError):
    return float(default)

def get_map(layer, keys):
  for k in keys:
    v = try_get(layer, k, None)
    if v:
      return v
  return None

def use_uv2(layer, keys):
  for k in keys:
    v = try_get(layer, k, None)
    if v is not None:
      try:
        return int(v) == 1
      except:
        return bool(v)
  return False

def math_bin(nt, op, a, b):
  """Create a Math node with operation `op` and link inputs a, b. Returns output socket."""
  m = nt.nodes.new('ShaderNodeMath'); m.operation = op
  nt.links.new(a, m.inputs[0]); nt.links.new(b, m.inputs[1])
  return m.outputs['Value']

def saturate_socket(nt, sock):
  """Clamp a float socket to [0,1]. Returns clamped output socket."""
  c = nt.nodes.new('ShaderNodeClamp'); c.clamp_type = 'MINMAX'
  c.inputs['Min'].default_value = 0.0
  c.inputs['Max'].default_value = 1.0
  nt.links.new(sock, c.inputs['Value'])
  return c.outputs['Result']

def mix_val_scalar(nt, a, b, t):
  """Return a*(1-t) + b*t for scalar sockets."""
  one = value_node(nt, 1.0)
  omt = math_bin(nt, 'SUBTRACT', one.outputs[0], t)
  at = math_bin(nt, 'MULTIPLY', a, omt)
  bt = math_bin(nt, 'MULTIPLY', b, t)
  return math_bin(nt, 'ADD', at, bt)

def rgb_to_bw_socket(nt, col):
  """Convert color socket to grayscale (R,G,B -> Y)."""
  n = nt.nodes.new('ShaderNodeRGBToBW')
  nt.links.new(col, n.inputs['Color'])
  return n.outputs['Val']

def sample_tiled_img(nt, relpath, level_dir, size_meters=1.0, colorspace='sRGB', invert_y=True, uv_name='UVMap', label='', mat_dir: Path | None = None):
  """
  Create UVMap + Mapping with tiling = 1/size_meters (Y flipped if invert_y), then an Image node.
  Returns (img_node, mapping_node). If relpath is falsy, returns (None, None).
  """
  if not relpath:
    return None, None
  uv = nt.nodes.new('ShaderNodeUVMap'); uv.uv_map = uv_name
  mapn = nt.nodes.new('ShaderNodeMapping'); mapn.vector_type='POINT'
  tiling = 1.0 / float(size_meters) if size_meters and float(size_meters) > 0 else 1.0
  mapn.inputs['Scale'].default_value[0] = tiling
  mapn.inputs['Scale'].default_value[1] = -tiling if invert_y else tiling
  mapn.inputs['Scale'].default_value[2] = 1.0
  nt.links.new(uv.outputs['UV'], mapn.inputs['Vector'])
  img = img_node(nt, relpath, level_dir, colorspace=colorspace, label=label, mat_dir=mat_dir)
  nt.links.new(mapn.outputs['Vector'], img.inputs['Vector'])
  return img, mapn

def ensure_uv_layers_named(me, uv0="UVMap", uv1="UVMap2"):
  if not me or not hasattr(me, "uv_layers"):
    return
  uvs = me.uv_layers

  if len(uvs) < 1:
    uvs.new(name=uv0)
  uvs[0].name = uv0

  if len(uvs) < 2:
    uvs.new(name=uv1)
  uvs[1].name = uv1