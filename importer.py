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
# - ts support
#   - add support for older forest format
# - light support, sync light energy properly
# - particle support
# - export support
# - integrate DTS importer
# - hide base position objects in different scene
# - handle all classes in level even if we dont support them
# - procedural meshes, trackbuilder, etc
# - import saved scene from game with vehicles

import bpy
import traceback
from .pipeline import import_level

class BeamNGLevelImporterLoader(bpy.types.Operator):
  bl_idname = "object.beamnglevelimporter_loader"
  bl_label = "Import BeamNG Level Objects"
  bl_options = {'REGISTER', 'UNDO'}
  bl_category = 'Import BeamNG Level'

  def execute(self, context):
    props = getattr(context.scene, "BeamNGLevelImporter", None)
    if props is None:
      self.report({'ERROR'}, "Scene.BeamNGLevelImporter is missing. Re-enable the add-on.")
      return {'CANCELLED'}
    try:
      import_level(context.scene, props, self)
      return {'FINISHED'}
    except Exception as e:
      traceback.print_exc()
      self.report({'ERROR'}, f"{e.__class__.__name__}: {e}")
      return {'CANCELLED'}