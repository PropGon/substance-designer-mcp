# substance-designer-mcp

Servidor MCP para que Claude cree y modifique grafos de materiales en Adobe Substance 3D Designer:
nodos, conexiones, parámetros, frames, salidas PBR, guardado y exportación. También cocina y renderiza
sin abrir Designer, con `sbscooker` y `sbsrender`.

Requiere Designer 16.0 o posterior. Probado en Windows con Designer 16.0.7 (Python 3.13, PySide6) y Claude Code. **En macOS está implementado pero no se ha
probado**: la ruta de las herramientas (`Designer.app/Contents/MacOS`) es una suposición, y puedes
corregirla con `SD_MCP_SAT_DIR`.

```
Claude ──stdio──> servidor MCP ──TCP 127.0.0.1 + token──> plugin ──señal Qt──> hilo principal de Designer
                       └──────> sbscooker / sbsrender (sin Designer)
```

## Instalación

Necesitas [uv](https://docs.astral.sh/uv/) y Designer 16.0 o posterior. El servidor usa los `sbscooker` y `sbsrender`
que vienen con Designer, o los del Automation Toolkit si indicas su carpeta. Este proyecto no los incluye: su uso
se rige por tu licencia de Adobe.

### 1. Instalar las dependencias

```bash
uv --directory "C:/ruta/a/substance-designer-mcp" sync
```

### 2. Copiar el plugin a Designer

Copia la carpeta `designer_plugin/sd_mcp_bridge` a la carpeta de plugins de usuario:

| Sistema | Carpeta |
|---|---|
| Windows | `%USERPROFILE%\Documents\Adobe\Adobe Substance 3D Designer\python\sduserplugins` |
| macOS | `~/Documents/Adobe/Adobe Substance 3D Designer/python/sduserplugins` (sin probar) |

Debe quedar así: `sduserplugins/sd_mcp_bridge/pluginInfo.json` y `sduserplugins/sd_mcp_bridge/sd_mcp_bridge/__init__.py`.

Reinicia Designer. El plugin carga solo y escribe en su consola `Puente MCP escuchando en 127.0.0.1:9817`.

Si prefieres no copiarlo, abre Designer con la variable `SBS_DESIGNER_PYTHON_PATH` apuntando a `designer_plugin`.

### 3. Elegir las carpetas permitidas

Copia `config.example.json` a `~/.substance-designer-mcp/config.json` y edita `allowed_dirs`. Sin ese archivo, la
única carpeta permitida es `~/Documents/SubstanceDesignerMCP`. Reinicia Designer tras cambiar el puerto.

### 4. Conectar Claude

**Claude Code**, en Git Bash, macOS o Linux:

```bash
claude mcp add --scope user substance-designer -- uv --directory "C:/ruta/a/substance-designer-mcp" run substance-designer-mcp
```

En PowerShell, `--` debe ir entre comillas; sin ellas, el comando falla con `unknown option '--directory'`:

```powershell
claude mcp add --scope user substance-designer '--' uv --directory "C:/ruta/a/substance-designer-mcp" run substance-designer-mcp
```

`claude mcp list` debe mostrar el servidor como conectado.

**Claude Desktop:** edita `%APPDATA%\Claude\claude_desktop_config.json` (en macOS,
`~/Library/Application Support/Claude/claude_desktop_config.json`) y reinicia la aplicación. Usa la ruta completa de
`uv`, porque Claude Desktop puede no ver tu `PATH`:

```json
{
  "mcpServers": {
    "substance-designer": {
      "command": "C:/Users/TU_USUARIO/.local/bin/uv.exe",
      "args": ["--directory", "C:/ruta/a/substance-designer-mcp", "run", "substance-designer-mcp"]
    }
  }
}
```

Para comprobarlo, pídele a Claude: *"usa get_app_info de Substance Designer"*.

## Configuración

Las variables de entorno tienen prioridad sobre `~/.substance-designer-mcp/config.json`.

| Variable | Clave en config.json | Para qué sirve | Por defecto |
|---|---|---|---|
| `SD_MCP_ALLOWED_DIRS` | `allowed_dirs` | Carpetas permitidas (separadas por `;` en Windows y `:` en macOS) | `~/Documents/SubstanceDesignerMCP` |
| `SD_MCP_DESIGNER_DIR` | `designer_dir` | Carpeta de Designer | Se detecta sola |
| `SD_MCP_SAT_DIR` | `sat_dir` | Carpeta de `sbsrender` y `sbscooker`, si usas otro SAT | Las de Designer |
| `SD_MCP_PORT` | `bridge_port` | Puerto del plugin | `9817` |
| `SD_MCP_HOME` | | Carpeta de `config.json` y `bridge.json` | `~/.substance-designer-mcp` |

El plugin y el servidor son procesos distintos: una variable definida en la configuración de Claude no llega a Designer.
Para `allowed_dirs` y el puerto, usa `config.json`, que leen los dos.

## Herramientas

| Herramienta | Designer | API o comando |
|---|---|---|
| `get_app_info` | Sí | `SDApplication.getVersion`, `getPath`, `SDUIMgr.getCurrentGraph` |
| `list_graphs` | Sí | `SDPackageMgr.getUserPackages`, `SDPackage.getChildrenResources` |
| `open_graph` | Sí | `SDPackageMgr.loadUserPackage`, `SDUIMgr.openResourceInEditor` |
| `create_graph` | Sí | `SDSBSCompGraph.sNew`, `setDefaultParentSize`, `SDPackageMgr.newUserPackage` |
| `list_nodes` | Sí | `SDGraph.getNodes`, `getGraphObjects` |
| `get_node_info` | Sí | `SDNode.getDefinition`, `getProperties`, `getPropertyConnections` |
| `create_node` | Sí | `SDGraph.newNode`, `newInstanceNode` |
| `delete_node` | Sí | `SDGraph.deleteNode` |
| `connect_nodes` | Sí | `SDNode.newPropertyConnectionFromId` |
| `set_node_parameter` / `get_node_parameter` | Sí | `SDNode.setPropertyValue`, `getPropertyValue`, clases `SDValue*` |
| `create_frame` | Sí | `SDGraphObjectFrame.sNew`, `setTitle`, `setSize`, `setColor` |
| `create_comment` | Sí | `SDGraphObjectComment.sNew`, `sNewAsChild` |
| `expose_parameter` | Sí | `SDResource.newProperty`, `setPropertyAnnotationValueFromId`, `SDNode.newPropertyGraph` |
| `create_output_node` | Sí | `sbs::compositing::output`, `SDUsage.sNew`, `setAnnotationPropertyValueFromId` |
| `auto_layout` | Sí | Algoritmo propio con `SDNode.setPosition` |
| `save_package` | Sí | `SDPackageMgr.savePackage`, `savePackageAs` |
| `export_sbsar` | Sí | `SDSBSARExporter.exportPackageToSBSAR` |
| `run_python` | Sí | `exec` en el hilo principal |
| `cook_sbs` | No | `sbscooker --inputs --output-path --output-name` |
| `render_outputs` | No | `sbsrender info` y `sbsrender render --set-value ...` |
| `batch_render` | No | `sbsrender render`, una vez por archivo y juego de parámetros |

Los hilos siguen el [patrón de la documentación de Adobe](https://experienceleague.adobe.com/en/docs/substance-3d-designer/using/scripting/using-threads):
el socket vive en un `QThread` y cada comando llega al hilo principal por una señal con `Qt.QueuedConnection`. El ejemplo
de esa página importa PySide2, pero Designer 16 trae PySide6.

Las firmas salen de la API instalada (`resources/python/sd`) y de sus ejemplos (`resources/python/samples`), más fiables que la
web para tu versión. En Designer: **Help > Python API Documentation**.

## Limitaciones de la API

Todas las herramientas funcionan, con estas diferencias respecto a lo que cabría esperar:

- **`auto_layout` no es de Adobe.** La API no ofrece layout automático; `sd.tools.graphlayout` solo alinea y ajusta a la
  cuadrícula. Este ordena por columnas, y no mueve frames ni comentarios.
- **Los frames solo agrupan visualmente.** `SDGraphObjectFrame` no sabe qué nodos contiene: colócalo a su alrededor.
  Los objetos de grafo tampoco tienen identificador, por eso no hay herramienta para borrarlos.
- **El tamaño del grafo no viaja al `.sbsar`.** Sin `width` y `height`, `sbsrender` usa 256×256 aunque el grafo sea de 1024.
  Un tamaño fijo (`Absolute`) sí se conservaría, pero `sbscooker` dejaría de exponer `$outputsize` y no se podría cambiar al renderizar.
- **Las bibliotecas aparecen en el Explorer de Designer.** `loadUserPackage` es la única vía para usar filtros como Perlin Noise.
  `list_graphs` y `get_app_info` las ocultan, pero Designer las muestra.
- **`set_node_parameter` no admite todos los tipos.** Acepta escalares, vectores, colores y enums. Curvas, gradientes y
  otras estructuras necesitan `run_python`.
- **`expose_parameter` crea una función en el nodo.** Enlaza con `sbs::function::get_float1` y similares, que no salen en los
  ejemplos de Adobe pero sí se comprobaron en Designer 16. Un parámetro ya controlado por una función se rechaza.

Comportamientos que el código ya tiene en cuenta, útiles si lo modificas:

- `APIException` hereda de `BaseException`, así que un `except Exception` no la captura.
- En una conexión vista desde un nodo, `getInputPropertyNode()` es siempre el otro extremo, no el destino.
- `sbsrender` ignora los `--set-value` desconocidos sin avisar; `render_outputs` los comprueba antes con `sbsrender info`.

## Seguridad

- El plugin solo escucha en `127.0.0.1` (no es configurable) y exige un token aleatorio que se regenera en cada inicio.
  Usa TCP en vez de HTTP para que una página web no pueda enviarle comandos.
- Solo acepta los comandos de una lista cerrada y valida los parámetros antes de tocar el grafo.
- Toda ruta se resuelve (incluidos `..` y symlinks) y debe caer dentro de `allowed_dirs`. Sobrescribir otro archivo requiere `overwrite=true`.

Dos límites que conviene conocer:

- **`run_python` queda fuera de todo esto.** Ejecuta cualquier código con tus permisos, y la lista de carpetas no aplica.
  `confirmed=true` lo escribe el propio modelo, así que la aprobación real es la de tu cliente:
  deja esa herramienta en "preguntar siempre" y lee el código antes de aceptar.
- **El token no protege de otros programas de tu usuario**, que pueden leer `bridge.json`. Protege de páginas web y de otros usuarios.

## Ejemplo: Template_Material

`examples/Template_Material.sbs` es el resultado de `build_template_material.py`, que usa solo herramientas MCP. Tiene frames
Shapes, Details, Color y Outputs; una salida por mapa PBR (`baseColor`, `normal`, `roughness`, `metallic`, `height`,
`ambientOcclusion`) y 3 parámetros: `base_tint`, `noise_scale` y `normal_intensity`.

Con Designer abierto y la carpeta de salida dentro de `allowed_dirs`:

```bash
uv run python examples/build_template_material.py "C:/Users/TU_USUARIO/Documents/SubstanceDesignerMCP"
```

Para comprobar que cada parámetro cambia solo los mapas esperados (no necesita Designer):

```bash
uv run python examples/verify_template_parameters.py "C:/Users/TU_USUARIO/Documents/SubstanceDesignerMCP"
```

Ejemplos de lo que puedes pedirle a Claude:

- *"Crea un grafo de 2048 llamado Ladrillo, con un Perlin Noise conectado a un normal y a su salida de normal."*
- *"Expón la intensidad del normal como parámetro de 0 a 5 y ordena el grafo."*
- *"Cocina Ladrillo.sbs y renderiza los mapas a 2048 en PNG de 16 bits."*
- *"Renderiza estos tres .sbsar con noise_scale 4, 8 y 16, cada uno en su carpeta."*

## Pruebas

```bash
uv run pytest
```

Cubren lo que no depende de Designer: protocolo, rutas, detección de la instalación, argumentos de `sbsrender`, layout y la cadena MCP completa con un plugin simulado.

Para probar con Designer de verdad (crea un grafo desechable y comprueba también los rechazos):

```bash
uv run python examples/verify_all_tools.py "C:/carpeta/permitida"
```

## Problemas frecuentes

| Mensaje | Qué hacer |
|---|---|
| `Substance 3D Designer no esta abierto` | Abre Designer. `cook_sbs`, `render_outputs` y `batch_render` funcionan sin él. |
| `el plugin sd_mcp_bridge no responde` | Revisa **Tools > Plugin Manager** y la estructura de carpetas del paso 2, y reinicia Designer. |
| `no pudo iniciar el puente` en la consola de Designer | El puerto está ocupado o `config.json` tiene un error. Cambia `bridge_port`. |
| `fuera de las carpetas permitidas` | Agrega la carpeta a `allowed_dirs` y reinicia Designer. |
| `Designer no respondio a tiempo` | Puede estar calculando o tener un diálogo abierto. El comando podría ejecutarse igualmente al liberarse. |
