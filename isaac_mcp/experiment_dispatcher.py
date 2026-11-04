"""One-shot, fail-closed dispatcher for future isolated Isaac experiments.

This deliberately is not a workflow framework.  It takes one immutable source
file and one explicit named command, proves a declared scratch-stage snapshot
using existing read helpers, then forwards that one command at most once.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from isaac_mcp.live_testing import ScratchRun, ScratchStageGuardError
from isaac_mcp.runtime_status import get_runtime_status


class ExperimentRejected(RuntimeError):
    """A failed preflight that must not forward the experiment command."""

    def __init__(self, code: str, expected: Any = None, observed: Any = None):
        self.code = code
        self.expected = expected
        self.observed = observed
        super().__init__(code)


def _utc_microseconds() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


class _TracedConnection:
    """Record each actual transport call without changing retry or policy behavior."""

    def __init__(self, connection: Any, events: list[dict[str, Any]]):
        self._connection = connection
        self._events = events

    def send_command(self, command: str, params: Any = None, **kwargs: Any) -> Any:
        started_at = _utc_microseconds()
        started_ns = time.perf_counter_ns()
        event: dict[str, Any] = {
            "event": "transport_call",
            "command": command,
            "command_id": kwargs.get("command_id"),
            "started_at": started_at,
        }
        try:
            result = self._connection.send_command(command, params, **kwargs)
        except Exception as exc:
            event.update({"ended_at": _utc_microseconds(), "elapsed_ms": (time.perf_counter_ns() - started_ns) / 1_000_000, "error": repr(exc), "raw_result": None})
            self._events.append(event)
            raise
        event.update({"ended_at": _utc_microseconds(), "elapsed_ms": (time.perf_counter_ns() - started_ns) / 1_000_000, "raw_result": result})
        self._events.append(event)
        return result


def _data(response: Mapping[str, Any], command: str) -> dict[str, Any]:
    if response.get("status") != "success" or not isinstance(response.get("data"), Mapping):
        raise ExperimentRejected("PREFLIGHT_READ_FAILED", command, dict(response))
    return dict(response["data"])


def _layer_identifier(composition: Mapping[str, Any]) -> str | None:
    layers = composition.get("layer_stack")
    if not isinstance(layers, list) or not layers or not isinstance(layers[0], Mapping):
        return None
    value = layers[0].get("identifier")
    return str(value) if value else None


def _matching_fields(expected: Mapping[str, Any], observed: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        key: {"expected": value, "observed": observed.get(key)}
        for key, value in expected.items()
        if key not in observed or observed.get(key) != value
    }


def owned_runtime_status_reader(
    *, host: str, port: int, state_file: Path
) -> Callable[[], Mapping[str, Any]]:
    """Bind PID provenance to one explicitly supplied supervisor state file.

    ``get_runtime_status`` normalizes its returned port to the requested endpoint,
    so inspect the stored document first.  A state file for another port must
    not lend its launcher PID to this experiment.
    """

    def read() -> Mapping[str, Any]:
        try:
            stored = json.loads(state_file.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            return {"port": None, "identity_error": f"owned runtime state unavailable: {exc}"}
        if not isinstance(stored, Mapping) or stored.get("port") != port:
            return {
                "port": stored.get("port") if isinstance(stored, Mapping) else None,
                "identity_error": "owned runtime state port does not match experiment endpoint",
            }
        return get_runtime_status(host=host, port=port, state_file=state_file)

    return read


@dataclass
class ExperimentDispatcher:
    """Dispatch exactly one command after strict byte and scene preflight."""

    connection: Any
    owned_output_root: Path
    runtime_status_reader: Callable[[], Mapping[str, Any]] | None = None

    def __post_init__(self) -> None:
        self.owned_output_root = self.owned_output_root.resolve(strict=False)

    def _runtime_identity(self) -> dict[str, Any]:
        if self.runtime_status_reader is None:
            return {
                "supervisor_pid": None,
                "launcher_pid": None,
                "launcher_pid_provenance": "unknown: no owned runtime state reader supplied",
                "legacy_runtime_pid": None,
                "kit_pid": None,
                "kit_pid_provenance": "unknown: system.get_capabilities has no process-id field",
                "kit_identity_read": "system.get_capabilities",
            }
        else:
            runtime = dict(self.runtime_status_reader() or {})
        expected_port = getattr(self.connection, "port", None)
        if expected_port is not None and runtime.get("port") not in {None, expected_port}:
            return {
                "supervisor_pid": None,
                "launcher_pid": None,
                "launcher_pid_provenance": "unknown: runtime state endpoint does not match connection port",
                "legacy_runtime_pid": None,
                "kit_pid": None,
                "kit_pid_provenance": "unknown: runtime state endpoint does not match connection port",
                "kit_identity_read": "system.get_capabilities",
            }
        return {
            "supervisor_pid": runtime.get("supervisor_pid"),
            "launcher_pid": runtime.get("launcher_pid"),
            "launcher_pid_provenance": runtime.get("launcher_pid_provenance"),
            "legacy_runtime_pid": runtime.get("runtime_pid"),
            "kit_pid": None,
            "kit_pid_provenance": "unknown: system.get_capabilities has no process-id field",
            "kit_identity_read": "system.get_capabilities",
        }

    def _trace_path(self, run_id: str) -> Path:
        # The runner owns this fixed root and only creates its own per-run leaf.
        run_dir = self.owned_output_root / run_id
        run_dir.mkdir(parents=True, exist_ok=False)
        return run_dir / "dispatch_trace.json"

    @staticmethod
    def _source(spec: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
        source_path = Path(str(spec.get("source_path") or ""))
        expected_hash = str(spec.get("frozen_sha256") or "").lower()
        if len(expected_hash) != 64 or any(character not in "0123456789abcdef" for character in expected_hash):
            raise ExperimentRejected("FROZEN_SHA256_REQUIRED", "64 lowercase hexadecimal characters", expected_hash)
        try:
            raw = source_path.read_bytes()
        except OSError as exc:
            raise ExperimentRejected("SOURCE_READ_FAILED", str(source_path), str(exc)) from exc
        try:
            source = raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise ExperimentRejected("SOURCE_NOT_STRICT_UTF8", "strict UTF-8", str(exc)) from exc
        actual_hash = hashlib.sha256(raw).hexdigest()
        observed = {"path": str(source_path), "sha256": actual_hash, "bytes": len(raw)}
        if actual_hash != expected_hash:
            raise ExperimentRejected("FROZEN_SOURCE_HASH_MISMATCH", expected_hash, observed)
        return source, observed

    def _preflight(self, connection: Any, spec: Mapping[str, Any], run_id: str) -> dict[str, Any]:
        preflight = spec.get("preflight")
        if not isinstance(preflight, Mapping):
            raise ExperimentRejected("PREFLIGHT_REQUIRED", "preflight mapping", preflight)
        required = {
            "expected_stage_path",
            "scratch_root",
            "root_layer",
            "session_layer",
            "paths",
            "metadata",
            "time_seconds",
            "time_tolerance",
        }
        missing = sorted(name for name in required if name not in preflight)
        if missing:
            raise ExperimentRejected("PREFLIGHT_FIELDS_REQUIRED", sorted(required), missing)
        text_fields = ("expected_stage_path", "scratch_root", "root_layer", "session_layer")
        invalid_text = [name for name in text_fields if not isinstance(preflight[name], str) or not preflight[name].strip()]
        if invalid_text:
            raise ExperimentRejected("PREFLIGHT_FIELDS_INVALID", "non-empty text fields", invalid_text)
        if not isinstance(preflight["paths"], list) or not preflight["paths"] or not all(
            isinstance(path, str) and path.startswith("/") for path in preflight["paths"]
        ):
            raise ExperimentRejected("PREFLIGHT_PATHS_INVALID", "non-empty absolute path list", preflight["paths"])
        if not isinstance(preflight["metadata"], Mapping) or not preflight["metadata"]:
            raise ExperimentRejected("PREFLIGHT_METADATA_INVALID", "non-empty metadata mapping", preflight["metadata"])
        try:
            expected_time = float(preflight["time_seconds"])
            tolerance = float(preflight["time_tolerance"])
        except (TypeError, ValueError) as exc:
            raise ExperimentRejected("PREFLIGHT_TIME_INVALID", "finite time=0 and non-negative tolerance", None) from exc
        if not math.isfinite(expected_time) or expected_time != 0.0 or not math.isfinite(tolerance) or tolerance < 0:
            raise ExperimentRejected(
                "PREFLIGHT_TIME_INVALID",
                "finite time_seconds=0 and non-negative time_tolerance",
                {"time_seconds": preflight["time_seconds"], "time_tolerance": preflight["time_tolerance"]},
            )
        if preflight.get("kit_pid") is not None:
            raise ExperimentRejected(
                "KIT_PID_IDENTITY_UNAVAILABLE",
                "no kit_pid assertion until a named read-only protocol exposes it",
                preflight.get("kit_pid"),
            )

        capability_response = connection.send_command("system.get_capabilities", command_id=f"{run_id}-capabilities")
        capabilities = _data(capability_response, "system.get_capabilities")
        commands = capabilities.get("extension", {}).get("command_names")
        allow_commands = spec.get("allow_commands")
        dispatch = spec.get("dispatch")
        expected_result = spec.get("expected_result")
        if not isinstance(dispatch, Mapping) or not isinstance(allow_commands, list) or not isinstance(expected_result, Mapping):
            raise ExperimentRejected("DISPATCH_ALLOWLIST_REQUIRED", "dispatch mapping and allow_commands list", dispatch)
        command = str(dispatch.get("command") or "")
        parameters = dispatch.get("params", {})
        source_parameter = dispatch.get("source_parameter", "code")
        if (
            not command
            or not all(isinstance(item, str) and item for item in allow_commands)
            or not isinstance(parameters, Mapping)
            or not isinstance(source_parameter, str)
            or not source_parameter
            or not expected_result
            or not isinstance(expected_result.get("status"), str)
            or not expected_result["status"]
        ):
            raise ExperimentRejected("DISPATCH_CONFIG_INVALID", "finite command allowlist, mapping params, source_parameter, expected_result", dispatch)
        if command not in allow_commands or not isinstance(commands, list) or command not in commands:
            raise ExperimentRejected(
                "DISPATCH_COMMAND_DENIED",
                {"allow_commands": allow_commands, "runtime_commands": commands},
                command,
            )
        command_id = str(dispatch.get("command_id") or f"experiment-{run_id}")
        if "command_id" in expected_result and expected_result["command_id"] != command_id:
            raise ExperimentRejected(
                "EXPECTED_COMMAND_ID_CONFLICT",
                command_id,
                expected_result["command_id"],
            )

        # Reuse the established scratch guard for exact stage path, stopped
        # state, and unique namespace before any write is forwarded.
        try:
            scratch = ScratchRun.validate(
                connection,
                expected_stage_path=str(preflight["expected_stage_path"]),
                scratch_root=str(preflight["scratch_root"]),
                run_id=run_id,
            )
        except ScratchStageGuardError as exc:
            raise ExperimentRejected("SCRATCH_GUARD_FAILED", "exact stopped scratch stage", str(exc)) from exc

        composition_response = connection.send_command("stage.get_composition", command_id=f"{run_id}-composition")
        composition = _data(composition_response, "stage.get_composition")
        simulation_response = connection.send_command("simulation.get_state", command_id=f"{run_id}-simulation")
        simulation = _data(simulation_response, "simulation.get_state")
        observed = {
            "root_layer": (composition.get("root_layer") or {}).get("identifier"),
            "session_layer": _layer_identifier(composition),
            "paths": composition.get("prim_paths"),
            "metadata": composition.get("metadata"),
            "timeline_state": simulation.get("timeline_state"),
            "time_seconds": simulation.get("current_time"),
        }
        mismatches: dict[str, Any] = {}
        for field in ("root_layer", "session_layer", "paths"):
            if observed[field] != preflight[field]:
                mismatches[field] = {"expected": preflight[field], "observed": observed[field]}
        metadata = observed["metadata"]
        if not isinstance(metadata, Mapping):
            mismatches["metadata"] = {"expected": preflight["metadata"], "observed": metadata}
        else:
            fields = _matching_fields(dict(preflight["metadata"]), metadata)
            if fields:
                mismatches["metadata"] = fields
        if observed["timeline_state"] != "stopped":
            mismatches["timeline_state"] = {"expected": "stopped", "observed": observed["timeline_state"]}
        try:
            time_delta = abs(float(observed["time_seconds"]) - expected_time)
            within_tolerance = math.isfinite(time_delta) and time_delta <= tolerance
        except (TypeError, ValueError):
            within_tolerance = False
            time_delta = None
        if not within_tolerance:
            mismatches["time_seconds"] = {
                "expected": preflight["time_seconds"],
                "tolerance": preflight["time_tolerance"],
                "observed": observed["time_seconds"],
                "delta": time_delta,
            }
        if mismatches:
            raise ExperimentRejected("PREFLIGHT_MISMATCH", "all declared guard fields", {"mismatches": mismatches, "observed": observed})

        identity = self._runtime_identity()
        return {"scratch_namespace": scratch.namespace, "identity": identity, "observed": observed}

    def run(self, spec: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(spec, Mapping):
            return {"status": "rejected", "code": "SPEC_MAPPING_REQUIRED"}
        run_id = str(spec.get("run_id") or uuid.uuid4().hex).lower()
        if len(run_id) != 32 or any(character not in "0123456789abcdef" for character in run_id):
            return {"status": "rejected", "code": "INVALID_RUN_ID"}
        trace: dict[str, Any] = {
            "run_id": run_id,
            "started_at": _utc_microseconds(),
            "started_monotonic_ns": time.perf_counter_ns(),
            "events": [],
        }
        try:
            path = self._trace_path(run_id)
        except FileExistsError:
            return {
                "status": "rejected",
                "code": "RUN_ID_ALREADY_EXISTS",
                "trace_path": str(self.owned_output_root / run_id / "dispatch_trace.json"),
            }
        try:
            traced_connection = _TracedConnection(self.connection, trace["events"])
            trace["events"].append({"event": "attempt", "at": _utc_microseconds()})
            source, source_observed = self._source(spec)
            trace["source"] = source_observed
            preflight = self._preflight(traced_connection, spec, run_id)
            trace["preflight"] = preflight
            dispatch = dict(spec["dispatch"])
            parameters = dict(dispatch.get("params") or {})
            source_parameter = str(dispatch.get("source_parameter") or "code")
            parameters[source_parameter] = source
            command = str(dispatch["command"])
            command_id = str(dispatch.get("command_id") or f"experiment-{run_id}")
            trace["events"].append({"event": "forward", "at": _utc_microseconds(), "command": command, "command_id": command_id})
            raw_result = traced_connection.send_command(command, parameters, command_id=command_id)
            trace["events"].append({"event": "result", "at": _utc_microseconds(), "raw_result": raw_result})
            observed_result = {
                "status": raw_result.get("status") if isinstance(raw_result, Mapping) else None,
                "code": raw_result.get("code") if isinstance(raw_result, Mapping) else None,
                "command_id": raw_result.get("command_id") if isinstance(raw_result, Mapping) else None,
            }
            expected = dict(spec["expected_result"])
            expected.setdefault("command_id", command_id)
            mismatches = _matching_fields(expected, observed_result)
            application_status = "accepted" if not mismatches else "rejected"
            trace["application"] = {"status": application_status, "expected": expected, "observed": observed_result, "mismatches": mismatches}
            trace["status"] = f"application_{application_status}"
            return {"status": f"application_{application_status}", "trace_path": str(path), "raw_result": raw_result}
        except ExperimentRejected as exc:
            trace["events"].append(
                {"event": "rejection", "at": _utc_microseconds(), "code": exc.code, "expected": exc.expected, "observed": exc.observed}
            )
            trace["status"] = "rejected"
            return {"status": "rejected", "code": exc.code, "trace_path": str(path)}
        except Exception as exc:
            trace["events"].append({"event": "error", "at": _utc_microseconds(), "error": repr(exc), "raw_result": None})
            trace["status"] = "error"
            return {"status": "error", "code": "DISPATCH_EXCEPTION", "trace_path": str(path)}
        finally:
            trace["ended_at"] = _utc_microseconds()
            trace["elapsed_ms"] = (time.perf_counter_ns() - trace["started_monotonic_ns"]) / 1_000_000
            path.write_text(json.dumps(trace, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def owned_output_root() -> Path:
    """Return the only root the executable dispatcher may create beneath."""
    configured = os.getenv("ISAAC_MCP_EXPERIMENT_OUTPUT_ROOT")
    return Path(configured) if configured else Path(__file__).resolve().parents[1] / "outputs" / "isolated_experiments"
