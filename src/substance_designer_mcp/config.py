"""Configuration and detection of the Designer installation."""

from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


def home_dir() -> Path:
    override = os.environ.get("SD_MCP_HOME")
    return Path(override) if override else Path.home() / ".substance-designer-mcp"


def discovery_file() -> Path:
    return home_dir() / "bridge.json"


def load_file_config() -> dict:
    # A single location on purpose: the plugin, started by Designer, reads this same file.
    path = home_dir() / "config.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text("utf-8"))
    except ValueError as exc:
        raise ValueError(f"El archivo de configuracion {path} no es JSON valido: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"El archivo de configuracion {path} debe contener un objeto JSON.")
    return data


def _designer_candidates(platform: str) -> list[Path]:
    if platform == "win32":
        roots = {os.environ.get("ProgramW6432"), os.environ.get("ProgramFiles"), r"C:\Program Files"}
        patterns = [str(Path(root) / "Adobe" / "Adobe Substance 3D Designer*") for root in roots if root]
    elif platform == "darwin":
        patterns = ["/Applications/Adobe Substance 3D Designer*.app"]
    else:
        patterns = []
    return sorted({Path(found) for pattern in patterns for found in glob.glob(pattern)}, reverse=True)


def _tool_dir(designer_dir: Path, platform: str) -> Path:
    if platform == "darwin" and designer_dir.suffix == ".app":
        return designer_dir / "Contents" / "MacOS"
    return designer_dir


def _executable(name: str, platform: str) -> str:
    return f"{name}.exe" if platform == "win32" else name


@dataclass(frozen=True)
class Installation:
    designer_dir: Path | None
    sbsrender: Path | None
    sbscooker: Path | None


def detect_installation(file_config: dict | None = None, platform: str = sys.platform) -> Installation:
    """Resolution order: env var, config file, default install locations, then PATH."""
    file_config = load_file_config() if file_config is None else file_config
    designer_value = os.environ.get("SD_MCP_DESIGNER_DIR") or file_config.get("designer_dir")
    sat_value = os.environ.get("SD_MCP_SAT_DIR") or file_config.get("sat_dir")

    candidates = _designer_candidates(platform)
    designer_dir = Path(designer_value) if designer_value else (candidates[0] if candidates else None)

    search_dirs: list[Path] = []
    if sat_value:
        sat_path = Path(sat_value)
        search_dirs += [sat_path, sat_path / "bin"]
    if designer_dir:
        search_dirs.append(_tool_dir(designer_dir, platform))

    def locate(name: str) -> Path | None:
        filename = _executable(name, platform)
        for directory in search_dirs:
            if (directory / filename).is_file():
                return directory / filename
        found = shutil.which(name)
        return Path(found) if found else None

    return Installation(designer_dir, locate("sbsrender"), locate("sbscooker"))


def tool_version(executable: Path) -> str | None:
    try:
        completed = subprocess.run(
            [str(executable), "--version"],
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=15, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return completed.stdout.strip() or None


def designer_process_running(platform: str = sys.platform) -> bool | None:
    """True/False when it can be determined, None when it cannot."""
    try:
        if platform == "win32":
            output = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq Adobe Substance 3D Designer.exe", "/NH"],
                stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=10, check=False,
            ).stdout
            return "Adobe Substance 3D Designer.exe" in output
        completed = subprocess.run(
            ["pgrep", "-f", "Adobe Substance 3D Designer"],
            stdin=subprocess.DEVNULL, capture_output=True, timeout=10, check=False,
        )
        return completed.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return None
