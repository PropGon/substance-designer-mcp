"""MCP server (stdio) for Substance 3D Designer."""

from __future__ import annotations

from typing import Any, Callable

import anyio
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from . import bridge_client, sat
from .config import detect_installation, tool_version

mcp = FastMCP("substance-designer")


def _designer(command: str, **params: Any) -> Any:
    try:
        return bridge_client.call(command, {k: v for k, v in params.items() if v is not None})
    except bridge_client.BridgeUnavailable as exc:
        raise ToolError(str(exc)) from None
    except bridge_client.BridgeCommandError as exc:
        raise ToolError(f"Designer rechazo '{command}' ({exc.code}): {exc}") from None


async def _offline(function: Callable, *args: Any, **kwargs: Any) -> dict:
    # Renders take minutes; a worker thread keeps the MCP event loop responsive meanwhile.
    def work():
        return function(*args, **kwargs)

    try:
        return await anyio.to_thread.run_sync(work)
    except (sat.ToolFailed, ValueError) as exc:
        raise ToolError(str(exc)) from None


def _local_installation() -> dict:
    found = detect_installation()
    return {
        "designer_dir": str(found.designer_dir) if found.designer_dir else None,
        "sbsrender": str(found.sbsrender) if found.sbsrender else None,
        "sbscooker": str(found.sbscooker) if found.sbscooker else None,
        "tools_version": tool_version(found.sbsrender) if found.sbsrender else None,
    }


# ---------------------------------------------------------------- application and graphs


@mcp.tool()
def get_app_info() -> dict:
    """Devuelve la version de Designer, el grafo y paquete activos y las herramientas detectadas. Requiere Designer abierto."""
    try:
        info = bridge_client.call("get_app_info")
    except bridge_client.BridgeUnavailable as exc:
        raise ToolError(f"{exc} Instalacion detectada: {_local_installation()}") from None
    except bridge_client.BridgeCommandError as exc:
        raise ToolError(f"Designer rechazo 'get_app_info' ({exc.code}): {exc}") from None
    return {**info, "local_installation": _local_installation()}


@mcp.tool()
def list_graphs() -> dict:
    """Lista los paquetes abiertos y sus grafos de composicion. Oculta las bibliotecas de Adobe."""
    return _designer("list_graphs")


@mcp.tool()
def open_graph(graph: str | None = None, package: str | None = None, file_path: str | None = None) -> dict:
    """Abre un grafo en el editor. file_path carga antes un .sbs de una carpeta permitida; package es un uid o ruta."""
    return _designer("open_graph", graph=graph, package=package, file_path=file_path)


@mcp.tool()
def create_graph(
    name: str,
    width: int = 1024,
    height: int = 1024,
    format: str = "8_bits_per_channel",
    package: str | None = None,
) -> dict:
    """Crea un grafo de composicion y lo abre. Sin package crea un paquete nuevo sin guardar.

    width y height son el tamano en Designer, en potencias de 2. No viajan al .sbsar: al renderizar,
    indicalos otra vez en render_outputs.
    format: 8_bits_per_channel, 16_bits_per_channel, hdr_low_precision o hdr_high_precision.
    """
    return _designer("create_graph", name=name, width=width, height=height, format=format, package=package)


# ---------------------------------------------------------------- nodes


@mcp.tool()
def list_nodes(graph: str | None = None, package: str | None = None) -> dict:
    """Lista nodos, frames y comentarios de un grafo (por defecto, el activo)."""
    return _designer("list_nodes", graph=graph, package=package)


@mcp.tool()
def get_node_info(node_id: str, graph: str | None = None, package: str | None = None) -> dict:
    """Devuelve id, definicion, entradas, salidas, parametros con sus valores y conexiones de un nodo."""
    return _designer("get_node_info", node_id=node_id, graph=graph, package=package)


@mcp.tool()
def create_node(
    definition: str | None = None,
    library: str | None = None,
    library_graph: str | None = None,
    x: float = 0,
    y: float = 0,
    graph: str | None = None,
    package: str | None = None,
) -> dict:
    """Crea un nodo. Indica definition para nodos atomicos (p. ej. sbs::compositing::blend)
    o library para filtros de la biblioteca de Adobe (p. ej. noise_perlin_noise), con library_graph
    si el paquete contiene varios. Devuelve el id del nodo."""
    return _designer(
        "create_node", definition=definition, library=library, library_graph=library_graph,
        x=x, y=y, graph=graph, package=package,
    )


@mcp.tool()
def delete_node(node_id: str, graph: str | None = None, package: str | None = None) -> dict:
    """Borra un nodo y sus conexiones."""
    return _designer("delete_node", node_id=node_id, graph=graph, package=package)


@mcp.tool()
def connect_nodes(
    from_node: str,
    to_node: str,
    to_input: str,
    from_output: str | None = None,
    graph: str | None = None,
    package: str | None = None,
) -> dict:
    """Conecta una salida con una entrada. Sin from_output usa la primera salida. get_node_info muestra los ids."""
    return _designer(
        "connect_nodes", from_node=from_node, to_node=to_node, to_input=to_input,
        from_output=from_output, graph=graph, package=package,
    )


@mcp.tool()
def set_node_parameter(
    node_id: str, parameter: str, value: Any, graph: str | None = None, package: str | None = None
) -> dict:
    """Cambia un parametro del nodo. Vectores y colores van como lista; los enums por su id.

    $outputsize usa log2: [10, 10] significa 1024x1024.
    """
    return _designer(
        "set_node_parameter", node_id=node_id, parameter=parameter, value=value, graph=graph, package=package
    )


@mcp.tool()
def get_node_parameter(
    node_id: str, parameter: str, graph: str | None = None, package: str | None = None
) -> dict:
    """Lee el valor y el tipo de un parametro de un nodo."""
    return _designer("get_node_parameter", node_id=node_id, parameter=parameter, graph=graph, package=package)


# ---------------------------------------------------------------- organization


@mcp.tool()
def create_frame(
    title: str,
    x: float = 0,
    y: float = 0,
    width: float = 400,
    height: float = 300,
    description: str | None = None,
    color: list[float] | None = None,
    graph: str | None = None,
    package: str | None = None,
) -> dict:
    """Crea un frame. Agrupa solo visualmente: la API no asocia nodos a frames, asi que colocalo alrededor de ellos."""
    return _designer(
        "create_frame", title=title, x=x, y=y, width=width, height=height,
        description=description, color=color, graph=graph, package=package,
    )


@mcp.tool()
def create_comment(
    text: str,
    x: float = 0,
    y: float = 0,
    node_id: str | None = None,
    graph: str | None = None,
    package: str | None = None,
) -> dict:
    """Crea un comentario suelto o, con node_id, unido a un nodo (x e y son entonces relativas a el)."""
    return _designer("create_comment", text=text, x=x, y=y, node_id=node_id, graph=graph, package=package)


@mcp.tool()
def auto_layout(
    spacing_x: float | None = None,
    spacing_y: float | None = None,
    graph: str | None = None,
    package: str | None = None,
) -> dict:
    """Ordena los nodos en columnas de izquierda a derecha. Es un layout propio: la API no ofrece uno.

    No mueve frames ni comentarios, asi que usalo antes de crear los frames.
    """
    return _designer("auto_layout", spacing_x=spacing_x, spacing_y=spacing_y, graph=graph, package=package)


# ---------------------------------------------------------------- parameters and outputs


@mcp.tool()
def expose_parameter(
    identifier: str,
    type: str = "float",
    default: Any = None,
    label: str | None = None,
    description: str | None = None,
    group: str | None = None,
    min: float | None = None,
    max: float | None = None,
    step: float | None = None,
    node_id: str | None = None,
    node_parameter: str | None = None,
    graph: str | None = None,
    package: str | None = None,
) -> dict:
    """Crea un parametro del grafo y, con node_id y node_parameter, hace que controle ese parametro del nodo.

    type: float, float2, float3, float4, color, int, int2, int3, int4, bool o string.
    """
    return _designer(
        "expose_parameter", identifier=identifier, type=type, default=default, label=label,
        description=description, group=group, min=min, max=max, step=step, node_id=node_id,
        node_parameter=node_parameter, graph=graph, package=package,
    )


@mcp.tool()
def create_output_node(
    usage: str,
    identifier: str | None = None,
    label: str | None = None,
    x: float = 0,
    y: float = 0,
    source_node: str | None = None,
    source_output: str | None = None,
    graph: str | None = None,
    package: str | None = None,
) -> dict:
    """Crea un nodo de salida con usage: baseColor, normal, roughness, metallic, height o ambientOcclusion.

    Con source_node lo conecta a esa fuente.
    """
    return _designer(
        "create_output_node", usage=usage, identifier=identifier, label=label, x=x, y=y,
        source_node=source_node, source_output=source_output, graph=graph, package=package,
    )


# ---------------------------------------------------------------- saving and export


@mcp.tool()
def save_package(path: str | None = None, package: str | None = None, overwrite: bool = False) -> dict:
    """Guarda un paquete. Un paquete nuevo necesita path (.sbs) dentro de una carpeta permitida."""
    return _designer("save_package", path=path, package=package, overwrite=overwrite or None)


@mcp.tool()
def export_sbsar(output_path: str, package: str | None = None, overwrite: bool = False) -> dict:
    """Exporta un paquete abierto a .sbsar desde Designer. Sin Designer abierto, usa cook_sbs."""
    return _designer("export_sbsar", output_path=output_path, package=package, overwrite=overwrite or None)


@mcp.tool()
async def cook_sbs(input_path: str, output_dir: str, output_name: str | None = None) -> dict:
    """Cocina un .sbs a .sbsar con sbscooker. No necesita Designer abierto."""
    return await _offline(sat.cook_sbs, input_path, output_dir, output_name)


@mcp.tool()
async def render_outputs(
    sbsar_path: str,
    output_dir: str,
    graph: str | None = None,
    outputs: list[str] | None = None,
    usages: list[str] | None = None,
    parameters: dict[str, Any] | None = None,
    output_format: str = "png",
    bit_depth: str | None = None,
    width: int | None = None,
    height: int | None = None,
) -> dict:
    """Renderiza los mapas de un .sbsar con sbsrender. No necesita Designer abierto.

    parameters es {identificador: valor}; los vectores van como lista. Rechaza parametros que el
    archivo no exponga. bit_depth: 8, 16, 16f o 32f.
    Indica width y height (potencias de 2): sin ellos, sbsrender usa 256x256, no el tamano del grafo.
    """
    return await _offline(
        sat.render_outputs, sbsar_path, output_dir, graph=graph, outputs=outputs, usages=usages,
        parameters=parameters, output_format=output_format, bit_depth=bit_depth, width=width, height=height,
    )


@mcp.tool()
async def batch_render(
    sbsar_paths: list[str],
    output_dir: str,
    parameter_sets: list[dict[str, Any]] | None = None,
    output_format: str = "png",
    bit_depth: str | None = None,
    width: int | None = None,
    height: int | None = None,
) -> dict:
    """Renderiza varios .sbsar con varios juegos de parametros. No necesita Designer abierto.

    parameter_sets es una lista de {"name": str, "parameters": {...}}. Los archivos quedan en
    output_dir/<sbsar>/<name>. Un fallo no detiene el resto; revisa "failed" y "jobs".
    Indica width y height: sin ellos, sbsrender usa 256x256.
    """
    return await _offline(
        sat.batch_render, sbsar_paths, output_dir, parameter_sets, output_format=output_format,
        bit_depth=bit_depth, width=width, height=height,
    )


# ---------------------------------------------------------------- escape hatch


@mcp.tool()
def run_python(code: str, confirmed: bool = False) -> dict:
    """Ejecuta codigo Python arbitrario dentro de Designer, en su hilo principal.

    REQUIERE CONFIRMACION EXPLICITA: muestra el codigo al usuario y espera su aprobacion antes de
    llamar con confirmed=true. Puede leer, modificar o borrar cualquier cosa a la que Designer tenga
    acceso; la restriccion de carpetas permitidas NO aplica dentro de este codigo. Usala solo cuando
    ninguna otra herramienta sirva. Dispones de `sd` y `app`; asigna a `result` lo que quieras devolver.
    """
    if not confirmed:
        raise ToolError("run_python requiere la confirmacion explicita del usuario (confirmed=true).")
    return _designer("run_python", code=code, confirmed=True)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
