# ##### BEGIN LICENSE BLOCK #####
#
# This program is licensed under The MIT License:
# see LICENSE for the full license text
#
# ##### END LICENSE BLOCK #####

from __future__ import annotations
import bpy
from bpy.types import Operator, Panel, PropertyGroup
from bpy.props import StringProperty, BoolProperty, PointerProperty
from pathlib import Path

from .core.import_sources import scan_material_json_packs, scan_material_cs_packs
from .materials.v15 import build_pbr_v15_material
from .materials.v0 import build_pbr_v0_material
from .materials.terrain_v15 import build_terrain_material_v15
from .materials.terrain_v0 import build_terrain_material_v0
from .utils.bpy_helpers import dedupe_materials


def _strip_numeric_suffix(name: str) -> str:
  base, dot, ext = name.rpartition(".")
  if dot and ext.isnumeric() and base:
    return base
  return name


def _build_material_from_def(v: dict, level_dir: Path) -> str | None:
  if not isinstance(v, dict):
    return None

  cls = v.get("class")

  if cls == "Material":
    map_to = v.get("mapTo")
    version = v.get("version")
    name = map_to if (map_to and map_to != "unmapped_mat") else v.get("name")
    if not name:
      return None

    if map_to and version == 1.5:
      build_pbr_v15_material(name, v, level_dir)
    elif map_to and (version == 0 or not version):
      build_pbr_v0_material(name, v, level_dir)
    else:
      # Fallback choice
      if version == 1.5:
        build_pbr_v15_material(name, v, level_dir)
      else:
        build_pbr_v0_material(name, v, level_dir)
    return name

  if cls == "TerrainMaterial":
    # Heuristic to pick v15 vs v0
    keys_v15 = (
      "baseColorBaseTex", "baseColorDetailTex", "baseColorMacroTex",
      "normalBaseTex", "roughnessBaseTex", "aoBaseTex"
    )
    if any(k in v for k in keys_v15):
      build_terrain_material_v15(level_dir, v, terrain_mats=[], terrain_world_size=None)
    else:
      build_terrain_material_v0(level_dir, v, terrain_mats=[], terrain_world_size=None)
    return v.get("internalName") or v.get("name")

  return None


def _replace_scene_slots(created_names: set[str]) -> int:
  replaced = 0
  mats = bpy.data.materials
  for obj in bpy.data.objects:
    if obj.type != 'MESH':
      continue
    for slot in obj.material_slots:
      mat = slot.material
      if not mat:
        continue
      base_name = _strip_numeric_suffix(mat.name)
      if base_name in created_names:
        new_mat = mats.get(base_name)
        if new_mat and new_mat != mat:
          slot.material = new_mat
          replaced += 1
  return replaced


class BeamNGMaterialsLoaderProperties(PropertyGroup):
  materials_root: StringProperty(
    name="Materials Root",
    subtype='DIR_PATH',
    description="Folder to scan recursively for materials.json and .materials.cs",
    default=""
  )
  include_terrain: BoolProperty(
    name="Include Terrain Materials",
    default=True,
    description="Also build TerrainMaterials found in packs"
  )
  replace_scene_slots: BoolProperty(
    name="Replace Scene Materials",
    default=True,
    description="Reassign scene slots by name to newly built materials"
  )


class BeamNG_OT_LoadReplaceMaterials(Operator):
  bl_idname = "beamng.load_replace_materials"
  bl_label = "Load & Replace Materials"
  bl_description = "Load BeamNG materials from folder and replace scene materials by name"
  bl_options = {'REGISTER', 'UNDO'}

  def execute(self, context):
    props = context.scene.BeamNGMaterialsLoader
    root = Path(props.materials_root).resolve() if props.materials_root else None

    if not root or not root.exists():
      self.report({'ERROR'}, "Materials Root not set or not found")
      return {'CANCELLED'}

    # Gather packs
    try:
      packs = scan_material_json_packs(root) + scan_material_cs_packs(root)
    except Exception as e:
      self.report({'ERROR'}, f"Failed to scan materials: {e}")
      return {'CANCELLED'}

    if not packs:
      self.report({'WARNING'}, "No material packs found in the selected folder")
      return {'FINISHED'}

    created_names: set[str] = set()
    total_defs = 0
    built_defs = 0

    for pack in packs:
      if not isinstance(pack, dict):
        continue
      for _, v in pack.items():
        if not isinstance(v, dict):
          continue
        total_defs += 1
        if v.get("class") == "TerrainMaterial" and not props.include_terrain:
          continue
        try:
          name = _build_material_from_def(v, root)
          if name:
            created_names.add(name)
            built_defs += 1
        except Exception as e:
          print(f"[BeamNG Materials Loader] Failed to build material: {e}")

    dedupe_materials()

    replaced_slots = 0
    if props.replace_scene_slots and created_names:
      replaced_slots = _replace_scene_slots(created_names)

    self.report(
      {'INFO'},
      f"Processed {total_defs} defs, built {built_defs}, replaced {replaced_slots} slots"
    )
    return {'FINISHED'}


class BeamNG_PT_MaterialsLoader(Panel):
  bl_label = "Materials Loader"
  bl_idname = "BEAMNG_PT_MATERIALS_LOADER"
  bl_space_type = 'VIEW_3D'
  bl_region_type = 'UI'
  bl_category = "BeamNG Level Importer"

  def draw(self, context):
    layout = self.layout
    props = context.scene.BeamNGMaterialsLoader
    col = layout.column(align=True)
    col.prop(props, "materials_root")
    col.prop(props, "include_terrain")
    col.prop(props, "replace_scene_slots")
    col.operator("beamng.load_replace_materials", icon='FILE_REFRESH')


classes = (
  BeamNGMaterialsLoaderProperties,
  BeamNG_OT_LoadReplaceMaterials,
  BeamNG_PT_MaterialsLoader,
)

def register_materials_loader():
  for c in classes:
    bpy.utils.register_class(c)
  bpy.types.Scene.BeamNGMaterialsLoader = PointerProperty(type=BeamNGMaterialsLoaderProperties)

def unregister_materials_loader():
  del bpy.types.Scene.BeamNGMaterialsLoader
  for c in reversed(classes):
    bpy.utils.unregister_class(c)
