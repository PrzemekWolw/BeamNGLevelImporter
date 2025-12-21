# ##### BEGIN LICENSE BLOCK #####
#
# This program is licensed under The MIT License:
# see LICENSE for the full license text
#
# ##### END LICENSE BLOCK #####
import bpy
from mathutils import Vector
try:
  import numpy as np
  _HAVE_NP = True
except Exception:
  _HAVE_NP = False
from ..utils.bpy_helpers import ensure_collection

# Internal state
_warned_no_density_prop = False

def _get_first_terrain_object():
  # Single pass over objects where possible to avoid repeated scans
  terrain = None
  fallback_uv = None
  fallback_mat = None
  for obj in bpy.data.objects:
    if obj.type != 'MESH':
      continue
    if obj.get("_beamng_is_terrain"):
      return obj
    if not fallback_uv and obj.data and obj.data.uv_layers.get("UV_TERRAIN01"):
      fallback_uv = obj
    if not fallback_mat and obj.data and len(obj.data.materials) > 0:
      fallback_mat = obj
  return fallback_uv or fallback_mat

def _ensure_visible_obj(obj: bpy.types.Object):
  obj.hide_set(False)
  obj.hide_viewport = False
  obj.hide_render = False
  try:
    if hasattr(obj, "display_type"):
      obj.display_type = 'SOLID'
  except Exception:
    pass
  if obj.name not in bpy.context.scene.objects:
    bpy.context.scene.collection.objects.link(obj)

def _object_from_shape_filename(shape_name):
  if not shape_name:
    return None
  base = shape_name.replace("\\","/").split("/")[-1]
  base_noext = base.rsplit(".",1)[0]
  obj = bpy.data.objects.get(base_noext)
  if obj and obj.type == 'MESH':
    _ensure_visible_obj(obj)
    return obj
  for cand in bpy.data.objects:
    if cand.type != 'MESH':
      continue
    nm = cand.name
    if nm == base_noext or nm.endswith(base_noext) or nm.startswith(base_noext):
      _ensure_visible_obj(cand)
      return cand
  return None

def _set_alpha_clip(mat: bpy.types.Material):
  if hasattr(mat, "blend_method"):
    mat.blend_method = 'CLIP'
  if hasattr(mat, "shadow_method"):
    try:
      mat.shadow_method = 'CLIP'
    except Exception:
      pass
  elif hasattr(mat, "shadow_mode"):
    try:
      mat.shadow_mode = 'CLIP'
    except Exception:
      pass
  try:
    if hasattr(mat, "use_backface_culling"):
      mat.use_backface_culling = False
  except Exception:
    pass

def _get_first_image_node(mat: bpy.types.Material):
  try:
    if not mat or not mat.use_nodes or not mat.node_tree:
      return None
    for n in mat.node_tree.nodes:
      if n.type == 'TEX_IMAGE':
        return n
  except Exception:
    pass
  return None

def _get_first_image_from_material(mat_name: str):
  try:
    base = bpy.data.materials.get(mat_name)
    img_node = _get_first_image_node(base) if base else None
    return img_node.image if img_node and getattr(img_node, "image", None) else None
  except Exception:
    return None

def _dup_or_make_material(base_name: str, new_name: str) -> bpy.types.Material:
  existing = bpy.data.materials.get(new_name)
  if existing:
    _set_alpha_clip(existing)
    return existing
  src = bpy.data.materials.get(base_name) if base_name else None
  if src:
    mat = src.copy(); mat.name = new_name
  else:
    mat = bpy.data.materials.new(new_name)
    mat.use_nodes = True
    nt = mat.node_tree
    for n in list(nt.nodes): nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
  _set_alpha_clip(mat)
  return mat

def _material_image_aspect(base_mat_name: str) -> float:
  try:
    if not base_mat_name:
      return 1.0
    mat = bpy.data.materials.get(base_mat_name)
    if not mat or not mat.use_nodes or not mat.node_tree:
      return 1.0
    for n in mat.node_tree.nodes:
      if n.type == 'TEX_IMAGE' and getattr(n, "image", None):
        img = n.image
        sz = getattr(img, "size", None)
        if sz and len(sz) >= 2 and sz[0] > 0 and sz[1] > 0:
          return float(sz[0]) / float(sz[1])
        w = int(getattr(img, "width", 0)); h = int(getattr(img, "height", 0))
        if w > 0 and h > 0:
          return float(w) / float(h)
        break
  except Exception:
    pass
  return 1.0

def _patch_material_uv_rect(mat: bpy.types.Material, rect, fallback_image=None):
  try:
    mat.use_nodes = True
    nt = mat.node_tree
    img_tex = _get_first_image_node(mat)
    principled = None
    out = None
    for n in nt.nodes:
      if n.type == 'BSDF_PRINCIPLED' and principled is None:
        principled = n
      if n.type == 'OUTPUT_MATERIAL' and out is None:
        out = n
    if not principled:
      principled = nt.nodes.new("ShaderNodeBsdfPrincipled")
      if not out:
        out = nt.nodes.new("ShaderNodeOutputMaterial")
      nt.links.new(principled.outputs["BSDF"], out.inputs["Surface"])
    if not img_tex:
      img_tex = nt.nodes.new("ShaderNodeTexImage")
      if fallback_image is not None:
        try: img_tex.image = fallback_image
        except Exception: pass
    texcoord = nt.nodes.new("ShaderNodeTexCoord")
    uv_out = texcoord.outputs.get("UV") or texcoord.outputs.get("Generated") or texcoord.outputs[0]
    x = float(rect[0]); y = float(rect[1]); w = float(rect[2]); h = float(rect[3])
    y_flipped = 1.0 - y - h
    mul = nt.nodes.new("ShaderNodeVectorMath"); mul.operation = 'MULTIPLY'
    mul.inputs[1].default_value = (w if w != 0 else 1.0, h if h != 0 else 1.0, 1.0)
    add = nt.nodes.new("ShaderNodeVectorMath"); add.operation = 'ADD'
    add.inputs[1].default_value = (x, y_flipped, 0.0)
    nt.links.new(uv_out, mul.inputs[0])
    nt.links.new(mul.outputs["Vector"], add.inputs[0])
    nt.links.new(add.outputs["Vector"], img_tex.inputs["Vector"])
    try:
      if not img_tex.outputs["Color"].is_linked:
        nt.links.new(img_tex.outputs["Color"], principled.inputs["Base Color"])
      if not img_tex.outputs["Alpha"].is_linked:
        nt.links.new(img_tex.outputs["Alpha"], principled.inputs["Alpha"])
    except Exception:
      pass
    _set_alpha_clip(mat)
  except Exception:
    pass

def _ensure_billboard_material(base_material_name: str, gc_name: str, type_idx: int, rect):
  mat_base = base_material_name or f"GC_BillboardMat_{gc_name}"
  target_name = f"{mat_base}_bb_{type_idx}"
  mat = bpy.data.materials.get(target_name)
  if not mat:
    mat = _dup_or_make_material(base_material_name, target_name)
  fallback_img = _get_first_image_from_material(base_material_name) if base_material_name else None
  _patch_material_uv_rect(mat, rect or [0.0, 0.0, 1.0, 1.0], fallback_image=fallback_img)
  return mat

def _get_or_create_billboard_for_type(gc_name: str, type_idx: int, base_material_name: str, rect):
  """
  Mesh: vertical quad (YZ), base at z=0, height=1.0, width = atlas_aspect * rect_aspect.
  """
  obj_name = f"GC_BB_{gc_name}_{type_idx}"
  rect = rect or [0.0, 0.0, 1.0, 1.0]
  rect_w = float(rect[2]) if rect[2] else 1.0
  rect_h = float(rect[3]) if rect[3] else 1.0
  atlas_aspect = _material_image_aspect(base_material_name) if base_material_name else 1.0
  rect_aspect = rect_w / rect_h if rect_h != 0 else 1.0
  aspect = max(0.01, min(100.0, atlas_aspect * rect_aspect))
  mesh_name = f"_GC_Q_{gc_name}_{type_idx}"
  me_old = bpy.data.meshes.get(mesh_name)
  if me_old:
    try: bpy.data.meshes.remove(me_old)
    except Exception: pass
  me = bpy.data.meshes.new(mesh_name)
  half_w = 0.5 * aspect
  verts = [(0.0, -half_w, 0.0), (0.0,  half_w, 0.0), (0.0,  half_w, 1.0), (0.0, -half_w, 1.0)]
  faces = [(0, 1, 2, 3)]
  me.from_pydata(verts, [], faces); me.update()
  uv = me.uv_layers.new(name="UV_BILLBOARD")
  try:
    uv.data[0].uv = (0.0, 0.0); uv.data[1].uv = (1.0, 0.0); uv.data[2].uv = (1.0, 1.0); uv.data[3].uv = (0.0, 1.0)
  except Exception:
    pass
  obj = bpy.data.objects.get(obj_name)
  if obj and obj.type == 'MESH':
    obj.data = me
  else:
    obj = bpy.data.objects.new(obj_name, me)
  obj.location = (0.0, 0.0, 0.0); obj.rotation_euler = (0.0, 0.0, 0.0); obj.scale = (1.0, 1.0, 1.0)
  _ensure_visible_obj(obj)
  mat = _ensure_billboard_material(base_material_name, gc_name, type_idx, rect)
  obj.data.materials.clear(); obj.data.materials.append(mat)
  coll = ensure_collection('_GroundCoverHelpers')
  if coll.name not in bpy.context.scene.collection.children:
    bpy.context.scene.collection.children.link(coll)
  if obj.name not in coll.objects:
    coll.objects.link(obj)
  return obj

def _safe_float(v, default=0.0):
  try:
    return float(v)
  except Exception:
    return float(default)

def _norm_probability_list(types):
  w = []
  for t in types:
    p = t.get('probability')
    p = 1.0 if p is None else _safe_float(p, 1.0)
    w.append(max(0.0, p))
  s = sum(w) if w else 1.0
  if s <= 0.0:
    s = 1.0
  return [x / s for x in w]

def _build_material_vertex_groups(terrain_obj, prefix="MAT_"):
  me = terrain_obj.data
  mats = list(me.materials)
  indices_by_mat = {}
  all_verts = set()
  for poly in me.polygons:
    if poly.material_index < 0 or poly.material_index >= len(mats):
      continue
    mat = mats[poly.material_index]
    if not mat:
      continue
    matname = mat.name
    s = indices_by_mat.setdefault(matname, set())
    for vi in poly.vertices:
      s.add(vi)
      all_verts.add(vi)
  groups_by_mat = {}
  for matname, idxs in indices_by_mat.items():
    gname = f"{prefix}{matname}"
    vg_existing = terrain_obj.vertex_groups.get(gname)
    if vg_existing:
      try:
        terrain_obj.vertex_groups.remove(vg_existing)
      except Exception:
        pass
    vg = terrain_obj.vertex_groups.new(name=gname)
    if idxs:
      vg.add(list(idxs), 1.0, 'REPLACE')
    groups_by_mat[matname] = vg
  return groups_by_mat, indices_by_mat, all_verts

def _match_mat_group_by_prefix(layer_name: str, groups_by_matname: dict):
  if not layer_name:
    return None, None
  ln = layer_name.lower()
  # exact
  for full_nm, vg in groups_by_matname.items():
    if full_nm.lower() == ln:
      return full_nm, vg
  # prefix
  best = None; best_len = 10**9
  for full_nm, vg in groups_by_matname.items():
    fnl = full_nm.lower()
    if fnl.startswith(ln):
      nextc = fnl[len(ln):len(ln)+1]
      is_delim = nextc in ("-", "_", ".", " ")
      score_len = len(full_nm)
      if is_delim: return full_nm, vg
      if score_len < best_len:
        best = (full_nm, vg); best_len = score_len
  return best if best else (None, None)

def _ensure_temp_group_from_indices(terrain_obj, name, indices):
  vg = terrain_obj.vertex_groups.get(name)
  if vg:
    try:
      terrain_obj.vertex_groups.remove(vg)
    except Exception:
      pass
  vg = terrain_obj.vertex_groups.new(name=name)
  if indices:
    vg.add(list(indices), 1.0, 'REPLACE')
  return vg

def _set_density_vertex_group(psys: bpy.types.ParticleSystem, pset: bpy.types.ParticleSettings, name: str) -> bool:
  if not name:
    return False
  for attr in ("vertex_group_density", "density_vertex_group"):
    try:
      if hasattr(psys, attr):
        setattr(psys, attr, name)
        val = getattr(psys, attr, "") or ""
        if val == name: return True
    except Exception:
      pass
  for attr in ("vertex_group_density", "density_vertex_group", "density_group", "vertex_group_name_density"):
    try:
      if hasattr(pset, attr):
        setattr(pset, attr, name)
        val = getattr(pset, attr, "") or ""
        if val == name: return True
    except Exception:
      pass
  return False

def _fix_invalid_enum(pset: bpy.types.ParticleSettings, attr: str, preferred: str, fallback: str = None):
  try:
    rna = getattr(pset, "bl_rna", None)
    prop = rna and rna.properties.get(attr)
    if not prop or not hasattr(prop, "enum_items"): return
    items = [e.identifier for e in prop.enum_items]
    target = preferred if preferred in items else (fallback if fallback in items else (items[0] if items else None))
    if target:
      try: setattr(pset, attr, target)
      except Exception: pass
  except Exception:
    pass

def _create_particle_system_for_type(terrain_obj, ps_name, vg_density, count, inst_obj, size_min, size_max, seed):
  # fresh ParticleSettings for consistent results
  if ps_name in bpy.data.particles:
    try: bpy.data.particles.remove(bpy.data.particles[ps_name], do_unlink=True)
    except Exception: pass
  pset = bpy.data.particles.new(ps_name)
  if hasattr(pset, "type"): pset.type = 'HAIR'
  if hasattr(pset, "use_advanced_hair"): pset.use_advanced_hair = True

  rna = getattr(pset, "bl_rna", None)
  if rna and rna.properties.get("render_as"):
    try: pset.render_as = 'OBJECT'
    except Exception: _fix_invalid_enum(pset, "render_as", "OBJECT")
  if rna and rna.properties.get("render_type"):
    try: pset.render_type = 'OBJECT'
    except Exception: _fix_invalid_enum(pset, "render_type", "OBJECT")

  for prop, pref, fb in (("display_method","RENDER","RENDERED"),("display_mode","RENDER","RENDERED"),("draw_as","RENDER",None)):
    try:
      if rna and rna.properties.get(prop): _fix_invalid_enum(pset, prop, pref, fb)
    except Exception:
      pass

  if hasattr(pset, "count"): pset.count = int(max(0, count))
  if hasattr(pset, "display_percentage"): pset.display_percentage = 100
  if hasattr(pset, "hair_length"): pset.hair_length = 1.0
  if hasattr(pset, "instance_object"): pset.instance_object = inst_obj
  if hasattr(pset, "show_emitter"): pset.show_emitter = True
  if hasattr(pset, "show_render_emitter"): pset.show_render_emitter = False
  elif hasattr(pset, "use_render_emitter"): pset.use_render_emitter = False

  if hasattr(pset, "use_rotations"):
    pset.use_rotations = True

  rna = getattr(pset, "bl_rna", None)
  if rna and rna.properties.get("rotation_mode"):
    try:
      pset.rotation_mode = 'GLOB_Y'
    except Exception:
      _fix_invalid_enum(pset, "rotation_mode", "GLOB_Y", "OB_Y")

  # No tilt, just yaw
  for attr, val in (("rotation_factor", 0.0), ("rotation_factor_random", 0.0),
                    ("phase_factor", 0.0), ("phase_factor_random", 1.0)):
    try:
      if hasattr(pset, attr):
        setattr(pset, attr, val)
    except Exception:
      pass

  if size_max < size_min: size_max = size_min
  base = 0.5 * (size_min + size_max); span = max(0.0, size_max - size_min)
  if hasattr(pset, "particle_size"): pset.particle_size = base
  if hasattr(pset, "size_random"):   pset.size_random   = min(1.0, span / base) if base > 1e-8 else 0.0

  ps_mod = terrain_obj.modifiers.new(name=ps_name, type='PARTICLE_SYSTEM')
  psys = terrain_obj.particle_systems[-1]; psys.settings = pset

  ok = False
  if vg_density: ok = _set_density_vertex_group(psys, psys.settings, vg_density.name)
  global _warned_no_density_prop
  if not ok and not _warned_no_density_prop:
    print("GroundCover/Particles WARN: density vertex-group slot not exposed on this Blender build; types will emit uniformly over the terrain.")
    _warned_no_density_prop = True

  s = int(seed) & 0x7FFFFFFF
  if hasattr(psys, "seed"): psys.seed = s
  elif hasattr(psys, "random_seed"): psys.random_seed = s
  elif hasattr(psys.settings, "seed"): psys.settings.seed = s
  elif hasattr(psys.settings, "random_seed"): psys.settings.random_seed = s

  ps_mod.show_viewport = True; ps_mod.show_render = True
  return psys

def _cleanup_previous_gc_particles(terrain_obj, gc_name_prefix="PART_GC_", vg_prefix="GCmask_"):
  for m in list(terrain_obj.modifiers):
    if m.type == 'PARTICLE_SYSTEM' and m.name.startswith(gc_name_prefix):
      try: terrain_obj.modifiers.remove(m)
      except Exception: pass
  for p in list(bpy.data.particles):
    if p.name.startswith(gc_name_prefix):
      try: bpy.data.particles.remove(p, do_unlink=True)
      except Exception: pass
  for vg in list(terrain_obj.vertex_groups):
    if vg.name.startswith(vg_prefix) or vg.name.startswith("MAT_"):
      try: terrain_obj.vertex_groups.remove(vg)
      except Exception: pass

def build_groundcover_objects(ctx):
  gcs = [rec for rec in (ctx.level_data or []) if rec.get('class') == 'GroundCover']
  if not gcs: return
  terr = _get_first_terrain_object()
  if not terr:
    print("GroundCover/Particles: No terrain mesh found, skipping.")
    return
  _ensure_visible_obj(terr)
  _cleanup_previous_gc_particles(terr, gc_name_prefix="PART_GC_", vg_prefix="GCmask_")
  mat_groups_by_name, idxs_by_mat, all_verts = _build_material_vertex_groups(terr, prefix="MAT_")

  total = len(gcs)
  for idx, gc in enumerate(gcs):
    try:
      name = (gc.get('name') or f"GC_{idx}").strip()
      max_elements = int(gc.get('maxElements') or 10000)
      seed = int(gc.get('seed') or 1)
      base_material_name = (gc.get('material') or "").strip()
      types = list((gc.get('Types') or []))
      if not types: continue
      probs = _norm_probability_list(types)
      for t, p in zip(types, probs):
        t['__prob_norm'] = p

      eff_total = int(max_elements)
      built_any_for_gc = False

      for tidx, t in enumerate(types):
        prob = float(t.get('__prob_norm', 1.0))
        count = max(0, int(eff_total * prob))
        if count <= 0: continue

        layer_name = (t.get('layer') or "").strip()
        if not layer_name: continue

        matched_full_mat, base_vg = _match_mat_group_by_prefix(layer_name, mat_groups_by_name)
        if not base_vg: continue

        if bool(t.get('invertLayer') or False):
          base_idxs = idxs_by_mat.get(matched_full_mat, set())
          comp = set(all_verts) - set(base_idxs)
          if not comp: continue
          vg = _ensure_temp_group_from_indices(terr, f"GCmask_{name}_{tidx}", comp)
        else:
          vg = base_vg
          if not idxs_by_mat.get(matched_full_mat, set()): continue

        shape_obj = _object_from_shape_filename(t.get('shapeFilename'))
        if shape_obj:
          inst_obj = shape_obj
        else:
          rect = t.get('billboardUVs') or [0.0, 0.0, 1.0, 1.0]
          inst_obj = _get_or_create_billboard_for_type(name, tidx, base_material_name, rect)

        _ensure_visible_obj(inst_obj)

        size_min = _safe_float(t.get('sizeMin'), 1.0)
        size_max = _safe_float(t.get('sizeMax'), size_min)
        ps_name = f"PART_GC_{name}_{tidx}"
        _create_particle_system_for_type(terr, ps_name, vg, count, inst_obj, size_min, size_max, seed + tidx*101)
        built_any_for_gc = True

      if not built_any_for_gc: continue
      if (idx % 8) == 0:
        ctx.progress.update(f"GroundCover/Particles: {idx}/{total}", step=1)
    except Exception as e:
      print(f"Error building GroundCover/Particles {gc.get('name') or ''}: {e}")
      import traceback; traceback.print_exc()

  try: bpy.context.view_layer.update()
  except Exception: pass
  ctx.progress.update(f"GroundCover/Particles: {total}/{total}", step=1)

def bake_groundcover_to_mesh(ctx=None,
                             remove_particles=True,
                             remove_gc_vgroups=True,
                             remove_mat_vgroups=True,
                             remove_helpers=True) -> list[bpy.types.Object]:
  """
  Incremental bake: for each PART_GC_* system, collect its instances, append them
  to BAKE_GC_<gcName> (creating it if needed), then immediately remove that psys.

  This reduces peak RAM usage compared to baking all systems at once.

  Returns list of baked GC objects.
  """
  terr = _get_first_terrain_object()
  if not terr:
    print("GroundCover/Bake: No terrain mesh found, abort.")
    return []

  # Parse gcName and typeIdx from psys name "PART_GC_<gcName>_<idx>"
  def _parse_gc(psname: str):
    rest = psname[len("PART_GC_"):]
    j = rest.rfind("_")
    if j < 0:
      return rest, None
    gcname = rest[:j]
    try:
      tidx = int(rest[j+1:])
    except Exception:
      tidx = None
    return gcname, tidx

  # Collection for baked meshes
  tgt_coll = ensure_collection('_GroundCoverBaked')
  if tgt_coll.name not in bpy.context.scene.collection.children:
    bpy.context.scene.collection.children.link(tgt_coll)

  # Map gcName -> baked object
  baked_objs: dict[str, bpy.types.Object] = {}

  # Common UV patterns
  base_quad_uv = [(0.0,0.0),(1.0,0.0),(1.0,1.0),(0.0,1.0)]
  base_tri_uv  = [(0.0,0.0),(1.0,0.0),(0.5,1.0)]

  # Iterate until no more PART_GC_ particle modifiers exist.
  while True:
    # Find next GC particle modifier on the terrain
    next_mod = None
    for m in terr.modifiers:
      if m.type == 'PARTICLE_SYSTEM':
        psys = m.particle_system
        if psys and psys.name.startswith("PART_GC_"):
          next_mod = m
          break
    if not next_mod:
      break  # no more systems

    psys = next_mod.particle_system
    pset = psys.settings
    inst_obj = getattr(pset, "instance_object", None)
    if not inst_obj or inst_obj.type != 'MESH':
      # Just remove it and move on
      try:
        terr.modifiers.remove(next_mod)
        if remove_particles and pset and pset.name.startswith("PART_GC_"):
          bpy.data.particles.remove(pset, do_unlink=True)
      except Exception:
        pass
      continue

    psname = psys.name
    gcname, tidx = _parse_gc(psname)

    # Ensure 100% display so depsgraph shows all instances
    saved_disp = None
    if hasattr(pset, "display_percentage"):
      saved_disp = pset.display_percentage
      pset.display_percentage = 100

    # Force depsgraph update
    bpy.context.view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get()
    terr_eval = terr.evaluated_get(dg)

    # Collect transforms for this single psys
    transforms = []
    for inst in dg.object_instances:
      try:
        if not getattr(inst, "is_instance", False):
          continue
        pinst = getattr(inst, "particle_system", None)
        if not pinst:
          continue
        if pinst.name != psname:
          continue
        emitter = getattr(pinst, "id_data", None)
        if emitter and getattr(emitter, "original", emitter) not in (terr, terr_eval):
          continue
        transforms.append(inst.matrix_world.copy())
      except Exception:
        pass

    # Restore display_percentage
    if saved_disp is not None:
      try:
        pset.display_percentage = saved_disp
      except Exception:
        pass
    bpy.context.view_layer.update()

    if not transforms:
      # Nothing to bake, just remove this system
      try:
        terr.modifiers.remove(next_mod)
        if remove_particles and pset and pset.name.startswith("PART_GC_"):
          bpy.data.particles.remove(pset, do_unlink=True)
      except Exception:
        pass
      continue

    # Get / create baked object for this GC
    me_name = f"BAKE_GC_{gcname}"
    bake_ob = baked_objs.get(gcname)
    if bake_ob and bake_ob.type != 'MESH':
      bake_ob = None
    if not bake_ob:
      existing = bpy.data.meshes.get(me_name)
      if existing:
        try:
          bpy.data.meshes.remove(existing)
        except Exception:
          pass
      me = bpy.data.meshes.new(me_name)
      bake_ob = bpy.data.objects.new(me_name, me)
      _ensure_visible_obj(bake_ob)
      if bake_ob.name not in tgt_coll.objects:
        tgt_coll.objects.link(bake_ob)
      baked_objs[gcname] = bake_ob

    me = bake_ob.data

    # Source mesh/topology
    src_me = inst_obj.data
    local_verts = [v.co.copy() for v in src_me.vertices]
    local_faces = [list(p.vertices) for p in src_me.polygons]
    if not local_faces:
      # fallback quad
      local_verts = [
        Vector((0.0,-0.5,0.0)),
        Vector((0.0, 0.5,0.0)),
        Vector((0.0, 0.5,1.0)),
        Vector((0.0,-0.5,1.0))
      ]
      local_faces = [[0,1,2,3]]
    face_lengths = [len(f) for f in local_faces]

    # Collect existing mesh data from baked mesh
    vert_coords = [v.co.copy() for v in me.vertices]
    polygon_loops = [list(p.vertices) for p in me.polygons]
    polygon_mat_indices = [p.material_index for p in me.polygons]
    existing_uvs = []
    if me.uv_layers:
      uv_layer = me.uv_layers.active
      existing_uvs = [Vector(lo.uv) for lo in uv_layer.data]
    uv_coords = existing_uvs or []

    # Ensure material is present and get its material index on the baked mesh
    mat = src_me.materials[0] if src_me.materials else None
    me.materials.clear()
    if mat:
      me.materials.append(mat)
    mat_index = 0  # single material on baked mesh for now

    # For each instance, append transformed verts + faces + UVs
    for M in transforms:
      base_index = len(vert_coords)
      tverts = [M @ v for v in local_verts]
      vert_coords.extend(tverts)
      for f in local_faces:
        polygon_loops.append([base_index + i for i in f])
        polygon_mat_indices.append(mat_index)
      for flen in face_lengths:
        if flen == 4:
          uv_coords.extend(base_quad_uv)
        elif flen == 3:
          uv_coords.extend(base_tri_uv)
        else:
          # simple gradient
          for i in range(flen):
            t = i / max(1, flen - 1)
            uv_coords.append((t, t))

    # Now write back into mesh
    me.clear_geometry()
    me.from_pydata(vert_coords, [], polygon_loops)
    me.update()

    # Material indices
    try:
      me.polygons.foreach_set("material_index", polygon_mat_indices)
    except Exception:
      for i, p in enumerate(me.polygons):
        try:
          p.material_index = polygon_mat_indices[i]
        except Exception:
          pass

    # UVs
    try:
      uv_layer = me.uv_layers.new(name="UV_BILLBOARD")
      flat_uv = [c for uv in uv_coords for c in (uv[0], uv[1])]
      total_loops = len(me.loops)
      if len(flat_uv) < total_loops * 2:
        flat_uv.extend([0.0, 0.0] * (total_loops - len(flat_uv)//2))
      elif len(flat_uv) > total_loops * 2:
        flat_uv = flat_uv[:total_loops*2]
      uv_layer.data.foreach_set("uv", flat_uv)
    except Exception:
      pass

    # Remove this particle system & settings to free RAM
    try:
      terr.modifiers.remove(next_mod)
    except Exception:
      pass
    if remove_particles and pset and pset.name.startswith("PART_GC_"):
      try:
        bpy.data.particles.remove(pset, do_unlink=True)
      except Exception:
        pass

    try:
      bpy.context.view_layer.update()
    except Exception:
      pass

  baked = list(baked_objs.values())

  # Remove GC and/or MAT vertex groups from terrain
  if remove_gc_vgroups or remove_mat_vgroups:
    removed_vg = 0
    for vg in list(terr.vertex_groups):
      if (remove_gc_vgroups and vg.name.startswith("GCmask_")) or \
         (remove_mat_vgroups and vg.name.startswith("MAT_")):
        try:
          terr.vertex_groups.remove(vg)
          removed_vg += 1
        except Exception:
          pass
    if removed_vg:
      print(f"GroundCover/Bake: removed {removed_vg} vertex groups from terrain.")

  # Remove helper billboard objects and their meshes
  if remove_helpers:
    removed_helpers = 0
    for ob in list(bpy.data.objects):
      if ob.type == 'MESH' and ob.name.startswith("GC_BB_"):
        try:
          for coll in list(ob.users_collection):
            try:
              coll.objects.unlink(ob)
            except Exception:
              pass
          bpy.data.objects.remove(ob, do_unlink=True)
          removed_helpers += 1
        except Exception:
          pass
    removed_meshes = 0
    for me in list(bpy.data.meshes):
      if me.name.startswith("_GC_Q_"):
        try:
          bpy.data.meshes.remove(me)
          removed_meshes += 1
        except Exception:
          pass
    if removed_helpers or removed_meshes:
      print(f"GroundCover/Bake: removed {removed_helpers} GC_BB_* objects and {removed_meshes} _GC_Q_* meshes.")

  try:
    bpy.context.view_layer.update()
  except Exception:
    pass

  print(f"GroundCover/Bake: created {len(baked)} baked GC objects (incremental).")
  return baked
