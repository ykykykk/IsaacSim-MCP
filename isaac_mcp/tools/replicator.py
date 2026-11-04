# MIT License
# Copyright (c) 2023-2025 omni-mcp
# Copyright (c) 2026 whats2000

"""Typed Replicator synthetic-data job tools."""

import json
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

from mcp.server.fastmcp import FastMCP

if TYPE_CHECKING:
    from isaac_mcp.connection import IsaacConnection


def register_tools(mcp: FastMCP, get_connection: "Callable[[], IsaacConnection]") -> None:
    def send(command: str, params: Optional[Dict[str, Any]] = None) -> str:
        try:
            result = get_connection().send_command(command, params or {})
            return json.dumps(result, indent=2)
        except Exception as exc:
            return json.dumps({"status": "error", "message": str(exc)})

    @mcp.tool("get_replicator_status")
    def get_replicator_status() -> str:
        """Read Replicator extension, orchestrator, job, writer, and trigger state."""
        return send("replicator.get_status")

    @mcp.tool("create_sdg_job")
    def create_sdg_job(
        camera_prim_path: str,
        frame_count: int,
        annotations: List[str],
        resolution: List[int] = [640, 480],
        seed: int = 0,
        randomizers: Optional[List[Dict[str, Any]]] = None,
        rt_subframes: int = 1,
        delta_time: float = 0.0,
        preview: bool = True,
    ) -> str:
        """Preview or create a bounded manual-trigger BasicWriter SDG job.

        Randomizers are typed records. ``transform`` accepts ``prim_paths`` and
        optional position/rotation/scale min/max vectors. ``light`` accepts
        ``prim_paths`` and optional intensity/color min/max values.

        Args:
            camera_prim_path: Absolute path of the camera sensor used by the job.
            frame_count: Number of frames requested, from 1 through 1000.
            annotations: Non-empty unique list of rgb, semantic_segmentation, instance_segmentation, or instance_id_segmentation.
            resolution: Image [width, height], each 1 through 4096 and at most 16777216 pixels total.
            seed: Randomization seed from 0 through 4294967295.
            randomizers: Optional list of at most 32 typed transform or light randomizer records.
            rt_subframes: Replicator real-time subframe count from 1 through 64.
            delta_time: Time increment between frames in seconds, from 0 through 1.
            preview: When true, validate and report a plan without applying the change.
        """
        return send(
            "replicator.create_job",
            {
                "camera_prim_path": camera_prim_path,
                "frame_count": frame_count,
                "annotations": annotations,
                "resolution": resolution,
                "seed": seed,
                "randomizers": randomizers or [],
                "rt_subframes": rt_subframes,
                "delta_time": delta_time,
                "preview": preview,
            },
        )

    @mcp.tool("start_sdg_job")
    def start_sdg_job(job_id: str, preview: bool = True) -> str:
        """Preview or asynchronously start one configured SDG job."""
        return send("replicator.start_job", {"job_id": job_id, "preview": preview})

    @mcp.tool("get_sdg_job_status")
    def get_sdg_job_status(job_id: str) -> str:
        """Read bounded SDG job progress, lifecycle state, and cleanup read-back.

        Args:
            job_id: Opaque ID of the job returned by its creation or start operation.
        """
        return send("replicator.get_job_status", {"job_id": job_id})

    @mcp.tool("cancel_sdg_job")
    def cancel_sdg_job(job_id: str, preview: bool = True) -> str:
        """Preview or request cancellation; resources detach at the next safe point.

        Args:
            job_id: Opaque ID of the job returned by its creation or start operation.
            preview: When true, validate and report a plan without applying the change.
        """
        return send("replicator.cancel_job", {"job_id": job_id, "preview": preview})

    @mcp.tool("get_sdg_manifest")
    def get_sdg_manifest(job_id: str) -> str:
        """Return a terminal job manifest and managed artifact handles.

        The manifest can be unavailable; inspect SDG_MANIFEST_NOT_READY and
        the job state rather than assuming every terminal job has a manifest.

        Args:
            job_id: Opaque ID of the job returned by its creation or start operation.
        """
        return send("replicator.get_manifest", {"job_id": job_id})

    @mcp.tool("delete_sdg_job")
    def delete_sdg_job(job_id: str, delete_artifacts: bool = False, preview: bool = True) -> str:
        """Preview or delete one terminal job record and optionally its artifacts.

        Args:
            job_id: Opaque ID of the job returned by its creation or start operation.
            delete_artifacts: Whether to delete artifacts produced by this job.
            preview: When true, validate and report a plan without applying the change.
        """
        return send(
            "replicator.delete_job",
            {"job_id": job_id, "delete_artifacts": delete_artifacts, "preview": preview},
        )
