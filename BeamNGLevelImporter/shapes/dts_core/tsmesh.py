# ##### BEGIN LICENSE BLOCK #####
#
# This program is licensed under The MIT License:
# see LICENSE for the full license text
#
# ##### END LICENSE BLOCK #####

import struct
from typing import List, BinaryIO
from .tsalloc import *

class TSDrawPrimitiveType:
  Triangles = 0 << 30
  Strip = 1 << 30
  Fan = 2 << 30

  Indexed = 1 << 29
  NoMaterial = 1 << 28

  MaterialMask = ~(Strip|Fan|Triangles|Indexed|NoMaterial)
  TypeMask   = Strip|Fan|Triangles

class TSDrawPrimitive:
  def __init__(self, start, num_elements, material_and_flags):
    self.start = start
    self.num_elements = num_elements
    self.material_index = material_and_flags

    self.has_no_material = (material_and_flags & TSDrawPrimitiveType.NoMaterial) == TSDrawPrimitiveType.NoMaterial
    self.type = material_and_flags & TSDrawPrimitiveType.TypeMask
    self.material_index = material_and_flags & TSDrawPrimitiveType.MaterialMask

class TSMeshFlags:
  Billboard = 1 << 0
  BillboardZAxis = 1 << 1

class TSNullMesh:
  pass

class TSMesh:
  def __init__(self):
    self._vertices: List[tuple[float, float, float]] = []
    self._tvertices: List[tuple[float, float]] = []
    self._t2vertices: List[tuple[float, float]] = []
    self._colors: List[tuple[float, float, float, float]] = []
    self._normals: List[tuple[float, float, float]] = []
    self._tangents: List[tuple[float, float, float]] = []
    self._primitives: List[TSDrawPrimitive] = []
    self._indices: List[int] = []
    self._primitives_name_index: List[int] = []
    self._parent_mesh: int = -1
    self._flags: int = 0
    self._num_frames: int = 1
    self._num_mat_frames: int = 1
    self._verts_per_frame: int = 0

  @property
  def vertices(self) -> List[tuple[float, float, float]]:
    return self._vertices

  @property
  def normals(self) -> List[tuple[float, float, float]]:
    return self._normals

  @property
  def tangents(self) -> List[tuple[float, float, float]]:
    return self._tangents
  @property
  def tvertices(self) -> List[tuple[float, float]]:
    return self._tvertices

  @property
  def t2vertices(self) -> List[tuple[float, float]]:
    return self._t2vertices

  @property
  def colors(self) -> List[tuple[float, float, float, float]]:
    return self._colors

  @property
  def primitives(self) -> List[TSDrawPrimitive]:
    return self._primitives

  @property
  def indices(self) -> List[int]:
    return self._indices
  @property
  def primitives_name_index(self) -> List[int]:
    return self._primitives_name_index
  @property
  def parent_mesh(self) -> int:
    return self._parent_mesh
  @property
  def flags(self) -> int:
    return self._flags
  @property
  def num_frames(self) -> int:
    return self._num_frames
  @property
  def verts_per_frame(self) -> int:
    return self._verts_per_frame

  def copy_vertex_data_from(self, other):
    """Copies mesh vertex data (and associated arrays) from a parent mesh"""
    self._vertices  = other._vertices.copy()
    self._tvertices = other._tvertices.copy()
    self._t2vertices= other._t2vertices.copy()
    self._colors  = other._colors.copy()
    self._normals   = other._normals.copy()
    self._tangents  = other._tangents.copy()

  def assemble(self, ts_alloc: TSAlloc, version: int):
    ts_alloc.check_guard()
    self._num_frames = ts_alloc.read32()
    self._num_mat_frames = ts_alloc.read32()
    self._parent_mesh = ts_alloc.read32()

    # bounds/center/radius (not used here)
    _ = [ts_alloc.read_float() for _ in range(6)]
    _ = [ts_alloc.read_float() for _ in range(3)]
    _ = ts_alloc.read_float()

    if version >= 27:
      _ = ts_alloc.read32()  # vert_offset
      _ = ts_alloc.read32()  # offset_num_verts
      _ = ts_alloc.read32()  # offset_vert_size

    # verts and texture coords
    num_verts = ts_alloc.read32()

    if self._parent_mesh < 0:
      verts_buffer = ts_alloc.read_float_list(num_verts * 3)
      for x in range(0, num_verts * 3, 3):
        vertex = (verts_buffer[x], verts_buffer[x+1], verts_buffer[x+2])
        self._vertices.append(vertex)

    num_tverts = ts_alloc.read32()
    if self._parent_mesh < 0:
      tverts_buffer = ts_alloc.read_float_list(num_tverts * 2)
      for x in range(0, num_tverts * 2, 2):
        tvertex = (tverts_buffer[x], tverts_buffer[x+1])
        self._tvertices.append(tvertex)

    # 2nd texture channel and colors
    if version > 25:
      num_t2verts = ts_alloc.read32()
      if self._parent_mesh < 0:
        t2verts_buffer = ts_alloc.read_float_list(num_t2verts * 2)
        for x in range(0, num_t2verts * 2, 2):
          tvertex = (t2verts_buffer[x], t2verts_buffer[x+1])
          self._t2vertices.append(tvertex)

      num_vcolors = ts_alloc.read32()
      if self._parent_mesh < 0:
        # packed ABGR -> RGBA floats
        vcolors = ts_alloc.read32_list(num_vcolors)
        for packed_color in vcolors:
          red   =  packed_color & 0xFF
          green = (packed_color >> 8)  & 0xFF
          blue  = (packed_color >> 16) & 0xFF
          alpha = (packed_color >> 24) & 0xFF

          self._colors.append((red / 255.0, green / 255.0, blue / 255.0, alpha / 255.0))


    # normals
    if self._parent_mesh < 0:
      normals_buffer = ts_alloc.read_float_list(num_verts * 3)
      for x in range(0, num_verts * 3, 3):
        normal = (normals_buffer[x], normals_buffer[x+1], normals_buffer[x+2])
        self._normals.append(normal)

    if version > 21 and self._parent_mesh < 0:
      ts_alloc.skip8(num_verts)  # encoded normals, skip

    # primitives and indices

    starts = []
    elements = []
    material_indices = []

    if version > 25:
      # mesh primitives (start, numElements) and indices are stored as 32 bit values
      sz_prim_in = ts_alloc.read32()
      for _ in range(sz_prim_in):
        starts.append(ts_alloc.read32())
        elements.append(ts_alloc.read32())
        material_indices.append(ts_alloc.read32())

      sz_ind_in = ts_alloc.read32()
      self._indices.extend(ts_alloc.read32_list(sz_ind_in))
    else:
      # mesh primitives (start, numElements) indices are stored as 16 bit values
      sz_prim_in = ts_alloc.read32()
      for _ in range(sz_prim_in):
        starts.append(ts_alloc.read16())
        elements.append(ts_alloc.read16())
      for _ in range(sz_prim_in):
        material_indices.append(ts_alloc.read32())

      sz_ind_in = ts_alloc.read32()
      self._indices.extend(ts_alloc.read16_list(sz_ind_in))

    for x in range(len(starts)):
      start = starts[x]
      num_elements = elements[x]
      material_index = material_indices[x]

      prim = TSDrawPrimitive(start, num_elements, material_index)
      self._primitives.append(prim)

    # merge indices (deprecated)
    num_merge_indices = ts_alloc.read32()
    ts_alloc.skip16(num_merge_indices)

    ts_alloc.align32()


    self._verts_per_frame = ts_alloc.read32()
    self._flags = ts_alloc.read32()
    ts_alloc.check_guard()

class TSSkinnedMesh(TSMesh):
  def __init__(self):
    super().__init__()
    self._initial_transforms: List[List[float]] = []  # 16 floats per transform
    self._vertex_index: List[int] = []
    self._bone_index: List[int] = []
    self._weight: List[float] = []
    self._node_index: List[int] = []

  @property
  def initial_transforms(self): return self._initial_transforms
  @property
  def vertex_index(self): return self._vertex_index
  @property
  def bone_index(self): return self._bone_index
  @property
  def weight(self): return self._weight
  @property
  def node_index(self): return self._node_index

  def assemble(self, ts_alloc: TSAlloc, version: int):
    super().assemble(ts_alloc, version)

    # v29 skin block
    max_bones = -1 if version < 27 else ts_alloc.read32()

    # initial verts/normals (we do not need these to bind in Blender)
    sz_inits_verts = ts_alloc.read32()
    if self._parent_mesh < 0:
      ts_alloc.skip32(sz_inits_verts * 3)  # initial verts
      if version > 21:
        ts_alloc.skip32(sz_inits_verts * 3)  # initial norms
        ts_alloc.skip8(sz_inits_verts)     # encoded norms
      else:
        ts_alloc.skip32(sz_inits_verts * 3)  # normals

    # initialTransforms
    sz_xforms = ts_alloc.read32()
    if sz_xforms > 0:
      raw = ts_alloc.read_float_list(sz_xforms * 16)
      self._initial_transforms = [raw[i*16:(i+1)*16] for i in range(sz_xforms)]
    else:
      self._initial_transforms = []

    # vertexIndex / boneIndex / weight
    sz_influences = ts_alloc.read32()
    self._vertex_index = ts_alloc.read32_list(sz_influences)
    self._bone_index   = ts_alloc.read32_list(sz_influences)
    self._weight     = ts_alloc.read_float_list(sz_influences)

    # nodeIndex: map bone slot -> node index
    sz_node_index = ts_alloc.read32()
    self._node_index  = ts_alloc.read32_list(sz_node_index)

    ts_alloc.check_guard()


