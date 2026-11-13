"""Guards for running the plugin on older and newer Designer versions."""

import ast
import json
from pathlib import Path

import pytest

from sd_mcp_bridge import transport

PLUGIN = Path(__file__).resolve().parent.parent / "designer_plugin" / "sd_mcp_bridge" / "sd_mcp_bridge"
SOURCES = sorted(PLUGIN.glob("*.py"))


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
def test_plugin_parses_as_python_3_9(path):
    # Designer 13.1 (2023-2024) ships Python 3.9; 14.x ships 3.11 and 16.x ships 3.13.
    ast.parse(path.read_text("utf-8"), filename=str(path), feature_version=(3, 9))


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
def test_qt_is_only_imported_through_the_compat_module(path):
    # PySide6 (Designer 14+) and PySide2 (13.1 and earlier) differ; qt_compat hides that.
    if path.name == "qt_compat.py":
        return
    tree = ast.parse(path.read_text("utf-8"))
    modules = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module]
    modules += [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
    assert not [m for m in modules if m.split(".")[0] in {"PySide2", "PySide6", "shiboken2", "shiboken6"}]


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
def test_no_union_types_evaluated_at_runtime(path):
    # `X | Y` outside annotations fails on Python 3.9; annotations are safe thanks to
    # `from __future__ import annotations`, which every module must keep.
    source = path.read_text("utf-8")
    tree = ast.parse(source)
    annotations = set()
    for node in ast.walk(tree):
        for child in getattr(node, "annotation", None), getattr(node, "returns", None):
            if child is not None:
                annotations.update(id(n) for n in ast.walk(child))
    runtime_unions = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.BinOp) and isinstance(n.op, ast.BitOr) and id(n) not in annotations
        and any(isinstance(side, ast.Name) and side.id in {"str", "int", "float", "bool", "None", "dict", "list"}
                for side in (n.left, n.right))
    ]
    assert runtime_unions == []
    if any(isinstance(n, (ast.AnnAssign, ast.arg)) and getattr(n, "annotation", None) for n in ast.walk(tree)):
        assert "from __future__ import annotations" in source


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("SD_MCP_HOME", str(tmp_path))
    return tmp_path


def test_autostart_defaults_to_on(home):
    assert transport.autostart_enabled() is True


def test_autostart_can_be_turned_off_and_keeps_other_settings(home):
    (home / "config.json").write_text(json.dumps({"allowed_dirs": ["C:/x"], "bridge_port": 9900}))
    transport.write_config_value("autostart", False)
    assert transport.autostart_enabled() is False
    data = json.loads((home / "config.json").read_text())
    assert data == {"allowed_dirs": ["C:/x"], "bridge_port": 9900, "autostart": False}
    assert transport.configured_port() == 9900
    transport.write_config_value("autostart", True)
    assert transport.autostart_enabled() is True


def test_write_creates_the_config_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("SD_MCP_HOME", str(tmp_path / "nuevo"))
    transport.write_config_value("autostart", False)
    assert transport.autostart_enabled() is False


def test_invalid_config_is_reported(home):
    (home / "config.json").write_text("[1, 2]")
    with pytest.raises(ValueError, match="objeto JSON"):
        transport.read_config()
