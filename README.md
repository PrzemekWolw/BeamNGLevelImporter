# BeamNG Level Importer & BeamNG Modding Tools

BeamNG Level Importer is a Blender add-on that imports BeamNG levels into Blender with correct position, rotation, and scale. All assets are brought in with their materials and texture maps properly assigned.

<img src="https://media.beamng.com/0AUIWsArutYp9yZF" width="512">

BeamNG Modding Tools is a Lua extension for BeamNG.drive that converts legacy TorqueScript (`.cs`) material files to modern JSON format.

<img src="https://media.beamng.com/dUPY0lx2yEqxB0d7" width="462">

Many features of BeamNG Modding Tools are now integrated into the game under
**World Editor → Window → Resources Checker**.

---

## Features

### BeamNG Level Importer

- Default time-of-day (TOD) setup using Multiscatter/Nishita sky
- Full support for Terrain Materials v0 and v1.5
- Materials v0 support
- Materials v1.5 support
- Water material support
- Support for relative textures
- Support for common `/art` folder
- Support for `/asset` folder and asset system
- Support for asset linking
- Custom COLLADA and DTS/CDAE importing that supports "locked" models or OpenCollada exports and other problematic mesh files
- `TerrainBlock` importing
- `WaterBlock` importing
- SpotLight and PointLight importing
- `WaterPlane` importing
- `DecalData` and decal instance importing
- River importing
- Groundcover importing
- Decal road importing
- Mesh road importing
- Camera bookmark importing
- Sound emitter importing
- Ground plane importing
- All other classes and their properties importing
- SceneTree folder structure recreation
- Forest item importing and placement via Geometry Nodes instances
- Ability to realize TSStatic and Forest instances
- Importing BeamNG material files
- Importing BeamNG vehicles state

### BeamNG Modding Tools

- Integration with the in-game World Editor
- Standalone mode
- Conversion of legacy TorqueScript (`.cs`) materials to JSON
- Cleanup of TorqueScript (`.cs`) materials
- Batch conversion support
- DDS → PNG texture exporter (reverse of Texture Cooker)
- Game mesh → COLLADA exporter
- Game mesh → Wavefront OBJ exporter
- Soft reloading of vehicle materials
- Hard reloading of vehicle materials
- Removal of temporary files for vehicles
- Exporting BeamNG vehicles state

---

## Screenshots

<img src="https://media.beamng.com/vdOkksVTmWqpzo2p" width="512"> <img src="https://media.beamng.com/VOgyzYL2XHcpZTGw" width="512"> <img src="https://media.beamng.com/JlBmeci9SvrhOaaX" width="512">

---

## Roadmap

### BeamNG Level Importer

Planned features:

- Importing levels and materials defined in TorqueScript
- Editing levels directly in Blender and saving changes back
- Particle emitter support

---

## Known Issues

### BeamNG Level Importer

- There may be additional issues that have not yet been discovered or documented

### BeamNG Modding Tools

- The game may crash when removing old `.cs` materials if a level is already loaded
- COLLADA and Wavefront exports from the game engine may produce unexpected results

---

## Requirements

### BeamNG Level Importer

- **Operating system:**
  - Windows (x64 or ARM64)
  - Linux (x64 or ARM64)
  - macOS (ARM64)
- **Blender:** 4.5 LTS or 5.0

### BeamNG Modding Tools

- **Operating system:** Windows or Linux (x64)
- **Game:** BeamNG.drive v0.38 or newer

---

## Installation

### BeamNG Level Importer (Blender Add-on)

1. Make sure your system meets the requirements above.
2. Download the Blender add-on from the [Releases](https://github.com/PrzemekWolw/BeamNGLevelImporter/releases) page.
   - **Important:** Download the **Blender add-on** file, *not* the source code or the BeamNG extension.
3. Open Blender.
4. Go to **Edit → Preferences → Add-ons → Install…**
5. Select the downloaded `.zip` and install it.
6. Enable the add-on in the Add-ons list if it is not enabled automatically.

### BeamNG Modding Tools (BeamNG Extension)

1. Make sure your system meets the requirements above.
2. Download the BeamNG extension from the [Releases](https://github.com/PrzemekWolw/BeamNGLevelImporter/releases) page.
   - **Important:** Download the **BeamNG extension**, *not* the source code or Blender add-on.
3. Copy the downloaded `.zip` file into your BeamNG `mods` folder.

---

## Usage

### BeamNG Level Importer

#### Importing a Level into Blender

1. In Blender, open the **Sidebar** (usually with the `N` key).
2. Go to the **BeamNG Level Importer** panel.
3. Set the paths to:
   - Your **BeamNG game install folder**
   - Your **BeamNG user folder**
4. Click **Scan** to detect available levels.
5. Select a level from the list.
6. Click **Import Level**.

---

### BeamNG Modding Tools

#### Converting Old Mods to New Material System

1. Start BeamNG.drive.
2. Open the Modding Tools interface (depending on installation, this may be under the World Editor or a dedicated UI).
3. Enter the path to your mod’s folder that you want to convert.
4. Click **Convert**.
5. After conversion:
   - Copy the generated `.json` material files from your BeamNG **user folder** back into your mod’s source folder.
   - Delete all `materials.cs` (or other `.cs` material) files from the mod.
   - Clear your mod’s cache so the game uses the new JSON-based materials.

#### Exporting Textures or Meshes

1. Start BeamNG.drive.
2. Open the Modding Tools interface.
3. Enter the path to the mod folder whose assets you want to export.
4. Go to the **Exporter** tab.
5. Click the export function you want to use (e.g., DDS → PNG, mesh → COLLADA, mesh → OBJ).
6. The exported files will appear in your BeamNG user folder at:
   `userfolder/temp/exported/`

---

## FAQ / Troubleshooting

### The game crashes when converting `.cs` materials

- Try running the conversion from the **main menu**, before loading any level.
  This reduces memory usage and can prevent crashes or long hangs during conversion.

---

## Credits

Special thanks to [@thomatoes50](https://github.com/thomatoes50) for help with cleaning up the Lua code and for providing the original Resource Explorer code that greatly assisted work on the Polish Roads project.

Additional thanks for testing, feedback, and ideas to:
[@AgentMooshroom5](https://www.beamng.com/members/272928/),
[@bob.blunderton](https://www.beamng.com/members/102419/),
[@DankMemeBunny](https://www.beamng.com/members/163405/),
[@falefee](https://www.beamng.com/members/52708/),
[@Nekkit](https://www.beamng.com/members/315904/).

---

## License

This project is licensed under the MIT License. See the `LICENSE` file for full details.
