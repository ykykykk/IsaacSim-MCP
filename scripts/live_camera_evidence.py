"""Capture a native MCP ImageContent for an already guarded live verifier."""

import asyncio
import base64
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def _invoke(name, arguments, profile):
    env = dict(os.environ, ISAAC_MCP_TOOL_PROFILE=profile)
    server = StdioServerParameters(command=sys.executable, args=['-m', 'isaac_mcp.server'], env=env)
    async with stdio_client(server) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        result = await session.call_tool(name, arguments)
        value = json.loads(next(x.text for x in result.content if x.type == 'text'))
        assert value['status'] == 'success', value
        return value, result


def capture(prim_path, destination):
    _, result = asyncio.run(_invoke('capture_camera_output', {
        'prim_path': prim_path, 'output_type': 'rgb', 'return_mode': 'image'}, 'legacy'))
    destination.write_bytes(base64.b64decode(next(x.data for x in result.content if x.type == 'image')))


def call_tool(name, arguments):
    value, _ = asyncio.run(_invoke(name, arguments, 'full'))
    return value
