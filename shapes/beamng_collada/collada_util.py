# ##### BEGIN LICENSE BLOCK #####
#
# This program is licensed under The MIT License:
# see LICENSE for the full license text
#
# ##### END LICENSE BLOCK #####

import numpy as np

_SOURCE_FLOAT_CACHE = {}
_INPUT_SR_CACHE = {}

def tag_name(el):
  if el is None or el.tag is None:
    return ""
  return el.tag.split('}', 1)[-1]

def parse_floats_np(text, dtype=np.float32):
  if not text:
    return np.empty(0, dtype=dtype)
  return np.fromstring(text, sep=' ', dtype=dtype)

def parse_ints_np(text, dtype=np.int64):
  if not text:
    return np.empty(0, dtype=dtype)
  return np.fromstring(text, sep=' ', dtype=dtype)

def mat_det(m):
  return m.determinant()

def comp(offsets, i, default_idx):
  if offsets is None:
    return default_idx
  if i < 0 or i >= len(offsets):
    return default_idx
  return offsets[i] if offsets[i] is not None else default_idx
