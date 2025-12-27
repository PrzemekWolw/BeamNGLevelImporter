# ##### BEGIN LICENSE BLOCK #####
#
# This program is licensed under The MIT License:
# see LICENSE for the full license text
#
# ##### END LICENSE BLOCK #####

import struct
from typing import List, BinaryIO
from .tsmesh import *
from .tsalloc import *
from .tsmateriallist import *
from .integerset import *

class MeshType:
  StandardMeshType = 0
  SkinMeshType = 1
  DecalMeshType = 2
  SortedMeshType = 3
  NullMeshType = 4

  TypeMask = 7  # result of 0 | 1 | 2 | 3 | 4

class SequenceFlags:
  UniformScale = 1 << 0
  AlignedScale = 1 << 1
  ArbitraryScale = 1 << 2
  Blend = 1 << 3
  Cyclic = 1 << 4
  MakePath = 1 << 5
  HasTranslucency = 1 << 6
  AnyScale = (1 << 0) | (1 << 1) | (1 << 2)

class TQuaternionF:
  def __init__(self, x, y, z, w):
    self.x = x; self.y = y; self.z = z; self.w = w

class TQuaternion16:
  MAX_VALUE = 0x7fff
  def __init__(self, x, y, z, w):
    self.x = x; self.y = y; self.z = z; self.w = w
  def to_quat_f(self):
    return TQuaternionF(self.x / TQuaternion16.MAX_VALUE,
              self.y / TQuaternion16.MAX_VALUE,
              self.z / TQuaternion16.MAX_VALUE,
              self.w / TQuaternion16.MAX_VALUE)

class ShapeNode:
  def __init__(self):
    self.name_index: int = -1
    self.parent_index: int = -1
    self.translation: tuple[float, float, float] = (0.0, 0.0, 0.0)
    self.rotation: TQuaternion16 = TQuaternion16(0, 0, 0, TQuaternion16.MAX_VALUE)
  def assemble(self, ts_alloc):
    self.name_index = ts_alloc.read32()
    self.parent_index = ts_alloc.read32()

    # runtime computed apparently
    ts_alloc.read32()
    ts_alloc.read32()
    ts_alloc.read32()

class ShapeObject:
  def __init__(self):
    self.name_index: int = -1
    self.num_meshes: int = -1
    self.start_mesh_index: int = -1
    self.node_index: int = -1
  def assemble(self, ts_alloc):
    self.name_index = ts_alloc.read32()
    self.num_meshes = ts_alloc.read32()
    self.start_mesh_index = ts_alloc.read32()
    self.node_index = ts_alloc.read32()

    # runtime computed apparently
    ts_alloc.read32()
    ts_alloc.read32()

class ShapeDetail:
  def __init__(self):
    self.name_index: int = -1
    self.sub_shape_num: int = -1
    self.object_detail_num: int = -1
    self.size: float = 0.0
    self.average_error: float = 0.0
    self.max_error: float = 0.0
    self.poly_count: int = 0
    self.billboard_dimension: int = 0
    self.billboard_detail_level: int = 0
    self.billboard_equator_steps: int = 0
    self.billboard_polar_steps: int = 0
    self.billboard_polar_angle: float = 0.0
    self.billboard_include_poles: int = 0
  def assemble(self, ts_alloc, version):
    self.name_index = ts_alloc.read32()
    self.sub_shape_num = ts_alloc.read32()
    self.object_detail_num = ts_alloc.read32()
    self.size = ts_alloc.read_float()
    self.average_error = ts_alloc.read_float()
    self.max_error = ts_alloc.read_float()
    self.poly_count = ts_alloc.read32()

    if version >= 26:
      self.billboard_dimension = ts_alloc.read32()
      self.billboard_detail_level = ts_alloc.read32()
      self.billboard_equator_steps = ts_alloc.read32()
      self.billboard_polar_steps = ts_alloc.read32()
      self.billboard_polar_angle = ts_alloc.read_float()
      self.billboard_include_poles = ts_alloc.read32()

class ShapeSequence:
  def __init__(self):
    self.name_index: int = -1
    self.flags: int = 0
    self.duration: float = 0.0
    self.first_ground_frame: int = -1
    self.num_ground_frames: int = 0
    self.priority: int = 0
    self.base_rotation: int = -1
    self.base_translation: int = -1
    self.base_scale: int = -1
    self.base_object_state: int = -1
    self.base_decal_state: int = -1
    self.first_trigger: int = -1
    self.num_triggers: int = 0
    self.num_keyframes: int = 0
    self.tool_begin: float = 0.0
    self.rotation_matters: TSIntegerSet = TSIntegerSet()
    self.translation_matters: TSIntegerSet = TSIntegerSet()
    self.scale_matters: TSIntegerSet = TSIntegerSet()
    self.vis_matters: TSIntegerSet = TSIntegerSet()
    self.frame_matters: TSIntegerSet = TSIntegerSet()
    self.mat_frame_matters: TSIntegerSet = TSIntegerSet()

  def read(self, stream: BinaryIO, version):
    r = stream
    self.name_index = struct.unpack('<i', r.read(4))[0]
    if version > 21:
      self.flags = struct.unpack('<L', r.read(4))[0]
    else:
      self.flags = 0
    self.num_keyframes = struct.unpack('<L', r.read(4))[0]
    self.duration = struct.unpack('<f', r.read(4))[0]
    if version < 22:
      if r.read(1)[0] != 0:
        self.flags |= SequenceFlags.Blend
      if r.read(1)[0] != 0:
        self.flags |= SequenceFlags.Cyclic
      if r.read(1)[0] != 0:
        self.flags |= SequenceFlags.MakePath
    self.priority = struct.unpack('<i', r.read(4))[0]
    self.first_ground_frame = struct.unpack('<i', r.read(4))[0]
    self.num_ground_frames = struct.unpack('<L', r.read(4))[0]
    if version > 21:
      self.base_rotation = struct.unpack('<i', r.read(4))[0]
      self.base_translation = struct.unpack('<i', r.read(4))[0]
      self.base_scale = struct.unpack('<i', r.read(4))[0]
      self.base_object_state = struct.unpack('<i', r.read(4))[0]
      self.base_decal_state = struct.unpack('<i', r.read(4))[0]
    else:
      self.base_rotation = struct.unpack('<i', r.read(4))[0]
      self.base_translation = self.base_rotation
      self.base_object_state = struct.unpack('<i', r.read(4))[0]
      _ = struct.unpack('<i', r.read(4))[0]
    self.first_trigger = struct.unpack('<i', r.read(4))[0]
    self.num_triggers = struct.unpack('<L', r.read(4))[0]
    self.tool_begin = struct.unpack('<f', r.read(4))[0]
    self.rotation_matters.read(stream)
    if version < 22:
      self.translation_matters.copy_from(self.rotation_matters)
    else:
      self.translation_matters.read(stream)
      self.scale_matters.read(stream)

    dummy_set = TSIntegerSet()
    dummy_set.read(stream) # DEPRECATED: decals
    dummy_set.read(stream) # DEPRECATED: Ifl materials

    self.vis_matters.read(stream)
    self.frame_matters.read(stream)
    self.mat_frame_matters.read(stream)



class TSShape:
  def __init__(self):
    self._sequences: List[ShapeSequence] = []
    self._details: List[ShapeDetail] = []
    self._meshes: List[TSMesh] = []
    self._nodes: List[ShapeNode] = []
    self._objects: List[ShapeObject] = []
    self._names: List[str] = []
    self._material_list: TSMaterialList = TSMaterialList()
    self._sub_shape_first_node : List[int] = []
    self._sub_shape_num_nodes : List[int] = []
    self._sub_shape_first_object : List[int] = []
    self._sub_shape_num_objects : List[int] = []
    # animated arrays (shared by DTS and CDAE)
    self._anim_node_rotations: List[TQuaternion16] = []
    self._anim_node_translations: List[tuple[float,float,float]] = []
    self._anim_node_uniform_scales: List[float] = []
    self._anim_node_aligned_scales: List[tuple[float,float,float]] = []
    self._anim_node_arbitrary_scale_rot: List[TQuaternion16] = []
    self._anim_node_arbitrary_scale_factors: List[tuple[float,float,float]] = []

  @property
  def sequences(self) -> List[ShapeSequence]:
    return self._sequences

  @property
  def details(self) -> List[ShapeDetail]:
    return self._details

  @property
  def materials(self) -> List[TSMaterial]:
    return self._material_list.materials

  @property
  def meshes(self) -> List[TSMesh]:
    return self._meshes

  @property
  def nodes(self) -> List[ShapeNode]:
    return self._nodes

  @property
  def objects(self) -> List[ShapeObject]:
    return self._objects

  @property
  def names(self) -> List[str]:
    return self._names

  def get_sub_shape_for_node(self, node_index) -> int:
    for x in range(len(self._sub_shape_first_node)):
      start = self._sub_shape_first_node[x]
      end = start + self._sub_shape_num_nodes[x]
      if (node_index >= start) and (node_index < end):
        return x
    return -1

  def get_sub_shape_for_object(self, object_index) -> int:
    for x in range(len(self._sub_shape_first_object)):
      start = self._sub_shape_first_object[x]
      end = start + self._sub_shape_num_objects[x]
      if (object_index >= start) and (object_index < end):
        return x
    return -1

  def get_sub_shape_details(self, sub_shape_index) -> List[ShapeDetail]:
    sub_shape_details = []
    for detail in self._details:
      if detail.sub_shape_num == sub_shape_index or detail.sub_shape_num < 0:
        sub_shape_details.append(detail)
    return sub_shape_details

  def read(self, stream: BinaryIO):
    reader = stream
    version_full = struct.unpack('<i', reader.read(4))[0]
    version = version_full & 0xFF
    if version < 19:
      raise Exception("This DTS file is too old")
    # v29+ files have a quick object-name header before the mem buffers
    if version >= 29 and version < 31:
      num_objects_header = struct.unpack('<i', reader.read(4))[0]
      for _ in range(num_objects_header):
        name_len = struct.unpack('<I', reader.read(4))[0]
        _ = reader.read(name_len)
    # mem buffers
    size_mem_buffer = struct.unpack('<i', reader.read(4))[0]
    start_u16 = struct.unpack('<i', reader.read(4))[0]
    start_u8 = struct.unpack('<i', reader.read(4))[0]

    buf = reader.read(size_mem_buffer * 4)

    ts_alloc = TSAlloc(buf, size_mem_buffer, start_u16, start_u8)
    self.assemble(ts_alloc, version)

    num_sequences = struct.unpack('<i', reader.read(4))[0]
    for _ in range(num_sequences):
      sequence = ShapeSequence()
      sequence.read(stream, version)
      self._sequences.append(sequence)
    self._material_list.read(stream, version)

    # postprocess: copy mesh data for parented meshes
    for mesh in self._meshes:
      if isinstance(mesh, TSMesh) and mesh.parent_mesh >= 0:
        mesh.copy_vertex_data_from(self._meshes[mesh.parent_mesh])

  def read_from_path(self, path: str):
    with open(path, "rb") as f:
      self.read(f)

  def assemble(self, ts_alloc: TSAlloc, version: int):
    num_nodes = ts_alloc.read32()
    num_objects = ts_alloc.read32()
    num_decals = ts_alloc.read32()
    num_sub_shapes = ts_alloc.read32()
    num_ifl_materials = ts_alloc.read32()
    if version < 22:
      num_node_rots = num_node_trans = ts_alloc.read32() - num_nodes
      num_node_uniform_scales = num_node_aligned_scales = num_node_arbitrary_scales = 0
    else:
      num_node_rots = ts_alloc.read32()
      num_node_trans = ts_alloc.read32()
      num_node_uniform_scales = ts_alloc.read32()
      num_node_aligned_scales = ts_alloc.read32()
      num_node_arbitrary_scales = ts_alloc.read32()

    num_ground_frames = ts_alloc.read32() if version > 23 else 0
    num_object_states = ts_alloc.read32()
    num_decal_states = ts_alloc.read32()
    num_triggers = ts_alloc.read32()
    num_details = ts_alloc.read32()
    num_meshes = ts_alloc.read32()
    num_skins = ts_alloc.read32() if version < 23 else 0
    num_names = ts_alloc.read32()

    _m_smallest_visible_size = ts_alloc.read_float()
    _m_smallest_visible_dl = ts_alloc.read32()
    ts_alloc.check_guard()

    _radius = ts_alloc.read_float()
    _tube_radius = ts_alloc.read_float()
    _ = [ts_alloc.read_float() for _ in range(3)]
    _ = [ts_alloc.read_float() for _ in range(3)]
    _ = [ts_alloc.read_float() for _ in range(3)]
    ts_alloc.check_guard()

    for _ in range(num_nodes):
      node = ShapeNode()
      node.assemble(ts_alloc)
      self._nodes.append(node)
    ts_alloc.check_guard()

    for _ in range(num_objects):
      obj = ShapeObject()
      obj.assemble(ts_alloc)
      self._objects.append(obj)

    if num_skins > 0:
      for _ in range(num_skins):
        for _ in range(6):
          ts_alloc.read32()
    ts_alloc.check_guard()

    for _ in range(num_decals):
      for _ in range(5):
        ts_alloc.read32()
    ts_alloc.check_guard()

    for _ in range(num_decals):
      for _ in range(5):
        ts_alloc.read32()
    ts_alloc.check_guard()

    for _ in range(num_sub_shapes):
      self._sub_shape_first_node.append(ts_alloc.read32())
    for _ in range(num_sub_shapes):
      self._sub_shape_first_object.append(ts_alloc.read32())
    for _ in range(num_sub_shapes):
      ts_alloc.read32()
    ts_alloc.check_guard()

    for _ in range(num_sub_shapes):
      self._sub_shape_num_nodes.append(ts_alloc.read32())
    for _ in range(num_sub_shapes):
      self._sub_shape_num_objects.append(ts_alloc.read32())
    for _ in range(num_sub_shapes):
      ts_alloc.read32()
    ts_alloc.check_guard()

    # default transforms
    for x in range(num_nodes):
      quat = TQuaternion16(ts_alloc.read16(), ts_alloc.read16(), ts_alloc.read16(), ts_alloc.read16())
      self._nodes[x].rotation = quat
    ts_alloc.align32()
    for x in range(num_nodes):
      self._nodes[x].translation = (ts_alloc.read_float(), ts_alloc.read_float(), ts_alloc.read_float())

    # animated transforms stored in shape (keep them!)
    self._anim_node_translations = []
    for _ in range(num_node_trans):
      x = ts_alloc.read32(); y = ts_alloc.read32(); z = ts_alloc.read32()
      self._anim_node_translations.append((
        struct.unpack("<f", struct.pack("<i", x))[0],
        struct.unpack("<f", struct.pack("<i", y))[0],
        struct.unpack("<f", struct.pack("<i", z))[0],
      ))
    self._anim_node_rotations = []
    for _ in range(num_node_rots):
      rx = ts_alloc.read16(); ry = ts_alloc.read16(); rz = ts_alloc.read16(); rw = ts_alloc.read16()
      self._anim_node_rotations.append(TQuaternion16(rx, ry, rz, rw))
    ts_alloc.align32()
    ts_alloc.check_guard()

    if version > 21:
      self._anim_node_uniform_scales = [struct.unpack("<f", struct.pack("<i", ts_alloc.read32()))[0] for _ in range(num_node_uniform_scales)]
      self._anim_node_aligned_scales = []
      for _ in range(num_node_aligned_scales):
        x = ts_alloc.read32(); y = ts_alloc.read32(); z = ts_alloc.read32()
        self._anim_node_aligned_scales.append((
          struct.unpack("<f", struct.pack("<i", x))[0],
          struct.unpack("<f", struct.pack("<i", y))[0],
          struct.unpack("<f", struct.pack("<i", z))[0],
        ))
      self._anim_node_arbitrary_scale_factors = []
      for _ in range(num_node_arbitrary_scales):
        x = ts_alloc.read32(); y = ts_alloc.read32(); z = ts_alloc.read32()
        self._anim_node_arbitrary_scale_factors.append((
          struct.unpack("<f", struct.pack("<i", x))[0],
          struct.unpack("<f", struct.pack("<i", y))[0],
          struct.unpack("<f", struct.pack("<i", z))[0],
        ))
      self._anim_node_arbitrary_scale_rot = []
      for _ in range(num_node_arbitrary_scales):
        rx = ts_alloc.read16(); ry = ts_alloc.read16(); rz = ts_alloc.read16(); rw = ts_alloc.read16()
        self._anim_node_arbitrary_scale_rot.append(TQuaternion16(rx, ry, rz, rw))
      ts_alloc.align32()
      ts_alloc.check_guard()

    if version > 23:
      for _ in range(num_ground_frames):
        for _ in range(3):
          ts_alloc.read32()
      for _ in range(num_ground_frames):
        for _ in range(4):
          ts_alloc.read16()
      ts_alloc.align32()
      ts_alloc.check_guard()

    for _ in range(num_object_states):
      for _ in range(3):
        ts_alloc.read32()
    ts_alloc.check_guard()

    for _ in range(num_decal_states):
      ts_alloc.read32()
    ts_alloc.check_guard()

    for _ in range(num_triggers):
      ts_alloc.read32()
      ts_alloc.read32()
    ts_alloc.check_guard()

    for _ in range(num_details):
      detail = ShapeDetail()
      detail.assemble(ts_alloc, version)
      self._details.append(detail)

    ts_alloc.check_guard()
    # Meshes (support >=27 here; TSMesh.assemble handles it)
    for _ in range(num_meshes):
      mesh_type_raw = ts_alloc.read32()

      mesh_type = mesh_type_raw & MeshType.TypeMask
      if mesh_type == MeshType.StandardMeshType:
        mesh = TSMesh()
        mesh.assemble(ts_alloc, version)
        self._meshes.append(mesh)
      elif mesh_type == MeshType.NullMeshType:
        self._meshes.append(TSNullMesh())
      elif mesh_type == MeshType.SkinMeshType:
        mesh = TSSkinnedMesh()
        mesh.assemble(ts_alloc, version)
        self._meshes.append(mesh)
      else:
        raise NotImplementedError(f"Can't parse mesh of type {mesh_type}")

    ts_alloc.check_guard()

    for m in self._meshes:
      if isinstance(m, TSMesh) and m.parent_mesh is not None and m.parent_mesh >= 0:
        if 0 <= m.parent_mesh < len(self._meshes):
          p = self._meshes[m.parent_mesh]
          if isinstance(p, TSMesh) and not m.vertices:
            m.copy_vertex_data_from(p)

    for _ in range(num_names):
      chars = []
      while True:
        b = ts_alloc.read8()
        if b == 0:
          break
        chars.append(chr(b))
      self._names.append(''.join(chars))

    ts_alloc.align32()
    ts_alloc.check_guard()

    if version < 23:
      # read skinned meshes from old versions
      ts_alloc.skip32(num_skins) # detail first skin
      ts_alloc.skip32(num_skins) # detail num skins

      ts_alloc.check_guard()

      for _ in range(num_skins):
        mesh = TSSkinnedMesh()
        mesh.assemble(ts_alloc, version)
        self._meshes.append(mesh)

      ts_alloc.check_guard()
