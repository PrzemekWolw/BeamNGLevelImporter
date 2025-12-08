# ##### BEGIN LICENSE BLOCK #####
#
# This program is licensed under The MIT License:
# see LICENSE for the full license text
#
# ##### END LICENSE BLOCK #####
import bpy

class BeamNGLevelImporterproperties(bpy.types.PropertyGroup):
  enable_zip: bpy.props.BoolProperty(name="Use ZIP Level")
  levelpath: bpy.props.StringProperty(name="",
                  description="Choose a level directory",
                  subtype='DIR_PATH')
  zippath: bpy.props.StringProperty(name="",
                  description="Choose a level zip",
                  default="*.zip",
                  subtype='FILE_PATH')