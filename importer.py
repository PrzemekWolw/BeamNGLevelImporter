# ##### BEGIN LICENSE BLOCK #####
#
# This program is licensed under The MIT License:
# see LICENSE for the full license text
#
# ##### END LICENSE BLOCK #####

# BeamNGLevelImporter
# Made by Car_Killer

######## todo ########
# - basic 4.x support...
# - persistentId removal compatibility (done)
# - rotation fix (done)
# - Forest data support (done)
# - Scene tree folders (done)
# - ground pane support (done)
# - sound emitters support (done)
# - camera support (done)
# - water pane support (done)
# - light support (done)
# - water block support (done)
# - terrain support (done)
# - zip support (done)
# - material support (done)
# - materials v0 support (done)
# - terrain material support (done)
# - default tod support using nishita (done)
# - assimp (done)
# - mesh road support
# - decal road support
# - groundcover support
# - prefabs support
# - rivers support
# - decal support
# - particle support
# - ts support
# - export support

import json
import bpy
import os
import sys
import re
import mathutils
import math
import zipfile
import subprocess
from bpy.utils import resource_path
from pathlib import Path

class BeamNGLevelImporterLoader(bpy.types.Operator):
  bl_idname = "object.beamnglevelimporter_loader"
  bl_label = "Import BeamNG Level Objects"
  bl_category = 'Import BeamNG Level'

  def execute(self, context):
    #notification system
    def ShowMessageBox(message = "", title = "BeamNGLevelImporter", icon = 'INFO'):

      def draw(self, context):
        self.layout.label(text=message)

      bpy.context.window_manager.popup_menu(draw, title = title, icon = icon)

    tempPath = bpy.app.tempdir
    BeamNGLevelImporter = bpy.context.scene.BeamNGLevelImporter
    if BeamNGLevelImporter.enable_zip == True:
      if tempPath and BeamNGLevelImporter.zippath:
        with zipfile.ZipFile(BeamNGLevelImporter.zippath, 'r') as zip_level:
          for filename in zip_level.namelist():
            pth = Path(filename)
            vpath = str(pth)
            if vpath.endswith('info.json'):
              virtualPath = vpath.replace('info.json', '')
          zip_level.extractall(tempPath)
        BeamNGLevelImporter.levelpath = tempPath + virtualPath
        print(BeamNGLevelImporter.levelpath)

    terDatapath = BeamNGLevelImporter.levelpath

    importpath = None
    forestpath = None
    managedItemData = None

    imageSpace = 'Linear'
    if bpy.app.version >= (4, 0):
      imageSpace = 'Non-Color'

    importpath = os.path.normpath(os.path.join(BeamNGLevelImporter.levelpath,'main'))
    forestpath = os.path.normpath(os.path.join(BeamNGLevelImporter.levelpath,'forest'))
    managedItemData = os.path.normpath(os.path.join(BeamNGLevelImporter.levelpath,'art','forest'))

    terrainExport = BeamNGLevelImporter.terpath
    level_data = []
    forest_data = []
    terrain_data = []
    forestItems = []
    materials = []
    forestNames = {}
    Shapes = []
    terrainMats = []

    for subdir, dirs, files in os.walk(importpath):
      for file in files:
        if file.endswith('.json'):
          readfile = subdir + os.sep + file
          with open(readfile,"r") as f:
            print(readfile)
            for line in f:
              data = json.loads(line)
              level_data.append(data)

    for subdir, dirs, files in os.walk(forestpath):
      for file in files:
        if file.endswith('.json'):
          readfile = subdir + os.sep + file
          with open(readfile,"r") as f:
            print(readfile)
            for line in f:
              data = json.loads(line)
              forest_data.append(data)

    for file in os.listdir(terDatapath):
        if file.endswith('.terrain.json'):
          readfile = terDatapath + file
          with open(readfile,"r") as f:
            data = json.load(f)
            terrain_data.append(data)

    for subdir, dirs, files in os.walk(terDatapath):
      for file in files:
        if file.endswith('materials.json'):
          readfile = subdir + os.sep + file
          with open(readfile,"r") as f:
            print(readfile)
            try:
              data = json.load(f)
              materials.append(data)
            except:
              print("Import failed skipping")
            pass

    try:
      for file in os.listdir(managedItemData):
        if file.endswith('.json'):
          readfile = managedItemData + file
          with open(readfile,"r") as f:
            data = json.load(f)
            forestItems = data
    except:
      print("Failed skipping")
      pass

    bpy.ops.object.select_all(action='DESELECT')
    print("Generating Scene Tree")
    for i in level_data:
      if i.get('class') == 'SimGroup':
        coll_scene = bpy.context.scene.collection
        collection = bpy.data.collections.new(i.get('name'))
        bpy.context.scene.collection.children.link(collection)

    print("Loading Shapes")
    for i in level_data:
      if i.get('class') == 'TSStatic':
        shape = i.get('shapeName')
        if shape in Shapes:
          print("Skipping...")
        else:
          Shapes.append(shape)

    for i in forestItems:
      shape = forestItems[i].get('shapeFile')
      name = forestItems[i].get('name')
      if shape in Shapes:
        print("Skipping...")
      else:
        Shapes.append(shape)
        model = os.path.split(shape)
        forestNames[name] = model[1]

    for i in materials:
      for k,v in i.items():
        count = -1
        #we have to ensure we are loading materials V1.5
        if v.get('mapTo') and v.get('version') == 1.5:
          pth = Path(terDatapath)
          mat = v.get('mapTo')
          color = None
          normal = None
          metallic = None
          roughness = None
          opacity = None
          clearcoat = None
          emissive = None
          if v.get('Stages'):
            for d in v.get('Stages'):
              count = count + 1
              #for now only layer 0 is loaded
              if count == 0:
                for e,m in d.items():
                  if e == 'baseColorMap' or e == 'colorMap':
                    color = m
                  if e == 'normalMap':
                    normal = m
                  if e == 'metallicMap':
                    metallic = m
                  if e == 'roughnessMap':
                    roughness = m
                  if e == 'opacityMap':
                    opacity = m
                  if e == 'clearCoatMap':
                    clearcoat = m
                  if e == 'emissiveMap':
                    emissive = m

          new_mat = bpy.data.materials.new(mat)
          new_mat.use_nodes = True
          bsdf = new_mat.node_tree.nodes["Principled BSDF"]
          if not color == None:
            colTex = new_mat.node_tree.nodes.new('ShaderNodeTexImage')
            pthObj = color.replace("levels", "/")
            pathTex = str(pth.parent) + pthObj
            if sys.platform == "win32":
            pathTex = pathTex.replace("/","\\")
            if not terrainExport == "":
              pth = Path(terrainExport)
              pathTex = str(pth.parent) + pthObj
              if sys.platform == "win32":
              pathTex = pathTex.replace("/","\\")
              if pathTex.endswith('.dds') or pathTex.endswith('.DDS'):
                pathTex = pathTex.replace(".dds", ".png")
              print(pathTex)
            try:
              colTex.image = bpy.data.images.load(pathTex)
            except:
              print("Import failed skipping")
              pass
            new_mat.node_tree.links.new(bsdf.inputs['Base Color'], colTex.outputs['Color'])
          if not normal == None:
            norTex = new_mat.node_tree.nodes.new('ShaderNodeTexImage')
            pthObj = normal.replace("levels", "/")
            pathTex = str(pth.parent) + pthObj
            if sys.platform == "win32":
            pathTex = pathTex.replace("/","\\")
            if not terrainExport == "":
              pth = Path(terrainExport)
              pathTex = str(pth.parent) + pthObj
              if sys.platform == "win32":
              pathTex = pathTex.replace("/","\\")
              if pathTex.endswith('.dds') or pathTex.endswith('.DDS'):
                pathTex = pathTex.replace(".dds", ".png")
              print(pathTex)
            try:
              norTex.image = bpy.data.images.load(pathTex)
            except:
              print("Import failed skipping")
              pass
            new_mat.node_tree.links.new(bsdf.inputs['Normal'], norTex.outputs['Color'])
          if not metallic == None:
            metalTex = new_mat.node_tree.nodes.new('ShaderNodeTexImage')
            pthObj = metallic.replace("levels", "/")
            pathTex = str(pth.parent) + pthObj
            if sys.platform == "win32":
            pathTex = pathTex.replace("/","\\")
            if not terrainExport == "":
              pth = Path(terrainExport)
              pathTex = str(pth.parent) + pthObj
              if sys.platform == "win32":
              pathTex = pathTex.replace("/","\\")
              if pathTex.endswith('.dds') or pathTex.endswith('.DDS'):
                pathTex = pathTex.replace(".dds", ".png")
              print(pathTex)
            try:
              metalTex.image = bpy.data.images.load(pathTex)
            except:
              print("Import failed skipping")
              pass
            new_mat.node_tree.links.new(bsdf.inputs['Metallic'], metalTex.outputs['Color'])
          if not roughness == None:
            roughTex = new_mat.node_tree.nodes.new('ShaderNodeTexImage')
            pthObj = roughness.replace("levels", "/")
            pathTex = str(pth.parent) + pthObj
            if sys.platform == "win32":
            pathTex = pathTex.replace("/","\\")
            if not terrainExport == "":
              pth = Path(terrainExport)
              pathTex = str(pth.parent) + pthObj
              if sys.platform == "win32":
              pathTex = pathTex.replace("/","\\")
              if pathTex.endswith('.dds') or pathTex.endswith('.DDS'):
                pathTex = pathTex.replace(".dds", ".png")
              print(pathTex)
            try:
              roughTex.image = bpy.data.images.load(pathTex)
            except:
              print("Import failed skipping")
              pass
            new_mat.node_tree.links.new(bsdf.inputs['Roughness'], roughTex.outputs['Color'])
          if not opacity == None:
            opTex = new_mat.node_tree.nodes.new('ShaderNodeTexImage')
            pthObj = opacity.replace("levels", "/")
            pathTex = str(pth.parent) + pthObj
            if sys.platform == "win32":
            pathTex = pathTex.replace("/","\\")
            if not terrainExport == "":
              pth = Path(terrainExport)
              pathTex = str(pth.parent) + pthObj
              if sys.platform == "win32":
              pathTex = pathTex.replace("/","\\")
              if pathTex.endswith('.dds') or pathTex.endswith('.DDS'):
                pathTex = pathTex.replace(".dds", ".png")
              print(pathTex)
            try:
              opTex.image = bpy.data.images.load(pathTex)
            except:
              print("Import failed skipping")
              pass
            new_mat.node_tree.links.new(bsdf.inputs['Alpha'], opTex.outputs['Color'])
          if not clearcoat == None:
            ccTex = new_mat.node_tree.nodes.new('ShaderNodeTexImage')
            pthObj = clearcoat.replace("levels", "/")
            pathTex = str(pth.parent) + pthObj
            if sys.platform == "win32":
            pathTex = pathTex.replace("/","\\")
            if not terrainExport == "":
              pth = Path(terrainExport)
              pathTex = str(pth.parent) + pthObj
              if sys.platform == "win32":
              pathTex = pathTex.replace("/","\\")
              if pathTex.endswith('.dds') or pathTex.endswith('.DDS'):
                pathTex = pathTex.replace(".dds", ".png")
              print(pathTex)
            try:
              ccTex.image = bpy.data.images.load(pathTex)
            except:
              print("Import failed skipping")
              pass
            new_mat.node_tree.links.new(bsdf.inputs['Clearcoat'], ccTex.outputs['Color'])
          if not emissive == None:
            emTex = new_mat.node_tree.nodes.new('ShaderNodeTexImage')
            pthObj = emissive.replace("levels", "/")
            pathTex = str(pth.parent) + pthObj
            if sys.platform == "win32":
            pathTex = pathTex.replace("/","\\")
            if not terrainExport == "":
              pth = Path(terrainExport)
              pathTex = str(pth.parent) + pthObj
              if sys.platform == "win32":
              pathTex = pathTex.replace("/","\\")
              if pathTex.endswith('.dds') or pathTex.endswith('.DDS'):
                pathTex = pathTex.replace(".dds", ".png")
              print(pathTex)
            try:
              emTex.image = bpy.data.images.load(pathTex)
            except:
              print("Import failed skipping")
              pass
            if bpy.app.version < (4, 0):
              new_mat.node_tree.links.new(bsdf.inputs['Emission'], emTex.outputs['Color'])

        if v.get('mapTo') and v.get('version') == 0 or v.get('mapTo')  and not v.get('version'):
          pth = Path(terDatapath)
          mat = v.get('mapTo')
          color = None
          normal = None
          reflectivity = None
          specular = None
          if v.get('Stages'):
            for d in v.get('Stages'):
              count = count + 1
              #for now only layer 0 is loaded
              if count == 0:
                for e,m in d.items():
                  if e == 'baseColorMap' or e == 'colorMap':
                    color = m
                  if e == 'normalMap':
                    normal = m
                  if e == 'reflectivityMap':
                    reflectivity = m
                  if e == 'roughnessMap':
                    specularMap = m

          new_mat = bpy.data.materials.new(mat)
          new_mat.use_nodes = True
          new_mat.node_tree.nodes.remove(new_mat.node_tree.nodes.get('Principled BSDF'))
          material_output = new_mat.node_tree.nodes.get('Material Output')
          bsdf = new_mat.node_tree.nodes.new("ShaderNodeBsdfDiffuse")
          new_mat.node_tree.links.new(material_output.inputs[0], bsdf.outputs[0])
          if not color == None:
            colTex = new_mat.node_tree.nodes.new('ShaderNodeTexImage')
            pthObj = color.replace("levels", "/")
            pathTex = str(pth.parent) + pthObj
            if sys.platform == "win32":
            pathTex = pathTex.replace("/","\\")
            if not terrainExport == "":
              pth = Path(terrainExport)
              pathTex = str(pth.parent) + pthObj
              if sys.platform == "win32":
              pathTex = pathTex.replace("/","\\")
              if pathTex.endswith('.dds') or pathTex.endswith('.DDS'):
                pathTex = pathTex.replace(".dds", ".png")
              print(pathTex)
            try:
              colTex.image = bpy.data.images.load(pathTex)
            except:
              print("Import failed skipping")
              pass
            new_mat.node_tree.links.new(bsdf.inputs['Color'], colTex.outputs['Color'])
          if not normal == None:
            norTex = new_mat.node_tree.nodes.new('ShaderNodeTexImage')
            pthObj = normal.replace("levels", "/")
            pathTex = str(pth.parent) + pthObj
            if sys.platform == "win32":
            pathTex = pathTex.replace("/","\\")
            if not terrainExport == "":
              pth = Path(terrainExport)
              pathTex = str(pth.parent) + pthObj
              if sys.platform == "win32":
              pathTex = pathTex.replace("/","\\")
              if pathTex.endswith('.dds') or pathTex.endswith('.DDS'):
                pathTex = pathTex.replace(".dds", ".png")
              print(pathTex)
            try:
              norTex.image = bpy.data.images.load(pathTex)
            except:
              print("Import failed skipping")
              pass
            new_mat.node_tree.links.new(material_output.inputs[2], norTex.outputs['Color'])
          '''if not reflectivity == None:
            metalTex = new_mat.node_tree.nodes.new('ShaderNodeTexImage')
            pthObj = reflectivity.replace("levels", "/")
            pathTex = str(pth.parent) + pthObj
            pathTex = pathTex.replace("/","\\")
            if not terrainExport == "":
              pth = Path(terrainExport)
              pathTex = str(pth.parent) + pthObj
              pathTex = pathTex.replace("/","\\")
              if pathTex.endswith('.dds') or pathTex.endswith('.DDS'):
                pathTex = pathTex.replace(".dds", ".png")
              print(pathTex)
            try:
              metalTex.image = bpy.data.images.load(pathTex)
            except:
              print("Import failed skipping")
              pass
            new_mat.node_tree.links.new(bsdf.inputs['Roughness'], metalTex.outputs['Color'])
          if reflectivity == None:
            colTex2 = new_mat.node_tree.nodes.new('ShaderNodeTexImage')
            pthObj = color.replace("levels", "/")
            pathTex = str(pth.parent) + pthObj
            pathTex = pathTex.replace("/","\\")
            if not terrainExport == "":
              pth = Path(terrainExport)
              pathTex = str(pth.parent) + pthObj
              pathTex = pathTex.replace("/","\\")
              if pathTex.endswith('.dds') or pathTex.endswith('.DDS'):
                pathTex = pathTex.replace(".dds", ".png")
              print(pathTex)
            try:
              colTex.image = bpy.data.images.load(pathTex)
            except:
              print("Import failed skipping")
              pass
            new_mat.node_tree.links.new(bsdf.inputs['Roughness'], colTex.outputs['Alpha'])
          if not specular == None:
            roughTex = new_mat.node_tree.nodes.new('ShaderNodeTexImage')
            pthObj = specular.replace("levels", "/")
            pathTex = str(pth.parent) + pthObj
            pathTex = pathTex.replace("/","\\")
            if not terrainExport == "":
              pth = Path(terrainExport)
              pathTex = str(pth.parent) + pthObj
              pathTex = pathTex.replace("/","\\")
              if pathTex.endswith('.dds') or pathTex.endswith('.DDS'):
                pathTex = pathTex.replace(".dds", ".png")
              print(pathTex)
            try:
              roughTex.image = bpy.data.images.load(pathTex)
            except:
              print("Import failed skipping")
              pass
            new_mat.node_tree.links.new(bsdf.inputs['Specular'], roughTex.outputs['Color'])'''

        if v.get('class') == "TerrainMaterial":
          pth = Path(terDatapath)
          termat = v.get('internalName') + '-' + v.get('persistentId')
          basecolor = v.get('baseColorBaseTex')
          baseheight = v.get('heightBaseTex')
          basenormal = v.get('normalBaseTex')
          baseroughness = v.get('roughnessBaseTex')
          terrainMats.append(termat)
          new_mat = bpy.data.materials.new(termat)
          new_mat.use_nodes = True
          bsdf = new_mat.node_tree.nodes["Principled BSDF"]
          material_output = new_mat.node_tree.nodes.get('Material Output')
          if not basecolor == None:
            colTex = new_mat.node_tree.nodes.new('ShaderNodeTexImage')
            pthObj = basecolor.replace("levels", "/")
            pathTex = str(pth.parent) + pthObj
            if sys.platform == "win32":
            pathTex = pathTex.replace("/","\\")
            try:
              colTex.image = bpy.data.images.load(pathTex)
            except:
              print("Import failed skipping")
              pass
            new_mat.node_tree.links.new(bsdf.inputs['Base Color'], colTex.outputs['Color'])
          if not basenormal == None:
            norTex = new_mat.node_tree.nodes.new('ShaderNodeTexImage')
            pthObj = basenormal.replace("levels", "/")
            pathTex = str(pth.parent) + pthObj
            if sys.platform == "win32":
            pathTex = pathTex.replace("/","\\")
            try:
              norTex.image = bpy.data.images.load(pathTex)
            except:
              print("Import failed skipping")
              pass
            new_mat.node_tree.links.new(bsdf.inputs['Normal'], norTex.outputs['Color'])
          if not baseheight == None:
            norTex = new_mat.node_tree.nodes.new('ShaderNodeTexImage')
            pthObj = baseheight.replace("levels", "/")
            pathTex = str(pth.parent) + pthObj
            if sys.platform == "win32":
            pathTex = pathTex.replace("/","\\")
            try:
              norTex.image = bpy.data.images.load(pathTex)
            except:
              print("Import failed skipping")
              pass
            new_mat.node_tree.links.new(material_output.inputs[2], norTex.outputs['Color'])
          if not baseroughness == None:
            metalTex = new_mat.node_tree.nodes.new('ShaderNodeTexImage')
            pthObj = baseroughness.replace("levels", "/")
            pathTex = str(pth.parent) + pthObj
            if sys.platform == "win32":
            pathTex = pathTex.replace("/","\\")
            try:
              metalTex.image = bpy.data.images.load(pathTex)
            except:
              print("Import failed skipping")
              pass
            new_mat.node_tree.links.new(bsdf.inputs['Roughness'], metalTex.outputs['Color'])

    for i in Shapes:
      if i.endswith('.dae'):
        pth = Path(terDatapath)
        pthObj = i.replace("levels", "/")
        pathmodel = str(pth.parent) + pthObj
        try:
          bpy.ops.wm.collada_import(filepath = pathmodel,
                        auto_connect = True,
                         find_chains = True,
                         fix_orientation = True)
        except:
          print("collada import failed")
          try:
            print("Blender cannot load this mesh, trying with assimp2obj")
            newName = pthObj.replace(".dae", "")
            if sys.platform == "win32":
            command = (os.path.dirname(os.path.splitext(__file__)[0]) + '\\assimp export "' + pathmodel + '" "' + tempPath + newName + '.obj"' )
            if sys.platform == "linux" or sys.platform == "linux2":
              command = ('assimp export "' + pathmodel + '" "' + tempPath + newName + '.obj"')
              command = command.replace('//', '/')
              command = command.replace('//', '/')
            if sys.platform == "win32":
            command = command.replace('/', '\\')
            command = command.replace('\\\\', '\\')
            if not os.path.exists(tempPath + newName):
              os.makedirs(tempPath + newName)
            if sys.platform == "linux" or sys.platform == "linux2":
              subprocess.call(command, shell=True)
            if sys.platform == "win32":
            subprocess.call(command)
            bpy.ops.import_scene.obj(filepath = tempPath + newName + '.obj' )
          except:
            print("Import failed skipping")
            pass
        junk = []
        poli = []
        lodSizes = []
        for o in bpy.context.selected_objects:
          try:
            bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
          except:
            pass
          if o.type == 'EMPTY':
            junk.append(o.name)
          if o.type == 'MESH':
            mesh = o.data
            print(len(mesh.polygons))
            try:
              lodSize = int(o.name.split('_a')[-1])
            except:
              pass
            if 'lodSize' in locals():
              lodSizes.append(lodSize)
            else:
              poli.append(int(len(mesh.polygons)))
        for o in bpy.context.selected_objects:
           if o.type == 'MESH':
            print(max(str(poli)))
            mesh = o.data
            try:
              lodSize = int(o.name.split('_a')[-1])
            except:
              pass

            if 'lodSize' in locals() and lodSize == max(lodSizes):
              print("Found highest lod")
              model = os.path.split(i)
              o.name = model[1]
              o.location = [0,0,-1000]
            elif poli and int(len(mesh.polygons)) == max(poli):
              print("Found highest lod")
              model = os.path.split(i)
              o.name = model[1]
              o.location = [0,0,-1000]
            else:
              junk.append(o.name)

        bpy.ops.object.select_all(action='DESELECT')
        for j in junk:
          print("Removing "+j)
          bpy.data.objects[j].select_set(True)
          bpy.ops.object.delete(use_global=False)

    if bpy.context.scene.objects.get("Cube"):
      print("Found default cube, removing")
      bpy.data.objects["Cube"].select_set(True)
      bpy.ops.object.delete(use_global=False)
      bpy.ops.object.select_all(action='DESELECT')
    if bpy.context.scene.objects.get("Light"):
      print("Found default light, removing")
      bpy.data.objects["Light"].select_set(True)
      bpy.ops.object.delete(use_global=False)
      bpy.ops.object.select_all(action='DESELECT')
    if bpy.context.scene.objects.get("Lamp"):
      print("Found default legacy lamp, removing")
      bpy.data.objects["Lamp"].select_set(True)
      bpy.ops.object.delete(use_global=False)
      bpy.ops.object.select_all(action='DESELECT')
    if bpy.context.scene.objects.get("Camera"):
      print("Found default camera, removing")
      bpy.data.objects["Camera"].select_set(True)
      bpy.ops.object.delete(use_global=False)
      bpy.ops.object.select_all(action='DESELECT')


    mats = bpy.data.materials
    for mat in mats:
      (original, _, ext) = mat.name.rpartition(".")
      if ext.isnumeric() and mats.find(original):
        try:
          mat.user_remap(mats[original])
          mats.remove(mat)
        except:
          pass

    bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=1)
    print("Importing Mission Data")

    for i in level_data:
      if i.get('class') == 'SimGroup':
        coll_scene = bpy.context.scene.collection
        collection = coll_scene.children.get(i.get('name'))
        if i.get('__parent'):
          coll_target = coll_scene.children.get(i.get('__parent'))
          if coll_target:
            coll_target.children.link(collection)

      if i.get('class') == 'ScatterSky':
        sky_texture = bpy.context.scene.world.node_tree.nodes.new("ShaderNodeTexSky")
        bg = bpy.context.scene.world.node_tree.nodes["Background"]
        bpy.context.scene.world.node_tree.links.new(bg.inputs["Color"], sky_texture.outputs["Color"])
        sky_texture.sky_type = 'NISHITA'
        sky_texture.sun_disc = True
        sky_texture.sun_elevation = math.radians(int(i.get('elevation'))) or math.radians(40)
        sky_texture.sun_rotation = math.radians(int(i.get('azimuth'))) or math.radians(60)
        sky_texture.sun_size = math.radians(1)
        sky_texture.sun_intensity = 0.4
        #sky_texture.strength = 0.4

      if i.get('class') == 'CameraBookmark':
        print(str(i.get('internalName')))
        position = i.get('position') or [0,0,0]
        rot = i.get('rotationMatrix') or [0,0,0,0,0,0,0,0,0]
        rotationMatrix = mathutils.Matrix([[rot[0], rot[1], rot[2]], [rot[3], rot[4], rot[5]], [rot[6], rot[7], rot[8]]]).transposed()
        rotationEuler = rotationMatrix.to_euler()
        internalName = i.get('internalName') or i.get('class')
        name = internalName
        cam = bpy.data.cameras.new(name=name)
        o = bpy.data.objects.new(name, cam)
        o.location = position
        o.rotation_euler = rotationEuler
        if coll_scene.children.get(i.get('__parent')):
          bpy.data.collections[i.get('__parent')].objects.link( o )

      if i.get('class') == 'SFXEmitter':
        print(str(i.get('name')))
        position = i.get('position') or [0,0,0]
        scale = i.get('scale') or [0,0,0]
        rot = i.get('rotationMatrix') or [0,0,0,0,0,0,0,0,0]
        rotationMatrix = mathutils.Matrix([[rot[0], rot[1], rot[2]], [rot[3], rot[4], rot[5]], [rot[6], rot[7], rot[8]]]).transposed()
        rotationEuler = rotationMatrix.to_euler()
        name = i.get('name') or i.get('class')
        bpy.ops.object.speaker_add(enter_editmode=False, location=position, rotation=rotationEuler, scale=scale)
        o = bpy.data.objects['Speaker']
        o.name = name
        if coll_scene.children.get(i.get('__parent')):
          bpy.data.collections[i.get('__parent')].objects.link( o )

      if i.get('class') == 'SpotLight':
        print(str(i.get('name')))
        position = i.get('position') or [0,0,0]
        scale = i.get('scale') or [1,1,1]
        rot = i.get('rotationMatrix') or [0,0,0,0,0,0,0,0,0]
        rotationMatrix = mathutils.Matrix([[rot[0], rot[1], rot[2]], [rot[3], rot[4], rot[5]], [rot[6], rot[7], rot[8]]]).transposed()
        rotationEuler = rotationMatrix.to_euler()
        rotationEuler.rotate_axis('X', math.radians(90))
        name = i.get('name') or i.get('class')
        brightness = i.get('brightness') or 1
        color = i.get('color') or [1,1,1]
        color = (color[0],color[1],color[2])
        bpy.ops.object.light_add(type='SPOT', location=position, rotation=rotationEuler, scale=scale)
        ob = bpy.data.objects['Spot']
        o = bpy.data.lights['Spot']
        ob.name = name
        o.energy = brightness*100
        o.color = color
        if coll_scene.children.get(i.get('__parent')):
          bpy.data.collections[i.get('__parent')].objects.link( ob )

      if i.get('class') == 'PointLight':
        print(str(i.get('name')))
        position = i.get('position') or [0,0,0]
        scale = i.get('scale') or [1,1,1]
        rot = i.get('rotationMatrix') or [0,0,0,0,0,0,0,0,0]
        rotationMatrix = mathutils.Matrix([[rot[0], rot[1], rot[2]], [rot[3], rot[4], rot[5]], [rot[6], rot[7], rot[8]]]).transposed()
        rotationEuler = rotationMatrix.to_euler()
        name = i.get('name') or i.get('class')
        brightness = i.get('brightness') or 1
        color = i.get('color') or [1,1,1]
        color = (color[0],color[1],color[2])
        bpy.ops.object.light_add(type='POINT', location=position, rotation=rotationEuler, scale=scale)
        ob = bpy.data.objects['Point']
        o = bpy.data.lights['Point']
        ob.name = name
        o.energy = brightness*100
        o.color = color
        if coll_scene.children.get(i.get('__parent')):
          bpy.data.collections[i.get('__parent')].objects.link( ob )

      if i.get('class') == 'GroundPlane':
        print(str(i.get('class')))
        position = i.get('position') or [0,0,0]
        rot = i.get('rotationMatrix') or [0,0,0,0,0,0,0,0,0]
        rotationMatrix = mathutils.Matrix([[rot[0], rot[1], rot[2]], [rot[3], rot[4], rot[5]], [rot[6], rot[7], rot[8]]]).transposed()
        rotationEuler = rotationMatrix.to_euler()
        name = i.get('class')
        bpy.ops.mesh.primitive_plane_add(size=100000, calc_uvs=True, enter_editmode=False, location=position, rotation=rotationEuler)
        o = bpy.data.objects['Plane']
        o.name = name
        if coll_scene.children.get(i.get('__parent')):
          bpy.data.collections[i.get('__parent')].objects.link( o )

      if i.get('class') == 'WaterBlock':
        print(str(i.get('name')))
        position = i.get('position') or [0,0,0]
        scale = i.get('scale') or [1,1,1]
        scale = (scale[0], scale[1], scale[2]/2)
        offset = scale[2]
        position = (position[0], position[1], position[2]-offset)
        rot = i.get('rotationMatrix') or [0,0,0,0,0,0,0,0,0]
        rotationMatrix = mathutils.Matrix([[rot[0], rot[1], rot[2]], [rot[3], rot[4], rot[5]], [rot[6], rot[7], rot[8]]]).transposed()
        rotationEuler = rotationMatrix.to_euler()
        name = i.get('name') or i.get('class')
        bpy.ops.mesh.primitive_cube_add(calc_uvs=True, enter_editmode=False, location=position, rotation=rotationEuler, scale=scale)
        o = bpy.data.objects['Cube']
        o.name = name
        if coll_scene.children.get(i.get('__parent')):
          bpy.data.collections[i.get('__parent')].objects.link( o )

      if not terrainExport == "":
        if i.get('class') == 'TerrainBlock':
          print(str(i.get('terrainFile')))
          res = 0
          for k in terrain_data:
            if k.get('datafile') == i.get('terrainFile'):
              res = k.get('size')
          offset = res/2
          position = i.get('position') or [0,0,0]
          position = (position[0]+offset, position[1]+offset, position[2])
          sqrSize = i.get('squareSize') or 1
          scale = [sqrSize,sqrSize,1]
          rot = i.get('rotationMatrix') or [0,0,0,0,0,0,0,0,0]
          rotationMatrix = mathutils.Matrix([[rot[0], rot[1], rot[2]], [rot[3], rot[4], rot[5]], [rot[6], rot[7], rot[8]]]).transposed()
          rotationEuler = rotationMatrix.to_euler()
          name = i.get('class')
          bpy.ops.mesh.primitive_plane_add(size=res, calc_uvs=True, enter_editmode=False, location=position, rotation=rotationEuler)
          o = bpy.data.objects['Plane']
          o.scale = scale
          o.name = name
          sub = o.modifiers.new("SubsurfModifier", 'SUBSURF')
          sub.levels = 11
          sub.render_levels = 11
          sub.subdivision_type = 'SIMPLE'
          disp = o.modifiers.new("DisplaceModifier", 'DISPLACE')
          disp.texture_coords = 'UV'
          disp.mid_level = 0
          for m in terrainMats:
            mat = bpy.data.materials.get(m)
            if mat:
              o.data.materials.append(mat)
              o.active_material_index = len(o.data.materials)-1
          disp.strength = i.get('maxHeight') or 2048
          texFile = ""
          for file in os.listdir(terrainExport):
            if file.endswith('heightmap.png') or file.endswith('heightMap.png'):
              texFile = terrainExport + file
          tex = bpy.data.textures.new(i.get('class')+'_heightmap', 'IMAGE')
          tex.image = bpy.data.images.load(texFile)
          tex.image.colorspace_settings.name = imageSpace
          disp.texture = bpy.data.textures[i.get('class')+'_heightmap']
          for poly in o.data.polygons:
            poly.use_smooth = True
          if coll_scene.children.get(i.get('__parent')):
            bpy.data.collections[i.get('__parent')].objects.link( o )

      if i.get('class') == 'TSStatic':
        print(str(i.get('shapeName')))
        position = i.get('position') or [0,0,0]
        scale = i.get('scale') or [1,1,1]
        rot = i.get('rotationMatrix') or [0,0,0,0,0,0,0,0,0]
        rotationMatrix = mathutils.Matrix([[rot[0], rot[1], rot[2]], [rot[3], rot[4], rot[5]], [rot[6], rot[7], rot[8]]]).transposed()
        rotationEuler = rotationMatrix.to_euler()
        shapeName = i.get('shapeName')
        model = os.path.split(shapeName)
        name = model[1]
        o = bpy.data.objects.new( name, None )
        o.empty_display_type = 'ARROWS'
        o.location.x = position[0]
        o.location.y = position[1]
        o.location.z = position[2]
        o.scale = scale
        o.rotation_euler = rotationEuler
        if coll_scene.children.get(i.get('__parent')):
          bpy.data.collections[i.get('__parent')].objects.link( o )
          try:
            ob = bpy.data.objects[model[1]].data
            cp = bpy.data.objects.new(ob.name, ob)
            bpy.data.collections[i.get('__parent')].objects.link( cp )
            cp.parent = o
          except:
            print("Failed skipping")
            pass

    bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=1)
    collection = bpy.data.collections.new('ForestData')
    bpy.context.scene.collection.children.link(collection)
    print("Importing Forest Data")
    for i in forest_data:
      print(str(i.get('type')) + str(i.get('pos')))
      position = i.get('pos') or [0,0,0]
      rot = i.get('rotationMatrix') or [0,0,0,0,0,0,0,0,0]
      rotationMatrix = mathutils.Matrix([[rot[0], rot[1], rot[2]], [rot[3], rot[4], rot[5]], [rot[6], rot[7], rot[8]]]).transposed()
      rotationEuler = rotationMatrix.to_euler()
      type = i.get('type')
      o = bpy.data.objects.new( type, None )
      o.empty_display_type = 'ARROWS'
      o.location.x = position[0]
      o.location.y = position[1]
      o.location.z = position[2]
      o.rotation_euler = rotationEuler
      bpy.data.collections['ForestData'].objects.link( o )
      try:
        ob = bpy.data.objects[forestNames[type]].data
        cp = bpy.data.objects.new(forestNames[type], ob)
        bpy.data.collections['ForestData'].objects.link( cp )
        cp.parent = o
      except:
        print("Failed skipping")
        pass

    ShowMessageBox("Finished running script successfully")
    print("Finished :)")
    return {'FINISHED'}
    ShowMessageBox("Now you can run exporter!")
    BeamNGLevelImporter.issues.append("Now you can run exporter")
    BeamNGLevelImporter.status = 1