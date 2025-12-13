# ##### BEGIN LICENSE BLOCK #####
#
# This program is licensed under The MIT License:
# see LICENSE for the full license text
#
# ##### END LICENSE BLOCK #####

from __future__ import annotations
import os
from pathlib import Path
from .sjson import read_json_records, decode_sjson_file
from . import ts_parser
from .forest_io import parse_forest4_lines, parse_forest_v23, read_fkdf
from .decals_io import read_decals_json, read_decals_tddf

def load_main_records(level_path: Path) -> list[dict]:
  out = []
  main_dir = (level_path / 'main').resolve()
  found_json = []
  if main_dir.exists():
    for subdir, dirs, files in os.walk(main_dir):
      for file in files:
        if file.endswith('.json'):
          found_json.append(Path(subdir) / file)
  if found_json:
    for p in found_json:
      try:
        out.extend(read_json_records(p))
      except Exception:
        pass
    if out:
      return out
  ts_objs = []
  if main_dir.exists():
    for subdir, dirs, files in os.walk(main_dir):
      for file in files:
        if file.endswith('.mis') or file.endswith('.cs'):
          fp = Path(subdir) / file
          try:
            txt = fp.read_text(encoding='utf-8', errors='ignore')
            ts_objs.extend(ts_parser.parse_torque_file(txt))
          except Exception:
            pass
  if not ts_objs:
    for file in level_path.iterdir():
      if file.is_file() and file.suffix.lower() in ('.mis', '.cs'):
        try:
          txt = file.read_text(encoding='utf-8', errors='ignore')
          ts_objs.extend(ts_parser.parse_torque_file(txt))
        except Exception:
          pass
  for o in ts_objs:
    if isinstance(o, dict) and o.get('class'):
      out.append(o)
  return out

def _gather_forest_files(base: Path):
  f4, v23, fkdf = [], [], []
  for subdir, dirs, files in os.walk(base):
    for fn in files:
      p = Path(subdir) / fn
      if fn.endswith('.forest4.json'):
        f4.append(p)
      elif fn.endswith('.forest.json'):
        v23.append(p)
      elif fn.endswith('.forest'):
        fkdf.append(p)
  return f4, v23, fkdf

def load_forest_records(level_path: Path) -> list[dict]:
  out = []
  forest_dir = (level_path / 'forest').resolve()
  f4_files, v23_files, fkdf_files = [], [], []
  if forest_dir.exists():
    f4_files, v23_files, fkdf_files = _gather_forest_files(forest_dir)
  if not (f4_files or v23_files or fkdf_files):
    f4_root, v23_root, fkdf_root = _gather_forest_files(level_path)
    f4_files, v23_files, fkdf_files = f4_root, v23_root, fkdf_root
  if f4_files:
    for fp in f4_files:
      try:
        out.extend(parse_forest4_lines(fp))
      except Exception:
        pass
    return out
  if v23_files:
    for fp in v23_files:
      try:
        out.extend(parse_forest_v23(fp))
      except Exception:
        pass
    if out:
      return out
  if fkdf_files:
    for fp in fkdf_files:
      try:
        out.extend(read_fkdf(fp))
      except Exception:
        pass
  return out

def load_decal_sets(level_path: Path) -> tuple[dict, dict]:
  decals_defs = {}
  decal_instances = {}
  managed = (level_path / 'art' / 'decals').resolve()
  if managed.exists():
    for file in managed.glob('*managedDecalData.json'):
      try:
        data = decode_sjson_file(file)
        if isinstance(data, dict):
          for k, v in data.items():
            if isinstance(v, dict) and v.get('class') == 'DecalData':
              decals_defs[k] = v
      except Exception:
        pass
  dec_json = list(level_path.glob('*.decals.json'))
  if dec_json:
    for fp in dec_json:
      try:
        dj = read_decals_json(fp)
        inst = dj.get('instances', {})
        for k, v in inst.items():
          if isinstance(v, list):
            decal_instances.setdefault(k, []).extend(v)
      except Exception:
        pass
    return decals_defs, decal_instances
  dec_bin = list(level_path.glob('*.decals'))
  for fp in dec_bin:
    try:
      dj = read_decals_tddf(fp)
      inst = dj.get('instances', {})
      for k, v in inst.items():
        if isinstance(v, list):
          decal_instances.setdefault(k, []).extend(v)
    except Exception:
      pass
  return decals_defs, decal_instances

def load_terrain_meta(level_path: Path) -> list[dict]:
  out = []
  for file in level_path.glob('*.terrain.json'):
    try:
      out.extend(read_json_records(file))
    except Exception:
      pass
  return out

def scan_material_json_packs(level_path: Path) -> list[dict]:
  packs = []
  for subdir, dirs, files in os.walk(level_path):
    for file in files:
      if file.endswith('materials.json'):
        try:
          packs.append(decode_sjson_file(Path(subdir) / file))
        except Exception:
          pass
  return packs

def scan_material_cs_packs(level_path: Path) -> list[dict]:
  packs = []
  for subdir, dirs, files in os.walk(level_path):
    for file in files:
      if file.endswith('.materials.cs'):
        fp = Path(subdir) / file
        try:
          txt = fp.read_text(encoding='utf-8', errors='ignore')
          objs = ts_parser.parse_torque_file(txt)
        except Exception:
          continue
        pack = {}
        for o in objs:
          if not isinstance(o, dict): continue
          cls = o.get('class')
          if cls not in ('Material', 'TerrainMaterial', 'CustomMaterial'):
            continue
          key = o.get('name') or o.get('internalName') or o.get('mapTo') or f"{cls}"
          if cls == 'TerrainMaterial':
            e = {'class': 'TerrainMaterial'}
            for k in ('internalName', 'name'):
              if k in o: e[k] = o[k]
            for k_src, k_dst in (
              ('baseTex', 'baseColorBaseTex'),
              ('detailMap', 'baseColorDetailTex'),
              ('macroMap', 'baseColorMacroTex'),
              ('normalMap', 'normalBaseTex'),
              ('roughnessMap', 'roughnessBaseTex'),
              ('aoMap', 'aoBaseTex'),
              ('heightBaseTex', 'heightBaseTex'),
            ):
              if k_src in o and isinstance(o[k_src], str): e[k_dst] = o[k_src]
            pack[key] = e
          else:
            e = {'class': 'Material', 'version': 1.5}
            if 'mapTo' in o: e['mapTo'] = o['mapTo']
            stage = {}
            for k_src, k_dst in (
              ('diffuseMap', 'baseColorMap'),
              ('colorMap', 'baseColorMap'),
              ('baseTex', 'baseColorMap'),
              ('normalMap', 'normalMap'),
              ('roughnessMap', 'roughnessMap'),
              ('metallicMap', 'metallicMap'),
              ('aoMap', 'ambientOcclusionMap'),
              ('opacityMap', 'opacityMap'),
              ('emissiveMap', 'emissiveMap'),
              ('detailMap', 'baseColorDetailMap'),
              ('normalDetailMap', 'normalDetailMap'),
            ):
              if k_src in o and isinstance(o[k_src], str):
                stage[k_dst] = o[k_src]
            if 'diffuseColor' in o and isinstance(o['diffuseColor'], list) and len(o['diffuseColor']) >= 3:
              c = o['diffuseColor']
              stage['baseColorFactor'] = [float(c[0]), float(c[1]), float(c[2]), float(c[3]) if len(c) >= 4 else 1.0]
            for k_src, k_dst in (('metallic','metallicFactor'), ('roughness','roughnessFactor'), ('opacity','opacityFactor')):
              if k_src in o:
                try: stage[k_dst] = float(o[k_src])
                except Exception: pass
            e['Stages'] = [stage]
            if 'alphaTest' in o: e['alphaTest'] = bool(o['alphaTest'])
            if 'alphaRef'  in o:
              try: e['alphaRef'] = int(o['alphaRef'])
              except Exception: pass
            if 'doubleSided' in o: e['doubleSided'] = bool(o['doubleSided'])
            pack[key] = e
        if pack:
          packs.append(pack)
  return packs

def load_forest_item_db(level_path: Path) -> dict:
  result = {}
  managed_dir = (level_path / 'art' / 'forest').resolve()
  if not managed_dir.exists():
    return result
  for file in managed_dir.glob('*.json'):
    try:
      data = decode_sjson_file(file)
      if isinstance(data, dict) and data:
        return data
    except Exception:
      pass
  cs_files = list(managed_dir.glob('*.cs'))
  for fp in cs_files:
    try:
      txt = fp.read_text(encoding='utf-8', errors='ignore')
      objs = ts_parser.parse_torque_file(txt)
    except Exception:
      continue
    for o in objs:
      if not isinstance(o, dict): continue
      cls = (o.get('class') or '').lower()
      if cls not in ('tsforestitemdata','forestitemdata'):
        continue
      internal = o.get('internalName') or o.get('name')
      shape = o.get('shapeFile')
      if not internal or not shape:
        continue
      entry = result.setdefault(internal, {})
      entry['internalName'] = internal
      entry['shapeFile'] = shape
      for k in ('rigidity','tightnessCoefficient','dampingCoefficient','mass','windScale','trunkBendScale','branchAmp','detailAmp','detailFreq'):
        if k in o:
          try: entry[k] = float(o[k])
          except Exception: pass
  return result
