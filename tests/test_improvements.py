"""Library search and the preview's image content, without Designer."""

import base64
import json
import sys
import threading

import anyio
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from sd_mcp_bridge import transport
from substance_designer_mcp import library

# 1x1 transparent PNG
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


@pytest.fixture
def packages(tmp_path):
    for name in (
        "noise_perlin_noise", "noise_perlin_noise_v2", "perlin_noise_zoom", "3d_perlin_noise",
        "pattern_brick", "brick_generator", "tile_generator", "grunge_map_001", "ambient_occlusion_2",
    ):
        (tmp_path / f"{name}.sbs").write_text("")
    (tmp_path / "notes.txt").write_text("")
    return tmp_path


def test_all_words_must_match_first(packages):
    found = library.search(packages, "Perlin noise")
    assert found["all_words_matched"] is True
    assert set(found["matches"]) == {"noise_perlin_noise", "noise_perlin_noise_v2", "perlin_noise_zoom", "3d_perlin_noise"}
    assert found["library_size"] == 9


def test_partial_matches_when_no_name_has_every_word(packages):
    found = library.search(packages, "brick wall")
    assert found["all_words_matched"] is False
    assert set(found["matches"]) == {"pattern_brick", "brick_generator"}


def test_limit_and_empty_query(packages):
    assert len(library.search(packages, "noise", limit=2)["matches"]) == 2
    with pytest.raises(ValueError):
        library.search(packages, "  ¿? ")


def test_missing_library_folder(tmp_path):
    assert library.packages_dir(tmp_path) is None
    assert library.packages_dir(None) is None


def test_preview_reaches_the_client_as_an_image(tmp_path):
    def dispatch(command, params):
        assert command == "get_node_preview" and params["size"] == 128
        return {"node_id": "1", "output": "output", "texture_size": [1, 1], "preview_size": [1, 1],
                "png_base64": base64.b64encode(PNG).decode()}

    token = transport.new_token()
    server = transport.BridgeTransport(token, dispatch, port=0)
    server.bind()
    previous = transport.os.environ.get("SD_MCP_HOME")
    transport.os.environ["SD_MCP_HOME"] = str(tmp_path)
    transport.write_discovery(server.port, token)
    if previous is None:
        del transport.os.environ["SD_MCP_HOME"]
    else:
        transport.os.environ["SD_MCP_HOME"] = previous
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    async def run():
        params = StdioServerParameters(
            command=sys.executable, args=["-m", "substance_designer_mcp.server"],
            env={"SD_MCP_HOME": str(tmp_path), "SYSTEMROOT": "C:\\Windows", "PATH": ""},
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await session.call_tool("get_node_preview", {"node_id": "1", "size": 128})

    try:
        result = anyio.run(run)
    finally:
        server.stop()
        thread.join(timeout=3)
    assert result.isError is False
    kinds = [block.type for block in result.content]
    assert "image" in kinds
    image = next(block for block in result.content if block.type == "image")
    assert image.mimeType == "image/png" and base64.b64decode(image.data) == PNG
    text = next(block for block in result.content if block.type == "text")
    assert json.loads(text.text)["texture_size"] == [1, 1]
