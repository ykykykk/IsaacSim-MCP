"""Unified long-running job lifecycle tools."""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, Optional


def register_tools(mcp: Any, get_connection: Callable[[], Any]) -> None:
    def send(command: str, params: Optional[Dict[str, Any]] = None) -> str:
        try:
            return json.dumps(get_connection().send_command(command, params or {}), indent=2)
        except Exception as exc:
            return json.dumps({"status": "error", "message": str(exc)})

    @mcp.tool("start_job")
    def start_job(command_type: str, params: Optional[Dict[str, Any]] = None, deadline_ms: int = 30000) -> str:
        """Start an eligible asset or sensor command as a bounded background job.

        Motion and SDG starts retain their typed tools; their returned IDs can
        still be queried and cancelled through the unified job tools.

        Args:
            command_type: One of assets.import_urdf, assets.load_usd, assets.spawn_nvidia,
                sensors.capture_image, sensors.capture_camera_output, sensors.get_point_cloud.
            params: Object of arguments for the selected extension command.
            deadline_ms: Integer deadline from 1 to 300000 milliseconds; default 30000.

        Use the returned job ID with get_job_status or cancel_job. An unavailable
        handler reports JOB_COMMAND_UNAVAILABLE; choose an available command before retrying.
        """
        return send("job.start", {"command_type": command_type, "params": params or {}, "deadline_ms": deadline_ms})

    @mcp.tool("get_job_status")
    def get_job_status(job_id: str) -> str:
        """Read a managed, motion, or SDG job without executing it again.

        Args:
            job_id: Opaque ID of the job returned by its creation or start operation.
        """
        return send("job.get_status", {"job_id": job_id})

    @mcp.tool("cancel_job")
    def cancel_job(job_id: str) -> str:
        """Request cancellation and inspect the returned lifecycle state.

        An already terminal job may be returned unchanged; cancellation does
        not prove that a running operation was stopped.

        Args:
            job_id: Opaque ID of the job returned by its creation or start operation.
        """
        return send("job.cancel", {"job_id": job_id})

    @mcp.tool("list_jobs")
    def list_jobs(count: int = 50, include_terminal: bool = True) -> str:
        """List the bounded retained managed-job registry.

        Args:
            count: Maximum number of jobs to return.
            include_terminal: Whether to include terminal jobs.
        """
        return send("job.list", {"count": count, "include_terminal": include_terminal})
