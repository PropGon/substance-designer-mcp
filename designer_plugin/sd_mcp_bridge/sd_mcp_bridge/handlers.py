"""Bridge commands. Everything here runs on Designer's main thread."""

from __future__ import annotations

import contextlib
import ctypes
import difflib
import importlib
import io
import math
import os
import re
import sys
import traceback

import sd
from PySide6 import QtCore
from sd.api import sdbasetypes
from sd.api.apiexception import APIException
from sd.api.sbs.sdsbsarexporter import SDSBSARExporter
from sd.api.sbs.sdsbscompgraph import SDSBSCompGraph
from sd.api.sdapplication import SDApplicationPath
from sd.api.sdbasetypes import ColorRGBA, float2
from sd.api.sdgraphobjectcomment import SDGraphObjectComment
from sd.api.sdgraphobjectframe import SDGraphObjectFrame
from sd.api.sdhistoryutils import SDHistoryUtils
from sd.api.sdproperty import SDPropertyCategory, SDPropertyInheritanceMethod
from sd.api.sdtypeenum import SDTypeEnum
from sd.api.sdtypeusage import SDTypeUsage
from sd.api.sdusage import SDUsage
from sd.api.sdvaluearray import SDValueArray
from sd.api.sdvalueenum import SDValueEnum
from sd.api.sdvaluestring import SDValueString
from sd.api.sdvalueusage import SDValueUsage
from sd.ui.graphgrid import GraphGrid

from .coercion import coerce_scalar
from .layout import compute_layout
from .security import check_path
from .transport import BridgeError

INPUT = SDPropertyCategory.Input
OUTPUT = SDPropertyCategory.Output

IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
LIBRARY_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")

GRAPH_SIZES = (1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024, 2048, 4096, 8192)

# Same usage names and RGBA components as Adobe's PBR templates in resources/templates.
OUTPUT_USAGES = {
    "basecolor": "baseColor",
    "normal": "normal",
    "roughness": "roughness",
    "metallic": "metallic",
    "height": "height",
    "ambientocclusion": "ambientOcclusion",
    "ambient occlusion": "ambientOcclusion",
    "ambient_occlusion": "ambientOcclusion",
    "ao": "ambientOcclusion",
}

# parameter type -> (sd type module, class, getter function node, node property types it can drive)
PARAMETER_TYPES = {
    "float": ("sdtypefloat", "SDTypeFloat", "get_float1", {"float"}),
    "float2": ("sdtypefloat2", "SDTypeFloat2", "get_float2", {"float2"}),
    "float3": ("sdtypefloat3", "SDTypeFloat3", "get_float3", {"float3"}),
    "float4": ("sdtypefloat4", "SDTypeFloat4", "get_float4", {"float4", "ColorRGBA"}),
    "color": ("sdtypefloat4", "SDTypeFloat4", "get_float4", {"float4", "ColorRGBA"}),
    "int": ("sdtypeint", "SDTypeInt", "get_integer1", {"int"}),
    "int2": ("sdtypeint2", "SDTypeInt2", "get_integer2", {"int2"}),
    "int3": ("sdtypeint3", "SDTypeInt3", "get_integer3", {"int3"}),
    "int4": ("sdtypeint4", "SDTypeInt4", "get_integer4", {"int4"}),
    "bool": ("sdtypebool", "SDTypeBool", "get_bool", {"bool"}),
    "string": ("sdtypestring", "SDTypeString", "get_string", {"string"}),
}

SCALAR_VALUES = {
    "bool": ("sdvaluebool", "SDValueBool"),
    "int": ("sdvalueint", "SDValueInt"),
    "float": ("sdvaluefloat", "SDValueFloat"),
    "double": ("sdvaluedouble", "SDValueDouble"),
    "string": ("sdvaluestring", "SDValueString"),
}

def _on_main_thread() -> bool:
    return QtCore.QThread.currentThread() == QtCore.QCoreApplication.instance().thread()


def _app():
    return sd.getContext().getSDApplication()


def _resources_dir() -> str:
    return _app().getPath(SDApplicationPath.DefaultResourcesDir)


def _require(params: dict, key: str, kind=str):
    value = params.get(key)
    if not isinstance(value, kind) or isinstance(value, bool) and kind is not bool or value == "":
        raise BridgeError("invalid_params", f"Parametro invalido o ausente: '{key}'.")
    return value


def _number(params: dict, key: str, default: float = 0.0) -> float:
    value = params.get(key, default)
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise BridgeError("invalid_params", f"'{key}' debe ser un numero.")
    return float(value)


def _identifier(value: object, what: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER_RE.match(value):
        raise BridgeError(
            "invalid_params", f"{what} debe usar solo letras, numeros y _ sin empezar por numero: {value!r}"
        )
    return value


# ---------------------------------------------------------------- packages and graphs


def _is_library_package(package) -> bool:
    file_path = package.getFilePath()
    if not file_path:
        return False
    root = os.path.normcase(os.path.realpath(_resources_dir()))
    return os.path.normcase(os.path.realpath(file_path)).startswith(root + os.sep)


def _user_packages() -> list:
    # loadUserPackage also lists Adobe's library packages as user packages; hide them.
    return [p for p in _app().getPackageMgr().getUserPackages() if not _is_library_package(p)]


def _describe_package(package) -> dict:
    return {
        "uid": package.getUID(),
        "file_path": package.getFilePath() or None,
        "modified": package.isModified(),
    }


def _graphs_in(package) -> list:
    return [r for r in package.getChildrenResources(True) if isinstance(r, SDSBSCompGraph)]


def _current_graph():
    ui_manager = _app().getUIMgr()
    return ui_manager.getCurrentGraph() if ui_manager else None


def _resolve_package(reference: str | None):
    packages = _user_packages()
    if reference is None:
        graph = _current_graph()
        if graph is not None:
            return graph.getPackage()
        if len(packages) == 1:
            return packages[0]
        raise BridgeError(
            "package_required", f"Indica 'package' (uid o ruta). Paquetes abiertos: {len(packages)}."
        )
    normalized = os.path.normcase(os.path.realpath(reference)) if os.path.isabs(reference) else None
    for package in packages:
        if package.getUID() == reference:
            return package
        file_path = package.getFilePath()
        if normalized and file_path and os.path.normcase(os.path.realpath(file_path)) == normalized:
            return package
    raise BridgeError("not_found", f"No hay ningun paquete abierto con uid o ruta: {reference}")


def _resolve_graph(params: dict):
    name = params.get("graph")
    package_ref = params.get("package")
    if name is None and package_ref is None:
        graph = _current_graph()
        if not isinstance(graph, SDSBSCompGraph):
            raise BridgeError(
                "graph_required", "No hay un grafo de composicion activo. Indica 'graph' o usa open_graph."
            )
        return graph
    packages = [_resolve_package(package_ref)] if package_ref else _user_packages()
    matches = [
        g for package in packages for g in _graphs_in(package) if name is None or g.getIdentifier() == name
    ]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise BridgeError("not_found", f"No existe el grafo '{name}'. Usa list_graphs para ver los disponibles.")
    raise BridgeError("ambiguous", f"Hay {len(matches)} grafos que coinciden; indica 'graph' y 'package'.")


def _resolve_node(graph, node_id: object, key: str = "node_id"):
    if not isinstance(node_id, str) or not node_id:
        raise BridgeError("invalid_params", f"Parametro invalido o ausente: '{key}'.")
    node = graph.getNodeFromId(node_id)
    if node is None:
        raise BridgeError(
            "not_found", f"El nodo '{node_id}' no existe en '{graph.getIdentifier()}'. Usa list_nodes."
        )
    return node


# ---------------------------------------------------------------- values


def _value_class(module: str, name: str):
    return getattr(importlib.import_module(f"sd.api.{module}"), name)


def _check_scalar(type_id: str, raw: object, where: str):
    try:
        return coerce_scalar(type_id, raw)
    except ValueError:
        raise BridgeError("invalid_value", f"{where} espera un valor de tipo {type_id}, no {raw!r}.") from None


def _make_value(sd_type, raw: object, where: str):
    type_id = sd_type.getId()
    if isinstance(sd_type, SDTypeEnum):
        choices = [item.getId() for item in sd_type.getEnumerators()]
        if raw not in choices:
            raise BridgeError("invalid_value", f"{where} debe ser uno de {choices}, no {raw!r}.")
        return SDValueEnum.sFromValueId(type_id, raw)
    if type_id in SCALAR_VALUES:
        module, name = SCALAR_VALUES[type_id]
        return _value_class(module, name).sNew(_check_scalar(type_id, raw, where))

    if type_id in ("ColorRGB", "ColorRGBA"):
        base, size = "float", 3 if type_id == "ColorRGB" else 4
    else:
        match = re.fullmatch(r"(bool|int|float|double)([234])", type_id)
        if not match:
            raise BridgeError(
                "unsupported_type",
                f"{where} es de tipo {type_id}, que esta herramienta no admite. Usa run_python.",
            )
        base, size = match.group(1), int(match.group(2))
    if not isinstance(raw, (list, tuple)) or len(raw) != size:
        raise BridgeError("invalid_value", f"{where} espera una lista de {size} valores de tipo {base}.")
    items = [_check_scalar(base, item, where) for item in raw]
    value_class = _value_class(f"sdvalue{type_id.lower()}", f"SDValue{type_id[0].upper()}{type_id[1:]}")
    return value_class.sNew(getattr(sdbasetypes, type_id)(*items))


def _to_json(value):
    if value is None:
        return None
    if isinstance(value, SDValueEnum):
        return value.getValueId()
    getter = getattr(value, "get", None)
    if getter is None:
        return f"<{type(value).__name__}>"
    try:
        raw = getter()
    except (Exception, APIException):
        return f"<{type(value).__name__}>"
    if raw is None or isinstance(raw, (bool, int, float, str)):
        return raw
    if isinstance(raw, ctypes.Structure):
        return [getattr(raw, field[0]) for field in raw._fields_]
    return f"<{type(value).__name__}>"


def _property(owner, property_id: str, category):
    found = owner.getPropertyFromId(property_id, category)
    if found is None:
        available = [p.getId() for p in owner.getProperties(category)]
        raise BridgeError("not_found", f"No existe la propiedad '{property_id}'. Disponibles: {available}")
    return found


# ---------------------------------------------------------------- read tools


def get_app_info(_params: dict) -> dict:
    app = _app()
    graph = _current_graph()
    return {
        "designer_version": app.getVersion(),
        "installation_dir": app.getPath(SDApplicationPath.InstallationDir),
        "python_version": sys.version.split()[0],
        "executed_on_main_thread": _on_main_thread(),
        "active_graph": graph.getIdentifier() if graph else None,
        "active_package": _describe_package(graph.getPackage()) if graph else None,
        "open_packages": [_describe_package(p) for p in _user_packages()],
    }


def list_graphs(_params: dict) -> dict:
    current = _current_graph()
    current_url = current.getUrl() if current else None
    return {
        "packages": [
            {
                **_describe_package(package),
                "graphs": [
                    {"identifier": g.getIdentifier(), "url": g.getUrl(), "active": g.getUrl() == current_url}
                    for g in _graphs_in(package)
                ],
            }
            for package in _user_packages()
        ]
    }


def _describe_node_brief(node) -> dict:
    position = node.getPosition()
    definition = node.getDefinition()
    return {
        "id": node.getIdentifier(),
        "definition": definition.getId() if definition else None,
        "label": definition.getLabel() if definition else None,
        "position": [position.x, position.y],
    }


def _describe_graph_object(item) -> dict:
    position = item.getPosition()
    described = {
        "type": type(item).__name__,
        "position": [position.x, position.y],
        "description": item.getDescription(),
    }
    if isinstance(item, SDGraphObjectFrame):
        size = item.getSize()
        described.update(title=item.getTitle(), size=[size.x, size.y])
    return described


def list_nodes(params: dict) -> dict:
    graph = _resolve_graph(params)
    return {
        "graph": graph.getIdentifier(),
        "nodes": [_describe_node_brief(node) for node in graph.getNodes()],
        "graph_objects": [_describe_graph_object(item) for item in graph.getGraphObjects()],
    }


def get_node_info(params: dict) -> dict:
    graph = _resolve_graph(params)
    node = _resolve_node(graph, params.get("node_id"))
    info = _describe_node_brief(node)

    resource = node.getReferencedResource()
    if resource is not None:
        info["referenced_resource"] = resource.getUrl()

    connectable_inputs, parameters, incoming = [], [], []
    for prop in node.getProperties(INPUT):
        if prop.isConnectable():
            connectable_inputs.append({"id": prop.getId(), "type": prop.getType().getId()})
            # Seen from a node, getInputProperty*() is always the far end of the connection.
            for connection in node.getPropertyConnections(prop):
                incoming.append(
                    {
                        "input": prop.getId(),
                        "from_node": connection.getInputPropertyNode().getIdentifier(),
                        "from_output": connection.getInputProperty().getId(),
                    }
                )
        else:
            parameters.append(
                {
                    "id": prop.getId(),
                    "label": prop.getLabel(),
                    "type": prop.getType().getId(),
                    "value": None if prop.isFunctionOnly() else _to_json(node.getPropertyValue(prop)),
                    "driven_by_function": node.getPropertyGraph(prop) is not None,
                }
            )

    outputs, outgoing = [], []
    for prop in node.getProperties(OUTPUT):
        outputs.append({"id": prop.getId(), "type": prop.getType().getId()})
        for connection in node.getPropertyConnections(prop):
            outgoing.append(
                {
                    "output": prop.getId(),
                    "to_node": connection.getInputPropertyNode().getIdentifier(),
                    "to_input": connection.getInputProperty().getId(),
                }
            )

    info.update(
        inputs=connectable_inputs, outputs=outputs, parameters=parameters, incoming=incoming, outgoing=outgoing
    )
    return info


def get_node_parameter(params: dict) -> dict:
    graph = _resolve_graph(params)
    node = _resolve_node(graph, params.get("node_id"))
    prop = _property(node, _require(params, "parameter"), INPUT)
    return {
        "parameter": prop.getId(),
        "type": prop.getType().getId(),
        "value": _to_json(node.getPropertyValue(prop)),
        "driven_by_function": node.getPropertyGraph(prop) is not None,
    }


# ---------------------------------------------------------------- graph tools


def open_graph(params: dict) -> dict:
    file_path = params.get("file_path")
    if file_path is not None:
        resolved = check_path(file_path, ".sbs", must_exist=True)
        package = _app().getPackageMgr().loadUserPackage(resolved)
        params = {**params, "package": package.getUID()}
    graph = _resolve_graph(params)
    _app().getUIMgr().openResourceInEditor(graph)
    return {"graph": graph.getIdentifier(), "package": _describe_package(graph.getPackage())}


def create_graph(params: dict) -> dict:
    name = _identifier(params.get("name"), "'name'")
    width, height = params.get("width", 1024), params.get("height", 1024)
    if width not in GRAPH_SIZES or height not in GRAPH_SIZES or isinstance(width, bool) or isinstance(height, bool):
        raise BridgeError("invalid_params", f"width y height deben ser potencias de 2: {GRAPH_SIZES}")

    format_name = params.get("format", "8_bits_per_channel")
    format_value = _make_value(SDTypeEnum.sNew("sbs::compositing::format"), format_name, "'format'")

    package_ref = params.get("package")
    if package_ref:
        package = _resolve_package(package_ref)
        if name in [g.getIdentifier() for g in _graphs_in(package)]:
            raise BridgeError("already_exists", f"El paquete ya tiene un grafo llamado '{name}'.")
    else:
        package = _app().getPackageMgr().newUserPackage()

    graph = SDSBSCompGraph.sNew(package)
    graph.setIdentifier(name)
    # Not an Absolute $outputsize: sbscooker would then stop exposing it and sbsrender could
    # no longer choose the resolution. A default parent size keeps it overridable.
    graph.setDefaultParentSize(sdbasetypes.int2(width, height))
    format_prop = graph.getPropertyFromId("$format", INPUT)
    graph.setPropertyInheritanceMethod(format_prop, SDPropertyInheritanceMethod.Absolute)
    graph.setPropertyValue(format_prop, format_value)
    _app().getUIMgr().openResourceInEditor(graph)
    return {
        "graph": graph.getIdentifier(),
        "url": graph.getUrl(),
        "width": width,
        "height": height,
        "format": format_name,
        "package": _describe_package(package),
    }


def _library_resource(library: object, wanted: object):
    if not isinstance(library, str) or not LIBRARY_NAME_RE.match(library):
        raise BridgeError("invalid_params", f"Nombre de biblioteca invalido: {library!r}")
    packages_dir = os.path.join(_resources_dir(), "packages")
    file_name = library if library.endswith(".sbs") else f"{library}.sbs"
    path = os.path.join(packages_dir, file_name)
    if not os.path.isfile(path):
        names = [n[:-4] for n in os.listdir(packages_dir) if n.endswith(".sbs")]
        close = difflib.get_close_matches(library, names, n=8, cutoff=0.4)
        raise BridgeError("not_found", f"No existe la biblioteca '{library}'. Parecidas: {close}")
    manager = _app().getPackageMgr()
    package = manager.getUserPackageFromFilePath(path) or manager.loadUserPackage(path)
    graphs = _graphs_in(package)
    identifiers = [g.getIdentifier() for g in graphs]
    if wanted is None:
        if len(graphs) == 1:
            return graphs[0]
        raise BridgeError("ambiguous", f"La biblioteca tiene varios grafos; indica 'library_graph': {identifiers}")
    for graph in graphs:
        if graph.getIdentifier() == wanted:
            return graph
    raise BridgeError("not_found", f"'{library}' no contiene '{wanted}'. Disponibles: {identifiers}")


def create_node(params: dict) -> dict:
    graph = _resolve_graph(params)
    definition = params.get("definition")
    library = params.get("library")
    x, y = _number(params, "x"), _number(params, "y")
    if bool(definition) == bool(library):
        raise BridgeError("invalid_params", "Indica 'definition' (nodo atomico) o 'library' (nodo de biblioteca).")
    if library:
        node = graph.newInstanceNode(_library_resource(library, params.get("library_graph")))
    else:
        available = [d.getId() for d in graph.getNodeDefinitions()]
        if definition not in available:
            raise BridgeError(
                "not_found",
                f"Definicion desconocida: {definition!r}. Atomicas disponibles: {available}. "
                "Para filtros como ruido o patrones usa 'library', p. ej. noise_perlin_noise.",
            )
        node = graph.newNode(definition)
    node.setPosition(float2(x, y))
    return _describe_node_brief(node)


def delete_node(params: dict) -> dict:
    graph = _resolve_graph(params)
    node = _resolve_node(graph, params.get("node_id"))
    identifier = node.getIdentifier()
    graph.deleteNode(node)
    return {"deleted": identifier}


def _connect(source, source_output, target, target_input):
    outputs = source.getProperties(OUTPUT)
    if source_output is None:
        if not outputs:
            raise BridgeError("invalid_params", f"El nodo {source.getIdentifier()} no tiene salidas.")
        source_output = outputs[0].getId()
    else:
        _property(source, source_output, OUTPUT)
    prop = _property(target, target_input, INPUT)
    if not prop.isConnectable():
        connectable = [p.getId() for p in target.getProperties(INPUT) if p.isConnectable()]
        raise BridgeError(
            "invalid_params", f"'{target_input}' es un parametro, no una entrada conectable. Entradas: {connectable}"
        )
    source.newPropertyConnectionFromId(source_output, target, target_input)
    return source_output


def connect_nodes(params: dict) -> dict:
    graph = _resolve_graph(params)
    source = _resolve_node(graph, params.get("from_node"), "from_node")
    target = _resolve_node(graph, params.get("to_node"), "to_node")
    to_input = _require(params, "to_input")
    from_output = _connect(source, params.get("from_output"), target, to_input)
    return {
        "from_node": source.getIdentifier(),
        "from_output": from_output,
        "to_node": target.getIdentifier(),
        "to_input": to_input,
    }


def set_node_parameter(params: dict) -> dict:
    graph = _resolve_graph(params)
    node = _resolve_node(graph, params.get("node_id"))
    parameter = _require(params, "parameter")
    prop = _property(node, parameter, INPUT)
    if prop.isConnectable():
        raise BridgeError("invalid_params", f"'{parameter}' es una entrada conectable. Usa connect_nodes.")
    if prop.isReadOnly():
        raise BridgeError("read_only", f"'{parameter}' es de solo lectura.")
    value = _make_value(prop.getType(), params.get("value"), f"'{parameter}'")
    if parameter in ("$outputsize", "$format", "$pixelsize", "$pixelratio", "$tiling"):
        # Inherited system parameters ignore their own value unless set to Absolute.
        node.setInputPropertyInheritanceMethodFromId(parameter, SDPropertyInheritanceMethod.Absolute)
    node.setPropertyValue(prop, value)
    return {"parameter": parameter, "value": _to_json(node.getPropertyValue(prop))}


def create_frame(params: dict) -> dict:
    graph = _resolve_graph(params)
    x, y = _number(params, "x"), _number(params, "y")
    width, height = _number(params, "width", 400.0), _number(params, "height", 300.0)
    if width <= 0 or height <= 0:
        raise BridgeError("invalid_params", "width y height deben ser mayores que 0.")
    color = params.get("color")
    if color is not None:
        valid = isinstance(color, list) and len(color) == 4
        if not valid or not all(isinstance(c, (int, float)) and not isinstance(c, bool) for c in color):
            raise BridgeError("invalid_value", "'color' debe ser [r, g, b, a].")
    frame = SDGraphObjectFrame.sNew(graph)
    frame.setPosition(float2(x, y))
    frame.setSize(float2(width, height))
    frame.setTitle(_require(params, "title"))
    if params.get("description"):
        frame.setDescription(str(params["description"]))
    if color is not None:
        frame.setColor(ColorRGBA(*color))
    return _describe_graph_object(frame)


def create_comment(params: dict) -> dict:
    graph = _resolve_graph(params)
    text = _require(params, "text")
    node_id = params.get("node_id")
    if node_id:
        comment = SDGraphObjectComment.sNewAsChild(_resolve_node(graph, node_id))
    else:
        comment = SDGraphObjectComment.sNew(graph)
    comment.setPosition(float2(_number(params, "x"), _number(params, "y")))
    comment.setDescription(text)
    return _describe_graph_object(comment)


def expose_parameter(params: dict) -> dict:
    graph = _resolve_graph(params)
    identifier = _identifier(params.get("identifier"), "'identifier'")
    type_name = params.get("type", "float")
    if type_name not in PARAMETER_TYPES:
        raise BridgeError("invalid_params", f"'type' debe ser uno de {sorted(PARAMETER_TYPES)}.")
    if graph.getPropertyFromId(identifier, INPUT) is not None:
        raise BridgeError("already_exists", f"El grafo ya tiene un parametro '{identifier}'.")
    module, class_name, getter_name, drivable = PARAMETER_TYPES[type_name]

    # Everything that can be refused is checked before the graph is touched.
    target_node, target_prop = None, None
    if params.get("node_id") or params.get("node_parameter"):
        target_node = _resolve_node(graph, params.get("node_id"))
        target_prop = _property(target_node, _require(params, "node_parameter"), INPUT)
        target_types = {t.getId() for t in target_prop.getTypes()}
        if not target_types & drivable:
            raise BridgeError(
                "type_mismatch",
                f"Un parametro {type_name} no puede controlar '{target_prop.getId()}' ({sorted(target_types)}).",
            )
        if target_node.getPropertyGraph(target_prop) is not None:
            raise BridgeError("already_exists", f"'{target_prop.getId()}' ya esta controlado por una funcion.")

    sd_type = _value_class(module, class_name).sNew()
    raw_default = params.get("default")
    if raw_default is None and target_node is not None:
        # Otherwise the new parameter starts empty and silently changes how the node looks.
        current = _to_json(target_node.getPropertyValue(target_prop))
        if isinstance(current, (bool, int, float, list)) or (isinstance(current, str) and not current.startswith("<")):
            raw_default = current
    default = _make_value(sd_type, raw_default, "'default'") if raw_default is not None else None

    prop = graph.newProperty(identifier, sd_type, INPUT)
    try:
        if default is not None:
            graph.setPropertyValue(prop, default)
        annotations = {a.getId(): a for a in graph.getPropertyAnnotations(prop)}
        settings = {key: params[key] for key in ("label", "description", "group", "min", "max", "step") if params.get(key) is not None}
        if type_name == "color":
            settings["editor"] = "color"
        if params.get("min") is not None and params.get("max") is not None:
            settings["clamp"] = True
        for key, raw in settings.items():
            if key in annotations:
                value = _make_value(annotations[key].getType(), raw, f"'{key}'")
                graph.setPropertyAnnotationValueFromId(prop, key, value)
        if target_node is not None:
            function_graph = target_node.newPropertyGraph(target_prop, "SDSBSFunctionGraph")
            getter = function_graph.newNode(f"sbs::function::{getter_name}")
            getter.setInputPropertyValueFromId("__constant__", SDValueString.sNew(identifier))
            function_graph.setOutputNode(getter, True)
    except BaseException:
        graph.deleteProperty(prop)
        raise
    return {
        "identifier": identifier,
        "type": type_name,
        "default": _to_json(graph.getPropertyValue(prop)),
        "linked_to": {"node_id": target_node.getIdentifier(), "parameter": target_prop.getId()} if target_node else None,
    }


def create_output_node(params: dict) -> dict:
    graph = _resolve_graph(params)
    requested = str(params.get("usage", ""))
    usage = OUTPUT_USAGES.get(requested.lower())
    if usage is None:
        raise BridgeError("invalid_params", f"'usage' no valido: {requested!r}. Opciones: {sorted(set(OUTPUT_USAGES.values()))}")
    identifier = _identifier(params.get("identifier") or usage, "'identifier'")
    source = _resolve_node(graph, params.get("source_node"), "source_node") if params.get("source_node") else None
    x, y = _number(params, "x"), _number(params, "y")

    node = graph.newNode("sbs::compositing::output")
    node.setPosition(float2(x, y))
    usages = SDValueArray.sNew(SDTypeUsage.sNew(), 0)
    usages.pushBack(SDValueUsage.sNew(SDUsage.sNew(usage, "RGBA", "")))
    node.setAnnotationPropertyValueFromId("usages", usages)
    node.setAnnotationPropertyValueFromId("identifier", SDValueString.sNew(identifier))
    node.setAnnotationPropertyValueFromId("label", SDValueString.sNew(str(params.get("label") or identifier)))
    if source is not None:
        try:
            _connect(source, params.get("source_output"), node, "inputNodeOutput")
        except BaseException:
            graph.deleteNode(node)
            raise
    return {**_describe_node_brief(node), "usage": usage, "output_identifier": identifier}


def auto_layout(params: dict) -> dict:
    graph = _resolve_graph(params)
    grid = GraphGrid.sGetFirstLevelSize()
    spacing_x = _number(params, "spacing_x", grid * 2.0)
    spacing_y = _number(params, "spacing_y", grid * 1.5)
    if spacing_x <= 0 or spacing_y <= 0:
        raise BridgeError("invalid_params", "El espaciado debe ser mayor que 0.")
    nodes = {node.getIdentifier(): node for node in graph.getNodes()}
    edges = []
    for identifier, node in nodes.items():
        for prop in node.getProperties(INPUT):
            if prop.isConnectable():
                for connection in node.getPropertyConnections(prop):
                    edges.append((connection.getInputPropertyNode().getIdentifier(), identifier))
    positions = compute_layout(list(nodes), edges, spacing_x, spacing_y)
    for identifier, (x, y) in positions.items():
        nodes[identifier].setPosition(float2(x, y))
    return {
        "moved": len(positions),
        "note": "Los frames y comentarios no se mueven: la API no indica que nodos contiene cada frame.",
    }


# ---------------------------------------------------------------- saving and export


def _check_overwrite(target: str, own_path: str | None, overwrite: object) -> None:
    same = own_path and os.path.normcase(os.path.realpath(own_path)) == os.path.normcase(target)
    if os.path.exists(target) and not same and overwrite is not True:
        raise BridgeError("already_exists", f"Ya existe {target}. Pasa overwrite=true para reemplazarlo.")


def save_package(params: dict) -> dict:
    package = _resolve_package(params.get("package"))
    manager = _app().getPackageMgr()
    current = package.getFilePath() or None
    path = params.get("path")
    if path is None:
        if current is None:
            raise BridgeError("path_required", "El paquete es nuevo y aun no tiene archivo: indica 'path' (.sbs).")
        check_path(current, ".sbs")
        manager.savePackage(package)
    else:
        target = check_path(path, ".sbs")
        _check_overwrite(target, current, params.get("overwrite"))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        manager.savePackageAs(package, target)
    return _describe_package(package)


def export_sbsar(params: dict) -> dict:
    package = _resolve_package(params.get("package"))
    target = check_path(params.get("output_path"), ".sbsar")
    _check_overwrite(target, None, params.get("overwrite"))
    os.makedirs(os.path.dirname(target), exist_ok=True)
    SDSBSARExporter.sNew().exportPackageToSBSAR(package, target)
    return {"output_path": target, "size_bytes": os.path.getsize(target)}


def run_python(params: dict) -> dict:
    if params.get("confirmed") is not True:
        raise BridgeError("confirmation_required", "run_python requiere confirmed=true.")
    code = params.get("code")
    if not isinstance(code, str) or not code.strip():
        raise BridgeError("invalid_params", "'code' debe ser texto no vacio.")
    scope = {"sd": sd, "app": _app(), "result": None}
    stdout = io.StringIO()
    try:
        with contextlib.redirect_stdout(stdout):
            exec(compile(code, "<run_python>", "exec"), scope)
    except BaseException:  # includes sd's APIException and SystemExit from the submitted code
        return {"ok": False, "stdout": stdout.getvalue(), "traceback": traceback.format_exc()}
    return {"ok": True, "stdout": stdout.getvalue(), "result": repr(scope.get("result"))}


COMMANDS = {
    "get_app_info": get_app_info,
    "list_graphs": list_graphs,
    "open_graph": open_graph,
    "create_graph": create_graph,
    "list_nodes": list_nodes,
    "get_node_info": get_node_info,
    "create_node": create_node,
    "delete_node": delete_node,
    "connect_nodes": connect_nodes,
    "set_node_parameter": set_node_parameter,
    "get_node_parameter": get_node_parameter,
    "create_frame": create_frame,
    "create_comment": create_comment,
    "expose_parameter": expose_parameter,
    "create_output_node": create_output_node,
    "auto_layout": auto_layout,
    "save_package": save_package,
    "export_sbsar": export_sbsar,
    "run_python": run_python,
}

# Grouped into a single undo step so Ctrl+Z reverts one tool call as a whole.
UNDOABLE = {
    "create_node",
    "delete_node",
    "connect_nodes",
    "set_node_parameter",
    "create_frame",
    "create_comment",
    "expose_parameter",
    "create_output_node",
    "auto_layout",
}


def execute(command: str, params: dict):
    handler = COMMANDS.get(command)
    if handler is None:
        raise BridgeError("unknown_command", f"Comando desconocido: {command}")
    if not _on_main_thread():
        raise BridgeError("wrong_thread", "El comando no se esta ejecutando en el hilo principal.")
    try:
        if command in UNDOABLE:
            with SDHistoryUtils.UndoGroup(f"MCP: {command}"):
                return handler(params)
        return handler(params)
    except APIException as exc:
        raise BridgeError("designer_api_error", f"La API de Designer devolvio {exc.mErrorCode}.") from None
