# ##### BEGIN LICENSE BLOCK #####
#
# This program is licensed under The MIT License:
# see LICENSE for the full license text
#
# ##### END LICENSE BLOCK #####

import bpy
from bpy.types import Panel

from . import importer

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
    box.label(text="Scanner / Overlay")
    box.prop(props, "use_scanner", toggle=True)
    col = box.column(align=True)
    col.prop(props, "game_install")
    col.prop(props, "user_folder")
    col.operator("beamng.scan_levels", icon='VIEWZOOM')
    col.prop(props, "selected_level")
    col.prop(props, "overlay_patches")

    layout.separator()

    # Manual fallback
    layout.label(text="Manual Import")
    col = layout.column(align=True)
    col.prop(props, "enable_zip", toggle=True)
    col.label(text="Level Path")
    if props.enable_zip:
      col.prop(props, "zippath")
    else:
      col.prop(props, "levelpath")

    layout.separator()

    layout.label(text="Import:")

    col = layout.column(align=True)

    if props.use_scanner:
      if not props.selected_level:
        col.label(text="No level selected (run scanner)")
      else:
        col.operator(importer.BeamNGLevelImporterLoader.bl_idname, text="Import Level Objects", icon='IMPORT')
    else:
      if props.levelpath == "" and props.zippath == "*.zip":
        col.label(text="You did not select location of files")
      else:
        col.operator(importer.BeamNGLevelImporterLoader.bl_idname, text="Import Level Objects", icon='IMPORT')