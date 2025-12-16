# ##### BEGIN LICENSE BLOCK #####
#
# This program is licensed under The MIT License:
# see LICENSE for the full license text
#
# ##### END LICENSE BLOCK #####

from __future__ import annotations
import bpy
from bpy.types import Operator
from pathlib import Path

from .core.level_scan import (
  scan_levels, remember_scan,
  scan_assets, remember_assets,
  scan_file_index, remember_file_index,
)

def _get_prefs():
  try:
    addon_key = __package__.split('.')[0] if __package__ else None
    if addon_key and addon_key in bpy.context.preferences.addons:
      return bpy.context.preferences.addons[addon_key].preferences
  except Exception:
    pass
  return None

def _apply_defaults_if_empty(props):
  try:
    prefs = _get_prefs()
    if not prefs:
      return
    if not getattr(props, "game_install", "") and prefs.default_game_install:
      props.game_install = prefs.default_game_install
    if not getattr(props, "user_folder", "") and prefs.default_user_folder:
      props.user_folder = prefs.default_user_folder
  except Exception:
    pass


class BEAMNG_OT_ScanLevels(Operator):
  bl_idname = "beamng.scan_levels"
  bl_label = "Scan Levels"
  bl_description = "Scan game/user for levels, art/assets, and index all files (mods and game, zips and unpacked)"
  bl_options = {'REGISTER', 'UNDO'}

  def execute(self, context):
    props = getattr(context.scene, "BeamNGLevelImporter", None)
    if props is None:
      self.report({'ERROR'}, "Scene.BeamNGLevelImporter is missing. Re-enable the add-on.")
      return {'CANCELLED'}

    # Make sure defaults are applied if fields are empty
    _apply_defaults_if_empty(props)

    game = Path(props.game_install).resolve() if getattr(props, "game_install", "") else None
    user = Path(props.user_folder).resolve() if getattr(props, "user_folder", "") else None

    # Levels
    try:
      lvl_result = scan_levels(game, user)
      remember_scan(game, user, lvl_result)
    except Exception as e:
      self.report({'ERROR'}, f"Scan levels failed: {e}")
      return {'CANCELLED'}

    # Assets (art/, assets/)
    try:
      assets_idx = scan_assets(game, user)
      remember_assets(game, user, assets_idx)
    except Exception as e:
      self.report({'ERROR'}, f"Scan assets failed: {e}")
      return {'CANCELLED'}

    # Full file index (all files across zips and unpacked) with deep search
    try:
      fidx = scan_file_index(game, user)
      remember_file_index(game, user, fidx)
    except Exception as e:
      self.report({'ERROR'}, f"Index files failed: {e}")
      return {'CANCELLED'}

    lvl_count = len(lvl_result)
    art_count = len(assets_idx.art or [])
    assets_count = len(assets_idx.assets or [])
    self.report({'INFO'},
      f"Found {lvl_count} levels, {art_count} art roots, {assets_count} assets roots; "
      f"indexed {fidx.total_files} files ({fidx.dir_count} dir, {fidx.zip_count} zip)"
    )

    # Refresh UI enum
    try:
      for area in context.window.screen.areas:
        area.tag_redraw()
    except Exception:
      pass

    return {'FINISHED'}
