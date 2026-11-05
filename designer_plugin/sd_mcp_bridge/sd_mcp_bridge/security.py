"""Folder allowlist for every path the plugin writes or loads. Standard library only."""

from __future__ import annotations

import json
import os
from pathlib import Path

from .transport import BridgeError, bridge_home


def default_allowed_dir() -> Path:
    return Path.home() / "Documents" / "SubstanceDesignerMCP"


def allowed_dirs() -> list[str]:
    env_value = os.environ.get("SD_MCP_ALLOWED_DIRS")
    if env_value:
        configured = [item for item in env_value.split(os.pathsep) if item.strip()]
    else:
        configured = []
        config_file = bridge_home() / "config.json"
        if config_file.is_file():
            configured = json.loads(config_file.read_text("utf-8")).get("allowed_dirs") or []
    return [os.path.realpath(item) for item in configured] or [os.path.realpath(default_allowed_dir())]


def is_inside(path: str, root: str) -> bool:
    path_norm, root_norm = os.path.normcase(path), os.path.normcase(root)
    try:
        return os.path.commonpath([path_norm, root_norm]) == root_norm
    except ValueError:  # different drives
        return False


def check_path(path: object, suffix: str, must_exist: bool = False) -> str:
    if not isinstance(path, str) or not os.path.isabs(path):
        raise BridgeError("invalid_path", f"Se necesita una ruta absoluta: {path!r}")
    resolved = os.path.realpath(path)
    roots = allowed_dirs()
    if not any(is_inside(resolved, root) for root in roots):
        raise BridgeError(
            "path_not_allowed",
            f"La ruta {resolved} esta fuera de las carpetas permitidas: {roots}. "
            "Agrega la carpeta a allowed_dirs en config.json y reinicia Designer.",
        )
    if not resolved.lower().endswith(suffix):
        raise BridgeError("invalid_path", f"La ruta debe terminar en {suffix}: {resolved}")
    if must_exist and not os.path.isfile(resolved):
        raise BridgeError("not_found", f"No existe el archivo: {resolved}")
    return resolved
