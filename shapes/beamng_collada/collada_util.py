# ##### BEGIN LICENSE BLOCK #####
#
# This program is licensed under The MIT License:
# see LICENSE for the full license text
#
# ##### END LICENSE BLOCK #####

import re
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

def make_valid_name(base, existing=None, maxlen=63):
  """
  Make a reasonably safe, short name from an arbitrary string.
  Uniqueness is up to the caller via the 'existing' set.
  """
  if not base:
    base = "Unnamed"
  base = str(base).strip()
  base = re.sub(r'[\r\n\t]', ' ', base)
  base = re.sub(r'\s+', ' ', base)
  base = base[:maxlen]

  if existing is None:
    return base

  name = base
  if name not in existing:
    return name

  i = 1
  while True:
    cand = f"{base}.{i:03d}"
    if cand not in existing:
      return cand
    i += 1
