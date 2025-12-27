# ##### BEGIN LICENSE BLOCK #####
#
# This program is licensed under The MIT License:
# see LICENSE for the full license text
#
# ##### END LICENSE BLOCK #####

import numpy as np

def apply_custom_normals(me, ln_np):
  if ln_np is None or ln_np.size == 0:
    return False
  if ln_np.ndim != 2 or ln_np.shape[1] != 3:
    return False
  if ln_np.shape[0] != len(me.loops):
    return False
  l = np.linalg.norm(ln_np, axis=1, keepdims=True)
  l[l == 0] = 1.0
  ln_np = ln_np / l
  try:
    me.use_auto_smooth = True
    me.calc_normals_split()
  except Exception:
    pass
  try:
    me.normals_split_custom_set(ln_np.tolist())
    return True
  except Exception:
    return False
