# ##### BEGIN LICENSE BLOCK #####
#
# This program is licensed under The MIT License:
# see LICENSE for the full license text
#
# ##### END LICENSE BLOCK #####

from __future__ import annotations
import re

_NUM_RE = re.compile(r'[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?')

_NUMERIC_KEYS_FLOAT = {
  'maxHeight','squareSize','decalBias','renderPriority','smoothness','detail',
  'textureLength','breakAngle','SubdivideLength','subdivideLength',
  'elevation','azimuth','brightness','alphaRef','alphaTestValue',
  'metallic','roughness','opacity','metallicFactor','roughnessFactor','opacityFactor',
  'normalMapStrength','detailBaseColorMapStrength','detailNormalMapStrength',
  'macroStrength','macroDistance','overallRippleMagnitude','specularPower','reflectivity','clarity',
}
_NUMERIC_KEYS_INT = {'widthSubdivisions','frame','texRows','texCols','seed','maxElements'}

def _extract_floats_from_str(s: str):
  return [float(t) for t in _NUM_RE.findall(s)] if isinstance(s, str) else []

def to_float_list(val, expect: int | None = None):
  out = []
  if isinstance(val, str):
    out = _extract_floats_from_str(val)
  elif isinstance(val, (list, tuple)):
    for it in val:
      if isinstance(it, (int, float)):
        out.append(float(it))
      elif isinstance(it, str):
        out.extend(_extract_floats_from_str(it))
      elif isinstance(it, (list, tuple)):
        sub = to_float_list(it)
        if sub: out.extend(sub)
  elif isinstance(val, (int, float)):
    out = [float(val)]
  if expect is not None:
    if len(out) < expect:
      return None
    if len(out) > expect:
      out = out[:expect]
  return out if out else None

def coerce_array(rec: dict, key: str, min_len: int, default_fill: float = 0.0):
  if key not in rec:
    return
  arr = to_float_list(rec[key])
  if not arr:
    rec[key] = [default_fill] * min_len
    return
  if len(arr) < min_len:
    arr = arr + [default_fill] * (min_len - len(arr))
  rec[key] = [float(x) for x in arr[:min_len]]

def coerce_vec3(rec: dict, key: str, default: list[float]):
  v = rec.get(key)
  if v is None:
    return
  if isinstance(v, (int, float)) and key == 'scale':
    rec[key] = [float(v), float(v), float(v)]
    return
  out = to_float_list(v)
  if not out:
    rec[key] = default[:]
    return
  if len(out) < 3:
    out = (out + default)[:3]
  rec[key] = [float(out[0]), float(out[1]), float(out[2])]

def coerce_rot9(rec: dict, key: str = 'rotationMatrix'):
  v = rec.get(key)
  if v is None:
    return
  out = to_float_list(v)
  if not out or len(out) < 9:
    rec[key] = [1.0,0.0,0.0, 0.0,1.0,0.0, 0.0,0.0,1.0]
  else:
    rec[key] = [float(x) for x in out[:9]]

def coerce_number(rec: dict, key: str, to_int: bool = False):
  if key not in rec:
    return
  v = rec[key]
  if isinstance(v, (int, float)):
    return
  if isinstance(v, str):
    if not re.search(r'\d', v):
      return
    try:
      rec[key] = int(float(v)) if to_int else float(v)
    except Exception:
      pass

def norm_nodes_generic(nodes):
  if not isinstance(nodes, list):
    return None
  out = []
  for n in nodes:
    if isinstance(n, str):
      nums = to_float_list(n)
      if nums: out.append(nums)
    elif isinstance(n, (list, tuple)):
      nums = to_float_list(n)
      if nums: out.append(nums)
    elif isinstance(n, dict):
      m = dict(n)
      for k in ('point','position','pos'):
        if k in m:
          vv = to_float_list(m[k], 3)
          if vv: m[k] = [float(vv[0]), float(vv[1]), float(vv[2])]
          else: del m[k]
      for k in ('width','depth','texLength','SubdivideLength','subdivideLength'):
        if k in m and isinstance(m[k], str) and re.search(r'\d', m[k]):
          try: m[k] = float(m[k])
          except Exception: pass
      out.append(m)
  return out

def sanitize_scalars(rec: dict):
  for k in _NUMERIC_KEYS_FLOAT:
    coerce_number(rec, k, to_int=False)
  for k in _NUMERIC_KEYS_INT:
    coerce_number(rec, k, to_int=True)

def normalize_record(rec: dict):
  coerce_vec3(rec, 'position', [0.0, 0.0, 0.0])
  coerce_vec3(rec, 'scale',    [1.0, 1.0, 1.0])
  coerce_rot9(rec, 'rotationMatrix')
  coerce_array(rec, 'color', 3, 1.0)
  coerce_array(rec, 'shadowDarkenColor', 3, 0.0)
  coerce_array(rec, 'attenuationRatio', 3, 1.0)
  coerce_array(rec, 'overDarkFactor', 4, 0.0)
  coerce_array(rec, 'rotation', 4, 0.0)
  sanitize_scalars(rec)
  if 'nodes' in rec:
    nn = norm_nodes_generic(rec.get('nodes'))
    if nn is not None:
      rec['nodes'] = nn

def normalize_records(recs: list[dict]):
  if not isinstance(recs, list):
    return
  for r in recs:
    if isinstance(r, dict):
      normalize_record(r)

def normalize_forest(forest_list: list[dict]):
  if not isinstance(forest_list, list):
    return
  for it in forest_list:
    if not isinstance(it, dict):
      continue
    if 'pos' in it:
      vv = to_float_list(it['pos'])
      it['pos'] = [float((vv + [0,0,0])[i]) for i in range(3)] if vv else [0.0,0.0,0.0]
    if 'rotationMatrix' in it:
      rr = to_float_list(it['rotationMatrix'])
      it['rotationMatrix'] = [float(x) for x in (rr[:9] if rr and len(rr) >= 9 else [1,0,0,0,1,0,0,0,1])]
    if 'scale' in it and isinstance(it['scale'], str) and re.search(r'\d', it['scale']):
      try: it['scale'] = float(it['scale'])
      except Exception: it['scale'] = 1.0

def resolve_texture_relative(tex: str, *, mat_dir: Path | None, level_dir: Path | None) -> str:
  """
  If 'tex' is just a filename (no '/' or '\\'), try to resolve it relative to
  the material file directory (mat_dir). If that fails, return original string.
  This returns a virtual / BeamNG-style path string (using '/') that
  try_resolve_image_path/resolve_any_beamng_path can understand.
  """
  if not tex or "/" in tex or "\\" in tex:
    return tex
  if not mat_dir:
    return tex
  # Try common relative locations from the material file
  # e.g. <mat_dir>/textures/<name>, <mat_dir>/<name>
  candidates = [
    mat_dir / "textures" / tex,
    mat_dir / tex,
  ]
  from .paths import exists_insensitive, get_real_case_path  # circular-safe import
  for c in candidates:
    if exists_insensitive(c):
      c2 = get_real_case_path(c)
      # Convert absolute filesystem path back to a virtual-style path, relative to level_dir if possible
      try:
        if level_dir and c2.is_relative_to(level_dir):
          # e.g. /.../levels/mylevel/art/road/road_d.dds -> "levels/mylevel/art/road/road_d.dds"
          rel = c2.relative_to(level_dir.parent)
          return str(rel).replace("\\", "/")
      except Exception:
        pass
      return str(c2).replace("\\", "/")
  return tex
