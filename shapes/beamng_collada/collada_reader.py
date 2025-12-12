# ##### BEGIN LICENSE BLOCK #####
#
# This program is licensed under The MIT License:
# see LICENSE for the full license text
#
# ##### END LICENSE BLOCK #####

import numpy as np
from . import collada_util as U

class SourceReader:
  def __init__(self, source_el, desired_params=None):
    self.source = source_el
    self.accessor = None
    self.offsets = []
    self.accessor_offset = 0
    self._init(desired_params)

  def _init(self, desired_params):
    if self.source is None:
      return
    tech = self.source.find('.//{*}technique_common')
    self.accessor = None if tech is None else tech.find('.//{*}accessor')
    if self.accessor is None:
      return
    try:
      self.accessor_offset = int(self.accessor.get('offset') or 0)
    except Exception:
      self.accessor_offset = 0
    acc_params = [p.get('name') or '' for p in self.accessor.findall('{*}param')]
    if desired_params:
      found = []
      for want in desired_params:
        try:
          found.append(acc_params.index(want))
        except ValueError:
          found.append(None)
      if any(o is None for o in found):
        k = min(len(desired_params), len(acc_params))
        self.offsets = list(range(k))
      else:
        self.offsets = found
    else:
      self.offsets = list(range(len(acc_params)))

  def size(self):
    if not self.accessor is None:
      return int(self.accessor.get('count') or 0)
    return 0

  def stride(self):
    if not self.accessor is None:
      return int(self.accessor.get('stride') or len(self.offsets) or 1)
    return 0

  def float_array_np(self, dtype=np.float32):
    farr = self.source.find('{*}float_array') if self.source is not None else None
    if farr is None or not farr.text:
      return np.empty(0, dtype=dtype)
    key = (id(farr), dtype)
    arr = U._SOURCE_FLOAT_CACHE.get(key)
    if arr is None:
      arr = np.fromstring(farr.text, sep=' ', dtype=dtype)
      U._SOURCE_FLOAT_CACHE[key] = arr
    return arr
