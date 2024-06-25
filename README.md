# BeamNG Level Importer + BeamNG Modding Tools
BeamNG Level Importer is a Blender addon that allows you to import BeamNG levels with all assets into a Blender scene with the correct location, rotation and scale. Imported assets will have all materials assigned with their texture maps.

<img src="https://media.beamng.com/LsSu3WLCSALBgf2i" width="512">

BeamNG Modding Tools is a lua extension for BeamNG that allows exporting your level files from game to make them more compatible with Blender
importer as well as convert your material files from TorqueScript (CS) to JSON.

<img src="https://media.beamng.com/dUPY0lx2yEqxB0d7" width="462">

Many features of BeamNG Modding Tools are now available in World Editor -> Window -> Resources Checker.

## Features
### BeamNG Level Importer
- Default TOD settings as Nishita sky
- Basic Terrain Materials v1.5 importing (WIP)
- Materials V0 support
- Materials v1.5 support
- BeamNG mod zip content importing
- TerrainBlock importing
- WaterBlock importing as a cube
- SpotLight and PointLight importing
- WaterPane importing as flat pane
- CameraBookmarks importing
- SoundEmitters importing
- GroundPane importing
- SceneTree folders structure
- ForestItems importing and placement

### BeamNG Modding Tools
- World Editor integration
- Standalone mode
- Legacy TorqueScript (CS) materials converter to JSON
- Cleaning up of TorqueScript (CS) materials
- Batch converting
- DDS to PNG exporter (opposite tool to Texture Cooker)
- Game meshes to COLLADA exporter
- Game meshes to Wavefront exporter
- BeamNG to Blender Exporting (game side)
- Soft Reloading of vehicle materials
- Hard Reloading of vehicle materials
- Removal of vehicle's temporary files

## Plans
### BeamNG Level Importer
- Add full Terrain Materials v1.5 support
- Add Terrain Materials v0 support
- Implement assimp importer to import incompatible COLLADA meshes
- TorqueScript levels and materials importing
- Legacy JSON levels support
- In Blender level editing and changes saving support
- Particle emitters support
- Decal data importing
- River objects importing
- Groundcover support
- Decal road support
- Mesh Road support
- Lower level of detail meshes importing
- More materials features support

### BeamNG Modding Tools
- Possibly better mesh exporters from GameEngine

## Issues
### BeamNG Level Importer
- Many legacy COLLADA files won't import due to issues with Blender COLLADA importer
- Random TerrainBlock placement issues in some corner cases
- Missing emissive textures in Blender 4.0+ due to shader changes
- Probably a lot more issues that I don't know of

### BeamNG Modding Tools
- Broken PNG exporting in Vulkan API mode
- Crashes when removing old CS materials when loaded into a level
- Unexpected results of COLLADA and Wavefront exports from GameEngine

## BeamNG Level Importer Requirements
- OS: Windows or Linux
- Blender: 3.0 or newer (3.6 LTS is targetted, includes a partial implementation for 4.0 and 4.1)

## BeamNG Modding Tools Requirements
- OS: Windows or Linux or Wine/Proton
- BeamNG.drive v0.31 or newer
- Direct3D 11 mode (Vulkan API might be buggy when exporting textures)

## BeamNG Level Importer Installation
- Make sure you met requirements above
- Download addon from [releases](https://github.com/PrzemekWolw/BeamNGLevelImporter/releases) tab. Make you download Blender addon not source code or BeamNG extension.
- Open Blender to install addon.
- Go to preferences, addons, and install addon from zip there.

## BeamNG Modding Tools Installation
- Make sure you met requirements above
- Download addon from [releases](https://github.com/PrzemekWolw/BeamNGLevelImporter/releases) tab. Make you downloaded BeamNG extension not source code or Blender addon.
- Copy downloaded zip into your BeamNG mods folder

## Usage
### BeamNG Level Importer
#### Importing levels
- Load BeamNG.drive
- Load level you want to export
- Open BeamNG Modding Tools by pressing `=`
- Go to `Exporter` tab and press `Export level to Blender` and wait till the process finishes
- Close BeamNG and launch Blender
- In the Blender sidebar open BeamNG Level Importer
- Select the level zip or folder you want to import, make sure to enable `Use ZIP Level` if you are importing zipped files
- In `Exporter terrain Path` select your level export location which usually is your userfolder `/temp/exported/levels/levelname`
- Press `Import Level Objects`

## BeamNG Modding Tools
### Generating new materials for old mods
- Start the game
- Insert a path to the folder of your mod that you want to convert
- Press the `Convert` button
- Copy the generated .json files from your userfolder back to your source files and remove all material.cs files, remove the cache of your mod.

### Exporting textures or meshes
- Start the game
- Insert a path to folder of your mod which you want to export
- Go to the `Exporter` tab
- Press the button you want to use
- Your exports will be available in your userfolder `/temp/exported/`

## FAQ / Troubleshooting
### My game crashes when converting CS materials
 - Try converting your mod in main menu before you even load any level to avoid issues and leave more RAM space for conversion. Game may hang when converting.
### Many meshes from my level are not visible in Blender import, most of them are just empties
 - Some COLLADA meshes are unsupported by Blender. You can try converting them yourself in other software first to avoid issues.
### I cannot seem to be able to export textures from the game
- Game might fail to export textures and levels when running in Vulkan API mode.

## Credits
Special thanks to [@thomatoes50](https://github.com/thomatoes50) who helped me to clean lua code. In addition, I want to thanks for the original resource explorer code that was made to help me working on Polish Roads.

Additional thanks for testing and giving ideas to: [@AgentMooshroom5](https://www.beamng.com/members/272928/), [@bob.blunderton](https://www.beamng.com/members/102419/), [@DankMemeBunny](https://www.beamng.com/members/163405/), [@falefee](https://www.beamng.com/members/52708/), [@Nekkit](https://www.beamng.com/members/315904/).

## License
This project is licensed under the MIT license. See LICENSE for more information.