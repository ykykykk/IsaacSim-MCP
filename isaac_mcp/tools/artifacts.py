"""Managed artifact MCP tools."""

import json
from typing import TYPE_CHECKING, Callable

from mcp.server.fastmcp import FastMCP

if TYPE_CHECKING:
    from isaac_mcp.connection import IsaacConnection


def register_tools(mcp: FastMCP, get_connection: "Callable[[], IsaacConnection]") -> None:
    @mcp.tool("get_artifact_info")
    def get_artifact_info(handle: str) -> str:
        """Get size, type, hash, expiry, and producer metadata for a managed artifact.

        Looking up an expired handle deletes its managed data and sidecar.

        Args:
            handle: Opaque managed artifact handle.
        """
        return json.dumps(get_connection().send_command("artifacts.info", {"handle": handle}), indent=2)

    @mcp.tool("read_artifact")
    def read_artifact(handle: str, offset: int = 0, length: int = 256 * 1024) -> str:
        """Read one bounded base64 chunk from a managed artifact.

        Use next_offset until eof is true; verify the chunk or complete SHA-256.
        Looking up an expired handle deletes its managed data and sidecar.

        Args:
            handle: Opaque managed artifact handle.
            offset: Non-negative starting byte offset, default 0.
            length: Positive requested byte count, default 262144; server chunk limits apply.
        """
        params = {"handle": handle, "offset": offset, "length": length}
        return json.dumps(get_connection().send_command("artifacts.read", params), indent=2)

    @mcp.tool("delete_artifact")
    def delete_artifact(handle: str) -> str:
        """Delete one managed artifact after validating its opaque handle.

        Args:
            handle: Opaque managed artifact handle to delete.
        """
        return json.dumps(get_connection().send_command("artifacts.delete", {"handle": handle}), indent=2)

    @mcp.tool("cleanup_artifacts")
    def cleanup_artifacts() -> str:
        """Delete expired managed artifacts and report reclaimed capacity."""
        return json.dumps(get_connection().send_command("artifacts.cleanup", {}), indent=2)
