"""sbscooker and sbsrender wrappers. These work without Designer running."""

from __future__ import annotations

import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path

from .config import detect_installation
from .paths import check_input_file, check_output_dir

TOOL_TIMEOUT_SECONDS = 900
PARAMETER_ID_RE = re.compile(r"^\$?[A-Za-z_][A-Za-z0-9_]*$")
SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")
OUTPUT_FORMATS = {"png", "jpg", "tga", "tif", "tiff", "exr", "hdr", "psd", "webp", "bmp", "dds"}
BIT_DEPTHS = {"8", "16", "16f", "32f"}
_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


class ToolFailed(RuntimeError):
    pass


def _executable(name: str) -> Path:
    found = getattr(detect_installation(), name)
    if found is None:
        raise ToolFailed(
            f"No encontre {name}. Viene incluido con Designer. Indica su carpeta con SD_MCP_SAT_DIR "
            "o sat_dir en config.json, o la de Designer con SD_MCP_DESIGNER_DIR o designer_dir."
        )
    return found


def _run(args: list[str]) -> subprocess.CompletedProcess:
    # stdin must not be inherited: it is the MCP stdio channel.
    try:
        completed = subprocess.run(
            args,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=TOOL_TIMEOUT_SECONDS,
            check=False,
            creationflags=_CREATE_NO_WINDOW,
        )
    except subprocess.TimeoutExpired:
        raise ToolFailed(f"{Path(args[0]).name} supero el limite de {TOOL_TIMEOUT_SECONDS} s.") from None
    except OSError as exc:
        raise ToolFailed(f"No se pudo ejecutar {args[0]}: {exc}") from None
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()[-2000:]
        raise ToolFailed(f"{Path(args[0]).name} termino con codigo {completed.returncode}: {detail}")
    return completed


def _format_value(value: object) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)) and math.isfinite(value):
        return str(value)
    if isinstance(value, (list, tuple)) and value and all(
        isinstance(item, (int, float)) and not isinstance(item, bool) and math.isfinite(item) for item in value
    ):
        return ",".join(str(item) for item in value)
    raise ValueError(f"Valor de parametro no admitido: {value!r}. Usa un numero, booleano o lista de numeros.")


def build_render_args(
    executable: str,
    sbsar: str,
    output_dir: str,
    graph: str | None = None,
    outputs: list[str] | None = None,
    usages: list[str] | None = None,
    parameters: dict | None = None,
    output_format: str = "png",
    bit_depth: str | None = None,
    width: int | None = None,
    height: int | None = None,
) -> list[str]:
    if output_format not in OUTPUT_FORMATS:
        raise ValueError(f"output_format debe ser uno de {sorted(OUTPUT_FORMATS)}.")
    if bit_depth is not None and bit_depth not in BIT_DEPTHS:
        raise ValueError(f"bit_depth debe ser uno de {sorted(BIT_DEPTHS)}.")
    args = [
        executable, "render", "--input", sbsar, "--output-path", output_dir,
        "--output-name", "{inputGraphUrl}_{outputNodeName}", "--output-format", output_format,
    ]
    if graph:
        args += ["--input-graph", graph]
    for output in outputs or []:
        args += ["--input-graph-output", output]
    for usage in usages or []:
        args += ["--input-graph-output-usage", usage]
    if bit_depth:
        args += ["--output-bit-depth", bit_depth]

    values = dict(parameters or {})
    if width is not None or height is not None:
        if "$outputsize" in values:
            raise ValueError("Usa width/height o $outputsize, no ambos.")
        if not width or not height or width & (width - 1) or height & (height - 1):
            raise ValueError("width y height deben indicarse juntos y ser potencias de 2.")
        values["$outputsize"] = [int(math.log2(width)), int(math.log2(height))]
    for identifier, value in values.items():
        if not PARAMETER_ID_RE.match(identifier):
            raise ValueError(f"Identificador de parametro no valido: {identifier!r}")
        args += ["--set-value", f"{identifier}@{_format_value(value)}"]
    return args


def _files_in_report(stdout: str) -> list[str]:
    try:
        report = json.loads(stdout)
    except ValueError:
        return []
    found = []

    def walk(item):
        if isinstance(item, dict):
            value = item.get("value")
            if item.get("type") == "image" and isinstance(value, str):
                found.append(value)
            for child in item.values():
                walk(child)
        elif isinstance(item, list):
            for child in item:
                walk(child)

    walk(report)
    return found


def parse_exposed_inputs(info_output: str) -> set[str]:
    return set(re.findall(r"^\s*INPUT\s+(\S+)", info_output, flags=re.MULTILINE))


def problems_only(log: str) -> str | None:
    """The tools write their whole GPU report to stderr; keep only what needs attention."""
    lines = [line for line in log.splitlines() if re.search(r"error|warn", line, re.IGNORECASE)]
    return "\n".join(lines)[-2000:] or None


def _check_requested_parameters(executable: str, sbsar: str, requested: set[str]) -> None:
    # sbsrender silently ignores unknown --set-value entries, which would yield a wrong render.
    if not requested:
        return
    exposed = parse_exposed_inputs(_run([executable, "info", sbsar]).stdout)
    unknown = requested - exposed
    if unknown:
        raise ValueError(
            f"{Path(sbsar).name} no expone {sorted(unknown)}. Parametros disponibles: {sorted(exposed)}. "
            "Si falta $outputsize, el grafo tiene un tamano Absolute y no admite cambiar la resolucion."
        )


def cook_sbs(input_path: str, output_dir: str, output_name: str | None = None) -> dict:
    source = check_input_file(input_path, ".sbs")
    target_dir = check_output_dir(output_dir)
    if output_name is not None and not SAFE_NAME_RE.match(output_name):
        raise ValueError(f"output_name solo admite letras, numeros, _ y -: {output_name!r}")
    args = [str(_executable("sbscooker")), "--inputs", source, "--output-path", target_dir]
    if output_name:
        args += ["--output-name", output_name]
    completed = _run(args)
    name = output_name or Path(source).stem
    produced = os.path.join(target_dir, f"{name}.sbsar")
    if not os.path.isfile(produced):
        raise ToolFailed(f"sbscooker no genero {produced}. Salida: {completed.stdout.strip()[-1000:]}")
    return {
        "sbsar": produced,
        "size_bytes": os.path.getsize(produced),
        "warnings": problems_only(completed.stderr),
    }


def render_outputs(sbsar_path: str, output_dir: str, **options) -> dict:
    source = check_input_file(sbsar_path, ".sbsar")
    target_dir = check_output_dir(output_dir)
    executable = str(_executable("sbsrender"))
    args = build_render_args(executable, source, target_dir, **options)
    requested = {args[i + 1].split("@", 1)[0] for i, item in enumerate(args) if item == "--set-value"}
    _check_requested_parameters(executable, source, requested)
    before = {entry.name: entry.stat().st_mtime_ns for entry in os.scandir(target_dir) if entry.is_file()}
    completed = _run(args)
    files = _files_in_report(completed.stdout)
    if not files:
        files = [
            entry.path
            for entry in os.scandir(target_dir)
            if entry.is_file() and before.get(entry.name) != entry.stat().st_mtime_ns
        ]
    if not files:
        raise ToolFailed(
            "sbsrender termino sin generar imagenes. Comprueba que el grafo tenga salidas conectadas "
            f"y que los filtros de output sean correctos. Salida: {completed.stdout.strip()[-1000:]}"
        )
    return {"files": sorted(files), "warnings": problems_only(completed.stderr)}


def batch_render(
    sbsar_paths: list[str], output_dir: str, parameter_sets: list[dict] | None = None, **options
) -> dict:
    """Renders every archive with every parameter set; one failure does not stop the rest."""
    sets = parameter_sets or [{"name": "default", "parameters": {}}]
    names = [item.get("name") for item in sets]
    for name in names:
        if not isinstance(name, str) or not SAFE_NAME_RE.match(name):
            raise ValueError(f"Cada parameter_set necesita un 'name' con letras, numeros, _ o -: {name!r}")
    if len(set(names)) != len(names):
        raise ValueError("Los nombres de parameter_sets deben ser unicos.")
    root = check_output_dir(output_dir)

    results = []
    for sbsar in sbsar_paths:
        for item in sets:
            job = {"sbsar": sbsar, "parameter_set": item["name"]}
            try:
                target = os.path.join(root, Path(sbsar).stem, item["name"])
                job.update(render_outputs(sbsar, target, parameters=item.get("parameters") or {}, **options))
                job["ok"] = True
            except (ToolFailed, ValueError) as exc:
                job.update(ok=False, error=str(exc))
            results.append(job)
    succeeded = sum(1 for job in results if job["ok"])
    return {"succeeded": succeeded, "failed": len(results) - succeeded, "jobs": results}
