# ##### BEGIN LICENSE BLOCK #####
#
# This program is licensed under The MIT License:
# see LICENSE for the full license text
#
# ##### END LICENSE BLOCK #####

import bpy
from ..utils.bpy_helpers import ensure_collection, link_object_to_collection
from .mission import get_euler_from_rotlist, make_matrix

def build_forest_objects(ctx):
  forest_coll = ensure_collection('ForestData')
  for idx, i in enumerate(ctx.forest_data):
    position = i.get('pos') or [0, 0, 0]
    rot = i.get('rotationMatrix')
    rotationEuler = get_euler_from_rotlist(rot)
    type_name = i.get('type') or 'ForestItem'
    empty = bpy.data.objects.new(type_name, None)
    empty.empty_display_type = 'ARROWS'
    empty.matrix_world = make_matrix(position, rotationEuler, (1,1,1))
    link_object_to_collection(empty, forest_coll)
    try:
      model_name = ctx.forest_names.get(type_name)
      if model_name:
        ob = bpy.data.objects.get(model_name)
        if ob and ob.type == 'MESH':
          cp = bpy.data.objects.new(model_name, ob.data)
          link_object_to_collection(cp, forest_coll)
          cp.parent = empty
    except Exception:
      pass
    if (idx & 63) == 0:
      ctx.progress.update(f"Forest: {idx+1}/{len(ctx.forest_data)}", step=1)
