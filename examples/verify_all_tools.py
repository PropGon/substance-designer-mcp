"""Exercises every tool against a real Designer, on a throwaway graph it creates itself.

It also checks the refusals: paths outside the allowlist, bad values, missing confirmation.
Requires Designer open with the plugin loaded. Usage:
    uv run python examples/verify_all_tools.py <carpeta_permitida>
"""

from __future__ import annotations

import sys
from pathlib import Path

import anyio
from mcp_client import connect

passed = 0


def ok(message: str) -> None:
    global passed
    passed += 1
    print("OK ", message)


async def main(folder: Path) -> None:
    work = folder / "verify_all_tools"
    outside = folder.parent.parent / "fuera_de_permitidas"

    async with connect() as tools:
        call, rejected = tools.call, tools.rejected

        info = await call("get_app_info")
        assert info["executed_on_main_thread"] is True
        assert info["local_installation"]["sbsrender"]
        ok(f"get_app_info: Designer {info['designer_version']}, herramientas {info['local_installation']['tools_version']}")

        graph = await call("create_graph", name="Verify_Graph", width=512, height=512, format="16_bits_per_channel")
        assert graph["graph"] == "Verify_Graph"
        ok("create_graph")
        for bad in (dict(name="1 mal"), dict(name="A", width=1000), dict(name="A", format="int16")):
            await rejected("create_graph", **bad)
        ok("create_graph rechaza nombre, tamano y formato invalidos")

        scope = dict(graph="Verify_Graph")
        listed = await call("list_graphs")
        ours = [p for p in listed["packages"] if any(g["identifier"] == "Verify_Graph" for g in p["graphs"])]
        assert len(ours) == 1
        package = ours[0]["uid"]
        assert not any("resources/packages" in (p["file_path"] or "") for p in listed["packages"])
        ok("list_graphs, sin bibliotecas de Adobe")

        uniform = (await call("create_node", definition="sbs::compositing::uniform", x=-300, y=0, **scope))["id"]
        blend = (await call("create_node", definition="sbs::compositing::blend", x=0, y=0, **scope))["id"]
        noise = (await call("create_node", library="noise_perlin_noise", x=-300, y=200, **scope))["id"]
        ok("create_node, atomico y de biblioteca")
        assert "Atomicas disponibles" in await rejected("create_node", definition="sbs::compositing::nope", **scope)
        assert "Parecidas" in await rejected("create_node", library="noise_perlin", **scope)
        await rejected("create_node", library="../../secreto", **scope)
        await rejected("create_node", definition="sbs::compositing::blend", library="noise_perlin_noise", **scope)
        ok("create_node rechaza definicion, biblioteca y ruta invalidas")

        await call("connect_nodes", from_node=uniform, to_node=blend, to_input="source", **scope)
        await call("connect_nodes", from_node=noise, to_node=blend, to_input="opacity", **scope)
        details = await call("get_node_info", node_id=blend, **scope)
        incoming = {c["input"]: c["from_node"] for c in details["incoming"]}
        assert incoming == {"source": uniform, "opacity": noise}, incoming
        source_info = await call("get_node_info", node_id=uniform, **scope)
        assert source_info["outgoing"][0]["to_node"] == blend
        ok("connect_nodes y get_node_info: conexiones en la direccion correcta")
        await rejected("connect_nodes", from_node=uniform, to_node=blend, to_input="noexiste", **scope)
        await rejected("connect_nodes", from_node=uniform, to_node=blend, to_input="blendingmode", **scope)
        ok("connect_nodes rechaza entradas invalidas o que no son conectables")

        cases = [
            (uniform, "outputcolor", [0.25, 0.5, 0.75, 1.0]),
            (uniform, "colorswitch", False),
            (noise, "scale", 12),
            (noise, "disorder", 0.5),
            (uniform, "$outputsize", [8, 8]),
            (uniform, "$format", "hdr_low_precision"),
        ]
        for node_id, parameter, value in cases:
            await call("set_node_parameter", node_id=node_id, parameter=parameter, value=value, **scope)
            read = await call("get_node_parameter", node_id=node_id, parameter=parameter, **scope)
            assert read["value"] == value, (parameter, read)
        ok(f"set_node_parameter y get_node_parameter: {len(cases)} tipos leidos de vuelta")
        bad_values = [
            (noise, "scale", "doce"), (noise, "scale", True), (noise, "disorder", [1, 2]),
            (uniform, "outputcolor", [1, 2]), (uniform, "$format", "int16"), (uniform, "colorswitch", 1),
            (uniform, "noexiste", 1), (blend, "source", 1),
        ]
        for node_id, parameter, value in bad_values:
            await rejected("set_node_parameter", node_id=node_id, parameter=parameter, value=value, **scope)
        ok(f"set_node_parameter rechaza {len(bad_values)} valores invalidos sin colgarse")
        for node_id, parameter, text, expected in (
            (noise, "scale", "14", 14), (noise, "disorder", "0.25", 0.25), (uniform, "colorswitch", "false", False),
        ):
            await call("set_node_parameter", node_id=node_id, parameter=parameter, value=text, **scope)
            read = await call("get_node_parameter", node_id=node_id, parameter=parameter, **scope)
            assert read["value"] == expected, (parameter, read)
        ok("set_node_parameter acepta numeros y booleanos en forma de texto, como los envia un modelo")

        await call("create_frame", title="Marco", x=-400, y=-100, width=500, height=400, color=[0.2, 0.3, 0.4, 0.5], **scope)
        await call("create_comment", text="Comentario suelto", x=-400, y=-150, **scope)
        await call("create_comment", text="Comentario de nodo", node_id=blend, **scope)
        objects = (await call("list_nodes", **scope))["graph_objects"]
        assert sorted(o["type"] for o in objects) == ["SDGraphObjectComment", "SDGraphObjectComment", "SDGraphObjectFrame"]
        ok("create_frame y create_comment")

        created = await call(
            "expose_parameter", identifier="amount", type="float", default=0.3, label="Amount", min=0, max=1, step=0.01,
            node_id=noise, node_parameter="disorder", **scope,
        )
        assert created["linked_to"]["node_id"] == noise and abs(created["default"] - 0.3) < 1e-6
        driven = await call("get_node_parameter", node_id=noise, parameter="disorder", **scope)
        assert driven["driven_by_function"] is True
        ok("expose_parameter enlazado a un nodo")
        for kind, default in (("int", 3), ("bool", True), ("string", "hola"), ("float2", [1, 2]), ("int3", [1, 2, 3]), ("color", [1, 0, 0, 1])):
            await call("expose_parameter", identifier=f"p_{kind}", type=kind, default=default, **scope)
        ok("expose_parameter con 6 tipos mas")
        normal_node = (await call("create_node", definition="sbs::compositing::normal", **scope))["id"]
        await call("set_node_parameter", node_id=normal_node, parameter="intensity", value=2.5, **scope)
        inherited = await call(
            "expose_parameter", identifier="inherited", type="float", node_id=normal_node, node_parameter="intensity", **scope
        )
        assert abs(inherited["default"] - 2.5) < 1e-6, inherited
        as_text = await call("expose_parameter", identifier="from_text", type="float", default="0.75", **scope)
        assert abs(as_text["default"] - 0.75) < 1e-6, as_text
        ok("expose_parameter sin default conserva el valor del nodo, y acepta el default como texto")
        before = {n["id"] for n in (await call("list_nodes", **scope))["nodes"]}
        await rejected("expose_parameter", identifier="amount", **scope)
        await rejected("expose_parameter", identifier="$malo", **scope)
        await rejected("expose_parameter", identifier="x1", type="nope", **scope)
        await rejected("expose_parameter", identifier="x2", type="string", node_id=noise, node_parameter="scale", **scope)
        await rejected("expose_parameter", identifier="x3", type="float", node_id=noise, node_parameter="disorder", **scope)
        await rejected("expose_parameter", identifier="x4", type="int", default="no", **scope)
        ok("expose_parameter rechaza duplicados y tipos incompatibles")

        for row, usage in enumerate(("baseColor", "normal", "roughness", "metallic", "height", "ambient occlusion")):
            created = await call("create_output_node", usage=usage, x=300, y=row * 120, identifier=f"out_{row}", source_node=blend, **scope)
            assert created["output_identifier"] == f"out_{row}"
        await rejected("create_output_node", usage="brillo", **scope)
        count = len((await call("list_nodes", **scope))["nodes"])
        await rejected("create_output_node", usage="height", identifier="out_x", source_node="noexiste", **scope)
        await rejected("create_output_node", usage="height", identifier="out_y", source_node=blend, source_output="noexiste", **scope)
        assert len((await call("list_nodes", **scope))["nodes"]) == count, "Un fallo dejo un nodo huerfano"
        ok("create_output_node, sin dejar nodos huerfanos si falla")

        temporary = (await call("create_node", definition="sbs::compositing::levels", x=900, y=900, **scope))["id"]
        await call("delete_node", node_id=temporary, **scope)
        await rejected("get_node_info", node_id=temporary, **scope)
        await rejected("delete_node", node_id=temporary, **scope)
        ok("delete_node")

        moved = await call("auto_layout", **scope)
        positions = {n["id"]: n["position"] for n in (await call("list_nodes", **scope))["nodes"]}
        assert moved["moved"] == len(positions)
        assert positions[uniform][0] < positions[blend][0]
        assert len({tuple(p) for p in positions.values()}) == len(positions), "Nodos solapados"
        ok(f"auto_layout: {moved['moved']} nodos sin solaparse")

        sbs = work / "Verify_Graph.sbs"
        await rejected("save_package", package=package)
        ok("save_package exige ruta en un paquete nuevo")
        assert "fuera de las carpetas" in await rejected("save_package", path=str(outside / "x.sbs"), package=package)
        assert "fuera de las carpetas" in await rejected("save_package", path=str(work / ".." / ".." / ".." / ".." / "x.sbs"), package=package)
        await rejected("save_package", path=str(work / "x.txt"), package=package)
        await rejected("save_package", path="relativa.sbs", package=package)
        assert not outside.exists()
        ok("save_package rechaza rutas fuera de las permitidas, traversal, extension y relativas")
        await call("save_package", path=str(sbs), package=package, overwrite=True)
        assert sbs.is_file()
        assert "overwrite" in await rejected("save_package", path=str(folder / "Template_Material.sbs"), package=package)
        await call("save_package", package=package)
        ok("save_package: guardar, proteger otros archivos y volver a guardar")

        sbsar = work / "Verify_Graph_designer.sbsar"
        exported = await call("export_sbsar", output_path=str(sbsar), package=package, overwrite=True)
        assert exported["size_bytes"] > 0
        await rejected("export_sbsar", output_path=str(outside / "x.sbsar"), package=package)
        ok("export_sbsar desde Designer")

        await call("open_graph", graph="Verify_Graph", package=package)
        assert (await call("get_app_info"))["active_graph"] == "Verify_Graph"
        await call("open_graph", file_path=str(folder / "Template_Material.sbs"), graph="Template_Material")
        assert (await call("get_app_info"))["active_graph"] == "Template_Material"
        await rejected("open_graph", file_path=str(outside / "x.sbs"))
        ok("open_graph, por grafo y por archivo")

        cooked = await call("cook_sbs", input_path=str(sbs), output_dir=str(work), output_name="Verify_Graph_cooked")
        assert cooked["size_bytes"] > 0
        await rejected("cook_sbs", input_path=str(outside / "x.sbs"), output_dir=str(work))
        await rejected("cook_sbs", input_path=str(sbs), output_dir=str(outside))
        ok("cook_sbs")

        rendered = await call(
            "render_outputs", sbsar_path=cooked["sbsar"], output_dir=str(work / "render"), usages=["baseColor"],
            output_format="tga", bit_depth="8", width=128, height=128, parameters={"amount": 0.8},
        )
        assert len(rendered["files"]) == 1 and rendered["files"][0].endswith(".tga"), rendered
        await rejected("render_outputs", sbsar_path=str(outside / "x.sbsar"), output_dir=str(work))
        ok("render_outputs con filtro de usage, formato y parametros")

        batch = await call(
            "batch_render", sbsar_paths=[cooked["sbsar"], str(sbsar)], output_dir=str(work / "batch"), width=64, height=64,
            parameter_sets=[{"name": "bajo", "parameters": {"amount": 0.1}}, {"name": "alto", "parameters": {"amount": 0.9}}],
        )
        assert (batch["succeeded"], batch["failed"]) == (4, 0), batch
        assert (work / "batch" / "Verify_Graph_cooked" / "alto").is_dir()
        ok("batch_render: 2 archivos x 2 juegos de parametros")
        partial = await call("batch_render", sbsar_paths=[cooked["sbsar"], str(work / "noexiste.sbsar")], output_dir=str(work / "batch2"))
        assert (partial["succeeded"], partial["failed"]) == (1, 1), partial
        ok("batch_render continua tras un fallo")

        assert "confirmacion" in await rejected("run_python", code="result = 1")
        assert "confirmacion" in await rejected("run_python", code="result = 1", confirmed=False)
        ok("run_python se niega sin confirmacion")
        done = await call("run_python", code="print('hola'); result = app.getVersion()", confirmed=True)
        assert done["ok"] and done["stdout"].strip() == "hola" and info["designer_version"] in done["result"]
        api_error = await call("run_python", code="from sd.api.sdvalueenum import SDValueEnum\nSDValueEnum.sFromValueId('a', 'b')", confirmed=True)
        assert api_error["ok"] is False and "APIException" in api_error["traceback"]
        exiting = await call("run_python", code="raise SystemExit(1)", confirmed=True)
        assert exiting["ok"] is False
        assert (await call("get_app_info"))["executed_on_main_thread"] is True
        ok("run_python: salida, errores de la API y SystemExit sin tumbar Designer")

    print(f"\n{passed} comprobaciones superadas.")


if __name__ == "__main__":
    anyio.run(main, Path(sys.argv[1]).resolve())
