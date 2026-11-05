"""Path allowlist, command building and layout: everything that does not need Designer."""

import json
import os

import pytest

from sd_mcp_bridge import security
from sd_mcp_bridge.layout import compute_layout
from sd_mcp_bridge.transport import BridgeError
from substance_designer_mcp import paths, sat


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    root = tmp_path / "permitida"
    root.mkdir()
    monkeypatch.setenv("SD_MCP_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SD_MCP_ALLOWED_DIRS", str(root))
    return root


# ---------------------------------------------------------------- allowlist


def test_input_inside_allowed_dir_is_accepted(workspace):
    source = workspace / "a.sbs"
    source.write_text("")
    assert paths.check_input_file(str(source), ".sbs") == os.path.realpath(source)


def test_path_outside_allowed_dir_is_rejected(workspace, tmp_path):
    outside = tmp_path / "fuera.sbs"
    outside.write_text("")
    with pytest.raises(paths.PathNotAllowed, match="fuera de las carpetas"):
        paths.check_input_file(str(outside), ".sbs")


def test_parent_traversal_is_rejected(workspace, tmp_path):
    (tmp_path / "secreto.sbs").write_text("")
    with pytest.raises(paths.PathNotAllowed, match="fuera de las carpetas"):
        paths.check_input_file(str(workspace / ".." / "secreto.sbs"), ".sbs")


def test_sibling_folder_with_same_prefix_is_rejected(workspace, tmp_path):
    sibling = tmp_path / "permitida_no"
    with pytest.raises(paths.PathNotAllowed, match="fuera de las carpetas"):
        paths.check_output_dir(str(sibling))
    assert not sibling.exists()


def test_symlink_escaping_allowed_dir_is_rejected(workspace, tmp_path):
    target = tmp_path / "real"
    target.mkdir()
    (target / "a.sbs").write_text("")
    link = workspace / "enlace"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("Crear symlinks requiere permisos en esta maquina")
    with pytest.raises(paths.PathNotAllowed, match="fuera de las carpetas"):
        paths.check_input_file(str(link / "a.sbs"), ".sbs")


def test_relative_path_is_rejected(workspace):
    with pytest.raises(paths.PathNotAllowed, match="absoluta"):
        paths.check_output_dir("relativa/carpeta")


def test_wrong_suffix_is_rejected(workspace):
    source = workspace / "a.txt"
    source.write_text("")
    with pytest.raises(paths.PathNotAllowed, match="terminar en"):
        paths.check_input_file(str(source), ".sbs")


def test_output_dir_is_created_inside_allowed(workspace):
    target = workspace / "x" / "y"
    assert paths.check_output_dir(str(target)) == os.path.realpath(target)
    assert target.is_dir()


def test_default_allowed_dir_when_nothing_configured(tmp_path, monkeypatch):
    monkeypatch.delenv("SD_MCP_ALLOWED_DIRS", raising=False)
    monkeypatch.setenv("SD_MCP_HOME", str(tmp_path))
    assert paths.allowed_dirs()[0].endswith("SubstanceDesignerMCP")
    assert security.allowed_dirs() == paths.allowed_dirs()


@pytest.mark.parametrize("via_env", [True, False])
def test_plugin_and_server_read_the_same_allowlist(tmp_path, monkeypatch, via_env):
    root = tmp_path / "compartida"
    monkeypatch.setenv("SD_MCP_HOME", str(tmp_path))
    monkeypatch.delenv("SD_MCP_ALLOWED_DIRS", raising=False)
    if via_env:
        monkeypatch.setenv("SD_MCP_ALLOWED_DIRS", str(root))
    else:
        (tmp_path / "config.json").write_text(json.dumps({"allowed_dirs": [str(root)]}))
    assert paths.allowed_dirs() == security.allowed_dirs() == [os.path.realpath(root)]


@pytest.mark.parametrize(
    "path, code",
    [("relativa.sbs", "invalid_path"), (None, "invalid_path"), (123, "invalid_path")],
)
def test_plugin_rejects_invalid_paths(workspace, path, code):
    with pytest.raises(BridgeError) as error:
        security.check_path(path, ".sbs")
    assert error.value.code == code


def test_plugin_rejects_path_outside_allowed_dir(workspace, tmp_path):
    with pytest.raises(BridgeError) as error:
        security.check_path(str(tmp_path / "fuera.sbs"), ".sbs")
    assert error.value.code == "path_not_allowed"


# ---------------------------------------------------------------- command building


def render_args(**options):
    return sat.build_render_args("sbsrender", "a.sbsar", "out", **options)


def test_render_arguments_use_documented_flags():
    args = render_args(graph="g", outputs=["o"], usages=["normal"], bit_depth="16", output_format="tga")
    assert args[:2] == ["sbsrender", "render"]
    for pair in (
        ["--input", "a.sbsar"], ["--output-path", "out"], ["--input-graph", "g"], ["--input-graph-output", "o"],
        ["--input-graph-output-usage", "normal"], ["--output-bit-depth", "16"], ["--output-format", "tga"],
    ):
        assert pair[1] == args[args.index(pair[0]) + 1]


def test_parameter_values_are_formatted():
    args = render_args(parameters={"rough": 0.5, "tint": [1, 0, 0, 1], "flag": True, "$randomseed": 7})
    values = [args[i + 1] for i, item in enumerate(args) if item == "--set-value"]
    assert values == ["rough@0.5", "tint@1,0,0,1", "flag@1", "$randomseed@7"]


def test_width_and_height_become_log2_outputsize():
    args = render_args(width=2048, height=512)
    assert "$outputsize@11,9" in args


@pytest.mark.parametrize(
    "options",
    [
        {"width": 1000, "height": 1024},
        {"width": 1024},
        {"width": 1024, "height": 1024, "parameters": {"$outputsize": [10, 10]}},
        {"output_format": "exe"},
        {"bit_depth": "7"},
        {"parameters": {"mal@id": 1}},
        {"parameters": {"--engine": 1}},
        {"parameters": {"a": "texto"}},
        {"parameters": {"a": float("nan")}},
        {"parameters": {"a": []}},
    ],
)
def test_invalid_render_options_are_rejected(options):
    with pytest.raises(ValueError):
        render_args(**options)


def test_exposed_inputs_are_parsed_from_real_info_output():
    output = (
        "GRAPH-URL pkg://Template_Material\n"
        "  INPUT $outputsize INTEGER2\n"
        "  INPUT base_tint FLOAT4\n"
        "  OUTPUT baseColor baseColor\n"
    )
    assert sat.parse_exposed_inputs(output) == {"$outputsize", "base_tint"}


def test_unknown_parameter_is_rejected_instead_of_silently_ignored(monkeypatch):
    monkeypatch.setattr(sat, "_run", lambda _args: type("R", (), {"stdout": "  INPUT rough FLOAT1\n"})())
    with pytest.raises(ValueError, match="no expone"):
        sat._check_requested_parameters("sbsrender", "a.sbsar", {"rought"})
    sat._check_requested_parameters("sbsrender", "a.sbsar", {"rough"})


def test_only_problems_are_kept_from_tool_logs():
    log = "[info] 2 SREAdapter(s) found\n[info] Vendor: NVIDIA\n[WARNING] algo\n[ERROR][SBSRender] fallo\n"
    assert sat.problems_only(log) == "[WARNING] algo\n[ERROR][SBSRender] fallo"
    assert sat.problems_only("[info] todo bien\n") is None


def test_missing_tool_explains_how_to_configure(tmp_path, monkeypatch):
    monkeypatch.setattr(sat, "detect_installation", lambda: type("I", (), {"sbsrender": None})())
    with pytest.raises(sat.ToolFailed, match="SD_MCP_SAT_DIR"):
        sat._executable("sbsrender")


def test_batch_continues_after_a_failure(workspace, monkeypatch):
    def fake_render(sbsar, output, **_options):
        if "malo" in sbsar:
            raise sat.ToolFailed("roto")
        return {"files": [output]}

    monkeypatch.setattr(sat, "render_outputs", fake_render)
    result = sat.batch_render(
        ["malo.sbsar", "bueno.sbsar"], str(workspace),
        [{"name": "a", "parameters": {}}, {"name": "b", "parameters": {}}],
    )
    assert (result["succeeded"], result["failed"]) == (2, 2)
    assert result["jobs"][0]["error"] == "roto"


@pytest.mark.parametrize("sets", [[{"name": "../fuera"}], [{"parameters": {}}], [{"name": "a"}, {"name": "a"}]])
def test_batch_rejects_unsafe_or_duplicate_set_names(workspace, sets):
    with pytest.raises(ValueError):
        sat.batch_render(["a.sbsar"], str(workspace), sets)


# ---------------------------------------------------------------- layout


def test_layout_places_nodes_after_their_sources():
    positions = compute_layout(["c", "a", "b"], [("a", "b"), ("b", "c")], 100, 50)
    assert positions["a"][0] < positions["b"][0] < positions["c"][0]


def test_layout_uses_longest_path():
    positions = compute_layout(["a", "b", "c"], [("a", "b"), ("b", "c"), ("a", "c")], 100, 50)
    assert positions["c"][0] == 200


def test_layout_does_not_overlap_nodes():
    nodes = [str(i) for i in range(6)]
    positions = compute_layout(nodes, [], 100, 50)
    assert len(set(positions.values())) == 6


def test_layout_survives_cycles_and_unknown_nodes():
    positions = compute_layout(["a", "b"], [("a", "b"), ("b", "a"), ("x", "a"), ("a", "a")], 100, 50)
    assert set(positions) == {"a", "b"}


def test_layout_handles_empty_graph():
    assert compute_layout([], [], 100, 50) == {}
