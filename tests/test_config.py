import json

import pytest

from substance_designer_mcp import config


@pytest.fixture(autouse=True)
def clean_env(tmp_path, monkeypatch):
    for name in ("SD_MCP_DESIGNER_DIR", "SD_MCP_SAT_DIR"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SD_MCP_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(config.shutil, "which", lambda _name: None)
    monkeypatch.setattr(config, "_designer_candidates", lambda _platform: [])


def make_tools(directory, suffix=""):
    directory.mkdir(parents=True, exist_ok=True)
    for name in ("sbsrender", "sbscooker"):
        (directory / f"{name}{suffix}").write_text("")


def test_env_var_selects_designer_on_windows(tmp_path, monkeypatch):
    make_tools(tmp_path / "Designer", ".exe")
    monkeypatch.setenv("SD_MCP_DESIGNER_DIR", str(tmp_path / "Designer"))
    found = config.detect_installation({}, platform="win32")
    assert found.sbsrender == tmp_path / "Designer" / "sbsrender.exe"
    assert found.sbscooker == tmp_path / "Designer" / "sbscooker.exe"


def test_macos_app_bundle_layout(tmp_path):
    app = tmp_path / "Adobe Substance 3D Designer.app"
    make_tools(app / "Contents" / "MacOS")
    found = config.detect_installation({"designer_dir": str(app)}, platform="darwin")
    assert found.sbsrender == app / "Contents" / "MacOS" / "sbsrender"


def test_sat_dir_takes_priority_over_designer_tools(tmp_path):
    make_tools(tmp_path / "Designer", ".exe")
    make_tools(tmp_path / "SAT" / "bin", ".exe")
    found = config.detect_installation(
        {"designer_dir": str(tmp_path / "Designer"), "sat_dir": str(tmp_path / "SAT")}, platform="win32"
    )
    assert found.sbsrender == tmp_path / "SAT" / "bin" / "sbsrender.exe"


def test_env_var_overrides_config_file(tmp_path, monkeypatch):
    make_tools(tmp_path / "desde_env", ".exe")
    monkeypatch.setenv("SD_MCP_DESIGNER_DIR", str(tmp_path / "desde_env"))
    found = config.detect_installation({"designer_dir": str(tmp_path / "desde_archivo")}, platform="win32")
    assert found.designer_dir == tmp_path / "desde_env"


def test_nothing_installed_returns_empty():
    found = config.detect_installation({}, platform="win32")
    assert found == config.Installation(None, None, None)


def test_missing_config_file_is_empty():
    assert config.load_file_config() == {}


def test_invalid_config_json_is_explained():
    config.home_dir().mkdir(parents=True)
    (config.home_dir() / "config.json").write_text("{ roto")
    with pytest.raises(ValueError, match="no es JSON valido"):
        config.load_file_config()


def test_config_file_is_read():
    config.home_dir().mkdir(parents=True)
    (config.home_dir() / "config.json").write_text(json.dumps({"bridge_port": 1234}))
    assert config.load_file_config() == {"bridge_port": 1234}
