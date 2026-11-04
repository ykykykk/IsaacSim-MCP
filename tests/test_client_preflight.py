"""Regression tests for controlled-client action-aware preflight."""

import pytest

from isaac_mcp.client_preflight import ClientPreflightRejected, validate_tool_call

QUERY_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["list", "get"]},
        "prim_path": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "root_path": {"type": "string"},
    },
    "required": ["action"],
}
BODY_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["get", "configure"]},
        "prim_path": {"type": "string"},
        "body_type": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "collider_enabled": {"anyOf": [{"type": "boolean"}, {"type": "null"}]},
        "approximation": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "mass_kg": {"anyOf": [{"type": "number"}, {"type": "null"}]},
        "density_kg_m3": {"anyOf": [{"type": "number"}, {"type": "null"}]},
    },
    "required": ["action", "prim_path"],
}
CAPTURE_SCHEMA = {
    "type": "object",
    "properties": {
        "prim_path": {"type": "string", "default": "/World/Camera"},
        "output_path": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "return_mode": {"type": "string", "enum": ["metadata", "artifact", "inline", "image"], "default": "artifact"},
        "output_type": {"type": "string", "default": "depth"},
        "inline_max_bytes": {"type": "integer", "default": 1048576},
    },
    "required": [],
}
LOGS_SCHEMA = {
    "type": "object",
    "properties": {"count": {"type": "integer"}, "command_id": {"anyOf": [{"type": "string"}, {"type": "null"}]}},
    "required": [],
}


@pytest.mark.parametrize(
    ("tool", "arguments", "schema", "code"),
    [
        ("query_prim", {"action": "get"}, QUERY_SCHEMA, "CLIENT_REQUIRED_FIELD"),
        ("query_prim", {"action": "get", "prim_path": ""}, QUERY_SCHEMA, "CLIENT_REQUIRED_FIELD"),
        ("query_prim", {"action": "list", "max_bytes": 1}, QUERY_SCHEMA, "CLIENT_UNKNOWN_FIELD"),
        ("physics_body_config", {"action": "configure", "prim_path": "/World/Cube"}, BODY_SCHEMA, "CLIENT_ACTION_FIELDS_REQUIRED"),
        ("capture_camera_output", {"prim_path": "/World/Camera", "output_path": "x.png", "return_mode": "inline"}, CAPTURE_SCHEMA, "CLIENT_INVALID_COMBINATION"),
    ],
)
def test_rejects_before_controlled_client_dispatch(tool, arguments, schema, code) -> None:
    with pytest.raises(ClientPreflightRejected) as exc:
        validate_tool_call(tool, arguments, schema)
    assert exc.value.code == code


def test_legal_action_is_admitted_for_controlled_client_dispatch() -> None:
    validate_tool_call("query_prim", {"action": "get", "prim_path": "/World/Cube"}, QUERY_SCHEMA)
    validate_tool_call("physics_body_config", {"action": "configure", "prim_path": "/World/Cube", "mass_kg": 1.0}, BODY_SCHEMA)


def test_explicit_false_and_zero_are_configuration_values() -> None:
    validate_tool_call("physics_body_config", {"action": "configure", "prim_path": "/World/Cube", "collider_enabled": False}, BODY_SCHEMA)
    validate_tool_call("physics_body_config", {"action": "configure", "prim_path": "/World/Cube", "mass_kg": 0.0}, BODY_SCHEMA)


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("query_prim", {"action": "delete"}),
        ("query_prim", {"action": "list", "root_path": 123}),
        ("physics_body_config", {"action": "configure", "prim_path": "/World/Cube", "mass_kg": "heavy"}),
        ("physics_body_config", {"action": "configure", "prim_path": "/World/Cube", "collider_enabled": 0}),
        ("capture_camera_output", {"prim_path": "/World/Camera", "return_mode": "bytes"}),
        ("capture_camera_output", {"prim_path": "/World/Camera", "inline_max_bytes": "1048576"}),
        ("capture_camera_output", {"prim_path": "/World/Camera", "return_mode": "inline", "inline_max_bytes": 4194305}),
        ("capture_camera_output", {"prim_path": "/World/Camera", "output_type": "optical_flow"}),
    ],
)
def test_actual_schema_and_camera_domain_violations_reject_before_dispatch(tool, arguments) -> None:
    schema = QUERY_SCHEMA if tool == "query_prim" else BODY_SCHEMA if tool == "physics_body_config" else CAPTURE_SCHEMA
    with pytest.raises(ClientPreflightRejected):
        validate_tool_call(tool, arguments, schema)


def test_camera_default_path_is_legal_and_rgb_image_is_constrained() -> None:
    validate_tool_call("capture_camera_output", {"output_type": "rgb", "return_mode": "artifact"}, CAPTURE_SCHEMA)
    with pytest.raises(ClientPreflightRejected) as exc:
        validate_tool_call("capture_camera_output", {"output_type": "depth", "return_mode": "image"}, CAPTURE_SCHEMA)
    assert exc.value.code == "CLIENT_INVALID_COMBINATION"


def test_unrelated_tools_list_type_constraint_rejects_before_dispatch() -> None:
    with pytest.raises(ClientPreflightRejected) as exc:
        validate_tool_call("get_isaac_logs", {"count": "10"}, LOGS_SCHEMA)
    assert exc.value.code == "CLIENT_SCHEMA_VALIDATION"
