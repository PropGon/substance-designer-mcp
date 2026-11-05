"""Builds "Template_Material" using only MCP tools, then cooks and renders it.

Requires Designer open with the plugin loaded. Usage:
    uv run python examples/build_template_material.py [carpeta_de_salida]
"""

from __future__ import annotations

import sys
from pathlib import Path

import anyio
from mcp_client import connect

FRAME_COLORS = {
    "Shapes": [0.15, 0.35, 0.55, 0.25],
    "Details": [0.45, 0.35, 0.10, 0.25],
    "Color": [0.50, 0.20, 0.25, 0.25],
    "Outputs": [0.15, 0.45, 0.25, 0.25],
}
PARAMETERS = {"base_tint", "noise_scale", "normal_intensity"}
USAGES = ["baseColor", "normal", "roughness", "metallic", "height", "ambientOcclusion"]


async def build(tools, output_dir: Path) -> Path:
    graph = await tools.call("create_graph", name="Template_Material", width=1024, height=1024)
    print("Grafo creado:", graph["graph"])

    async def node(x, y, **source):
        return (await tools.call("create_node", x=x, y=y, **source))["id"]

    async def connect_to(source, target, target_input):
        await tools.call("connect_nodes", from_node=source, to_node=target, to_input=target_input)

    async def gray_uniform(x, y, level):
        uniform = await node(x, y, definition="sbs::compositing::uniform")
        await tools.call("set_node_parameter", node_id=uniform, parameter="colorswitch", value=False)
        await tools.call("set_node_parameter", node_id=uniform, parameter="outputcolor", value=[level, level, level, 1.0])
        return uniform

    # Shapes
    noise = await node(-900, 0, library="noise_perlin_noise")

    # Details
    blur = await node(-600, -130, definition="sbs::compositing::blur")
    normal = await node(-600, 0, definition="sbs::compositing::normal")
    ambient = await node(-600, 130, library="ambient_occlusion_2")
    await connect_to(noise, blur, "input1")
    await connect_to(noise, normal, "input1")
    await connect_to(noise, ambient, "Source")

    # Color
    tint = await node(-300, -260, definition="sbs::compositing::uniform")
    dark = await node(-300, -130, definition="sbs::compositing::uniform")
    await tools.call("set_node_parameter", node_id=dark, parameter="outputcolor", value=[0.05, 0.05, 0.06, 1.0])
    blend = await node(-300, 0, definition="sbs::compositing::blend")
    await connect_to(tint, blend, "source")
    await connect_to(dark, blend, "destination")
    await connect_to(noise, blend, "opacity")
    roughness = await gray_uniform(-300, 130, 0.6)
    metallic = await gray_uniform(-300, 260, 0.0)

    # Outputs
    sources = {
        "baseColor": blend, "normal": normal, "roughness": roughness,
        "metallic": metallic, "height": blur, "ambientOcclusion": ambient,
    }
    for row, usage in enumerate(USAGES):
        await tools.call("create_output_node", usage=usage, label=usage, x=0, y=-325 + row * 130, source_node=sources[usage])

    await tools.call(
        "expose_parameter", identifier="base_tint", type="color", default=[0.72, 0.45, 0.28, 1.0], label="Base Tint",
        group="Material", node_id=tint, node_parameter="outputcolor",
    )
    await tools.call(
        "expose_parameter", identifier="noise_scale", type="int", default=8, label="Noise Scale", group="Shapes",
        min=1, max=64, node_id=noise, node_parameter="scale",
    )
    await tools.call(
        "expose_parameter", identifier="normal_intensity", type="float", default=10.0, label="Normal Intensity",
        group="Details", min=0, max=50, node_id=normal, node_parameter="intensity",
    )

    # The API does not attach nodes to frames: these are simply placed around each column.
    for title, x in (("Shapes", -980), ("Details", -680), ("Color", -380), ("Outputs", -80)):
        await tools.call(
            "create_frame", title=title, x=x, y=-420, width=260, height=840, color=FRAME_COLORS[title],
            description=f"Seccion {title} de Template_Material",
        )
    await tools.call(
        "create_comment", text="Plantilla generada con substance-designer-mcp: cambia Shapes y Details por tu material.",
        x=-980, y=-600,
    )

    sbs = output_dir / "Template_Material.sbs"
    await tools.call("save_package", path=str(sbs), overwrite=True)
    print("Guardado:", sbs)
    return sbs


async def verify_graph(tools) -> None:
    listing = await tools.call("list_nodes", graph="Template_Material")
    titles = {o["title"] for o in listing["graph_objects"] if "title" in o}
    assert titles == set(FRAME_COLORS), titles
    outputs = [n for n in listing["nodes"] if n["definition"] == "sbs::compositing::output"]
    assert len(outputs) == len(USAGES), outputs
    for output in outputs:
        info = await tools.call("get_node_info", node_id=output["id"], graph="Template_Material")
        assert info["incoming"], f"Salida sin conectar: {output['id']}"
    print(f"Grafo verificado: {len(listing['nodes'])} nodos, {len(outputs)} salidas conectadas, frames {sorted(titles)}")


async def main(output_dir: Path) -> None:
    async with connect() as tools:
        info = await tools.call("get_app_info")
        print("Designer", info["designer_version"], "- hilo principal:", info["executed_on_main_thread"])
        sbs = await build(tools, output_dir)
        await verify_graph(tools)

        cooked = await tools.call("cook_sbs", input_path=str(sbs), output_dir=str(output_dir))
        print("Cocinado:", cooked["sbsar"], cooked["size_bytes"], "bytes")
        rendered = await tools.call(
            "render_outputs", sbsar_path=cooked["sbsar"], output_dir=str(output_dir / "render_default"), width=1024, height=1024
        )
        print("Mapas renderizados:", len(rendered["files"]))
        for path in rendered["files"]:
            print(" ", Path(path).name)


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home() / "Documents" / "SubstanceDesignerMCP"
    anyio.run(main, target.resolve())
