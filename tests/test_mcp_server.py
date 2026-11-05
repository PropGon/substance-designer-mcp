"""End-to-end over real stdio: MCP client -> server process -> TCP bridge."""

import json
import sys
import threading

import anyio
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from sd_mcp_bridge import transport


def call_tool(home, name):
    async def run():
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "substance_designer_mcp.server"],
            env={"SD_MCP_HOME": str(home), "SYSTEMROOT": "C:\\Windows", "PATH": ""},
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                return [t.name for t in tools.tools], await session.call_tool(name, {})

    return anyio.run(run)


@pytest.fixture
def fake_plugin(tmp_path):
    token = transport.new_token()
    server = transport.BridgeTransport(token, lambda command, params: {"command": command}, port=0)
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
    yield tmp_path
    server.stop()
    thread.join(timeout=3)


def test_get_app_info_travels_the_whole_chain(fake_plugin):
    names, result = call_tool(fake_plugin, "get_app_info")
    assert "get_app_info" in names
    assert result.isError is False
    assert json.loads(result.content[0].text)["command"] == "get_app_info"


def test_missing_plugin_returns_actionable_tool_error(tmp_path):
    _, result = call_tool(tmp_path, "get_app_info")
    assert result.isError is True
    assert "Designer" in result.content[0].text
