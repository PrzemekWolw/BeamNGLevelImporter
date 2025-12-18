# ##### BEGIN LICENSE BLOCK #####
#
# This program is licensed under The MIT License:
# see LICENSE for the full license text
#
# ##### END LICENSE BLOCK #####

from __future__ import annotations
import os
import json
import zipfile
from pathlib import Path
from .sjson import read_json_records, decode_sjson_file, decode_sjson_text
from . import ts_parser
from .forest_io import parse_forest4_lines, parse_forest_v23, read_fkdf
from .decals_io import read_decals_json, read_decals_tddf
from .paths import resolve_any_beamng_path

def _read_link_target(p: Path) -> str | None:
  """Read a JSON .link file and return the 'path' string or None."""
  try:
    with open(p, 'r', encoding='utf-8', errors='ignore') as f:
      obj = json.load(f)
    if isinstance(obj, dict):
      t = obj.get('path')
      if isinstance(t, str) and t.strip():
        return t.strip()
  except Exception:
    pass
  return None

def _maybe_deref_link(p: Path, level_root: Path) -> Path:
  """
  If p ends with .link, read the target and resolve via global index (can be in a zip),
  then return the local cached file path. Otherwise return p.
  """
  if not p or not isinstance(p, Path):
    return p
  if p.suffix.lower() != '.link':
    return p
  tgt = _read_link_target(p)
  if not tgt:
    return p
  real = resolve_any_beamng_path(tgt, level_root)
  return real if real else p

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
  """
  Link-aware: accepts *.json.link and *.decals.link pointing outside the level.
  """
  decals_defs = {}
  decal_instances = {}

  managed = (level_path / 'art' / 'decals').resolve()
  if managed.exists():
    for file in managed.glob('*managedDecalData.json*'):
      fp = file
      if fp.suffix.lower() == '.link':
        fp = _maybe_deref_link(fp, level_path)
      if not fp or not fp.exists():
        continue
      try:
        data = decode_sjson_file(fp)
        if isinstance(data, dict):
          for k, v in data.items():
            if isinstance(v, dict) and v.get('class') == 'DecalData':
              decals_defs[k] = v
      except Exception:
        pass

  dec_json = list(level_path.glob('*.decals.json')) + list(level_path.glob('*.decals.json.link'))
  if dec_json:
    for fp in dec_json:
      if fp.suffix.lower() == '.link':
        fp = _maybe_deref_link(fp, level_path)
      if not fp or not fp.exists():
        continue
      try:
        dj = read_decals_json(fp)
        inst = dj.get('instances', {})
        for k, v in inst.items():
          if isinstance(v, list):
            decal_instances.setdefault(k, []).extend(v)
      except Exception:
        pass
    return decals_defs, decal_instances

  dec_bin = list(level_path.glob('*.decals')) + list(level_path.glob('*.decals.link'))
  for fp in dec_bin:
    if fp.suffix.lower() == '.link':
      fp = _maybe_deref_link(fp, level_path)
    if not fp or not fp.exists():
      continue
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

def scan_material_json_packs(level_path: Path) -> list[tuple[dict, Path]]:
  """
  Link-aware: .json and .json.link
  Returns list of (pack_dict, source_dir).
  """
  packs: list[tuple[dict, Path]] = []
  for subdir, dirs, files in os.walk(level_path):
    subpath = Path(subdir)
    for file in files:
      if not file.endswith('materials.json') and not file.endswith('materials.json.link'):
        continue
      fp = subpath / file
      if fp.suffix.lower() == '.link':
        fp = _maybe_deref_link(fp, level_path)
      if not fp or not fp.exists():
        continue
      try:
        pack = decode_sjson_file(fp)
        if isinstance(pack, dict):
          packs.append((pack, fp.parent))
      except Exception:
        pass
  return packs

def scan_material_cs_packs(level_path: Path) -> list[tuple[dict, Path]]:
  """
  Link-aware: .materials.cs and .materials.cs.link
  Returns list of (pack_dict, source_dir).
  """
  packs: list[tuple[dict, Path]] = []
  for subdir, dirs, files in os.walk(level_path):
    subpath = Path(subdir)
    for file in files:
      if not file.endswith('.materials.cs') and not file.endswith('.materials.cs.link'):
        continue
      fp = subpath / file
      if fp.suffix.lower() == '.link':
        fp = _maybe_deref_link(fp, level_path)
      if not fp or not fp.exists():
        continue
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
        packs.append((pack, fp.parent))
  return packs

def scan_material_packs_in_zip(zip_path: Path) -> list[tuple[dict, Path]]:
  """
  Scan a zip for all materials.json and .materials.cs, return list of (pack dict, pseudo_dir).
  pseudo_dir is a Path representing the directory inside the zip (not necessarily real FS dir).
  """
  packs: list[tuple[dict, Path]] = []
  try:
    with zipfile.ZipFile(zip_path, "r") as zf:
      names = zf.namelist()
      # JSON packs
      for name in names:
        nl = name.replace("\\", "/")
        ln = nl.lower()
        if not ln.endswith("materials.json"):
          continue
        try:
          with zf.open(name, "r") as fp:
            text = fp.read().decode("utf-8", errors="ignore")
          pack = decode_sjson_text(text)
          if isinstance(pack, dict):
            packs.append((pack, Path(nl).parent))
        except Exception:
          pass
      # CS packs
      for name in names:
        nl = name.replace("\\", "/")
        ln = nl.lower()
        if not ln.endswith(".materials.cs"):
          continue
        try:
          with zf.open(name, "r") as fp:
            text = fp.read().decode("utf-8", errors="ignore")
          objs = ts_parser.parse_torque_file(text)
        except Exception:
          continue
        pack = {}
        # ... existing conversion logic ...
        if pack:
          packs.append((pack, Path(nl).parent))
  except Exception:
    pass
  return packs

def load_forest_item_db(level_path: Path) -> dict:
  """
  Link-aware: *.json[.link] and *.cs[.link] in art/forest
  """
  result = {}
  managed_dir = (level_path / 'art' / 'forest').resolve()
  if not managed_dir.exists():
    return result
  for file in managed_dir.glob('*.json*'):
    fp = file
    if fp.suffix.lower() == '.link':
      fp = _maybe_deref_link(fp, level_path)
    if not fp or not fp.exists() or fp.suffix.lower() != '.json':
      continue
    try:
      data = decode_sjson_file(fp)
      if isinstance(data, dict) and data:
        return data
    except Exception:
      pass
  for file in managed_dir.glob('*.cs*'):
    fp = file
    if fp.suffix.lower() == '.link':
      fp = _maybe_deref_link(fp, level_path)
    if not fp or not fp.exists() or fp.suffix.lower() != '.cs':
      continue
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
