"""Run one P0 controlled-client preflight against an explicitly selected port.

The script is an evidence-oriented stdio MCP client. It must not be described
as an external Client/Gateway implementation. ``--intentional-server-negative``
is for the separately recorded Server negative case only.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from isaac_mcp.client_preflight import ClientPreflightRejected, validate_tool_call


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _wire_value(value: Any) -> Any:
    message = getattr(value, "message", value)
    if hasattr(message, "model_dump"):
        return message.model_dump(by_alias=True, mode="json", exclude_none=True)
    return str(message)


class _TracedReadStream:
    def __init__(self, stream: Any, events: list[dict[str, Any]]) -> None:
        self._stream = stream
        self._events = events

    async def __aenter__(self):
        await self._stream.__aenter__()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self._stream.__aexit__(*args)

    def __aiter__(self):
        return self

    async def __anext__(self):
        value = await self._stream.__anext__()
        self._events.append({"direction": "server_to_client", "utc": _utc_now(), "monotonic_ns": time.perf_counter_ns(), "jsonrpc": _wire_value(value)})
        return value


class _TracedWriteStream:
    def __init__(self, stream: Any, events: list[dict[str, Any]]) -> None:
        self._stream = stream
        self._events = events

    async def __aenter__(self):
        await self._stream.__aenter__()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self._stream.__aexit__(*args)

    async def send(self, value: Any) -> None:
        self._events.append({"direction": "client_to_server", "utc": _utc_now(), "monotonic_ns": time.perf_counter_ns(), "jsonrpc": _wire_value(value)})
        await self._stream.send(value)


def _payload(result: Any) -> Any:
    structured = getattr(result, "structuredContent", None)
    if structured is not None:
        return structured
    return result.model_dump(mode="json") if hasattr(result, "model_dump") else str(result)


async def run(args: argparse.Namespace, trace: dict[str, Any]) -> dict[str, Any]:
    arguments = json.loads(args.arguments)
    if not isinstance(arguments, dict):
        return {"status": "rejected", "code": "CLIENT_ARGUMENTS_MAPPING_REQUIRED", "mcp_dispatch_count": 0}
    if arguments.get("command_id") not in (None, args.command_id):
        return {"status": "rejected", "code": "CLIENT_COMMAND_ID_MISMATCH", "mcp_dispatch_count": 0}
    arguments["command_id"] = args.command_id
    environment = {
        **os.environ,
        "ISAAC_MCP_HOST": args.host,
        "ISAAC_MCP_PORT": str(args.port),
        "ISAAC_MCP_TOOL_PROFILE": args.profile,
        "ISAAC_MCP_RUNTIME_STATE_FILE": str(args.runtime_state_file.resolve()),
        "ISAAC_MCP_RUNTIME_LOG_FILE": str(args.runtime_log_file.resolve()),
    }
    server = StdioServerParameters(command=os.sys.executable, args=["-m", "isaac_mcp.server"], env=environment)
    async with stdio_client(server) as (read, write):
        async with ClientSession(_TracedReadStream(read, trace["events"]), _TracedWriteStream(write, trace["events"])) as session:
            await session.initialize()
            listed = await session.list_tools()
            schemas = {tool.name: tool.inputSchema for tool in listed.tools}
            schema = schemas.get(args.tool)
            if schema is None:
                return {"status": "rejected", "code": "CLIENT_TOOL_NOT_LISTED", "mcp_dispatch_count": 0, "tool_count": len(schemas)}
            if not args.intentional_server_negative:
                try:
                    validate_tool_call(args.tool, arguments, schema)
                except ClientPreflightRejected as exc:
                    return {
                        "status": "rejected",
                        "code": exc.code,
                        "message": exc.message,
                        "mcp_dispatch_count": 0,
                        "schema": schema,
                        "controlled_client": True,
                    }
            raw = await session.call_tool(args.tool, arguments)
            return {
                "status": "forwarded",
                "mcp_dispatch_count": 1,
                "controlled_client": True,
                "intentional_server_negative": bool(args.intentional_server_negative),
                "schema": schema,
                "result": _payload(raw),
            }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--profile", choices=("legacy", "consolidated", "full"), default="consolidated")
    parser.add_argument("--tool", required=True)
    parser.add_argument("--arguments", required=True)
    parser.add_argument("--command-id", required=True)
    parser.add_argument("--runtime-state-file", type=Path, required=True)
    parser.add_argument("--runtime-log-file", type=Path, required=True)
    parser.add_argument("--trace-file", type=Path, required=True)
    parser.add_argument("--intentional-server-negative", action="store_true")
    args = parser.parse_args()
    if not args.trace_file.parent.is_dir():
        print(json.dumps({"status": "rejected", "code": "CLIENT_TRACE_PARENT_MISSING", "mcp_dispatch_count": 0}))
        return 2
    trace = {
        "schema_version": "1.0",
        "started_at_utc": _utc_now(),
        "started_monotonic_ns": time.perf_counter_ns(),
        "endpoint": {"host": args.host, "port": args.port},
        "command_id": args.command_id,
        "runtime_state_file": str(args.runtime_state_file.resolve()),
        "runtime_log_file": str(args.runtime_log_file.resolve()),
        "events": [],
    }
    try:
        result = asyncio.run(run(args, trace))
    except Exception as exc:
        result = {"status": "error", "code": "CLIENT_RUNNER_EXCEPTION", "message": str(exc)[:512], "mcp_dispatch_count": 0}
    trace["finished_at_utc"] = _utc_now()
    trace["finished_monotonic_ns"] = time.perf_counter_ns()
    trace["result"] = result
    args.trace_file.write_text(json.dumps(trace, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] in {"rejected", "forwarded"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
