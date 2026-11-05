"""Minimal MCP client for the examples: starts the real server over stdio and calls its tools."""

from __future__ import annotations

import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class ToolCallFailed(RuntimeError):
    pass


class Tools:
    def __init__(self, session: ClientSession):
        self._session = session

    async def call(self, tool: str, /, **arguments):
        result = await self._session.call_tool(tool, arguments)
        text = result.content[0].text if result.content else ""
        if result.isError:
            raise ToolCallFailed(f"{tool}: {text}")
        return json.loads(text) if text else None

    async def rejected(self, tool: str, /, **arguments) -> str:
        """Calls a tool that is expected to refuse and returns its error message."""
        result = await self._session.call_tool(tool, arguments)
        if not result.isError:
            raise ToolCallFailed(f"{tool} debia rechazar {arguments}, pero acepto: {result.content[0].text}")
        return result.content[0].text


class connect:
    async def __aenter__(self) -> Tools:
        parameters = StdioServerParameters(
            command=sys.executable, args=["-m", "substance_designer_mcp.server"], env=dict(os.environ)
        )
        self._stdio = stdio_client(parameters, errlog=open(os.devnull, "w"))
        read, write = await self._stdio.__aenter__()
        self._session = ClientSession(read, write)
        await self._session.__aenter__()
        await self._session.initialize()
        return Tools(self._session)

    async def __aexit__(self, *exc_info):
        await self._session.__aexit__(*exc_info)
        await self._stdio.__aexit__(*exc_info)
