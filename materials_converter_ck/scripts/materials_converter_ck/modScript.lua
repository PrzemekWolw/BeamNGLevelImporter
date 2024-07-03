local m = {}

local convertAPI = extensions.util_ckmaterialsAPI

--Decompiler command listener
local cmdArgs = Engine.getStartingArgs()
local arg = nil
local listString = ""
local meshesTable = {}
for i, v in ipairs(cmdArgs) do
  if v == '-decompileMeshes' then
    arg = i
  end
end
if arg then
  for i, v in ipairs(cmdArgs) do
    if i > arg then
      listString = listString..v
    end
  end
  if listString ~= "" then
    for arg in string.gmatch(listString, '([^,]+)') do
      table.insert(meshesTable, arg)
    end
    dump(meshesTable)
    convertAPI.shapeDecompiler(meshesTable)
  else
    print('String is empty')
  end
end

return m