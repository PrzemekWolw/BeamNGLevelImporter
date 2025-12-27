# ##### BEGIN LICENSE BLOCK #####
#
# This program is licensed under The MIT License:
# see LICENSE for the full license text
#
# ##### END LICENSE BLOCK #####

from __future__ import annotations

import json
from pathlib import Path
from bpy.types import Operator


def _default_export_root(props) -> Path | None:
  user = getattr(props, "user_folder", "") or ""
  if not user.strip():
    return None
  return (Path(user).expanduser() / "current" / "temp" / "blender_exports")


def _scan_root(props) -> Path | None:
  raw = getattr(props, "manifests_root", "") or ""
  if isinstance(raw, str) and raw.strip():
    return Path(raw).expanduser()
  return _default_export_root(props)


def _read_manifest_summary(p: Path) -> dict:
  try:
    with open(p, "r", encoding="utf-8") as f:
      m = json.load(f)
  except Exception:
    return {}

  vehicles = m.get("vehicles") if isinstance(m.get("vehicles"), list) else []
  exported_at = m.get("exportedAt") or p.parent.name
  level = m.get("level")
  level_vfs = level if isinstance(level, str) else ""

  return {
    "exportedAt": str(exported_at),
    "levelVfs": str(level_vfs),
    "vehiclesCount": int(len(vehicles)),
  }


def scan_manifests_into_props(props) -> int:
  root = _scan_root(props)
  props.manifests.clear()
  props.manifests_index = 0

  if not root or not root.exists():
    return 0

  found = list(root.rglob("export_manifest.json"))
  found.sort(key=lambda p: p.parent.name, reverse=True)

  for mf in found:
    info = _read_manifest_summary(mf)
    it = props.manifests.add()
    it.exportedAt = info.get("exportedAt", mf.parent.name)
    it.path = str(mf)
    it.out_dir = str(mf.parent)
    it.level_vfs = info.get("levelVfs", "")
    it.vehicles_count = int(info.get("vehiclesCount", 0))

  if props.manifests:
    props.manifests_index = min(props.manifests_index, len(props.manifests) - 1)

  return len(props.manifests)


class BEAMNG_OT_ScanManifests(Operator):
  bl_idname = "beamng.scan_manifests"
  bl_label = "Scan Vehicle States"
  bl_description = "Scan for BeamNG export_manifest.json under <User Folder>/temp/blender_exports"
  bl_options = {'REGISTER', 'UNDO'}

  def execute(self, context):
    props = getattr(context.scene, "BeamNGLevelImporter", None)
    if props is None:
      self.report({'ERROR'}, "Scene.BeamNGLevelImporter is missing.")
      return {'CANCELLED'}

    count = scan_manifests_into_props(props)
    if count <= 0:
      self.report({'WARNING'}, "No export manifests found. Check User Folder.")
    else:
      self.report({'INFO'}, f"Found {count} manifest(s).")
    return {'FINISHED'}