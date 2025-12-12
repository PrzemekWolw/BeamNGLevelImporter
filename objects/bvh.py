# ##### BEGIN LICENSE BLOCK #####
#
# This program is licensed under The MIT License:
# see LICENSE for the full license text
#
# ##### END LICENSE BLOCK #####

import bpy
import mathutils

def _dr_build_bvh_targets(include_objects: bool):
  targets = []
  try:
    from mathutils.bvhtree import BVHTree
  except Exception:
    return targets
  depsgraph = bpy.context.evaluated_depsgraph_get()
  objs = [o for o in bpy.context.scene.objects if o.type == 'MESH']
  terr = [o for o in objs if 'terrain' in (o.name or '').lower()]
  ordered = terr + ([o for o in objs if o not in terr] if include_objects else [])
  for o in ordered:
    try:
      oe = o.evaluated_get(depsgraph)
      tree = BVHTree.FromObject(oe, depsgraph, epsilon=0.0)
      if not tree:
        continue
      w2l = oe.matrix_world.inverted_safe()
      l2w = oe.matrix_world.copy()
      targets.append({'tree': tree, 'w2l': w2l, 'l2w': l2w})
    except Exception:
      continue
  return targets

def _dr_bvh_ray_down(world_origin, max_down, targets):
  if not targets:
    return None
  direction_ws = mathutils.Vector((0.0, 0.0, -1.0))
  best_z = None
  for T in targets:
    tree = T.get('tree')
    if not tree:
      continue
    try:
      o_local = T['w2l'] @ world_origin
      d_local = (T['w2l'].to_3x3() @ direction_ws).normalized()
      hit = tree.ray_cast(o_local, d_local, distance=float(max_down))
      if not hit or hit[0] is None:
        continue
      loc_w = T['l2w'] @ hit[0]
      z = loc_w.z
      if best_z is None or z > best_z:
        best_z = z
    except Exception:
      continue
  return best_z