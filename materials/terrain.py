# ##### BEGIN LICENSE BLOCK #####
#
# This program is licensed under The MIT License:
# see LICENSE for the full license text
#
# ##### END LICENSE BLOCK #####

import bpy
from pathlib import Path
from ..core.paths import try_resolve_image_path

def create_terrain_material(level_dir: Path, v: dict, terrain_mats_list: list[str]):
  termat = f"{v.get('internalName','Terrain')}-{v.get('persistentId','')}"
  mat = bpy.data.materials.get(termat) or bpy.data.materials.new(termat)
  mat.use_nodes = True
  nt = mat.node_tree
  for n in list(nt.nodes):
    nt.nodes.remove(n)
  out = nt.nodes.new('ShaderNodeOutputMaterial')
  bsdf = nt.nodes.new('ShaderNodeBsdfPrincipled')
  nt.links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])
  terrain_mats_list.append(termat)

  def plug(rel, colorspace, connect_fn):
    if not rel:
      return
    p = try_resolve_image_path(rel, level_dir, None)
    if not p:
      return
    img = nt.nodes.new('ShaderNodeTexImage')
    try:
      img.image = bpy.data.images.load(str(p), check_existing=True)
      img.image.colorspace_settings.name = colorspace
    except Exception:
      return
    connect_fn(img)

  plug(v.get('baseColorBaseTex'), 'sRGB', lambda img: nt.links.new(bsdf.inputs['Base Color'], img.outputs['Color']))
  plug(v.get('normalBaseTex'), 'Non-Color', lambda img: (lambda nm:
       (nt.links.new(img.outputs['Color'], nm.inputs['Color']), nt.links.new(nm.outputs['Normal'], bsdf.inputs['Normal'])))(
       nt.nodes.new('ShaderNodeNormalMap')))
  plug(v.get('roughnessBaseTex'), 'Non-Color', lambda img: nt.links.new(bsdf.inputs['Roughness'], img.outputs['Color']))

  if v.get('heightBaseTex'):
    p = try_resolve_image_path(v.get('heightBaseTex'), level_dir, None)
    if p:
      try:
        img = nt.nodes.new('ShaderNodeTexImage')
        img.image = bpy.data.images.load(str(p), check_existing=True)
        img.image.colorspace_settings.name = 'Non-Color'
        disp = nt.nodes.new('ShaderNodeDisplacement')
        nt.links.new(img.outputs['Color'], disp.inputs['Height'])
        nt.links.new(disp.outputs['Displacement'], out.inputs['Displacement'])
      except Exception:
        pass
