# ##### BEGIN LICENSE BLOCK #####
#
# This program is licensed under The MIT License:
# see LICENSE for the full license text
#
# ##### END LICENSE BLOCK #####

import numpy as np
from . import collada_util as U
from .collada_reader import SourceReader

def build_mesh_index(mesh_el):
  idx = {}
  for el in mesh_el.iter():
    idv = el.get('id')
    if idv:
      idx[idv] = el
  return idx

def find_local_element_by_id(mesh_el, target_id):
  if not target_id:
    return None
  for el in mesh_el.iter():
    if el.get('id') == target_id and U.tag_name(el) in ('source','vertices'):
      return el
  return None

def resolve_input_source(mesh_el, input_el, want_semantic=None):
  if input_el is None:
    return None
  url = input_el.get('source') or ''
  if not url:
    return None
  if url.startswith('#'):
    url = url[1:]
  el = find_local_element_by_id(mesh_el, url)
  if el is None:
    return None
  t = U.tag_name(el)
  if t == 'source':
    return el
  if t == 'vertices':
    chosen = None
    for ip in el.findall('{*}input'):
      if want_semantic and (ip.get('semantic') or '').upper() == want_semantic:
        chosen = ip
        break
    if chosen is None:
      chosen = el.find('{*}input')
    if chosen is None:
      return None
    return resolve_input_source(mesh_el, chosen, want_semantic)
  return None

def classify_inputs(inputs):
  buckets = {'POSITION': None, 'NORMAL': None, 'COLOR': None, 'TEXCOORD_0': None, 'TEXCOORD_1': None}
  offsets = {}
  all_offsets = []
  for inp in inputs:
    off = int(inp.get('offset') or 0)
    all_offsets.append(off)
    sem = (inp.get('semantic') or '').upper()
    if sem == 'VERTEX':
      buckets['POSITION'] = inp
      offsets['POSITION'] = off
    elif sem == 'POSITION':
      buckets['POSITION'] = inp
      offsets['POSITION'] = off
    elif sem == 'NORMAL':
      buckets['NORMAL'] = inp
      offsets['NORMAL'] = off
    elif sem == 'COLOR':
      buckets['COLOR'] = inp
      offsets['COLOR'] = off
    elif sem == 'TEXCOORD':
      set_idx = int(inp.get('set') or 0)
      key = 'TEXCOORD_0' if set_idx == 0 and buckets['TEXCOORD_0'] is None else 'TEXCOORD_1'
      buckets[key] = inp
      offsets[key] = off
  max_offset = max(all_offsets) if all_offsets else 0
  return buckets, offsets, max_offset

def read_source_reader_from_input(mesh_el, inp, desired, want_sem):
  src = resolve_input_source(mesh_el, inp, want_sem)
  if src is None:
    return None
  src_id = src.get('id') or id(src)
  for params in desired:
    key = (src_id, tuple(params))
    sr = U._INPUT_SR_CACHE.get(key)
    if sr is None:
      sr_try = SourceReader(src, params)
      if sr_try.size() > 0:
        U._INPUT_SR_CACHE[key] = sr_try
        sr = sr_try
    if sr is not None:
      return sr
  return None

def _triangles_stride_autofix_from_count(prim, a_size, stride):
  try:
    cnt = int(prim.get('count') or 0)
  except Exception:
    cnt = 0
  if cnt > 0:
    den = cnt * 3
    if den > 0 and a_size % den == 0:
      s2 = a_size // den
      if s2 != stride:
        return s2
  return stride

def _polylist_stride_autofix_from_vcount(prim, p_size, stride):
  vc = prim.find('{*}vcount')
  if vc is None:
    return stride
  counts = U.parse_ints_np(vc.text, dtype=np.int64)
  totv = int(counts.sum()) if counts.size else 0
  if totv > 0 and p_size % totv == 0:
    s2 = p_size // totv
    if s2 != stride:
      return s2
  return stride

def triangles_from_primitive_np(prim, stride):
  tname = U.tag_name(prim)
  if tname == 'triangles':
    parr = prim.find('{*}p')
    a = U.parse_ints_np(parr.text, dtype=np.int64)
    stride = _triangles_stride_autofix_from_count(prim, a.size, stride)
    if a.size % stride != 0:
      return np.empty((0, stride), dtype=np.int64)
    return a.reshape((-1, stride))
  elif tname in ('tristrips', 'trifans', 'polylist', 'polygons'):
    out = []
    if tname == 'tristrips':
      for P in prim.findall('{*}p'):
        d = U.parse_ints_np(P.text, dtype=np.int64).tolist()
        if stride <= 0: continue
        n = len(d) // stride
        for i in range(n - 2):
          i0 = i * stride
          if i & 1:
            out.extend(d[i0:i0+stride])
            out.extend(d[(i0 + 2*stride):(i0 + 3*stride)])
            out.extend(d[(i0 + stride):(i0 + 2*stride)])
          else:
            out.extend(d[i0:i0+stride])
            out.extend(d[(i0 + stride):(i0 + 2*stride)])
            out.extend(d[(i0 + 2*stride):(i0 + 3*stride)])
    elif tname == 'trifans':
      for P in prim.findall('{*}p'):
        d = U.parse_ints_np(P.text, dtype=np.int64).tolist()
        if stride <= 0: continue
        n = len(d) // stride
        for i in range(1, n - 1):
          out.extend(d[0:stride])
          out.extend(d[(i*stride):((i+1)*stride)])
          out.extend(d[((i+1)*stride):((i+2)*stride)])
    elif tname == 'polylist':
      p = prim.find('{*}p'); vc = prim.find('{*}vcount')
      if p is None or vc is None:
        return np.empty((0, stride), dtype=np.int64)
      d = U.parse_ints_np(p.text, dtype=np.int64).tolist()
      stride = _polylist_stride_autofix_from_vcount(prim, len(d), stride)
      counts = U.parse_ints_np(vc.text, dtype=np.int64)
      base = 0
      for c in counts:
        c = int(c)
        first_flat = base * stride
        for i in range(1, c - 1):
          out.extend(d[first_flat:first_flat+stride])
          out.extend(d[(base + i)*stride:(base + i + 1)*stride])
          out.extend(d[(base + i + 1)*stride:(base + i + 2)*stride])
        base += c
    elif tname == 'polygons':
      for P in prim.findall('{*}p'):
        d = U.parse_ints_np(P.text, dtype=np.int64).tolist()
        if stride <= 0: continue
        n = len(d) // stride
        for i in range(1, n - 1):
          out.extend(d[0:stride])
          out.extend(d[(i*stride):((i+1)*stride)])
          out.extend(d[((i+1)*stride):((i+2)*stride)])
    if not out:
      return np.empty((0, stride), dtype=np.int64)
    a = np.array(out, dtype=np.int64, copy=False)
    a = a.reshape((-1, stride))
    return a
  return np.empty((0, stride), dtype=np.int64)
