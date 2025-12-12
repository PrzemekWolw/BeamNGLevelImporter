# ##### BEGIN LICENSE BLOCK #####
#
# This program is licensed under The MIT License:
# see LICENSE for the full license text
#
# ##### END LICENSE BLOCK #####

import bpy

def get_first_bound_material_name(inst, doc_root):
  tc = inst.find('.//{*}bind_material/{*}technique_common')
  if tc is None:
    return None
  for im in tc.findall('{*}instance_material'):
    target = im.get('target') or ''
    if target.startswith('#'):
      target = target[1:]
    for mm in doc_root.findall('.//{*}material'):
      if mm.get('id') == target:
        return mm.get('name') or mm.get('id') or target
    if target:
      return target
  return None

def build_instance_material_bindings(inst, doc_root):
  table = {}
  tc = inst.find('.//{*}bind_material/{*}technique_common')
  if tc is None:
    return table
  for im in tc.findall('{*}instance_material'):
    sym = im.get('symbol') or ''
    target = im.get('target') or ''
    if target.startswith('#'):
      target = target[1:]
    name = None
    for mm in doc_root.findall('.//{*}material'):
      if mm.get('id') == target:
        name = mm.get('name') or mm.get('id') or target
        break
    if name is None and target:
      name = target
    if sym and name:
      table[sym] = name
  return table

def ensure_empty_material(name):
  if not name:
    return None
  m = bpy.data.materials.get(name)
  if m is None:
    m = bpy.data.materials.new(name=name)
    m.use_nodes = False
  return m

def ensure_material_slot(me, mat):
  for i, m in enumerate(me.materials):
    if m == mat:
      return i
  me.materials.append(mat)
  return len(me.materials) - 1
