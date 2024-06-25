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
  "blender": (3, 0, 0),
  "location": "View3D > Sidebar > BeamNG Level Importer",
  "description": "Import all level objects",
  "warning": "",
  "doc_url": "",
  "category": "Object",
}

import bpy
from . import ui
from . import importer
from . import properties

classes = [
  ui.BeamNGLevelImporterUI,
  importer.BeamNGLevelImporterLoader,
]

def register():
  from bpy.utils import register_class
  for cls in classes:
    register_class(cls)


def unregister():
  from bpy.utils import unregister_class
  for cls in reversed(classes):
    unregister_class(cls)

if __name__ == "__main__":
  register()