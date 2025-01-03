------ BEGIN LICENSE BLOCK
--
-- This program is licensed under The MIT License:
-- see LICENSE for the full license text
--
------ END LICENSE BLOCK

--extensions.editor_ckmaterials.show()

local windowOpen = ui_imgui.BoolPtr(false)

local M = {}
M.dependencies = {"ui_imgui"}

local logTag = 'addon_ck_ckmaterials'
local im = ui_imgui
local convertAPI = extensions.util_ckmaterialsAPI
local convertUtil = extensions.util_ckmaterialsConverter
local ffi = require("ffi")

--independent GUI
local showUI = nil
local tempFloat = nil

local matdata = im.ArrayChar(256)
local convertdata
local removeCS = false

--game version
local ver = nil
local bigver = nil

--platforms
local isVulkan = 0
local isLinux = 0

--da app info
local tool_version = "2.0.1"
local appTitle = " Car_Killer Modding Tools - ".. tool_version .." - ".. beamng_buildtype .." - ".. beamng_arch

local toolWindowName = 'addon_ckmaterials'

--game version check
local function gameVER()
  ver = beamng_version
  bigver = string.format("%0.4s", ver)
  --print(bigver)

end

--get api info to prevent vk
local function getGFX()
  gameVER()
  --print(gfx)
  if tonumber(bigver) <= 0.22 then
    isVulkan = 2
    log('E', '', 'Cannot retrieve API information' )
    log('E', '', 'Old game version detected' )
  else
    local gfx = Engine.Render.getAdapterType()
    if not string.match(gfx, "Direct3D11") then
      isVulkan = 1
      log('W', '', 'Vulkan API mode detected' )

      else
      log('I', '', 'Vulkan API mode not detected' )
    end
  end
end

--get os version
local function getOS()
  local os = Engine.Platform.getOSInfo()
  --print(dump(os))
  --print(os.shortname)
  if not os.shortname == "Windows" then
    isLinux = 1
    log('W', '', 'Linux Detected' )

  else
    log('I', '', 'Windows Detected' )
  end
end

local function checkEditor(job, matdata)
  ::notRunning::
  if editor and not editor.active then
    job.sleep(0.1)
    goto notRunning
  else
    editor_fileDialog.openFile(
      function(data)
        ffi.copy(matdata, data.path)
    end, nil, true, "/")
  end
end

local function searchModule()
  im.Spacing()
  --get level path
  if im.Button("Get Current Level path") then
    local levelpath = convertAPI.getLevel()
    ffi.copy(matdata, levelpath)
  end

  im.SameLine()

  --get vehicle path
  if im.Button("Get Seated Vehicle path") then
    local vehiclepath = convertAPI.getPlayerVehicle()
    ffi.copy(matdata, vehiclepath)
  end

  im.SameLine()
  if im.Button("Select directory") then
    if editor and not editor.active then
      editor.toggleActive()
      extensions.core_jobsystem.create(checkEditor, 2, matdata)
    else
      editor_fileDialog.openFile(
        function(data)
          --if not string.find(data.path, "mods") then
            ffi.copy(matdata, data.path)
          --else
            --log('E', '', 'You cannot load files from mods folder! ' )
            --messageBox(" Car_Killer Modding Tools - File Browser", "You are not allowed to load files from mods folder. Please select folder directly by gonig into /vehicles/your_vehicle or /levels/your_level folders.", 0, 0)
          --end
      end, nil, true, "/")
    end
  end

  im.Text("Insert path to files:")
  --im.PushItemWidth(im.GetContentRegionAvailWidth())
  im.PushItemWidth(450)

  if im.InputText("##inputText1", matdata) then
  end

  im.PopItemWidth()
  im.Spacing()
end

local converter

local function getConversionProgress()
  local progress = convertUtil.getProgress()
  return progress
end

local function convTab()
  searchModule()
  local removeCSEnabled = im.BoolPtr(removeCS)
  if im.Checkbox("Remove old cs files", removeCSEnabled) then
    removeCS = removeCSEnabled[0]
  end
  if im.IsItemHovered() then
    im.BeginTooltip()
    im.Text("All leftover material.cs files will be removed from unpacked folders after conversion is done")
    im.EndTooltip()
  end
  local checkdata = ffi.string(matdata) or ""
  local levelID = getCurrentLevelIdentifier()
  if checkdata and levelID and checkdata:find(levelID) then
    im.TextColored(im.ImVec4(1, 1, 0.2, 1), "You cannot convert files that are currently in use")
  else
    if im.Button("Convert") then
      --print(matdata)
      convertdata = ffi.string(matdata)
      --No fuckin idea how to use cdata, so we convert to string
      --print(convertdata)
      if not convertdata then
        log('E', '', 'There is no material path' )
      elseif not string.match(convertdata, "/") then
        log('E', '', 'Incorrect path' )
      else

      log('I', '', 'Starting conversion' )
      convertUtil.startJob(convertdata, removeCS)
      end
    end

    if im.IsItemHovered() then
      im.BeginTooltip()
      im.Text("You'll run conversion job, game might hang if your mod contains large amounts of materials")
      im.EndTooltip()
    end

    im.SameLine()

    if im.Button("Exit game") then
      log('I', '', 'Exiting game per user request' )
      shutdown(0)
    end

    if im.IsItemHovered() then
      im.BeginTooltip()
      im.Text("You'll exit game, now check your user folder for new files")
      im.EndTooltip()
    end

    im.SameLine()

    --info what is going on to user, no need to use console
    if not convertdata then
      im.Text("You didn't set path")
    elseif not string.match(convertdata, "/") then
      im.TextColored(im.ImVec4(1, 1, 0.2, 1), "Incorrect path")
    elseif getConversionProgress() ~= nil then
      im.ProgressBar(getConversionProgress()/100, im.ImVec2(120, 0))
    elseif converter and converter == 1 then
      im.TextColored(im.ImVec4(0.2, 1, 0.2, 1), "Finished Conversion")
    elseif converter and converter == 2 then
      im.TextColored(im.ImVec4(1, 0, 0, 1), "Conversion Failed")
    end
  end
  im.Text("Only for advanced users!")
  if im.Button("Convert all levels") then
    log('I', '', 'Converting all levels' )
    convertdata = ffi.string("/levels/")
    convertUtil.startJob(convertdata, removeCS)
  end

  if im.IsItemHovered() then
    im.BeginTooltip()
    im.Text("This job will convert all levels existing in game universe, game might hang for few minutes")
    im.EndTooltip()
  end

  im.SameLine()

  if im.Button("Convert all vehicles") then
    log('I', '', 'Converting all vehicles' )
    convertdata = ffi.string("/vehicles/")
    convertUtil.startJob(convertdata, removeCS)
  end

  if im.IsItemHovered() then
    im.BeginTooltip()
    im.Text("This job will convert all vehicles available in game universe, game might hang for few minutes")
    im.EndTooltip()
  end
end

local function getApiProgress()
  local progress = convertAPI.getProgress()
  return progress
end

local exporter
local function exportTab()
  searchModule()
  im.Text("This tool is exporting files from game")
  if im.Button("Export Meshes to Collada (DAE)") then
    convertdata = ffi.string(matdata)
    exporter = convertAPI.shapeExporter(convertdata, 1)
  end
  im.SameLine()
  if im.Button("Export Meshes to Wavefront (OBJ)") then
    convertdata = ffi.string(matdata)
    exporter = convertAPI.shapeExporter(convertdata, 2)
  end
  if im.Button("Export DDS Textures to PNG") then
    convertdata = ffi.string(matdata)
    exporter = convertAPI.textureExporter(convertdata)
  end
  im.SameLine()
  if im.Button("Export level to Blender") then
    convertdata = ffi.string(matdata)
    exporter = convertAPI.blenderExporter(convertdata)
  end
  if not exporter and getApiProgress() == nil then
    im.Text("Press one of the buttons to get informations!")
  elseif not exporter and getApiProgress() ~= nil then
    im.ProgressBar(getApiProgress()/100, im.ImVec2(450, 0))
  elseif exporter and exporter == 1 then
    im.TextColored(im.ImVec4(1, 1, 0.2, 1), "Exported files")
  elseif exporter and exporter == 2 then
    im.TextColored(im.ImVec4(1, 1, 0.2, 1), "Export failed")
  end
end

local function renderImgui()
  im.Begin(appTitle, showUI, im.WindowFlags_AlwaysAutoResize)

  im.Text("This tool is here to help you converting materials from cs to json")

  --we need to show if people using vulkan
  if isVulkan == 1 then
    im.TextColored(im.ImVec4(1, 0, 0, 1), "Vulkan API Detected! Some features might be broken")
  end

  --old version info
  if isVulkan == 2 then
    im.TextColored(im.ImVec4(1, 0, 0, 1), "Old game version detected!")
    im.TextColored(im.ImVec4(1, 0, 0, 1), "Can't detect rendering API!")
  end

  --same but Linux
  if isLinux == 1 then
    im.TextColored(im.ImVec4(1, 0, 0, 1), "Linux Detected! Some features might be broken")
  end

  im.Spacing()

  if im.BeginTabBar("tabs") then
    if im.BeginTabItem("Materials Converter", nil, im.TabItemFlags_None) then
      convTab()
      im.EndTabItem()
    end
    if im.BeginTabItem("Exporter", nil, im.TabItemFlags_None) then
      exportTab()
      im.EndTabItem()
    end
  end
  im.Spacing()
  im.Separator()
  im.Spacing()

  im.Text("Current vehicle materials reloading")

  if im.Button("Soft Reload Materials") then
    local vehiclepath = convertAPI.getPlayerVehicle()
    convertAPI.matReload(vehiclepath, 0)
  end
  if im.IsItemHovered() then
    im.BeginTooltip()
    im.Text("Forces reloading vehicle materials")
    im.EndTooltip()
  end

  im.SameLine()

  if im.Button("Hard Reload Materials") then
    local vehiclepath = convertAPI.getPlayerVehicle()
    convertAPI.matReload(vehiclepath, 1)
  end
  if im.IsItemHovered() then
    im.BeginTooltip()
    im.Text("Forces reloading vehicle materials and updates textures")
    im.EndTooltip()
  end

  im.SameLine()

  if im.Button("Reset temporary files") then
    local vehiclepath = convertAPI.getPlayerVehicle()
    convertAPI.resetCache(vehiclepath)
  end
  if im.IsItemHovered() then
    im.BeginTooltip()
    im.Text("You'll reset vehicle cache")
    im.EndTooltip()
  end

  im.Text("Always follow tutorial in util thread!")

  im.End()
end

local function jobData(type, data)
  if type == 1 then
    converter = data
  end
  if type == 4 then
    exporter = data
  end
end

local function onUpdate()
  if not showUI[0] then
    return
  end
  renderImgui()
end

local function onWindowMenuItem()
  showUI[0] = true
end

local function openUI()
  showUI[0] = true
end

local function hideUI()
  showUI[0] = false
end

local function toggleUI()
  if showUI[0] then
    hideUI()
  else
    openUI()
  end
end

local function onExtensionLoaded()
  getGFX(gfx)
  getOS(os)
  if showUI == nil then
    showUI = ui_imgui.BoolPtr(false)
  end
  if not tempFloat then
    tempFloat = ui_imgui.FloatPtr(0)
  end
end


local function onEditorActivated()

end

local function onEditorDeactivated()

end

local function onEditorInitialized()
  editor.addWindowMenuItem("Materials Converter", onWindowMenuItem, {groupMenuName = 'Car_Killer Addons'})
  editor.registerWindow(toolWindowName, im.ImVec2(500, 200))
end

M.show = openUI
M.hide = hideUI
M.toggle = toggleUI
M.onExtensionLoaded = onExtensionLoaded
M.jobData = jobData
M.onUpdate = onUpdate
--M.onEditorGui = onEditorGui
M.onEditorInitialized = onEditorInitialized
M.onEditorActivated = onEditorActivated
M.onEditorDeactivated = onEditorDeactivated

return M