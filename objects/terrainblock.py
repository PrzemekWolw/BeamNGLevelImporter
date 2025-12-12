# ##### BEGIN LICENSE BLOCK #####
#
# This program is licensed under The MIT License:
# see LICENSE for the full license text
#
# ##### END LICENSE BLOCK #####

import bpy
import os
import struct
from pathlib import Path
from ..core.paths import resolve_beamng_path, exists_insensitive, get_real_case_path

try:
  import numpy as np
  HAS_NUMPY = True
except Exception:
  HAS_NUMPY = False

def _r_u8(f):
  b = f.read(1)
  if not b:
    raise EOFError
  return struct.unpack('<B', b)[0]

def _r_u32(f):
  b = f.read(4)
  if len(b) != 4:
    raise EOFError
  return struct.unpack('<I', b)[0]

def _r_len_string(f):
  # Torque FileStream writes u32 length + raw bytes
  ln = _r_u32(f)
  if ln > 20_000_000:
    raise RuntimeError("Unreasonable string length in .ter")
  b = f.read(ln)
  if len(b) != ln:
    raise EOFError
  return b.decode('utf-8', errors='replace')

def read_ter_any(path: Path):
  """
  Returns dict: { version, size, heights (2D), layer (2D), material_names (list[str]) }
  heights: uint16, layer: uint8
  """
  with open(path, 'rb') as f:
    version = _r_u8(f)

    if version >= 7:
      size = _r_u32(f)
      n = size * size

      if HAS_NUMPY:
        heights = np.fromfile(f, dtype='<u2', count=n)
        layer = np.fromfile(f, dtype=np.uint8, count=n)
      else:
        heights = struct.unpack('<' + 'H' * n, f.read(2 * n))
        layer = struct.unpack('<' + 'B' * n, f.read(n))

      # v8+ has extra 4*n bytes (layerTextureMap); v7 stored it differently; we skip it
      if version >= 8:
        f.seek(n * 4, 1)
      else:
        f.read(n * 4)

      material_names = []
      try:
        mcount = _r_u32(f)
        for _ in range(mcount):
          material_names.append(_r_len_string(f))
      except Exception:
        material_names = []

      if HAS_NUMPY:
        heights = heights.reshape((size, size))
        layer = layer.reshape((size, size))
      else:
        heights = [list(heights[i*size:(i+1)*size]) for i in range(size)]
        layer = [list(layer[i*size:(i+1)*size]) for i in range(size)]

      return dict(version=version, size=size, heights=heights, layer=layer, material_names=material_names)

    # Legacy 1..6
    MaterialGroups = 8
    BlockSquareWidth = 256
    size = BlockSquareWidth
    n = size * size

    if HAS_NUMPY:
      heights = np.fromfile(f, dtype='<u2', count=n).reshape((size, size))
    else:
      heights_flat = struct.unpack('<' + 'H' * n, f.read(2 * n))
      heights = [list(heights_flat[i*size:(i+1)*size]) for i in range(size)]

    base_groups_bytes = f.read(n)
    if len(base_groups_bytes) != n:
      raise RuntimeError("Unexpected EOF in legacy .ter")
    if HAS_NUMPY:
      base_groups = (np.frombuffer(base_groups_bytes, dtype=np.uint8) & 0x07)
    else:
      base_groups = [(b & 0x07) for b in base_groups_bytes]

    if HAS_NUMPY:
      layer = base_groups.reshape((size, size)).astype(np.uint8)
    else:
      layer = [base_groups[i*size:(i+1)*size] for i in range(size)]


    material_names = []
    try:
      for _ in range(MaterialGroups):
        s = _r_len_string(f)
        if s:
          material_names.append(s)
    except Exception:
      material_names = [f"LegacyMat{i}" for i in range(MaterialGroups)]

    if HAS_NUMPY:
      layer = np.array(base_groups, dtype=np.uint8).reshape((size, size))
    else:
      layer = [base_groups[i*size:(i+1)*size] for i in range(size)]

    return dict(version=version, size=size, heights=heights, layer=layer, material_names=material_names)

def _map_materials(material_names):
  """Return a list of Blender materials in slot order; tries exact match and 'internalName-*' prefix match."""
  mats = []
  for nm in material_names or []:
    m = bpy.data.materials.get(nm)
    if not m:
      for cand in bpy.data.materials:
        if cand.name == nm or cand.name.startswith(nm + "-"):
          m = cand
          break
    if not m:
      m = bpy.data.materials.new(nm)
    mats.append(m)
  return mats

def build_terrain_object(name, size, heights, layer, square_size, height_scale, step=1, skip_holes=True, material_names=None):
  # Fast path: NumPy + foreach_set
  if HAS_NUMPY:
    import numpy as np

    # Grid sampling
    sy = (size - 1) // step + 1
    sx = (size - 1) // step + 1
    ys, xs = np.indices((sy, sx), dtype=np.int32)
    ys0 = ys * step
    xs0 = xs * step

    # Vertex positions (float32 for foreach_set)
    z = heights[ys0, xs0].astype(np.float32) * float(height_scale)
    vx = xs0.astype(np.float32) * float(square_size)
    vy = ys0.astype(np.float32) * float(square_size)

    nverts = sy * sx
    # XYZ interleaved
    co = np.empty(nverts * 3, dtype=np.float32)
    co[0::3] = vx.ravel()
    co[1::3] = vy.ravel()
    co[2::3] = z.ravel()

    # Face selection (quads on reduced grid)
    if skip_holes:
      # Need to ensure all 4 corners of a cell are not holes (255)
      c0 = layer[ys0[:-1, :-1], xs0[:-1, :-1]]
      c1 = layer[ys0[:-1, 1:], xs0[:-1, 1:]]
      c2 = layer[ys0[1:, 1:], xs0[1:, 1:]]
      c3 = layer[ys0[1:, :-1], xs0[1:, :-1]]
      valid_mask = (c0 != 255) & (c1 != 255) & (c2 != 255) & (c3 != 255)
      ys_f, xs_f = np.where(valid_mask)
    else:
      ys_f, xs_f = np.indices((sy - 1, sx - 1))
      ys_f = ys_f.ravel()
      xs_f = xs_f.ravel()

    nfaces = int(ys_f.size)
    # Early out: empty terrain (degenerate)
    import bpy
    me = bpy.data.meshes.new(name)
    if nverts == 0 or nfaces == 0:
      me.validate()
      me.update()
      obj = bpy.data.objects.new(name, me)
      return obj

    # Compute loop vertex indices for quads: [i, i+1, i+1+sx, i+sx]
    i = (ys_f * sx + xs_f).astype(np.int32)
    loops = np.empty((nfaces, 4), dtype=np.int32)
    loops[:, 0] = i
    loops[:, 1] = i + 1
    loops[:, 2] = i + 1 + sx
    loops[:, 3] = i + sx
    loops_1d = loops.ravel()

    # Create mesh and fill with foreach_set
    me.vertices.add(nverts)
    me.vertices.foreach_set("co", co)

    me.loops.add(nfaces * 4)
    me.loops.foreach_set("vertex_index", loops_1d)

    loop_start = (np.arange(nfaces, dtype=np.int32) * 4)
    loop_total = np.full(nfaces, 4, dtype=np.int32)
    me.polygons.add(nfaces)
    me.polygons.foreach_set("loop_start", loop_start)
    me.polygons.foreach_set("loop_total", loop_total)

    # UVs: per-vertex UV from normalized XY, then remap to loops
    world_w = float((size - 1) * square_size) if size and square_size else 1.0
    inv_w = 1.0 / world_w if world_w > 0 else 1.0
    uv_vert = np.empty((nverts, 2), dtype=np.float32)
    uv_vert[:, 0] = (vx.ravel() * inv_w)
    uv_vert[:, 1] = (vy.ravel() * inv_w)
    uv_loop = uv_vert[loops_1d]
    uv_layer_n = me.uv_layers.get("UV_TERRAIN01") or me.uv_layers.new(name="UV_TERRAIN01")
    uv_layer_n.data.foreach_set("uv", uv_loop.ravel())

    # Build object
    obj = bpy.data.objects.new(name, me)

    # Materials
    if material_names:
      mats = _map_materials(material_names)
      for m in mats:
        obj.data.materials.append(m)
      matcount = len(mats)

      # Per-face material index, vectorized like engine sampling:
      # center sample first; fallback to first valid of four corners if invalid
      y0 = ys_f * step
      x0 = xs_f * step
      cy = np.minimum(y0 + step // 2, size - 1)
      cx = np.minimum(x0 + step // 2, size - 1)

      lid = layer[cy, cx].astype(np.int32)
      invalid = (lid == 255) | (lid >= matcount)

      if invalid.any():
        # Gather corners (clamped)
        y0c = y0
        x0c = x0
        y1c = np.minimum(y0 + step, size - 1)
        x1c = np.minimum(x0 + step, size - 1)

        c00 = layer[y0c, x0c].astype(np.int32)
        c01 = layer[y0c, x1c].astype(np.int32)
        c11 = layer[y1c, x1c].astype(np.int32)
        c10 = layer[y1c, x0c].astype(np.int32)

        corners = np.stack([c00, c01, c11, c10], axis=1)
        valid_corner = (corners != 255) & (corners < matcount)
        has_valid = valid_corner.any(axis=1)
        first_idx = np.argmax(valid_corner, axis=1)  # 0 if none; guard with has_valid

        fallback_lid = corners[np.arange(nfaces), first_idx]
        lid = np.where(invalid, np.where(has_valid, fallback_lid, 0), lid)

      me.polygons.foreach_set("material_index", lid.astype(np.int32))

    # Smooth shading for all faces at once
    me.polygons.foreach_set("use_smooth", np.ones(nfaces, dtype=np.bool_))

    me.validate()
    me.update()
    return obj

  # Fallback to original implementation if NumPy is missing
  # (kept functionally identical to your original)
  verts = []
  faces = []
  face_cells = []
  sy = (size - 1) // step + 1
  sx = (size - 1) // step + 1
  for y in range(0, size, step):
    for x in range(0, size, step):
      z = heights[y][x] * height_scale
      verts.append((x * square_size, y * square_size, z))
  for y in range(sy - 1):
    for x in range(sx - 1):
      y0 = y * step
      x0 = x * step
      if skip_holes:
        if (layer[y0][x0] == 255 or layer[y0][x0 + step] == 255 or
            layer[y0 + step][x0 + step] == 255 or layer[y0 + step][x0] == 255):
          continue
      i = y * sx + x
      faces.append([i, i + 1, i + 1 + sx, i + sx])
      face_cells.append((y, x))
  me = bpy.data.meshes.new(name)
  me.from_pydata(verts, [], faces)
  me.validate()
  me.update()
  loops = me.loops
  verts_co = [v.co for v in me.vertices]
  uv_layer_n = me.uv_layers.get("UV_TERRAIN01") or me.uv_layers.new(name="UV_TERRAIN01")
  world_w = float((size - 1) * square_size) if size and square_size else 1.0
  inv_w = 1.0 / world_w if world_w > 0 else 1.0
  for poly in me.polygons:
    for li in poly.loop_indices:
      vi = loops[li].vertex_index
      vco = verts_co[vi]
      uv_layer_n.data[li].uv = (vco.x * inv_w, vco.y * inv_w)
  obj = bpy.data.objects.new(name, me)
  if material_names:
    mats = _map_materials(material_names)
    for m in mats:
      obj.data.materials.append(m)
    matcount = len(mats)
    polys = obj.data.polygons
    def get_layer_at(y, x):
      return int(layer[y][x])
    for face_idx, (y, x) in enumerate(face_cells):
      y0 = y * step
      x0 = x * step
      cy = min(y0 + step // 2, size - 1)
      cx = min(x0 + step // 2, size - 1)
      lid = get_layer_at(cy, cx)
      if lid == 255 or lid >= matcount:
        lids = []
        for dy, dx in ((0, 0), (0, step), (step, step), (step, 0)):
          yy = min(y0 + dy, size - 1)
          xx = min(x0 + dx, size - 1)
          v = get_layer_at(yy, xx)
          if v != 255 and v < matcount:
            lids.append(v)
        lid = lids[0] if lids else 0
      polys[face_idx].material_index = int(lid)
  try:
    for p in obj.data.polygons:
      p.use_smooth = True
  except Exception:
    pass
  return obj

def resolve_ter_path(level_root: Path, terrain_file: str | None) -> Path | None:
  if not terrain_file:
    return None
  p = resolve_beamng_path(terrain_file, level_root, None)
  return get_real_case_path(p) if p and exists_insensitive(p) else None

def find_terrain_meta_for_ter(ctx, ter_path: Path):
  ter_name = str(ter_path).replace('\\', '/')
  for rec in ctx.terrain_meta or []:
    df = (rec or {}).get('datafile')
    if not df:
      continue
    cand = df.replace('\\', '/')
    if cand.endswith(os.path.basename(ter_name)) or cand == ter_name:
      return rec
  return None

def import_terrain_block(ctx, simobj):
  """
  Build TerrainBlock mesh from .ter file and place it.
  simobj: one record from mission data (class == 'TerrainBlock')
  """
  level_root = ctx.config.level_path
  tfile = simobj.get('terrainFile')
  square_size = float(simobj.get('squareSize') or 1.0)
  max_height_m = float(simobj.get('maxHeight') or 2048.0)
  step = 1
  skip_holes = True

  ter_path = resolve_ter_path(level_root, tfile)
  if not ter_path or not ter_path.exists():
    print(f"WARN: Terrain .ter not found: {tfile}")
    return None

  data = read_ter_any(ter_path)
  size = data['size']
  heights = data['heights']
  layer = data['layer']

  meta = find_terrain_meta_for_ter(ctx, ter_path)
  mat_names = list((meta or {}).get('materials') or data.get('material_names') or [])

  height_scale = max_height_m / 65536.0
  name = os.path.splitext(os.path.basename(str(ter_path)))[0]
  obj = build_terrain_object(
    name=name,
    size=size,
    heights=heights,
    layer=layer,
    square_size=square_size,
    height_scale=height_scale,
    step=step,
    skip_holes=skip_holes,
    material_names=mat_names
  )

  from ..objects.common import make_matrix
  pos = simobj.get('position') or [0, 0, 0]
  rot = simobj.get('rotationMatrix') or None

  import mathutils
  rot_euler = mathutils.Euler((0.0, 0.0, 0.0))
  if rot and len(rot) == 9:
    rot_euler = mathutils.Matrix([[rot[0], rot[1], rot[2]],
                    [rot[3], rot[4], rot[5]],
                    [rot[6], rot[7], rot[8]]]).transposed().to_euler()

  obj.matrix_world = make_matrix(pos, rot_euler, (1, 1, 1))

  try:
    for p in obj.data.polygons:
      p.use_smooth = True
  except Exception:
    pass

  return obj
