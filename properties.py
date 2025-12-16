# ##### BEGIN LICENSE BLOCK #####
#
# This program is licensed under The MIT License:
# see LICENSE for the full license text
#
# ##### END LICENSE BLOCK #####
from __future__ import annotations
import bpy
from bpy.props import (
  StringProperty, BoolProperty, CollectionProperty, IntProperty, EnumProperty,
)

def _levels_enum_cb(self, context):
  try:
    from .core.level_scan import last_scan
    data = last_scan() or {}
    items = []
    for idx, (lvl, info) in enumerate(sorted(
        data.items(),
        key=lambda kv: ((kv[1].title or "").lower(), kv[0].lower()))):
      items.append((lvl, f"{info.title} ({lvl})", f"{len(info.providers)} source(s)", idx))
    if items:
      return items
  except Exception:
    pass
  return [("", "<no scan>", "", 0)]

def _get_addon_prefs():
  try:
    addon_key = __package__.split('.')[0] if __package__ else None
    if addon_key and addon_key in bpy.context.preferences.addons:
      return bpy.context.preferences.addons[addon_key].preferences
  except Exception:
    pass
  return None

def _get_game_install(self):
  val = self.get("_game_install", "")
  if isinstance(val, str) and val:
    return val
  prefs = _get_addon_prefs()
  if prefs:
    v = getattr(prefs, "default_game_install", "")
    if isinstance(v, str):
      return v
  return ""

def _set_game_install(self, value):
  try:
    self["_game_install"] = str(value or "")
  except Exception:
    pass

def _get_user_folder(self):
  val = self.get("_user_folder", "")
  if isinstance(val, str) and val:
    return val
  prefs = _get_addon_prefs()
  if prefs:
    v = getattr(prefs, "default_user_folder", "")
    if isinstance(v, str):
      return v
  return ""

def _set_user_folder(self, value):
  try:
    self["_user_folder"] = str(value or "")
  except Exception:
    pass

class LevelEntry(bpy.types.PropertyGroup):
  title: StringProperty(name="Title", default="")
  name: StringProperty(name="Name", default="")
  origin: StringProperty(name="Origin", default="")

class BeamNGLevelImporterproperties(bpy.types.PropertyGroup):
  enable_zip: BoolProperty(name="Use ZIP Level", default=False)
  levelpath: StringProperty(name="", description="Choose a level directory", subtype='DIR_PATH', default="")
  zippath: StringProperty(name="", description="Choose a level zip", default="*.zip", subtype='FILE_PATH')

  # Scanner / overlay props
  use_scanner: BoolProperty(
    name="Use Level Scanner",
    default=True,
    description="Scan game and user folders for levels and build virtual overlay"
  )
  # Dynamic-default fields (show Add-on Preferences defaults if scene value empty)
  game_install: StringProperty(
    name="Game Install",
    subtype='DIR_PATH',
    description="BeamNG game root (contains 'levels', 'art', or zips)",
    get=_get_game_install,
    set=_set_game_install
  )
  user_folder: StringProperty(
    name="User Folder",
    subtype='DIR_PATH',
    description="BeamNG user folder (contains 'current/mods' and 'current/mods/unpacked')",
    get=_get_user_folder,
    set=_set_user_folder
  )

  overlay_patches: BoolProperty(
    name="Merge Patches",
    default=True,
    description="Merge unpacked/zips (mods override game) into a temporary overlay"
  )

  selected_level: EnumProperty(
    name="Found Levels",
    items=_levels_enum_cb
  )

  levels: CollectionProperty(type=LevelEntry)
  levels_index: IntProperty(name="Level Index", default=0, min=0)