# ##### BEGIN LICENSE BLOCK #####
#
# This program is licensed under The MIT License:
# see LICENSE for the full license text
#
# ##### END LICENSE BLOCK #####


# Init BeamNGLevelImporter
bl_info = {
  "name": "BeamNG Level Importer",
  "author": "Przemysław Wolny (Car_Killer)",
  "version": (0, 1, 0),
  "blender": (4, 5, 0),
  "location": "View3D > Sidebar > BeamNG Level Importer",
  "description": "Import all level objects",
  "warning": "",
  "doc_url": "",
  "category": "Object",
}

import bpy
from . import ui
from . import importer
from . import properties as props_mod

classes = (
  props_mod.BeamNGLevelImporterproperties,
  ui.BeamNGLevelImporterUI,
  importer.BeamNGLevelImporterLoader,
)

def register():
  from bpy.utils import register_class
  for cls in classes:
    register_class(cls)
  if not hasattr(bpy.types.Scene, "BeamNGLevelImporter"):
    bpy.types.Scene.BeamNGLevelImporter = bpy.props.PointerProperty(
      type=props_mod.BeamNGLevelImporterproperties
    )

def unregister():
  from bpy.utils import unregister_class
  if hasattr(bpy.types.Scene, "BeamNGLevelImporter"):
    try:
      del bpy.types.Scene.BeamNGLevelImporter
    except Exception:
      pass
  for cls in reversed(classes):
    try:
      unregister_class(cls)
    except Exception:
      pass

if __name__ == "__main__":
  register()