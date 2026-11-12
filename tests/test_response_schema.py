"""Common response schema tests for extension, connection, and all named tools."""

from __future__ import annotations

import asyncio
import base64
import inspect
import json

from mcp.types import CallToolResult, ImageContent, TextContent

from isaac_mcp.command_context import command_id_var
from isaac_mcp.responses import NativeImageResponse, normalize_response
from isaac_mcp.tool_inventory import tool_count
from isaac_mcp.tools import _serialize_tool_response, _wrap_tool, register_all_tools

REQUIRED_FIELDS = {
    "schema_version",
    "status",
    "code",
    "message",
    "data",
    "warnings",
    "command_id",
    "timing",
    "artifacts",
    "readback",
}


def test_normalize_response_is_idempotent_and_classifies_legacy_results():
    partial = normalize_response(
        {
            "status": "error",
            "message": "Some settings are not supported",
            "applied": ["gravity"],
            "unsupported": ["time_step"],
        },
        command_id="command-1",
    )
    assert partial["status"] == "partial"
    assert partial["code"] == "PARTIAL_SUCCESS"
    assert partial["command_id"] == "command-1"
    assert normalize_response(partial) == partial

    unsupported = normalize_response({"status": "error", "message": "Not supported by adapter"})
    timeout = normalize_response({"status": "error", "message": "Timeout waiting for Isaac response"})
    cancelled = normalize_response({"status": "error", "message": "Request was cancelled"})
    assert unsupported["status"] == "unsupported"
    assert timeout["status"] == "timeout"
    assert cancelled["status"] == "cancelled"


class _FakeMCP:
    def __init__(self):
        self.tools = {}

    def tool(self, name, **kwargs):
        def decorator(function):
            self.tools[name] = function
            return function

        return decorator


class _Connection:
    port = 8766

    def send_command(self, command, params=None):
        return normalize_response(
            {"status": "success", "command": command, "params": params or {}},
            command_id=f"id-{command}",
        )


def test_all_source_named_tools_are_registered_through_schema_wrapper():
    mcp = _FakeMCP()
    register_all_tools(mcp, lambda: _Connection())

    assert len(mcp.tools) == tool_count()
    for name, function in mcp.tools.items():
        signature = inspect.signature(function)
        assert signature, name
        assert "command_id" in signature.parameters, name
        assert "idempotency_key" in signature.parameters, name
        assert getattr(function, "__wrapped__", None) is not None, name
        # Calling without arguments either runs a no-argument tool or triggers
        # the wrapper's validation error path. Both must still be schema 1.0.
        response = json.loads(function())
        assert set(response) == REQUIRED_FIELDS, name
        assert response["status"] in {
            "success",
            "error",
            "partial",
            "unsupported",
            "timeout",
            "cancelled",
        }, name

    correlated = json.loads(mcp.tools["get_scene_info"](command_id="caller-id", idempotency_key="read-scene-1"))
    assert correlated["status"] == "success"


def test_schema_wrapper_returns_all_fields_for_success_and_legacy_error():
    mcp = _FakeMCP()
    register_all_tools(mcp, lambda: _Connection())

    success = json.loads(mcp.tools["get_scene_info"]())
    assert set(success) == REQUIRED_FIELDS
    assert success["status"] == "success"
    assert success["command_id"] == "id-scene.get_info"
    assert success["timing"]["mcp_tool_ms"] >= 0

    class _FailingConnection:
        def send_command(self, _command, _params=None):
            raise TimeoutError("timed out")

    failing_mcp = _FakeMCP()
    register_all_tools(failing_mcp, lambda: _FailingConnection())
    timeout = json.loads(failing_mcp.tools["get_scene_info"]())
    assert set(timeout) == REQUIRED_FIELDS
    assert timeout["status"] == "timeout"
    assert timeout["code"] == "TIMEOUT"


def test_schema_wrapper_preserves_caller_command_id_for_local_runtime_status():
    mcp = _FakeMCP()
    register_all_tools(mcp, lambda: _Connection())

    response = json.loads(mcp.tools["get_runtime_status"](command_id="caller-runtime-status"))

    assert response["command_id"] == "caller-runtime-status"


def test_schema_wrapper_preserves_caller_command_id_across_outcomes_and_context():
    def success():
        return {"status": "success", "data": {"ok": True}}

    def timeout():
        raise TimeoutError("deadline")

    def error():
        raise ValueError("bad input")

    async def cancelled():
        raise asyncio.CancelledError()

    cases = [
        (_wrap_tool(success), "success"),
        (_wrap_tool(timeout), "timeout"),
        (_wrap_tool(error), "error"),
    ]
    for tool, expected_status in cases:
        response = json.loads(tool(command_id=f"caller-{expected_status}"))
        assert response["status"] == expected_status
        assert response["command_id"] == f"caller-{expected_status}"
        assert command_id_var.get() is None

    cancelled_response = json.loads(asyncio.run(_wrap_tool(cancelled)(command_id="caller-cancelled")))
    assert cancelled_response["status"] == "cancelled"
    assert cancelled_response["command_id"] == "caller-cancelled"
    assert command_id_var.get() is None


def test_schema_wrapper_does_not_overwrite_downstream_command_id_mismatch():
    def downstream():
        return {"status": "success", "command_id": "downstream-id"}

    response = json.loads(_wrap_tool(downstream)(command_id="caller-id"))

    assert response["command_id"] == "downstream-id"
    assert any("COMMAND_ID_MISMATCH" in warning for warning in response["warnings"])


def test_schema_wrapper_preserves_envelope_when_returning_native_image_content():
    encoded = base64.b64encode(b"png").decode("ascii")
    result = _serialize_tool_response(
        NativeImageResponse(
            response={"status": "success", "return_mode": "image"},
            data_base64=encoded,
            mime_type="image/png",
        ),
        elapsed_ms=1.25,
    )

    assert isinstance(result, CallToolResult)
    assert isinstance(result.content[0], TextContent)
    assert isinstance(result.content[1], ImageContent)
    envelope = json.loads(result.content[0].text)
    assert set(envelope) == REQUIRED_FIELDS
    assert envelope["data"]["return_mode"] == "image"
    assert envelope["timing"]["mcp_tool_ms"] == 1.25
    assert result.structuredContent == {"result": result.content[0].text}
