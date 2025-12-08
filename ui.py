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
    BeamNGLevelImporter = bpy.context.scene.BeamNGLevelImporter

    layout.label(text="File path:")
    col = layout.column(align=True)
    col.prop(BeamNGLevelImporter, "enable_zip", toggle=True)
    col.label(text="Level Path")
    if BeamNGLevelImporter.enable_zip == True:
      col.prop(BeamNGLevelImporter, "zippath")
    else:
      col.prop(BeamNGLevelImporter, "levelpath")

    layout.separator()

    layout.label(text="Import:")

    col = layout.column(align=True)

    if BeamNGLevelImporter.levelpath == "" and BeamNGLevelImporter.zippath == "*.zip" :
      col.label(text="You did not select location of files")
    else:
      col.operator(importer.BeamNGLevelImporterLoader.bl_idname, text="Import Level Objects", icon='IMPORT')