------ BEGIN LICENSE BLOCK
--
-- This program is licensed under The MIT License:
-- see LICENSE for the full license text
--
------ END LICENSE BLOCK

local M = {}

local workJob

local convertAPI = extensions.util_ckmaterialsAPI

local function onExtensionUnloaded()
  extensions.unload('util_ckmaterialsConverter')
end

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

local function work(job, imguilist, rem)
  job.progress = 0
  local isDone
  --load path from file
  local modpath = imguilist
  --print(modpath)
  if not modpath then
    log('E', '', 'You didn\'t set the path in ' .. dumps(imguilist))
    isDone = 2
    return
  end
  if not FS:directoryExists(modpath) then
    log('E', '', 'The path ' .. dumps(modpath).. ' does not exist!')
    isDone = 2
    return
  end

  local persistenceMgr = PersistenceManager()
  persistenceMgr:registerObject('matResave_PersistMan')
  job.progress = 5

  -- for now we only convert materials.cs
  local files = FS:findFiles(modpath, 'materials.cs\tmanaged*Data.csNOP', -1, true, false)
  local fixedFiles = {}
  for k,v in ipairs(files) do
    if string.find(v, "mods") then
      fixedFiles[k] = v:gsub('mods/(%a+)/(%a+)/', '')
    else
      fixedFiles[k] = v
    end
  end
  job.progress = 25
  files = fixedFiles
  log('I', '', 'Welcome in Materials Converter v2.0 for my dear imgui by CK!' )
  log('I', '', 'loading material' )
  --repeat if there is still something in cs
  ::notempty::
  for _, fn in ipairs(files) do
    local dir, basefilename, ext = path.splitWithoutExt(fn)
    local objects = {}

    if getFileSize(fn) > 0 then
      TorqueScript.exec(fn)
      objects = getSimObjects(fn)
    end

    if not tableIsEmpty(objects) then
      log('I', '', 'parsing materials file: ' .. tostring(fn))

      for _, obj in ipairs(objects) do
        -- the old material files can also contain other stuff ...
        log('I', '', ' * ' .. tostring(obj:getClassName()) .. ' - ' .. tostring(obj:getName()) )
        --convertinginfo = tostring(obj:getName())
        if job.progress < 70 then
          job.progress = job.progress + 0.1
        end
        persistenceMgr:setDirty(obj, '')
        job.yield()
      end
      persistenceMgr:saveDirtyNewFormat()

      for _, obj in ipairs(objects) do
        obj:delete()
      end

      --persistenceMgr:clearAll()
    end
    job.sleep(0.001)
  end
  --do we need to repeat script?
  for _, fn in ipairs(files) do
    local dir, basefilename, ext = path.splitWithoutExt(fn)
    local objects_test = {}

    if getFileSize(fn) > 0 then
      TorqueScript.exec(fn)
      objects_test = getSimObjects(fn)
    end

    if not tableIsEmpty(objects_test) then
      log('W', '', 'There are still materials left, repeating job!')
      goto notempty
    end
  end
  job.progress = 80

  if rem == true then
    log('I', '', 'removing old materials' )
    for k,v in ipairs(files) do
      job.yield()
      if FS:removeFile(v) ~= 0 then
        log('E', '', 'Could not remove old file: ' .. tostring(v))
      end
    end
  end
  convertAPI.filesFixer(modpath)

  persistenceMgr:delete()
  job.progress = 100
  isDone = 1
  local data = isDone
  extensions.editor_ckmaterials.jobData(1, data)
  log('I', '', 'DONE')
  onExtensionUnloaded()
  --jobsystem test
  --print(core_jobsystem.getRunningJobCount())
  --don't turn off game when you are converting from imgui
  --log('I', '', 'Goodbye!')
  --shutdown(0)
end

local function onExtensionLoaded()

end

local function startJob(convertdata, rem)
  workJob = extensions.core_jobsystem.create(work, 1, convertdata, rem) -- yield every second, good for background tasks
end

local function getProgress()
  if workJob and workJob.running then
    return workJob.progress
  end
end

-- interface
M.onExtensionLoaded = onExtensionLoaded
M.onExtensionUnloaded = onExtensionUnloaded
M.getProgress = getProgress
M.startJob = startJob

return M