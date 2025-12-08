# ##### BEGIN LICENSE BLOCK #####
#
# This program is licensed under The MIT License:
# see LICENSE for the full license text
#
# ##### END LICENSE BLOCK #####

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

@dataclass
class ImportConfig:
  level_path: Path
  enable_zip: bool
  zip_path: Optional[Path]

@dataclass
class ImportContext:
  config: ImportConfig
  progress: Any
  level_data: List[Dict]
  forest_data: List[Dict]
  terrain_meta: List[Dict]
  materials_packs: List[Dict]
  forest_items: Dict[str, Dict]
  forest_names: Dict[str, str]
  shapes: List[str]
  terrain_mats: List[str]