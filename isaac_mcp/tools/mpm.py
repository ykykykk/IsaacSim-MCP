"""Optional MPM integration; the particle extension owns configuration and solving."""

from typing import Any, Callable, Dict


def register_tools(mcp, get_connection: Callable) -> None:
    @mcp.tool("get_mpm_status")
    def get_mpm_status() -> dict:
        """Read MPM build/timeline/runtime status without rebuilding or downloading particles."""
        return get_connection().send_command("mpm.get_status", {})

    @mcp.tool("get_mpm_config")
    def get_mpm_config(expected_stage: str, prim_path: str) -> dict:
        """Read composed MPM configuration, defaults and its revision hash. No mutation.

        Args:
            expected_stage: Exact root-layer identifier returned by get_mpm_status.
            prim_path: Absolute prim path owning granular_mpm:config.
        """
        return get_connection().send_command("mpm.get_config", {
            "expected_stage": expected_stage, "prim_path": prim_path,
        })

    @mcp.tool("update_mpm_config")
    def update_mpm_config(
        expected_stage: str, prim_path: str, expected_config_sha256: str,
        changes: Dict[str, Any], preview: bool = True,
    ) -> dict:
        """Validate a parameter patch; apply only to the session layer when preview=false.

        Requires a stopped timeline and idle builder. Never saves, plays or rebuilds.
        Existing material keeps its old runtime configuration until an explicit rebuild.

        Args:
            expected_stage: Exact root-layer identifier from get_mpm_status.
            prim_path: Existing configuration owner's absolute prim path.
            expected_config_sha256: Revision returned by get_mpm_config; stale writes are rejected.
            changes: ScenarioConfig fields to change; prim_path and schema are protected.
            preview: True validates and returns proposed changes without authoring.
        """
        return get_connection().send_command("mpm.update_config", {
            "expected_stage": expected_stage, "prim_path": prim_path,
            "expected_config_sha256": expected_config_sha256,
            "changes": changes, "preview": preview,
        })

    @mcp.tool("request_mpm_rebuild")
    def request_mpm_rebuild(
        expected_stage: str, prim_path: str, expected_config_sha256: str,
        preview: bool = True,
    ) -> dict:
        """Preview or queue one MPM rebuild from the current composed configuration.

        A rebuild replaces material state and may take minutes. A queued response is
        NOT completion; poll get_mpm_status. Never resubmit after a timeout without
        reading status. Never plays or saves, and does not author config into source layers.

        Args:
            expected_stage: Exact root-layer identifier from get_mpm_status.
            prim_path: Existing configuration owner's absolute prim path.
            expected_config_sha256: Current revision from get_mpm_config/update_mpm_config.
            preview: True performs validation only; false queues the requested rebuild.
        """
        return get_connection().send_command("mpm.request_rebuild", {
            "expected_stage": expected_stage, "prim_path": prim_path,
            "expected_config_sha256": expected_config_sha256, "preview": preview,
        })

    @mcp.tool("list_mpm_configs")
    def list_mpm_configs(offset: int = 0, limit: int = 50) -> dict:
        """List MPM config prims in loaded active scene content without loading payloads.

        Args:
            offset: Non-negative result offset.
            limit: Page size, 1..100.
        """
        return get_connection().send_command("mpm.list_configs", {"offset": offset, "limit": limit})
