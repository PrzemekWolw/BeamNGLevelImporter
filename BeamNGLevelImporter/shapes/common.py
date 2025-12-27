# pipeline.py
# ##### BEGIN LICENSE BLOCK #####
#
# This program is licensed under The MIT License:
# see LICENSE for the full license text
#
# ##### END LICENSE BLOCK #####

from __future__ import annotations
import os

def shape_key(shape_name: str) -> str:
  """
  Canonical key for a TSStatic shapeName.
  MUST stay in sync with objects/tsstatic._shape_key.
  """
  s = (shape_name or "").replace("\\", "/").strip()
  return os.path.basename(s).lower()