# ##### BEGIN LICENSE BLOCK #####
#
# This program is licensed under The MIT License:
# see LICENSE for the full license text
#
# ##### END LICENSE BLOCK #####

from typing import List, BinaryIO
import struct

class TSMaterialFlags:
   SWrap = 1 << 0
   TWrap = 1 << 1
   Translucent = 1 << 2
   Additive = 1 << 3
   Subtractive = 1 << 4
   SelfIlluminating = 1 << 5
   NeverEnvMap = 1 << 6
   NoMipMap = 1 << 7
   MipMap_ZeroBorder = 1 << 8
   AuxMap = (1 << 27 | 1 << 28 | 1 << 29 | 1 << 30 | 1 << 31) # DEPRECATED

class TSMaterial:
    def __init__(self, name):
        self.name: str = name
        self.flags: int = 0

    def read(self, stream:BinaryIO, version):
        self.flags = struct.unpack('<L', stream.read(4))[0]

class TSMaterialList:
    def __init__(self):
       self._materials : List[TSMaterial] = []

    @property
    def materials(self) -> List[TSMaterial]:
        return self._materials

    def read(self, stream:BinaryIO, version):
        reader = stream

        mat_list_version = struct.unpack('<B', reader.read(1))[0]
        if mat_list_version != 0x1:
            raise Exception(f"Cannot read materials list version {mat_list_version}")

        # read material names
        mat_count = struct.unpack('<i', reader.read(4))[0]
        for _ in range(mat_count):
            mat_name_length = struct.unpack('<B', reader.read(1))[0]
            mat_name_bytes = reader.read(mat_name_length)
            mat_name = mat_name_bytes.decode('utf-8')

            self._materials.append(TSMaterial(mat_name))

        # read flags
        for x in range(mat_count):
            self._materials[x].flags = struct.unpack('<i', reader.read(4))[0]

        # read reflection maps
        for x in range(mat_count):
            struct.unpack('<i', reader.read(4))[0]

        # read bump maps
        for x in range(mat_count):
            struct.unpack('<i', reader.read(4))[0]

        # read detail maps
        for x in range(mat_count):
            struct.unpack('<i', reader.read(4))[0]

        if version == 25:
            # unused
            for x in range(mat_count):
                struct.unpack('<i', reader.read(4))[0]

        # read detail scales
        for x in range(mat_count):
            struct.unpack('<f', reader.read(4))[0]

        # read reflection amounts
        for x in range(mat_count):
            struct.unpack('<f', reader.read(4))[0]