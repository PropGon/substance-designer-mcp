# substance-designer-mcp

An MCP server that lets Claude create and modify material graphs in Adobe Substance 3D Designer:
nodes, connections, parameters, frames, PBR outputs, saving and export. It also cooks and renders
without opening Designer, using `sbscooker` and `sbsrender`.

Windows only. It works with Claude Code and Claude Desktop, verified on Windows 11 with Designer 16.0.7; the plugin
is also prepared for Designer 13.1 (2024) and later (see [Designer version compatibility](#designer-version-compatibility)).
Every tool that modifies the graph can be undone with Ctrl+Z in a single step.

An independent, free project, with no affiliation with or endorsement from Adobe. You need your own Designer license.

```
Claude ──stdio──> MCP server ──TCP 127.0.0.1 + token──> plugin ──Qt signal──> Designer main thread
                       └──────> sbscooker / sbsrender (no Designer needed)
```

## Installation

You need [uv](https://docs.astral.sh/uv/) and Designer (16.0 or later recommended); uv installs Python for you. The server uses the `sbscooker` and `sbsrender`
that ship with Designer, or those from the Automation Toolkit if you point it to their folder. This project does not include them: their use
is governed by your Adobe license.

### 1. Install the dependencies

```bash
uv --directory "C:/path/to/substance-designer-mcp" sync
```

### 2. Copy the plugin into Designer

With Designer closed and from the project folder, in PowerShell, create the plugins folder if it doesn't exist and copy the plugin:

```powershell
New-Item -ItemType Directory -Force "$env:USERPROFILE\Documents\Adobe\Adobe Substance 3D Designer\python\sduserplugins"
Copy-Item -Recurse designer_plugin\sd_mcp_bridge "$env:USERPROFILE\Documents\Adobe\Adobe Substance 3D Designer\python\sduserplugins\sd_mcp_bridge"
```

The result should be: `sduserplugins/sd_mcp_bridge/pluginInfo.json` and `sduserplugins/sd_mcp_bridge/sd_mcp_bridge/__init__.py`.

Restart Designer. The plugin loads by itself, writes `Puente MCP escuchando en 127.0.0.1:9817` ("MCP bridge listening on…") to its console and adds
the **MCP** menu to the menu bar (see [The MCP menu in Designer](#the-mcp-menu-in-designer)).

If you are upgrading from an earlier version, delete the old `sd_mcp_bridge` folder first: if two copies of the plugin
are present, both load.

If you prefer not to copy it, start Designer with the `SBS_DESIGNER_PYTHON_PATH` variable pointing to `designer_plugin`.

### 3. Choose the allowed folders

Copy `config.example.json` to `~/.substance-designer-mcp/config.json` and edit `allowed_dirs`. Without that file, the
only allowed folder is `~/Documents/SubstanceDesignerMCP`. Restart Designer after changing the port.

### 4. Connect Claude

**Claude Code**, in Git Bash:

```bash
claude mcp add --scope user substance-designer -- uv --directory "C:/path/to/substance-designer-mcp" run substance-designer-mcp
```

In PowerShell, `--` must go in quotes; without them, the command fails with `unknown option '--directory'`:

```powershell
claude mcp add --scope user substance-designer '--' uv --directory "C:/path/to/substance-designer-mcp" run substance-designer-mcp
```

`claude mcp list` should show the server as connected.

**Claude Desktop:** edit `claude_desktop_config.json`. Depending on how the app was installed, it is in
`%LOCALAPPDATA%\Claude-Data\<folder>\` or in `%APPDATA%\Claude\`. Add this inside the file, without deleting what it
already has, and close Claude Desktop completely before opening it again. Use the full path to `uv`, because Claude
Desktop may not see your `PATH`:

```json
{
  "mcpServers": {
    "substance-designer": {
      "command": "C:/Users/YOUR_USER/.local/bin/uv.exe",
      "args": ["--directory", "C:/path/to/substance-designer-mcp", "run", "substance-designer-mcp"]
    }
  }
}
```

To check it, ask Claude: *"use Substance Designer's get_app_info"*.

## Configuration

Environment variables take precedence over `~/.substance-designer-mcp/config.json`.

| Variable | config.json key | What it is for | Default |
|---|---|---|---|
| `SD_MCP_ALLOWED_DIRS` | `allowed_dirs` | Allowed folders (separated by `;`) | `~/Documents/SubstanceDesignerMCP` |
| `SD_MCP_DESIGNER_DIR` | `designer_dir` | Designer folder | Detected automatically |
| `SD_MCP_SAT_DIR` | `sat_dir` | Folder of `sbsrender` and `sbscooker`, if you use a different SAT | Those of Designer |
| `SD_MCP_PORT` | `bridge_port` | Plugin port | `9817` |
| `SD_MCP_HOME` | | Folder of `config.json` and `bridge.json` | `~/.substance-designer-mcp` |
| | `autostart` | Turn the bridge on when Designer opens | `true` |

The plugin and the server are separate processes: a variable defined in Claude's configuration does not reach Designer.
For `allowed_dirs` and the port, use `config.json`, which both read.

## The MCP menu in Designer

The plugin adds an **MCP** menu to Designer's menu bar and an indicator on the right of the status bar:

| Indicator | State |
|---|---|
| `MCP ●` green | Bridge on, waiting for Claude |
| `MCP ◉` cyan | Claude is using a tool right now |
| `MCP ○` gray | Bridge off: Claude can't touch Designer |
| `MCP ✕` | The bridge could not start (port in use or `config.json` with errors); the details appear in the menu |

From the menu:

- **Activar el puente / Desactivar el puente** (enable / disable the bridge) turns it on or off without restarting Designer. When it is off, Claude gets
  a clear message instead of waiting; when it is turned on, a new token is generated.
- **Activar al abrir Designer** (enable on Designer startup) decides whether the bridge starts by itself. It is saved as `autostart` in `config.json`.

The first line of the menu shows the port and the last tool used.

## Designer version compatibility

| Designer | Year | Qt / Python | Status |
|---|---|---|---|
| 16.x | 2025-2026 | PySide6 / 3.13 | Verified (16.0.7) |
| 14.x – 15.x | 2024-2025 | PySide6 / 3.11 | Prepared, not verified |
| 13.1.x | 2024 | PySide2 / 3.9 | Prepared, not verified |

How this is achieved without maintaining one version per Designer release:

- **Qt:** the whole plugin imports Qt through `qt_compat.py`, which uses PySide6 and, if it is not available, PySide2.
- **Python:** the code is limited to Python 3.9 syntax; the tests check it file by file.
- **API:** functions that don't exist in every version are detected when they are used. If grouped undo is missing, the
  tool works the same without it (`get_app_info` reports it in `undo_supported`); if the texture-to-image converter is missing,
  the preview uses a temporary file.
- **Future versions:** there are no version lists in the code, so a new version works as long as Adobe
  keeps the Python API. `get_app_info` returns the Designer, Qt and plugin versions for diagnosis.

Versions earlier than 13.1 are not supported. If you try the plugin on 13.1, 14 or 15, open an issue with what
`uv run python examples/verify_all_tools.py "C:/allowed/folder"` returns (see [Tests](#tests)).

## Tools

| Tool | Designer | API or command |
|---|---|---|
| `get_app_info` | Yes | `SDApplication.getVersion`, `getPath`, `SDUIMgr.getCurrentGraph` |
| `list_graphs` | Yes | `SDPackageMgr.getUserPackages`, `SDPackage.getChildrenResources` |
| `open_graph` | Yes | `SDPackageMgr.loadUserPackage`, `SDUIMgr.openResourceInEditor` |
| `create_graph` | Yes | `SDSBSCompGraph.sNew`, `setDefaultParentSize`, `SDPackageMgr.newUserPackage` |
| `list_nodes` | Yes | `SDGraph.getNodes`, `getGraphObjects` |
| `get_node_info` | Yes | `SDNode.getDefinition`, `getProperties`, `getPropertyConnections` |
| `get_node_preview` | Yes | `SDSBSCompGraph.compute`, `SDValueTexture`, `QtForPythonUIMgrWrapper.convertSDTextureToQImage` |
| `search_library` | No | Searches Designer's `resources/packages` |
| `create_node` | Yes | `SDGraph.newNode`, `newInstanceNode`; returns inputs, outputs and parameters |
| `delete_node` | Yes | `SDGraph.deleteNode` |
| `connect_nodes` | Yes | `SDNode.newPropertyConnectionFromId` |
| `set_node_parameter` / `get_node_parameter` | Yes | `SDNode.setPropertyValue`, `getPropertyValue`, `SDValue*`, `SDValueArray` and `SDValueStruct` classes for gradients and curves |
| `create_frame` | Yes | `SDGraphObjectFrame.sNew`, `setTitle`, `setSize`, `setColor` |
| `create_comment` | Yes | `SDGraphObjectComment.sNew`, `sNewAsChild` |
| `expose_parameter` | Yes | `SDResource.newProperty`, `setPropertyAnnotationValueFromId`, `SDNode.newPropertyGraph` |
| `create_output_node` | Yes | `sbs::compositing::output`, `SDUsage.sNew`, `setAnnotationPropertyValueFromId` |
| `auto_layout` | Yes | Custom algorithm with `SDNode.setPosition` |
| `save_package` | Yes | `SDPackageMgr.savePackage`, `savePackageAs` |
| `export_sbsar` | Yes | `SDSBSARExporter.exportPackageToSBSAR` |
| `run_python` | Yes | `exec` on the main thread |
| `cook_sbs` | No | `sbscooker --inputs --output-path --output-name` |
| `render_outputs` | No | `sbsrender info` and `sbsrender render --set-value ...` |
| `batch_render` | No | `sbsrender render`, once per file and parameter set |

Threading follows the [pattern in Adobe's documentation](https://experienceleague.adobe.com/en/docs/substance-3d-designer/using/scripting/using-threads):
the socket lives in a `QThread` and each command reaches the main thread through a signal with `Qt.QueuedConnection`. The example
on that page imports PySide2, but Designer 16 ships PySide6.

Signatures come from the installed API (`resources/python/sd`) and its examples (`resources/python/samples`), which are more reliable than the
web for your version. In Designer: **Help > Python API Documentation**.

## API limitations

All the tools work, with these differences from what you might expect:

- **`auto_layout` is not from Adobe.** The API offers no automatic layout; `sd.tools.graphlayout` only aligns and snaps to the
  grid. This one arranges nodes in columns, and does not move frames or comments.
- **Frames only group visually.** `SDGraphObjectFrame` doesn't know which nodes it contains: place it around them.
  Graph objects also have no identifier, which is why there is no tool to delete them.
- **The graph size does not travel to the `.sbsar`.** Without `width` and `height`, `sbsrender` uses 256×256 even if the graph is 1024.
  A fixed size (`Absolute`) would be preserved, but `sbscooker` would stop exposing `$outputsize` and it could not be changed when rendering.
- **Libraries appear in Designer's Explorer.** `loadUserPackage` is the only way to use filters such as Perlin Noise.
  `list_graphs` and `get_app_info` hide them, but Designer shows them.
- **The preview only works on nodes that reach an output.** Designer doesn't compute loose nodes; `get_node_preview`
  explains this and asks you to connect the node, or a later one, to `create_output_node`.
- **Gradients and curves are passed as a list of points.** `gradientrgba`: `[{"position": 0, "value": [r, g, b, a]}, ...]`, with an
  optional `midpoint` (0.5). `curveluminance` and the other curves: `[{"position": [x, y]}, ...]`, with optional `left` and `right`
  (by default, the point itself). Other structures with different fields are accepted with all of their fields.
- **`expose_parameter` creates a function on the node.** It links with `sbs::function::get_float1` and similar ones, which don't appear in
  Adobe's examples but were verified in Designer 16. A parameter that is already controlled by a function is rejected.

Behaviors the code already takes into account, useful if you modify it:

- `APIException` inherits from `BaseException`, so an `except Exception` does not catch it.
- On a connection seen from a node, `getInputPropertyNode()` is always the other end, not the destination.
- `sbsrender` silently ignores unknown `--set-value` options; `render_outputs` checks them beforehand with `sbsrender info`.

## Security

- The plugin only listens on `127.0.0.1` (not configurable) and requires a random token that is regenerated at every startup.
  It uses TCP instead of HTTP so that a web page cannot send it commands.
- It only accepts commands from a closed list and validates the parameters before touching the graph.
- Every path is resolved (including `..` and symlinks) and must fall inside `allowed_dirs`. Overwriting another file requires `overwrite=true`.

Two limits worth knowing:

- **`run_python` is outside all of this.** It runs any code with your permissions, and the folder list does not apply.
  `confirmed=true` is written by the model itself, so the real approval is your client's:
  leave that tool on "ask every time" and read the code before accepting.
- **The token does not protect against other programs of your user**, which can read `bridge.json`. It protects against web pages and other users.

## Example: Template_Material

`examples/Template_Material.sbs` is the result of `build_template_material.py`, which uses only MCP tools. It has the frames
Shapes, Details, Color and Outputs; one output per PBR map (`baseColor`, `normal`, `roughness`, `metallic`, `height`,
`ambientOcclusion`) and 3 parameters: `base_tint`, `noise_scale` and `normal_intensity`.

The `.sbsar` is not included: the script generates it. With Designer open and the output folder inside `allowed_dirs`:

```bash
uv run python examples/build_template_material.py "C:/Users/YOUR_USER/Documents/SubstanceDesignerMCP"
```

To check that each parameter changes only the expected maps (it uses that `.sbsar` and does not need Designer):

```bash
uv run python examples/verify_template_parameters.py "C:/Users/YOUR_USER/Documents/SubstanceDesignerMCP"
```

Examples of what you can ask Claude:

- *"Create a 2048 graph called Brick, with a Perlin Noise connected to a normal and to its normal output."*
- *"Expose the normal's intensity as a parameter from 0 to 5 and arrange the graph."*
- *"Cook Brick.sbs and render the maps at 2048 as 16-bit PNG."*
- *"Render these three .sbsar files with noise_scale 4, 8 and 16, each in its own folder."*
- *"Look for a clouds-type noise, connect it to a gradient map from black to red and yellow, like lava, and check the preview
  before approving it."*

## Tests

```bash
uv run pytest
```

They cover what does not depend on Designer: protocol, paths, installation detection, `sbsrender` arguments, layout and the full MCP chain with a simulated plugin.

To test with a real Designer (it creates a disposable graph and also checks the rejections):

```bash
uv run python examples/verify_all_tools.py "C:/allowed/folder"
```

## Common problems

The plugin's menu labels and messages are in Spanish; the English translation is given in parentheses.

| Message | What to do |
|---|---|
| `Substance 3D Designer no esta abierto` (Substance 3D Designer is not open) | Open Designer. `cook_sbs`, `render_outputs` and `batch_render` work without it. |
| `el plugin sd_mcp_bridge no responde` (the sd_mcp_bridge plugin is not responding) | If the menu shows `MCP ○`, choose **MCP > Activar el puente** (enable the bridge). If there is no MCP menu, check **Tools > Plugin Manager** and the folder structure from step 2, and restart Designer. |
| `no pudo iniciar el puente` (could not start the bridge) in Designer's console | The port is in use or `config.json` has an error. Change `bridge_port`. |
| `fuera de las carpetas permitidas` (outside the allowed folders) | Add the folder to `allowed_dirs` and restart Designer. |
| `Designer no respondio a tiempo` (Designer did not respond in time) | It may be computing or have a dialog open. The command might still run once it frees up. |

## License

[MIT](LICENSE), © PropGon. Adobe and Substance 3D Designer are trademarks of Adobe; the use of `sbscooker` and `sbsrender` is governed by your Adobe license.
