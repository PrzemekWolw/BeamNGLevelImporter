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
  "version": (0, 2, 0),
  "blender": (4, 5, 0),
  "location": "View3D > Sidebar > BeamNG Level Importer",
  "description": "Import all level objects",
  "warning": "",
  "doc_url": "",
  "category": "Object",
}

import bpy
from bpy.app.handlers import persistent
from bpy.props import StringProperty
from . import ui
from . import importer
from . import properties as props_mod
from . import ops_scan
from . import ops_scan_manifests
from . import materials_loader
from . import realize_instances

# Add-on preferences so user can set defaults that populate the UI
class BeamNGLevelImporterPreferences(bpy.types.AddonPreferences):
  bl_idname = __name__

  default_game_install: StringProperty(
    name="Default Game Install",
    subtype='DIR_PATH',
    description="Path to the BeamNG game install (used to prefill UI)",
    default=""
  )
  default_user_folder: StringProperty(
    name="Default User Folder",
    subtype='DIR_PATH',
    description="Path to the BeamNG user folder (used to prefill UI)",
    default=""
  )

  def draw(self, context):
    layout = self.layout
    layout.prop(self, "default_game_install")
    layout.prop(self, "default_user_folder")

def _get_prefs():
  try:
    addon = bpy.context.preferences.addons.get(__name__)
    return addon and addon.preferences or None
  except Exception:
    return None

def _apply_defaults_to_scene(scene: bpy.types.Scene):
  try:
    prefs = _get_prefs()
    props = getattr(scene, "BeamNGLevelImporter", None)
    if not prefs or not props:
      return
    if not getattr(props, "game_install", "") and prefs.default_game_install:
      props.game_install = prefs.default_game_install
    if not getattr(props, "user_folder", "") and prefs.default_user_folder:
      props.user_folder = prefs.default_user_folder
  except Exception:
    return

def _apply_defaults_to_all_scenes():
  for scn in bpy.data.scenes:
    _apply_defaults_to_scene(scn)

@persistent
def _beamng_apply_defaults_on_load(_dummy):
  _apply_defaults_to_all_scenes()

classes = (
  BeamNGLevelImporterPreferences,
  props_mod.LevelEntry,
  props_mod.ManifestEntry,
  props_mod.BeamNGLevelImporterproperties,
  ui.BEAMNG_UL_Levels,
  ui.BEAMNG_UL_Manifests,
  ui.BeamNGLevelImporterUI,
  ops_scan.BEAMNG_OT_ScanLevels,
  ops_scan_manifests.BEAMNG_OT_ScanManifests,
  importer.BeamNGLevelImporterLoader,
  importer.BeamNGExportManifestImporter,
)

def register():
  from bpy.utils import register_class
  for cls in classes:
    register_class(cls)
  if not hasattr(bpy.types.Scene, "BeamNGLevelImporter"):
    bpy.types.Scene.BeamNGLevelImporter = bpy.props.PointerProperty(
      type=props_mod.BeamNGLevelImporterproperties
    )
  materials_loader.register_materials_loader()
  realize_instances.register_realize_instances()
  _apply_defaults_to_all_scenes()
  if _beamng_apply_defaults_on_load not in bpy.app.handlers.load_post:
    bpy.app.handlers.load_post.append(_beamng_apply_defaults_on_load)

def unregister():
  from bpy.utils import unregister_class
  try:
    materials_loader.unregister_materials_loader()
  except Exception:
    pass
  try:
    realize_instances.unregister_realize_instances()
  except Exception:
    pass
  try:
    if _beamng_apply_defaults_on_load in bpy.app.handlers.load_post:
      bpy.app.handlers.load_post.remove(_beamng_apply_defaults_on_load)
  except Exception:
    pass
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