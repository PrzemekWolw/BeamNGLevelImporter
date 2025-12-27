# ##### BEGIN LICENSE BLOCK #####
#
# This program is licensed under The MIT License:
# see LICENSE for the full license text
#
# ##### END LICENSE BLOCK #####

import struct
from typing import List, BinaryIO

# The standard mathmatical set, where there are no duplicates.  However,
# this set uses bits instead of numbers.
class TSIntegerSet:
  def __init__(self):
    # 64 * 32 = 2048 bits; TS meshes rarely exceed this
    self.values: List[int] = [0] * 64

  def copy_from(self, other):
    self.values = other.values.copy()

  def read(self, stream: BinaryIO):
    reader = stream
    # numInts (unused)
    _ = struct.unpack('<L', reader.read(4))[0]
    # actual number of 32-bit words
    sz = struct.unpack('<L', reader.read(4))[0]
    self.values = [0] * 64
    for x in range(min(sz, 64)):
      self.values[x] = struct.unpack('<L', reader.read(4))[0]
    # skip extras if sz > 64
    if sz > 64:
      reader.read(4 * (sz - 64))

  def from_list(self, ints: List[int]):
    self.values = [0] * 64
    n = min(len(ints), 64)
    for i in range(n):
      self.values[i] = int(ints[i])

  def indices(self) -> List[int]:
    # Return indices of set bits (in increasing order)
    out = []
    for wi, w in enumerate(self.values):
      if not w:
        continue
      base = wi * 32
      bits = w
      while bits:
        b = bits & -bits
        bit_idx = (b.bit_length() - 1)
        out.append(base + bit_idx)
        bits ^= b
    return out

  def rank(self, idx: int) -> int:
    # Number of set bits with index < idx (used to compute rotNum/tranNum)
    word = idx // 32
    bit = idx % 32
    count = 0
    for i in range(min(word, 64)):
      count += self.values[i].bit_count()
    if word < 64 and bit:
      mask = (1 << bit) - 1
      count += (self.values[word] & mask).bit_count()
    return count
