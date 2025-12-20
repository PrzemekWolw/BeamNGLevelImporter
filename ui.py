# ##### BEGIN LICENSE BLOCK #####
#
# This program is licensed under The MIT License:
# see LICENSE for the full license text
#
# ##### END LICENSE BLOCK #####

from __future__ import annotations
import bpy
from bpy.types import Panel, UIList

from . import importer

class BEAMNG_UL_Levels(UIList):
  bl_idname = "BEAMNG_UL_Levels"

  def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
    # item: LevelEntry
    if self.layout_type in {'DEFAULT', 'COMPACT'}:
      # Choose a basic icon
      ic = 'FILE_FOLDER'
      if getattr(item, "origin", "") == "zip":
        ic = 'FILE_ARCHIVE'
      elif getattr(item, "origin", "") == "mod":
        ic = 'OUTLINER_OB_GROUP_INSTANCE'
      label = item.title or item.name
      layout.label(text=f"{label} ({item.name})", icon=ic)
    elif self.layout_type in {'GRID'}:
      layout.alignment = 'CENTER'
      layout.label(text=item.name)

class BeamNGLevelImporterUI(Panel):
  bl_label = 'BeamNG Level Importer Menu'
  bl_idname = 'object.beamnglevelimporterui_3dview'
  bl_space_type = 'VIEW_3D'
  bl_region_type = 'TOOLS' if bpy.app.version < (2, 80) else 'UI'
  bl_category = 'BeamNG Level Importer'

  def draw(self, context):
    layout = self.layout
    props = getattr(context.scene, "BeamNGLevelImporter", None)
    if props is None:
      layout.label(text="Add-on is not initialized. Please re-enable it.")
      layout.operator("preferences.addon_show", text="Open Add-ons").module = __package__
      return

    # Scanner section
    box = layout.box()
    box.label(text="BeamNG Filesystem Scanner")
    box.prop(props, "use_scanner", toggle=True)
    col = box.column(align=True)
    col.prop(props, "game_install")
    col.prop(props, "user_folder")
    col.operator("beamng.scan_levels", icon='VIEWZOOM')
    if props.use_scanner:
      box.template_list("BEAMNG_UL_Levels", "", props, "levels", props, "levels_index", rows=8)
      box.prop(props, "overlay_patches")

    layout.separator()

    # Only show Manual Import if scanner is disabled
    if not props.use_scanner:
      layout.label(text="Manual Import")
      col = layout.column(align=True)
      col.prop(props, "enable_zip", toggle=True)
      col.label(text="Level Path")
      if props.enable_zip:
        col.prop(props, "zippath")
      else:
        col.prop(props, "levelpath")
      layout.separator()

    # Import section
    layout.label(text="Import:")
    col = layout.column(align=True)
    if props.use_scanner:
      has_list = bool(props.levels) and 0 <= props.levels_index < len(props.levels)
      if not has_list:
        col.label(text="No level selected (run scanner)")
      else:
        col.operator(importer.BeamNGLevelImporterLoader.bl_idname,
                    text="Import Level", icon='IMPORT')
    else:
      if props.levelpath == "" and props.zippath == "*.zip":
        col.label(text="You did not select location of files")
      else:
        col.operator(importer.BeamNGLevelImporterLoader.bl_idname,
                    text="Import Level", icon='IMPORT')

    # TSStatic / Forest realization tools
    layout.separator()
    box2 = layout.box()
    box2.label(text="Instances")

    row = box2.row(align=True)
    row.operator("beamng.realize_tsstatic_instances", text="Realize TSStatic")

    row = box2.row(align=True)
    row.operator("beamng.realize_forest_instances", text="Realize Forest")