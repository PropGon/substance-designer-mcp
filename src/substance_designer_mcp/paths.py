"""Folder allowlist for the tools that run without Designer."""

from __future__ import annotations

import os
from pathlib import Path

from .config import load_file_config


class PathNotAllowed(ValueError):
    pass


def allowed_dirs() -> list[str]:
    env_value = os.environ.get("SD_MCP_ALLOWED_DIRS")
    if env_value:
        configured = [item for item in env_value.split(os.pathsep) if item.strip()]
    else:
        configured = load_file_config().get("allowed_dirs") or []
    default = Path.home() / "Documents" / "SubstanceDesignerMCP"
    return [os.path.realpath(item) for item in configured] or [os.path.realpath(default)]


def _is_inside(path: str, root: str) -> bool:
    path_norm, root_norm = os.path.normcase(path), os.path.normcase(root)
    try:
        return os.path.commonpath([path_norm, root_norm]) == root_norm
    except ValueError:  # different drives
        return False


def _check(path: str) -> str:
    if not os.path.isabs(path):
        raise PathNotAllowed(f"Se necesita una ruta absoluta: {path!r}")
    resolved = os.path.realpath(path)
    roots = allowed_dirs()
    if not any(_is_inside(resolved, root) for root in roots):
        raise PathNotAllowed(
            f"La ruta {resolved} esta fuera de las carpetas permitidas: {roots}. "
            "Agrega la carpeta a allowed_dirs en config.json o a SD_MCP_ALLOWED_DIRS."
        )
    return resolved


def check_input_file(path: str, suffix: str) -> str:
    resolved = _check(path)
    if not resolved.lower().endswith(suffix):
        raise PathNotAllowed(f"El archivo debe terminar en {suffix}: {resolved}")
    if not os.path.isfile(resolved):
        raise PathNotAllowed(f"No existe el archivo: {resolved}")
    return resolved


def check_output_dir(path: str) -> str:
    resolved = _check(path)
    os.makedirs(resolved, exist_ok=True)
    return resolved
