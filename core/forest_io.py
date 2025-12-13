# ##### BEGIN LICENSE BLOCK #####
#
# This program is licensed under The MIT License:
# see LICENSE for the full license text
#
# ##### END LICENSE BLOCK #####

import json
import struct

def parse_forest4_lines(path):
  out = []
  with open(path, 'r', encoding='utf-8', errors='ignore') as f:
    for line in f:
      line = line.strip()
      if not line: continue
      try:
        v = json.loads(line)
      except Exception:
        continue
      if not isinstance(v, dict): continue
      if 'type' not in v: continue
      # normalize
      o = dict(v)
      # ensure pos, rotationMatrix/rotd/quat, scale
      if 'scale' not in o: o['scale'] = 1.0
      out.append(o)
  return out

def parse_forest_v23(path):
  with open(path, 'r', encoding='utf-8', errors='ignore') as f:
    doc = json.load(f)
  out = []
  header = doc.get('header', {})
  fmt = header.get('format') or doc.get('format')
  if fmt == 'JSON Forest Data v2':
    inst = doc.get('instances', {})
    # inst: { typeName: [ [posx, posy, posz, rotx, roty, rotz, rotw, scale], ... ] }
    for t, arr in inst.items():
      for row in arr:
        if not isinstance(row, list) or len(row) != 8:
          continue
        pos = [float(row[0]), float(row[1]), float(row[2])]
        quat = [float(row[3]), float(row[4]), float(row[5]), float(row[6])]
        scale = float(row[7])
        out.append({'type': t, 'pos': pos, 'quat': quat, 'scale': scale})
    return out
  if fmt == 'JSON Forest Data v3':
    data = doc.get('data', [])
    # each: [type, px,py,pz, rot3x3 (9 floats), scale]
    for row in data:
      if not isinstance(row, list) or len(row) != 14 or not isinstance(row[0], str):
        continue
      t = row[0]
      pos = [float(row[1]), float(row[2]), float(row[3])]
      rotm = [float(x) for x in row[4:13]]
      scale = float(row[13])
      out.append({'type': t, 'pos': pos, 'rotationMatrix': rotm, 'scale': scale})
    return out
  # unknown format -> return empty so caller can fallback
  return []

def read_fkdf(path):
  # FKDF binary format
  with open(path, 'rb') as f:
    sig = f.read(4)
    if sig != b'FKDF':
      return []
    ver = f.read(1)
    if not ver:
      return []
    version = ver[0]
    # datablocks
    count = struct.unpack('<I', f.read(4))[0]
    names = []
    for _ in range(count):
      ln = struct.unpack('<I', f.read(4))[0]
      names.append(f.read(ln).decode('utf-8', 'ignore'))
    # items
    out = []
    count = struct.unpack('<I', f.read(4))[0]
    for _ in range(count):
      idx = struct.unpack('<B', f.read(1))[0]
      px, py, pz = struct.unpack('<fff', f.read(12))
      rx, ry, rz, rw = struct.unpack('<ffff', f.read(16))
      scale = struct.unpack('<f', f.read(4))[0]
      t = names[idx] if 0 <= idx < len(names) else 'ForestItem'
      out.append({'type': t, 'pos': [px,py,pz], 'quat': [rx,ry,rz,rw], 'scale': scale})
    return out