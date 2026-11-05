"""Values as a real model sends them: numbers often arrive as text."""

import anyio
import pytest

from sd_mcp_bridge.coercion import coerce_scalar
from substance_designer_mcp import sat, server


@pytest.mark.parametrize(
    "type_id, raw, expected",
    [
        ("float", "5", 5.0),
        ("float", "5.0", 5.0),
        ("float", " -0.25 ", -0.25),
        ("float", "1e2", 100.0),
        ("float", 5, 5.0),
        ("double", ".5", 0.5),
        ("int", "3", 3),
        ("int", "3.0", 3),
        ("int", 3.0, 3),
        ("bool", "true", True),
        ("bool", "False", False),
        ("bool", True, True),
        ("string", "5", "5"),
    ],
)
def test_valid_values_are_converted(type_id, raw, expected):
    result = coerce_scalar(type_id, raw)
    assert result == expected and type(result) is type(expected)


@pytest.mark.parametrize(
    "type_id, raw",
    [
        ("float", "doce"),
        ("float", "nan"),
        ("float", "inf"),
        ("float", "1_000"),
        ("float", ""),
        ("float", True),
        ("float", [5.0]),
        ("float", float("nan")),
        ("float", None),
        ("int", "3.5"),
        ("int", 3.5),
        ("int", True),
        ("bool", 1),
        ("bool", "si"),
        ("string", 5),
    ],
)
def test_invalid_values_are_rejected(type_id, raw):
    with pytest.raises(ValueError):
        coerce_scalar(type_id, raw)


def test_render_values_accept_numbers_as_text():
    args = sat.build_render_args(
        "sbsrender", "a.sbsar", "out", parameters={"a": "0.5", "b": ["1", 0, "0.5"], "c": "true"}
    )
    values = [args[i + 1] for i, item in enumerate(args) if item == "--set-value"]
    assert values == ["a@0.5", "b@1,0,0.5", "c@1"]


@pytest.mark.parametrize("value", ["texto", "nan", ["1", "x"], [True, 1]])
def test_render_values_still_reject_non_numbers(value):
    with pytest.raises(ValueError):
        sat.build_render_args("sbsrender", "a.sbsar", "out", parameters={"a": value})


def test_every_tool_argument_declares_a_type():
    # An untyped argument (Any) makes models send numbers as text; this caught it in real use.
    tools = anyio.run(server.mcp.list_tools)
    untyped = [
        f"{tool.name}.{name}"
        for tool in tools
        for name, schema in tool.inputSchema.get("properties", {}).items()
        if not ({"type", "anyOf", "oneOf", "$ref"} & set(schema))
    ]
    assert untyped == []


def test_value_schema_offers_numbers_booleans_and_lists():
    tools = {tool.name: tool for tool in anyio.run(server.mcp.list_tools)}
    options = tools["set_node_parameter"].inputSchema["properties"]["value"]["anyOf"]
    assert {"number", "integer", "boolean", "string", "array"} <= {option["type"] for option in options}
