# ##### BEGIN LICENSE BLOCK #####
#
# This program is licensed under The MIT License:
# see LICENSE for the full license text
#
# ##### END LICENSE BLOCK #####

import os, sys, struct, time, zipfile
from .tsshape import *
from .tsmesh import TSMesh, TSSkinnedMesh, TSNullMesh, TSDrawPrimitive
from .tsmateriallist import TSMaterial
from . import import_common as C

def _try_import(name: str) -> bool:
  try:
    __import__(name)
    return True
  except Exception:
    return False

def _ensure_cdae_deps():
  ok_msgpack = _try_import("msgpack")
  ok_zstd  = _try_import("zstandard")
  if ok_msgpack and ok_zstd:
    return

  addon_dir = os.path.dirname(__file__)
  wheels_dir = os.path.join(addon_dir, "third_party", "wheels")
  site_dir   = os.path.join(addon_dir, "third_party", "sitepkgs")
  os.makedirs(site_dir, exist_ok=True)
  if site_dir not in sys.path:
    sys.path.insert(0, site_dir)

  py = sys.version_info
  cp_tag = f"cp{py.major}{py.minor}"
  plat = sys.platform

  def platform_ok(fname: str) -> bool:
    lname = fname.lower()
    if plat.startswith("win"):
      return ("win" in lname) and ("amd64" in lname or "win_amd64" in lname or "arm64" in lname)
    elif plat == "darwin":
      return "macosx" in lname
    else:
      return ("manylinux" in lname) or ("musllinux" in lname) or ("linux" in lname)

  def install_one(dist_prefix: str) -> bool:
    if _try_import(dist_prefix):
      return True
    if not os.path.isdir(wheels_dir):
      return False
    candidates = []
    for fn in os.listdir(wheels_dir):
      if not fn.endswith(".whl"):
        continue
      lower = fn.lower()
      if not (lower.startswith(dist_prefix.replace("_", "-")) or lower.startswith(dist_prefix)):
        continue
      if cp_tag not in lower:
        continue
      if not platform_ok(lower):
        continue
      candidates.append(fn)
    if not candidates:
      return False
    def score(name):
      s = 0
      if "universal2" in name: s += 10
      if "manylinux2014" in name: s += 8
      if "manylinux" in name: s += 5
      if cp_tag in name: s += 4
      return -s
    candidates.sort(key=score)
    wheel_path = os.path.join(wheels_dir, candidates[0])
    try:
      with zipfile.ZipFile(wheel_path, "r") as zf:
        zf.extractall(site_dir)
    except Exception as e:
      print(f"[CDAE bootstrap] Failed to extract {wheel_path}: {e}")
      return False
    return _try_import(dist_prefix)

  if not ok_msgpack:
    ok_msgpack = install_one("msgpack")
  if not ok_zstd:
    ok_zstd = install_one("zstandard")

  if not (ok_msgpack and ok_zstd):
    raise ImportError(
      "Missing dependencies for CDAE importer. "
      "Place msgpack and zstandard wheels into third_party/wheels, "
      "or install them into Blender’s Python."
    )

# ======================================================
# CDAE v31+ support (msgpack + optional zstd)
# ======================================================
def _read_header_v31(f):
  header_size = struct.unpack("<I", f.read(4))[0]
  header_bytes = f.read(header_size)
  import msgpack
  mp = msgpack.unpackb(header_bytes, strict_map_key=False, raw=False)
  is_compressed = bool(mp.get("compression", False))
  bodysize = int(mp.get("bodysize", 0))
  return is_compressed, bodysize

class _UnpackStream:
  def __init__(self, data: bytes):
    import msgpack
    kwargs = dict(strict_map_key=False, raw=False)
    caps = dict(
      max_buffer_size=0,
      max_bin_len=2**31 - 1,
      max_array_len=2**31 - 1,
      max_map_len=2**31 - 1,
      max_str_len=2**31 - 1,
    )
    for k, v in list(caps.items()):
      try:
        msgpack.Unpacker(**kwargs, **{k: v})
        kwargs[k] = v
      except TypeError:
        pass
    self._u = msgpack.Unpacker(**kwargs)
    self._u.feed(data)
  def next(self):
    return self._u.unpack()

def _read_packed_vector(u: "_UnpackStream"):
  size = int(u.next())
  elem_size = int(u.next())
  blob = u.next()
  if not isinstance(blob, (bytes, bytearray)) or len(blob) != size * elem_size:
    raise ValueError("pack_vector size mismatch")
  return size, elem_size, blob

def _unpack_array(blob: bytes, fmt: str):
  es = struct.calcsize("<" + fmt)
  n = len(blob) // es
  out = []
  off = 0
  for _ in range(n):
    out.append(struct.unpack_from("<" + fmt, blob, off))
    off += es
  return out

def _decode_color_bytes_to_rgba_floats(blob: bytes):
  out = []
  for i in range(0, len(blob), 4):
    out.append((blob[i]/255.0, blob[i+1]/255.0, blob[i+2]/255.0, blob[i+3]/255.0))
  return out

def _unpack_i32_list(blob: bytes):
  cnt = len(blob) // 4
  return list(struct.unpack("<" + "i"*cnt, blob)) if cnt else []

def _unpack_details(blob: bytes, count: int, elem_size: int):
  out = []
  for i in range(count):
    off = i * elem_size
    if off + elem_size > len(blob):
      break
    nameIndex, subShapeNum, objectDetailNum = struct.unpack_from("<iii", blob, off)
    size = 0.0
    avg = -1.0
    maxe = -1.0
    poly = 0
    bbDim = 0
    bbDL = 0
    bbEq = 0
    bbPo = 0
    bbAng = 0.0
    bbInc = 0
    if elem_size >= 16:
      size = struct.unpack_from("<f", blob, off + 12)[0]
    if elem_size >= 20:
      avg = struct.unpack_from("<f", blob, off + 16)[0]
    if elem_size >= 24:
      maxe = struct.unpack_from("<f", blob, off + 20)[0]
    if elem_size >= 28:
      poly = struct.unpack_from("<i", blob, off + 24)[0]
    if elem_size >= 52:
      bbDim, bbDL = struct.unpack_from("<ii", blob, off + 28)
      bbEq, bbPo = struct.unpack_from("<II", blob, off + 36)
      bbAng = struct.unpack_from("<f", blob, off + 44)[0]
      bbInc = struct.unpack_from("<I", blob, off + 48)[0]
    det = ShapeDetail()
    det.name_index = nameIndex
    det.sub_shape_num = subShapeNum
    det.object_detail_num = objectDetailNum
    det.size = size
    det.average_error = avg
    det.max_error = maxe
    det.poly_count = poly
    det.billboard_dimension = bbDim
    det.billboard_detail_level = bbDL
    det.billboard_equator_steps = bbEq
    det.billboard_polar_steps = bbPo
    det.billboard_polar_angle = bbAng
    det.billboard_include_poles = bbInc
    out.append(det)
  return out

def _read_tsintset(u: "_UnpackStream") -> list[int]:
  obj = u.next()
  if isinstance(obj, (bytes, bytearray)):
    cnt = len(obj) // 4
    return list(struct.unpack("<" + "I" * cnt, obj[:cnt * 4])) if cnt else []
  if isinstance(obj, list):
    if all(isinstance(x, int) for x in obj):
      return [int(x) for x in obj]
    candidates = [sub for sub in obj if isinstance(sub, list) and all(isinstance(x, int) for x in sub)]
    if candidates:
      return [int(x) for x in max(candidates, key=len)]
    return [int(x) for x in obj if isinstance(x, int)]
  if isinstance(obj, dict):
    for k in ("values", "v", "data"):
      v = obj.get(k)
      if isinstance(v, list) and all(isinstance(x, int) for x in v):
        return [int(x) for x in v]
  return []

def _read_cdae_shape(filepath: str) -> TSShape:
  _ensure_cdae_deps()
  import msgpack
  try:
    import zstandard as zstd
  except Exception:
    zstd = None

  with open(filepath, "rb") as f:
    version = struct.unpack("<i", f.read(4))[0] & 0xFF
    if version < 31:
      raise Exception(f"Not a CDAE v31+ file (version={version})")
    is_compressed, bodysize = _read_header_v31(f)
    body = f.read(bodysize) if bodysize > 0 else f.read()
    if is_compressed:
      if not zstd:
        raise RuntimeError("CDAE is compressed; 'zstandard' is unavailable.")
      body = zstd.ZstdDecompressor().decompress(body)

  u = _UnpackStream(body)
  shape = TSShape()
  shape._from_cdae = True

  # header scalars (unused here but consumed to match stream layout)
  _ = float(u.next()); _ = int(u.next())
  _ = float(u.next()); _ = float(u.next())
  _ = u.next(); _ = u.next()

  # nodes/objects/subshape headers
  _, _, n_blob = _read_packed_vector(u)
  nodes_raw = _unpack_array(n_blob, "iiiii")
  _, _, o_blob = _read_packed_vector(u)
  objects_raw = _unpack_array(o_blob, "iiiiii")
  _, _, s1_blob = _read_packed_vector(u)
  _, _, s2_blob = _read_packed_vector(u)
  _, _, s3_blob = _read_packed_vector(u)
  _, _, s4_blob = _read_packed_vector(u)
  shape._sub_shape_first_node   = _unpack_i32_list(s1_blob)
  shape._sub_shape_first_object = _unpack_i32_list(s2_blob)
  shape._sub_shape_num_nodes  = _unpack_i32_list(s3_blob)
  shape._sub_shape_num_objects  = _unpack_i32_list(s4_blob)

  # default transforms
  _, _, drr_blob = _read_packed_vector(u)
  default_rots = _unpack_array(drr_blob, "hhhh")
  _, _, dtr_blob = _read_packed_vector(u)
  default_trans = _unpack_array(dtr_blob, "fff")

  def _unpack_quat16_blob(blob: bytes):
    es = struct.calcsize("<hhhh")
    n = len(blob) // es
    out = []
    off = 0
    for _ in range(n):
      rx, ry, rz, rw = struct.unpack_from("<hhhh", blob, off)
      out.append(TQuaternion16(rx, ry, rz, rw))
      off += es
    return out

  # animated node transforms
  sz, _, blob = _read_packed_vector(u)
  anim_node_rots = _unpack_quat16_blob(blob) if sz else []
  sz, _, blob = _read_packed_vector(u)
  anim_node_trans = _unpack_array(blob, "fff") if sz else []
  sz, _, blob = _read_packed_vector(u)
  anim_node_uniform = list(struct.unpack("<" + "f"*sz, blob)) if sz else []
  sz, _, blob = _read_packed_vector(u)
  anim_node_aligned = _unpack_array(blob, "fff") if sz else []
  sz, _, blob = _read_packed_vector(u)
  anim_node_arb_factors = _unpack_array(blob, "fff") if sz else []
  sz, _, blob = _read_packed_vector(u)
  anim_node_arb_rots = _unpack_quat16_blob(blob) if sz else []

  # DEPRECATED arrays we still need to consume
  _ = _read_packed_vector(u)
  _ = _read_packed_vector(u)

  # objects/targets/details
  _obj_sz, _obj_es, _obj_blob = _read_packed_vector(u)
  _trg_sz, _trg_es, _trg_blob = _read_packed_vector(u)
  det_sz, det_es, det_blob = _read_packed_vector(u)
  shape._details = _unpack_details(det_blob, det_sz, det_es) if det_sz else []

  # names
  num_names = int(u.next())
  names = [str(u.next()) for _ in range(num_names)]

  # meshes
  num_meshes = int(u.next())
  meshes = []
  for _ in range(num_meshes):
    mtype = int(u.next())
    if mtype == MeshType.NullMeshType:
      meshes.append(TSNullMesh())
      continue

    numFrames = int(u.next())
    numMatFrames = int(u.next())
    parentMesh = int(u.next())
    _ = u.next()
    _ = u.next()
    _ = float(u.next())

    v_sz, _, v_blob = _read_packed_vector(u)
    verts = _unpack_array(v_blob, "fff")
    t_sz, _, t_blob = _read_packed_vector(u)
    tverts = _unpack_array(t_blob, "ff")
    t2_sz, _, t2_blob = _read_packed_vector(u)
    t2verts = _unpack_array(t2_blob, "ff") if t2_sz else []
    c_sz, _, c_blob = _read_packed_vector(u)
    colors = _decode_color_bytes_to_rgba_floats(c_blob) if c_sz else []
    n_sz, _, n_blob = _read_packed_vector(u)
    norms = _unpack_array(n_blob, "fff") if n_sz else []

    _ = _read_packed_vector(u)  # encoded normals (unused)
    p_sz, _, p_blob = _read_packed_vector(u)
    prims_raw = _unpack_array(p_blob, "iii")
    i_sz, _, i_blob = _read_packed_vector(u)
    indices = list(struct.unpack("<" + "I"*i_sz, i_blob)) if i_sz else []
    tan_sz, _, tan_blob = _read_packed_vector(u)
    tangents = _unpack_array(tan_blob, "fff") if tan_sz else []

    vertsPerFrame = int(u.next())
    flags = int(u.next())

    # skin extras
    if mtype == MeshType.SkinMeshType:
      initV_sz, _, _ = _read_packed_vector(u)
      initN_sz, _, _ = _read_packed_vector(u)
      xforms_sz, _, xforms_blob = _read_packed_vector(u)
      vi_sz, _, vi_blob = _read_packed_vector(u)
      bi_sz, _, bi_blob = _read_packed_vector(u)
      w_sz,  _, w_blob  = _read_packed_vector(u)
      ni_sz, _, ni_blob = _read_packed_vector(u)

    # Keep primitives as provided; import_common will triangulate strips
    prims = []
    for (start, num, mat_and_flags) in prims_raw:
      prims.append(TSDrawPrimitive(start, num, mat_and_flags))

    if mtype == MeshType.SkinMeshType:
      sm = TSSkinnedMesh()
      sm._vertices  = [tuple(v) for v in verts]
      sm._tvertices = [tuple(t) for t in tverts]
      sm._t2vertices= [tuple(t) for t in t2verts]
      sm._colors  = colors
      sm._indices   = indices
      sm._primitives= prims
      sm._normals   = [tuple(n) for n in norms] if n_sz else []
      sm._tangents  = [tuple(t) for t in tangents] if tan_sz else []

      sm._parent_mesh = parentMesh
      sm._flags = flags
      sm._num_frames = numFrames
      sm._num_mat_frames = numMatFrames
      sm._verts_per_frame = vertsPerFrame

      if xforms_sz:
        xf_floats = struct.unpack("<" + "f" * (xforms_sz * 16), xforms_blob)
        sm._initial_transforms = [list(xf_floats[i * 16:(i + 1) * 16]) for i in range(xforms_sz)]
      sm._vertex_index = list(struct.unpack("<" + "I" * vi_sz, vi_blob)) if vi_sz else []
      sm._bone_index   = list(struct.unpack("<" + "I" * bi_sz, bi_blob)) if bi_sz else []
      sm._weight     = list(struct.unpack("<" + "f" * w_sz,  w_blob))  if w_sz  else []
      sm._node_index   = list(struct.unpack("<" + "I" * ni_sz, ni_blob)) if ni_sz else []

      meshes.append(sm)
    else:
      tm = TSMesh()
      tm._vertices  = [tuple(v) for v in verts]
      tm._tvertices = [tuple(t) for t in tverts]
      tm._t2vertices= [tuple(t) for t in t2verts]
      tm._colors  = colors
      tm._indices   = indices
      tm._primitives= prims
      tm._normals   = [tuple(n) for n in norms] if n_sz else []
      tm._tangents  = [tuple(t) for t in tangents] if tan_sz else []

      tm._parent_mesh = parentMesh
      tm._flags = flags
      tm._num_frames = numFrames
      tm._num_mat_frames = numMatFrames
      tm._verts_per_frame = vertsPerFrame

      meshes.append(tm)

  # copy vertex data from parent meshes where needed
  for i, m in enumerate(meshes):
    if isinstance(m, TSMesh) and m.parent_mesh is not None and m.parent_mesh >= 0:
      p = meshes[m.parent_mesh] if m.parent_mesh < len(meshes) else None
      if isinstance(p, TSMesh) and not m.vertices:
        m.copy_vertex_data_from(p)

  # sequences
  num_seqs = int(u.next())
  shape._sequences = []
  for _ in range(num_seqs):
    seq = ShapeSequence()
    seq.name_index = int(u.next())
    seq.flags = int(u.next())
    seq.num_keyframes = int(u.next())
    seq.duration = float(u.next())
    seq.priority = int(u.next())
    seq.first_ground_frame = int(u.next())
    seq.num_ground_frames = int(u.next())
    seq.base_rotation = int(u.next())
    seq.base_translation = int(u.next())
    seq.base_scale = int(u.next())
    seq.base_object_state = int(u.next())
    seq.base_decal_state = int(u.next())
    seq.first_trigger = int(u.next())
    seq.num_triggers = int(u.next())
    seq.tool_begin = float(u.next())

    seq.rotation_matters.from_list(_read_tsintset(u))
    seq.translation_matters.from_list(_read_tsintset(u))
    seq.scale_matters.from_list(_read_tsintset(u))
    seq.vis_matters.from_list(_read_tsintset(u))
    seq.frame_matters.from_list(_read_tsintset(u))
    seq.mat_frame_matters.from_list(_read_tsintset(u))
    shape._sequences.append(seq)

  # materials
  materials = []
  try:
    mcount = int(u.next())
  except Exception:
    mcount = 0
  for _ in range(mcount):
    mname = str(u.next())
    _ = int(u.next()); _ = int(u.next()); _ = int(u.next()); _ = int(u.next())
    _ = float(u.next()); _ = float(u.next())
    materials.append(TSMaterial(mname))

  # Assign directly to the TSShape material list (no try/except fallback)
  mats = shape._material_list.materials
  mats.clear()
  mats.extend(materials)

  # names, nodes, objects, anim arrays onto shape
  shape._names = names
  shape._nodes = []
  for i, (nameIdx, parentIdx, _fo, _fc, _ns) in enumerate(nodes_raw):
    n = ShapeNode()
    n.name_index = nameIdx
    n.parent_index = parentIdx
    rx, ry, rz, rw = default_rots[i]
    n.rotation = TQuaternion16(rx, ry, rz, rw)
    tx, ty, tz = default_trans[i]
    n.translation = (tx, ty, tz)
    shape._nodes.append(n)

  shape._objects = []
  for (nameIdx, numMeshes, startMeshIndex, nodeIndex, _ns, _fd) in objects_raw:
    o = ShapeObject()
    o.name_index = nameIdx
    o.num_meshes = numMeshes
    o.start_mesh_index = startMeshIndex
    o.node_index = nodeIndex
    shape._objects.append(o)

  shape._meshes = meshes
  shape._anim_node_rotations = anim_node_rots
  shape._anim_node_translations = [tuple(t) for t in anim_node_trans]
  shape._anim_node_uniform_scales = anim_node_uniform
  shape._anim_node_aligned_scales = [tuple(t) for t in anim_node_aligned]
  shape._anim_node_arbitrary_scale_factors = [tuple(t) for t in anim_node_arb_factors]
  shape._anim_node_arbitrary_scale_rot = anim_node_arb_rots

  return shape

def load_cdae(filepath, context, merge_verts: bool = True):
  print("importing CDAE: %r..." % (filepath))
  t0 = time.perf_counter()
  shape = _read_cdae_shape(filepath)
  C._create_scene_from_shape(shape, merge_verts=merge_verts)
  print(" done in %.4f sec." % (time.perf_counter() - t0))
