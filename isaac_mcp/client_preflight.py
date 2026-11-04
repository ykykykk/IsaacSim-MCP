"""Action-aware preflight for the repository's controlled stdio MCP client.

This is deliberately a client-side guard for the local verification runner. It
does not represent or relax an external Client/Gateway policy. Callers must
obtain the schema from the current MCP ``tools/list`` response and preserve it
with their trace.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from jsonschema import Draft202012Validator, ValidationError

MAX_INLINE_BYTES = 4 * 1024 * 1024
CAMERA_OUTPUT_TYPES = frozenset(
    {
        "rgb",
        "depth",
        "distance_to_image_plane",
        "semantic_segmentation",
        "instance_segmentation",
        "instance_id_segmentation",
        "normals",
        "motion_vectors",
    }
)

@dataclass(frozen=True)
class ClientPreflightRejected(ValueError):
    code: str
    message: str

    def __str__(self) -> str:
        return self.message


def _required_text(arguments: Mapping[str, Any], name: str) -> None:
    value = arguments.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ClientPreflightRejected("CLIENT_REQUIRED_FIELD", f"{name} must be a non-empty string for this action")


def _schema_validate(arguments: Mapping[str, Any], input_schema: Mapping[str, Any]) -> None:
    """Validate the actual ``tools/list`` schema before action-specific rules."""
    try:
        Draft202012Validator(input_schema).validate(dict(arguments))
    except ValidationError as exc:
        location = ".".join(str(part) for part in exc.absolute_path) or "arguments"
        raise ClientPreflightRejected("CLIENT_SCHEMA_VALIDATION", f"{location}: {exc.message}") from exc


def validate_tool_call(tool_name: str, arguments: Mapping[str, Any], input_schema: Mapping[str, Any]) -> None:
    """Reject malformed action branches before the controlled client dispatches.

    ``input_schema`` is supplied by the current MCP ``tools/list`` response.
    The action rules supplement JSON Schema where conditional requirements are
    not expressible in the registered top-level schema.
    """
    if not isinstance(arguments, Mapping):
        raise ClientPreflightRejected("CLIENT_ARGUMENTS_MAPPING_REQUIRED", "tool arguments must be an object")
    properties = input_schema.get("properties")
    if not isinstance(properties, Mapping):
        raise ClientPreflightRejected("CLIENT_SCHEMA_INVALID", "tools/list input schema has no properties mapping")
    unknown = sorted(set(arguments) - set(properties))
    if unknown:
        raise ClientPreflightRejected("CLIENT_UNKNOWN_FIELD", f"tool schema does not define: {', '.join(unknown)}")
    _schema_validate(arguments, input_schema)

    if tool_name == "query_prim" and arguments.get("action") == "get":
        _required_text(arguments, "prim_path")
    elif tool_name == "physics_body_config":
        _required_text(arguments, "prim_path")
        if arguments.get("action") == "configure":
            configurable = ("body_type", "collider_enabled", "approximation", "mass_kg", "density_kg_m3")
            if not any(name in arguments and arguments[name] is not None for name in configurable):
                raise ClientPreflightRejected(
                    "CLIENT_ACTION_FIELDS_REQUIRED",
                    "physics_body_config(action=configure) requires at least one configuration field",
                )
    elif tool_name == "capture_camera_output":
        if "prim_path" in arguments:
            _required_text(arguments, "prim_path")
        output_type = arguments.get("output_type", "depth")
        if output_type not in CAMERA_OUTPUT_TYPES:
            raise ClientPreflightRejected(
                "CLIENT_INVALID_CAMERA_OUTPUT_TYPE",
                f"output_type must be one of {sorted(CAMERA_OUTPUT_TYPES)}",
            )
        return_mode = arguments.get("return_mode", "artifact")
        if return_mode == "image" and output_type != "rgb":
            raise ClientPreflightRejected(
                "CLIENT_INVALID_COMBINATION", "return_mode='image' requires output_type='rgb'"
            )
        if arguments.get("output_path") is not None and arguments.get("return_mode", "artifact") != "artifact":
            raise ClientPreflightRejected(
                "CLIENT_INVALID_COMBINATION", "output_path requires return_mode='artifact'"
            )
        if return_mode == "inline":
            inline_max_bytes = arguments.get("inline_max_bytes", 1024 * 1024)
            if isinstance(inline_max_bytes, bool) or not isinstance(inline_max_bytes, int) or not 1 <= inline_max_bytes <= MAX_INLINE_BYTES:
                raise ClientPreflightRejected(
                    "CLIENT_INVALID_INLINE_LIMIT",
                    f"inline_max_bytes must be an integer from 1 to {MAX_INLINE_BYTES}",
                )
