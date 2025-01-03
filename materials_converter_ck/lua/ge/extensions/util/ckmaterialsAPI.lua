------ BEGIN LICENSE BLOCK
--
-- This program is licensed under The MIT License:
-- see LICENSE for the full license text
--
------ END LICENSE BLOCK

local M = {}

local objects = nil

local luaType = type
local im = ui_imgui
local ffi = require("ffi")

local function onExtensionUnloaded()
  extensions.unload('util_ckmaterialsAPI')
end

--get scene tree all objects
local function getSimObjects(fileName)
  local ret = {}
  local objs = scenetree.getAllObjects()
  --log('E', '', '# objects existing: ' .. tostring(#scenetree.getAllObjects()))
  for _, objName in ipairs(objs) do
    local o = scenetree.findObject(objName)
    if o and o.getFileName then
      if o:getFileName() == fileName then
        table.insert(ret, o)
      end
    end
  end
  return ret
  --log('E', '', '# objects left: ' .. tostring(#scenetree.getAllObjects()))
end

--write stuff into player disk
local function _write2File(filename,data)
  local f = io.open(filename, "w")
  if not f then
    log("E", "writeFile", "can't open file "..dumps(filename))
    return
  end
  for k,v in pairs(data) do
    f:write(tostring(k)..","..tostring(v)..",\n")
  end
  f:close()
end

--rename files after conversion
local function filesFixer(modpath)
  log('I', '', 'Optimizing files' )
  local isDone
  local type = 4
  local count = 0
  local changed = {}
  if not modpath then
    log('E', '', 'There is no material path' )
    isDone = 2
  elseif not string.match(modpath, "/") then
    log('E', '', 'Incorrect path' )
    isDone = 2
  else
    local filesToFix = FS:findFiles(modpath, 'materials.json', -1, true, false)
    local fixedFiles = {}
    for k,v in ipairs(filesToFix) do
      if string.find(v, "mods") then
        fixedFiles[k] = v:gsub('mods/(%a+)/(%a+)/', '')
      else
        fixedFiles[k] = v
      end
    end
    filesToFix = fixedFiles

    for k,v in ipairs(filesToFix) do
      count = count +1
      table.insert(changed, v)
      local path = v:gsub('materials.json', '')
      if FS:renameFile(v, path.."ckconverted.materials.json") ~= 0 then
        count = count -1
        log('E', '', 'Could not fix file: ' .. tostring(v))
      end
    end
    isDone = 1
    log('I', '', 'Fixed all files' )
    log('I', '', 'Fixed '..count..' materials' )
    _write2File("ckmaterials_fixedFiles.csv",changed)
  end
  local data = {type, count, "dummy", changed, isDone}
  return data
end

--get player level
local function getLevel()
  log('I', '', 'Getting current level path' )
  local getlevel = getCurrentLevelIdentifier()
  local levelpath
  -- idiot proof
  if not getlevel then
    log('E', '', 'Level not loaded' )
    levelpath = "Please load level before getting path"
  else
    -- level loaded
    log('I', '', 'Level is loaded' )
    levelpath = ("/levels/" .. getlevel .. "/")
  end
  return levelpath
end

--get material layers fields
local function getMaterialTexFields(mat)
  local fields = {}
  if mat and mat.___type == "class<Material>" then
    local layers = mat:getField("activeLayers",0)
    local layer = 0
    for i=1, layers do
      for k,v in pairs(mat:getFields()) do
        if v["type"] == "filename" then
          fields[k.."."..layer] = mat:getField(k,layer)
        end
      end
      layer = layer + 1
    end
    return fields
  else
    log('E', '', 'Material not found' )
  end
end

--get player vehicle
local function getPlayerVehicle()
  log('I', '', 'Getting current vehicle path' )
  local vehid = be:getPlayerVehicleID(0)
  local vehiclepath
  -- idiot proof
  if string.match(vehid, "-1") then
    log('E', '', 'There is no player vehicle' )
    vehiclepath =  "Please make sure you have seated vehicle"
  else
    -- vehicle exist
    local getveh = scenetree.findObjectById(vehid)
    local playerveh = getveh.JBeam
    --print(playervehicle)
    vehiclepath = ("/vehicles/" .. playerveh .. "/")
  end
  return vehiclepath
end

local countduplicate = 0
local duplicatedM = {}
local duplicatedN = {}
local duplicatedPID = {}

--exporters

local shapeExporterworkJob

local function shapeExporterwork(job, convertdata, extension)
  local verifydata = convertdata
  local isDone
  job.progress = 0
  job.sleep(0.001)
  if not verifydata then
    log('E', '', 'There is no material path' )
    isDone = 2
  elseif not string.match(verifydata, "/") then
    log('E', '', 'Incorrect path' )
    isDone = 2
  else
    log('I', '', 'Exporting meshes' )

    --V2, shortcode much more efficient, checks all types of files at once
    local meshFiles = FS:findFiles(verifydata, "*.dae\t*.dts\t*.cdae\t*.cached.dts", -1, true, false)
    for k,v in ipairs(meshFiles) do
      if job.progress < 98 then
        job.progress = job.progress + 0.1
      end
      job.yield()
      local dir, basefilename, ext = path.splitWithoutExt(v)
      local shapeLoader
      if not shapeLoader then
        shapeLoader = ShapePreview()
      end
      shapeLoader:setObjectModel(v)
      local patchSplit = {}
      for part in string.gmatch("/temp/exported"..dir, "([^/]+)") do
        table.insert(patchSplit, part)
      end
      local current_path = ""
      for i, part in ipairs(patchSplit) do
          current_path = current_path .. "/" .. part
          if not FS:directoryExists(current_path) then FS:directoryCreate(current_path) end
      end
      if extension == 1 then
        shapeLoader:exportToCollada("/temp/exported"..dir..basefilename..".dae")
        log('I', 'Converted TSStatic to DAE: ' .. tostring(v))
      end
      if extension == 2 then
        shapeLoader:exportToWavefront("/temp/exported"..dir..basefilename..".obj")
        log('I', 'Converted TSStatic to OBJ: ' .. tostring(v))
      end
      shapeLoader:clearShape()
    end
    job.progress = 100
    job.sleep(0.001)
    isDone = 1
  end
  extensions.editor_ckmaterials.jobData(4, isDone)
end

local function shapeExporter(convertdata, extension)
  shapeExporterworkJob = extensions.core_jobsystem.create(shapeExporterwork, 1, convertdata, extension)
end

local textureExporterworkJob

local function textureExporterwork(job, convertdata)
  local verifydata = convertdata
  local isDone
  job.progress = 0
  job.sleep(0.001)
  if not verifydata then
    log('E', '', 'There is no material path' )
    isDone = 2
  elseif not string.match(verifydata, "/") then
    log('E', '', 'Incorrect path' )
    isDone = 2
  else
    log('I', '', 'Exporting textures to PNG' )

    --V2, shortcode much more efficient, checks all types of files at once
    local meshFiles = FS:findFiles(verifydata, "*.dds", -1, true, false)
    for k,v in ipairs(meshFiles) do
      if job.progress < 98 then
        job.progress = job.progress + 0.1
      end
      job.yield()
      local dir, basefilename, ext = path.splitWithoutExt(v)
      local filepathIn = v
      local filepath = "temp/exported/"..dir..basefilename..".png"
      if not convertDDSToPNG(filepathIn, filepath) then
        log('E', 'Unable to convert dds to png: ' .. tostring(filepathIn))
      end
      log('I', 'Converted dds to png: ' .. tostring(filepath))
    end
    job.progress = 100
    job.sleep(0.001)
    isDone = 1
  end
  extensions.editor_ckmaterials.jobData(4, isDone)
end

local function textureExporter(convertdata)
  textureExporterworkJob = extensions.core_jobsystem.create(textureExporterwork, 1, convertdata)
end

local blenderExporterworkJob

local function blenderExporterwork(job, convertdata)
  local verifydata = convertdata
  local isDone
  job.progress = 0
  job.sleep(0.001)
  if not verifydata then
    log('E', '', 'There is no material path' )
    isDone = 2
  elseif not string.match(verifydata, "/") or not string.match(verifydata, "levels/") then
    log('E', '', 'Incorrect path' )
    isDone = 2
  else
    log('I', '', 'Exporting level' )

    --V2, shortcode much more efficient, checks all types of files at once
    local meshFiles = FS:findFiles(verifydata, "*.dds", -1, true, false)
    for k,v in ipairs(meshFiles) do
      if job.progress < 50 then
        job.progress = job.progress + 0.1
      end
      job.yield()
      local dir, basefilename, ext = path.splitWithoutExt(v)
      local filepathIn = v
      local filepath = "temp/exported/"..dir..basefilename..".png"
      if not convertDDSToPNG(filepathIn, filepath) then
        log('E', 'Unable to convert dds to png: ' .. tostring(filepathIn))
      end
      log('I', 'Converted dds to png: ' .. tostring(filepath))
    end
    job.progress = 50
    local terrain = core_terrain.getTerrain()
    if terrain then
      local filepath = "temp/exported/"..verifydata.."/"
      terrain:exportHeightMap(filepath..'heightMap.png', 'png')
      terrain:exportHoleMaps(filepath..'holeMap', 'png')
      terrain:exportLayerMaps(filepath..'layerMap', 'png')
      log('I', 'Exported current terrain layers: '..filepath)
    end
    job.progress = 100
    job.sleep(0.001)
    isDone = 1
  end
  extensions.editor_ckmaterials.jobData(4, isDone)
end

local function shapeDecompiler(meshesTable)
  if not meshesTable then
    log('E', '', 'There is no material path' )
  else
    log('I', '', 'Exporting meshes' )

    --V2, shortcode much more efficient, checks all types of files at once
    for k,v in ipairs(meshesTable) do
      local dir, basefilename, ext = path.splitWithoutExt(v)
      local shapeLoader
      if not shapeLoader then
        shapeLoader = ShapePreview()
      end
      shapeLoader:setObjectModel(v)
      if not FS:directoryExists("temp/exported/"..dir) then FS:directoryCreate("temp/exported/"..dir) end
      shapeLoader:exportToCollada("temp/exported/"..dir..basefilename..".dae")
      log('I', 'Converted TSStatic to DAE: ' .. tostring(v))
      shapeLoader:clearShape()
    end
  end
  log('I', '', 'Goodbye!')
  shutdown(0)
end

local function blenderExporter(convertdata)
  blenderExporterworkJob = extensions.core_jobsystem.create(blenderExporterwork, 1, convertdata)
end

--reloading materials (not a coroutine)
local function matReload(convertdata, optional)
  local verifydata = convertdata
  if not verifydata then
    log('E', '', 'There is no material path' )
  elseif not string.match(verifydata, "/") then
    log('E', '', 'Incorrect path' )
  else
    log('I', '', 'Forcing reload materials' )

    local materialFiles = FS:findFiles(verifydata, "*.cs\t*materials.json", -1, true, false)
    local fixedFiles = {}
    for k,v in ipairs(materialFiles) do
      if string.find(v, "mods") then
        fixedFiles[k] = v:gsub('mods/(%a+)/(%a+)/', '')
      else
        fixedFiles[k] = v
      end
    end
    materialFiles = fixedFiles

    if materialFiles then
      log('I', '', 'Updating material files' )
      FS:triggerFilesChanged(materialFiles)
    end

    for _, filename in ipairs(materialFiles) do
      if string.find(filename, 'materials.cs$') then
        TorqueScript.exec(filename)
        objects = getSimObjects(filename)
      elseif string.find(filename, 'materials.json$') then
        loadJsonMaterialsFile(filename)
        objects = getSimObjects(filename)
      end
      if optional == 1 then
        if not tableIsEmpty(objects) then
          log('I', '', 'parsing all materials file: ' .. tostring(filename))

          for _, obj in ipairs(objects) do
            -- the old material files can also contain other stuff ...
            if obj.___type == "class<Material>" then
              local maxLayers = obj.activeLayers
              local files = {}
              log('I', '', ' * Reloading - ' .. tostring(obj:getClassName()) .. ' - ' .. tostring(obj:getName()))
              for k,v in pairs(obj:getFields()) do
                if v.type == "filename" then
                  for i=0,maxLayers-1 do
                    local filepath = obj:getField(k, i)
                    if tmp ~= "" and string.sub(filepath, 1, 1) ~= '/' then
                      filepath = "/"..filepath
                    end
                    if tmp ~= "" and FS:fileExists(filepath) then
                      log("D", "reloadTex", dumps(k).."["..dumps(i).."]="..dumps(filepath))
                      files[#files+1] = filepath
                    end
                  end
                end
              end
              if #files then
                log('I', '', 'Updating textures files' )
                FS:triggerFilesChanged(files)
              end
            end
          end
        end
      end
    end

    log('I', '', 'Reloading Vehicle' )
    local physicsreset = be:reloadVehicle(0)
    log('I', '', 'MATERIALS RELOADED' )
  end
end

local function resetCache(convertdata)
  local verifydata = convertdata
  if not verifydata then
    log('E', '', 'There is no material path' )
  elseif not string.match(verifydata, "/") then
    log('E', '', 'Incorrect path' )
  else
    log('I', '', 'Resetting temporary files' )
    local tempPath = "/temp/"..verifydata
    local tempFiles = FS:directoryRemove(tempPath)

    local badMeshes = FS:findFiles(verifydata, "*.cdae\t*.cached.dts", -1, true, false)

    if badMeshes then
      log('I', '', 'Removing problematic files' )
      for k,v in ipairs(badMeshes) do
        log('I', '', 'Removing '..v )
        FS:removeFile(v)
      end
      FS:triggerFilesChanged(badMeshes)
    end

    local meshFiles = FS:findFiles(verifydata, "*.dae", -1, true, false)
    if meshFiles then
      log('I', '', 'Updating mesh files' )
      FS:triggerFilesChanged(meshFiles)
    end
    matReload(verifydata)
  end
end
--interface
local function getProgress()
  if shapeExporterworkJob and shapeExporterworkJob.running then
    return shapeExporterworkJob.progress
  end
  if textureExporterworkJob and textureExporterworkJob.running then
    return textureExporterworkJob.progress
  end
  if blenderExporterworkJob and blenderExporterworkJob.running then
    return blenderExporterworkJob.progress
  end
end


local function onExtensionLoaded()
end

-- interface
M.onExtensionLoaded = onExtensionLoaded
M.onExtensionUnloaded = onExtensionUnloaded
M._write2File = _write2File
M.filesFixer = filesFixer
M.getLevel = getLevel
M.getMaterialTexFields = getMaterialTexFields
M.getPlayerVehicle = getPlayerVehicle
M.shapeExporter = shapeExporter
M.textureExporter = textureExporter
M.blenderExporter = blenderExporter
M.shapeDecompiler = shapeDecompiler
M.matReload = matReload
M.resetCache = resetCache
M.getProgress = getProgress

return M