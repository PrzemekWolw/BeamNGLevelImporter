# ##### BEGIN LICENSE BLOCK #####
#
# This program is licensed under The MIT License:
# see LICENSE for the full license text
#
# ##### END LICENSE BLOCK #####

import struct

class TSAlloc:
  def __init__(self, data: bytes, size_mem_buffer: int, start_u16: int, start_u8: int):
    self.data = data

    self.ptr32 = 0
    self.ptr16 = start_u16 * 4
    self.ptr8 = start_u8 * 4

    self.count32 = start_u16
    self.count16 = start_u8 - start_u16
    self.count8 = size_mem_buffer - start_u8

    self.guard8 = 0
    self.guard16 = 0
    self.guard32 = 0

    self.size = 0

  @property
  def file_offset32(self):
    return self.ptr32 + 16  # + size of mesh header

  @property
  def file_offset16(self):
    return self.ptr16 + 16  # + size of mesh header

  @property
  def file_offset8(self):
    return self.ptr8 + 16  # + size of mesh header

  def read_float(self):
    value = struct.unpack_from('<f', self.data, self.ptr32)[0]
    self.ptr32 += 4
    self.size += 4
    return value

  def read32(self):
    value = struct.unpack_from('<i', self.data, self.ptr32)[0]
    self.ptr32 += 4
    self.size += 4
    return value

  def read16(self):
    value = struct.unpack_from('<h', self.data, self.ptr16)[0]
    self.ptr16 += 2
    self.size += 2
    return value

  def read8(self):
    value = self.data[self.ptr8]
    self.ptr8 += 1
    self.size += 1
    return value

  def read_float_list(self, count: int):
    values = list(struct.unpack_from(f'<{count}f', self.data, self.ptr32))
    self.ptr32 += count * 4
    self.size += count * 4
    return values

  def read32_list(self, count: int):
    values = list(struct.unpack_from(f'<{count}i', self.data, self.ptr32))
    self.ptr32 += count * 4
    self.size += count * 4
    return values

  def read16_list(self, count: int):
    values = list(struct.unpack_from(f'<{count}h', self.data, self.ptr16))
    self.ptr16 += count * 2
    self.size += count * 2
    return values

  def read8_list(self, count: int):
    values = list(self.data[self.ptr8:self.ptr8 + count])
    self.ptr8 += count
    self.size += count
    return values

  def skip8(self, count: int = 1):
    self.ptr8 += count
    self.size += count

  def skip16(self, count: int = 1):
    self.ptr16 += count * 2
    self.size += count * 2

  def skip32(self, count: int = 1):
    self.ptr32 += count * 4
    self.size += count * 4

  def check_guard(self):
    got32 = self.read32()
    if self.guard32 != got32:
      raise ValueError(f"Bad 32-bit guard, wanted {self.guard32}, got {got32}")

    got16 = self.read16()
    if self.guard16 != got16:
      raise ValueError(f"Bad 16-bit guard, wanted {self.guard16}, got {got16}")

    got8 = self.read8()
    if self.guard8 != got8:
      raise ValueError(f"Bad 8-bit guard, wanted {self.guard8}, got {got8}")

    self.guard32 += 1
    self.guard16 = ((self.guard16 + 1) & 0xFFFF)
    self.guard8 = ((self.guard8 + 1) & 0xFF)

    return True

  def align32(self):
    # no-op, but this is called so keep it
    pass