# ##### BEGIN LICENSE BLOCK #####
#
# This program is licensed under The MIT License:
# see LICENSE for the full license text
#
# ##### END LICENSE BLOCK #####

# BeamNGLevelImporter
# Made by Car_Killer

######## todo ########
# - basic 5.x support...
#     - multiscatter instead of nishita
#     - check other issues
# - add support for older forest format
# - light support, sync light energy properly
# - zip support, rework how we handle zip
# - mesh road support
# - decal road support
# - prefabs support
# - decal support
# - particle support
# - ts support
# - export support
# - integrate DTS importer
# - hide base position objects in different scene
# - asset link support
# - handle all classes in level even if we dont support them

import bpy
from .pipeline import import_level

class BeamNGLevelImporterLoader(bpy.types.Operator):
  bl_idname = "object.beamnglevelimporter_loader"
  bl_label = "Import BeamNG Level Objects"
  bl_options = {'REGISTER', 'UNDO'}
  bl_category = 'Import BeamNG Level'

  def execute(self, context):
    try:
      import_level(context.scene, context.scene.BeamNGLevelImporter, self)
      return {'FINISHED'}
    except Exception as e:
      self.report({'ERROR'}, str(e))
      return {'CANCELLED'}