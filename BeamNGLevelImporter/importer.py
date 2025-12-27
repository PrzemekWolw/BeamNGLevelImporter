# ##### BEGIN LICENSE BLOCK #####
#
# This program is licensed under The MIT License:
# see LICENSE for the full license text
#
# ##### END LICENSE BLOCK #####

# BeamNGLevelImporter
# Made by Car_Killer

######## todo ########
# --- must have for 0.2 release ----
# - basic 5.x support...
#     - check other issues
# - ts support
#   - add support for older forest format
# --- support in future ----
# - light support, sync light energy properly
# - particle support
# - export support
# - procedural meshes, trackbuilder, etc

import bpy
import traceback
from pathlib import Path
from bpy.props import BoolProperty
from .pipeline import import_level
from .manifest_import import import_manifest
from .ops_scan_manifests import scan_manifests_into_props

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

class BeamNGExportManifestImporter(bpy.types.Operator):
  bl_idname = "beamng.import_export_manifest"
  bl_label = "Import BeamNG Vehicle State"
  bl_options = {'REGISTER', 'UNDO'}

  import_level_too: BoolProperty(
    name="Import Level Too",
    default=False,
    description="Also import level referenced by manifest['level'] (VFS path)."
  )

  def execute(self, context):
    props = getattr(context.scene, "BeamNGLevelImporter", None)
    if props is None:
      self.report({'ERROR'}, "Scene.BeamNGLevelImporter is missing. Re-enable the add-on.")
      return {'CANCELLED'}

    # Auto-scan manifests if list is empty
    if not props.manifests:
      scan_manifests_into_props(props)

    if not props.manifests or not (0 <= props.manifests_index < len(props.manifests)):
      self.report({'ERROR'}, "No manifest selected/found. Set User Folder and click 'Scan Vehicle States'.")
      return {'CANCELLED'}

    manifest_path = Path(props.manifests[props.manifests_index].path)
    if not manifest_path.exists():
      self.report({'ERROR'}, f"Manifest file missing: {manifest_path}")
      return {'CANCELLED'}

    try:
      import_manifest(manifest_path, import_level_too=bool(self.import_level_too), operator=self)
    except Exception as e:
      traceback.print_exc()
      self.report({'ERROR'}, f"{e.__class__.__name__}: {e}")
      return {'CANCELLED'}

    return {'FINISHED'}
