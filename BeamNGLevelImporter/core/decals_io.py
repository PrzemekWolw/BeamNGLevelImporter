# ##### BEGIN LICENSE BLOCK #####
#
# This program is licensed under The MIT License:
# see LICENSE for the full license text
#
# ##### END LICENSE BLOCK #####

import json
import struct

def read_decals_json(path):
  with open(path, 'r', encoding='utf-8', errors='ignore') as f:
    try:
      doc = json.load(f)
    except Exception:
      return {}
  if not isinstance(doc, dict) or 'instances' not in doc:
    return {}
  return {'instances': doc.get('instances', {})}

def read_decals_tddf(path):
  with open(path, 'rb') as f:
    sig = f.read(4)
    if sig != b'TDDF':
      return {}
    ver = struct.unpack('<B', f.read(1))[0]
    # names
    count = struct.unpack('<I', f.read(4))[0]
    names = []
    for _ in range(count):
      ln = struct.unpack('<I', f.read(4))[0]
      names.append(f.read(ln).decode('utf-8', 'ignore'))
    # instances
    count = struct.unpack('<I', f.read(4))[0]
    out_map = {}
    for _ in range(count):
      dataIndex = struct.unpack('<B', f.read(1))[0]
      px, py, pz = struct.unpack('<fff', f.read(12))
      nx, ny, nz = struct.unpack('<fff', f.read(12))
      tx, ty, tz = struct.unpack('<fff', f.read(12))
      rectIdx = struct.unpack('<i', f.read(4))[0]
      size = struct.unpack('<f', f.read(4))[0]
      prio = struct.unpack('<B', f.read(1))[0]
      name = names[dataIndex] if 0 <= dataIndex < len(names) else 'Decal'
      arr = [rectIdx, size, prio, px,py,pz, nx,ny,nz, tx,ty,tz]
      out_map.setdefault(name, []).append(arr)
    return {'instances': out_map}
