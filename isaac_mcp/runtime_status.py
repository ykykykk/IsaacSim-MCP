"""Bounded cross-process status for the supervised Isaac Sim runtime."""

from __future__ import annotations

import json
import os
import re
import socket
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from isaac_mcp.responses import normalize_response

STATE_SCHEMA_VERSION = "1.0"
MAX_STATE_BYTES = 64 * 1024
DEFAULT_PROBE_TIMEOUT_SECONDS = 1.0
MAX_LOG_SCAN_BYTES = 1024 * 1024
MAX_DIAGNOSTIC_LINES = 24
RECENT_LOG_SECONDS = 24 * 60 * 60
MAX_IDENTITY_STATE_AGE_SECONDS = 5 * 60
_LAST_ENDPOINT_RUNTIME: dict[tuple[str, int], dict[str, Any]] = {}

_LOG_LINE_MARKERS = (
    "[error]",
    "[fatal]",
    "[crash]",
    "exception_access_violation",
    "cudaerrorillegaladdress",
    "simulation cannot continue",
    "failed to launch kernel",
    "error 700",
    "error_device_lost",
    "physxgpu_64.dll",
    "waiting for pid",
)
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?token|token|password|secret)\b(\s*[:=]\s*)([^\s,;]+)"
)
_BEARER = re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)([^\s,;]+)")
_LOG_PREFIX = re.compile(r"^\s*\d{4}-\d{2}-\d{2}T\S+\s+\[[^]]+\]\s+")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def remember_runtime_identity(host: str, port: int, runtime: Mapping[str, Any]) -> None:
    _LAST_ENDPOINT_RUNTIME[(host, port)] = {**runtime, "observed_at": utc_now()}


def default_state_file() -> Path:
    configured = os.getenv("ISAAC_MCP_RUNTIME_STATE_FILE")
    if configured:
        return Path(configured).expanduser()
    if os.getenv("LOCALAPPDATA"):
        base = Path(os.environ["LOCALAPPDATA"])
    elif os.getenv("XDG_STATE_HOME"):
        base = Path(os.environ["XDG_STATE_HOME"])
    else:
        base = Path.home() / ".local" / "state"
    port = int(os.getenv("ISAAC_MCP_PORT", "8766"))
    return base / "IsaacSim-MCP" / "6.2" / f"runtime-{port}.json"


def _kit_log_candidates() -> tuple[list[Path], str]:
    configured = os.getenv("ISAAC_MCP_RUNTIME_LOG_FILE")
    if configured:
        return [Path(configured).expanduser()], "configured"

    configured_root = os.getenv("ISAAC_MCP_KIT_LOG_ROOT")
    kit_root = (Path(configured_root).expanduser() if configured_root else
                Path.home() / ".nvidia-omniverse" / "logs" / "Kit")
    if not kit_root.is_dir():
        return [], "automatic"
    try:
        candidates = sorted(
            (path for path in kit_root.glob("**/kit_*.log") if path.is_file()),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        candidates = []
    return candidates, "configured_root" if configured_root else "automatic"


def _configured_or_latest_kit_log() -> tuple[Path | None, str]:
    candidates, source = _kit_log_candidates()
    return (candidates[0] if candidates else None), source


def _redact_log_line(line: str) -> str:
    value = _BEARER.sub(r"\1[REDACTED]", line)
    return _SECRET_ASSIGNMENT.sub(r"\1\2[REDACTED]", value)


def _bounded_log_tail(path: Path) -> tuple[str, int, int]:
    size = path.stat().st_size
    scan_bytes = min(size, MAX_LOG_SCAN_BYTES)
    with path.open("rb") as stream:
        if scan_bytes < size:
            stream.seek(-scan_bytes, os.SEEK_END)
        payload = stream.read(scan_bytes)
    text = payload.decode("utf-8", errors="replace")
    if scan_bytes < size and "\n" in text:
        text = text.split("\n", 1)[1]
    return text, size, scan_bytes


def _crash_signatures(text: str) -> list[str]:
    lowered = text.lower()
    signatures: list[str] = []
    checks = (
        ("CUDA_ERROR_700", "error 700" in lowered or "cudaerrorillegaladdress" in lowered),
        ("PHYSX_SIMULATION_FATAL", "simulation cannot continue" in lowered),
        ("NATIVE_CRASH", "[crash] a crash has occurred" in lowered),
        ("PHYSX_GPU_DLL_CRASH", "physxgpu_64.dll" in lowered),
        ("GPU_DEVICE_LOST", "error_device_lost" in lowered),
        ("ACCESS_VIOLATION", "exception_access_violation" in lowered),
    )
    for name, matched in checks:
        if matched:
            signatures.append(name)
    return signatures


def _signature_evidence(text: str, signatures: list[str]) -> dict[str, str]:
    lines = text.splitlines()
    patterns = {
        "CUDA_ERROR_700": ("cudaerrorillegaladdress", "simulation cannot continue", "error 700"),
        "PHYSX_SIMULATION_FATAL": ("simulation cannot continue",),
        "NATIVE_CRASH": ("[crash] a crash has occurred",),
        "PHYSX_GPU_DLL_CRASH": ("physxgpu_64.dll",),
        "GPU_DEVICE_LOST": ("error_device_lost",),
        "ACCESS_VIOLATION": ("exception_access_violation",),
    }
    evidence: dict[str, str] = {}
    for signature in signatures:
        for pattern in patterns[signature]:
            match = next((line.strip() for line in lines if pattern in line.lower()), None)
            if match:
                evidence[signature] = _redact_log_line(match)[:2048]
                break
    return evidence


def read_runtime_diagnostics(
    log_file: str | os.PathLike[str] | None = None,
    *,
    source: str | None = None,
) -> dict[str, Any]:
    """Return a redacted, bounded summary from the latest local Kit log."""
    if log_file is None:
        path, resolved_source = _configured_or_latest_kit_log()
    else:
        path, resolved_source = Path(log_file), source or "selected"
    if path is None:
        return {"available": False, "source": resolved_source, "reason": "kit_log_not_found"}
    try:
        if not path.is_file():
            return {
                "available": False,
                "source": resolved_source,
                "log_path": str(path),
                "reason": "configured_kit_log_not_found",
            }
        text, size, scan_bytes = _bounded_log_tail(path)
        stat = path.stat()
    except OSError as exc:
        return {
            "available": False,
            "source": resolved_source,
            "log_path": str(path),
            "reason": "kit_log_unreadable",
            "error": str(exc)[:512],
        }

    records: list[str] = []
    seen: set[str] = set()
    for raw_line in reversed(text.splitlines()):
        line = raw_line.strip()
        lowered = line.lower()
        if not line or not any(marker in lowered for marker in _LOG_LINE_MARKERS):
            continue
        redacted = _redact_log_line(line)[:2048]
        key = _LOG_PREFIX.sub("", redacted).lower()
        if key in seen:
            continue
        seen.add(key)
        records.append(redacted)
        if len(records) >= MAX_DIAGNOSTIC_LINES:
            break
    records.reverse()

    signatures = _crash_signatures(text)
    modified_at = datetime.fromtimestamp(stat.st_mtime, timezone.utc)
    age_seconds = max(0, int((datetime.now(timezone.utc) - modified_at).total_seconds()))
    return {
        "available": True,
        "source": resolved_source,
        "log_path": str(path),
        "log_size_bytes": size,
        "scanned_tail_bytes": scan_bytes,
        "log_modified_at": modified_at.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "log_age_seconds": age_seconds,
        "recent": age_seconds <= RECENT_LOG_SECONDS,
        "crash_detected": bool(signatures),
        "primary_signature": signatures[0] if signatures else None,
        "signatures": signatures,
        "signature_evidence": _signature_evidence(text, signatures),
        "diagnostic_lines": records,
        "truncated": size > scan_bytes,
    }


def read_previous_crash_diagnostics(*, exclude: str | None = None) -> dict[str, Any] | None:
    """Find one recent prior Kit session containing a bounded crash signature."""
    candidates, source = _kit_log_candidates()
    for path in candidates[:6]:
        if exclude and str(path) == exclude:
            continue
        diagnostics = read_runtime_diagnostics(path, source=f"{source}_previous_session")
        if diagnostics.get("recent") and diagnostics.get("crash_detected"):
            return diagnostics
    return None


def _probe_timeout() -> float:
    try:
        value = float(os.getenv("ISAAC_MCP_RUNTIME_PROBE_TIMEOUT_SECONDS", DEFAULT_PROBE_TIMEOUT_SECONDS))
    except (TypeError, ValueError):
        return DEFAULT_PROBE_TIMEOUT_SECONDS
    return value if 0 < value <= 30 else DEFAULT_PROBE_TIMEOUT_SECONDS


def probe_runtime_health(*, host: str, port: int, timeout: float | None = None) -> dict[str, Any]:
    """Query the read-only capability command so an open-but-hung port is not considered ready."""
    checked_at = utc_now()
    timeout = timeout if timeout is not None else _probe_timeout()
    command = {
        "type": "system.get_capabilities",
        "params": {},
        "command_id": f"runtime-health-{uuid.uuid4()}",
    }
    port_open = False
    try:
        with socket.create_connection((host, port), timeout=timeout) as connection:
            port_open = True
            connection.settimeout(timeout)
            connection.sendall(json.dumps(command, separators=(",", ":")).encode("utf-8"))
            chunks: list[bytes] = []
            total = 0
            response: Any = None
            while True:
                chunk = connection.recv(16384)
                if not chunk:
                    break
                total += len(chunk)
                if total > 1024 * 1024:
                    raise ValueError("health response exceeds 1048576 bytes")
                chunks.append(chunk)
                try:
                    response = json.loads(b"".join(chunks).decode("utf-8"))
                    break
                except json.JSONDecodeError:
                    continue
            if not chunks:
                raise ConnectionError("runtime closed the health connection without a response")
            if response is None:
                raise ValueError("runtime returned incomplete health JSON")
        responding = isinstance(response, Mapping) and response.get("status") == "success"
        runtime = response.get("data", {}).get("runtime", {}) if responding else {}
        if responding:
            remember_runtime_identity(host, port, runtime)
        return {
            "responding": responding,
            "port_open": True,
            "checked_at": checked_at,
            "error": None if responding else "capability health response was not successful",
            "runtime": runtime,
        }
    except (OSError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        return {
            "responding": False,
            "port_open": port_open,
            "checked_at": checked_at,
            "error": str(exc)[:512],
        }


def _read_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "schema_version": STATE_SCHEMA_VERSION,
            "state": "unmanaged",
            "supervised": False,
        }
    try:
        if path.stat().st_size > MAX_STATE_BYTES:
            raise ValueError(f"runtime state exceeds {MAX_STATE_BYTES} bytes")
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or value.get("schema_version") != STATE_SCHEMA_VERSION:
            raise ValueError("runtime state schema is invalid")
        return value
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {
            "schema_version": STATE_SCHEMA_VERSION,
            "state": "diagnostic_unavailable",
            "supervised": True,
            "diagnostic_error": str(exc)[:512],
        }


def _availability_code(state: str, responding: bool) -> str:
    if responding:
        return "ISAAC_RUNTIME_READY"
    if state in {"starting", "restarting", "restart_backoff"}:
        return "ISAAC_RUNTIME_RECOVERING"
    if state in {"crashed", "recovery_failed"}:
        return "ISAAC_RUNTIME_CRASHED"
    return "ISAAC_RUNTIME_UNAVAILABLE"


def _identity_state_is_fresh(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        recorded = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    if recorded.tzinfo is None:
        return False
    age_seconds = (datetime.now(timezone.utc) - recorded.astimezone(timezone.utc)).total_seconds()
    return -60 <= age_seconds <= MAX_IDENTITY_STATE_AGE_SECONDS


def _identity_problem(state: Mapping[str, Any], *, host: str, port: int) -> tuple[str | None, str | None]:
    """Return an identity failure without treating endpoint health as PID proof."""
    pid_fields = ("runtime_pid", "supervisor_pid", "launcher_pid", "kit_pid")
    has_pid = any(state.get(field) is not None for field in pid_fields)
    stored_port = state.get("port")
    if stored_port is None and has_pid:
        return "identity_unverified", "runtime state has PID fields but no endpoint port"
    if stored_port is not None and stored_port != port:
        return "endpoint_mismatch", "runtime state port does not match requested endpoint"
    stored_host = state.get("host")
    if has_pid and stored_host != host:
        return "identity_unverified", "runtime state host does not match requested endpoint"
    if has_pid and not _identity_state_is_fresh(state.get("updated_at")):
        return "identity_unverified", "runtime state identity is stale or lacks a valid timestamp"
    return None, None


def _recommended_actions(code: str, state: str) -> list[str]:
    actions = ["query_get_runtime_status"]
    if code == "ISAAC_RUNTIME_RECOVERING":
        actions.extend(["wait_for_recovery", "retry_read_when_ready"])
    elif code == "ISAAC_RUNTIME_CRASHED":
        actions.extend(["inspect_last_crash", "fix_root_cause", "restart_supervisor"])
    elif code == "ISAAC_RUNTIME_UNAVAILABLE":
        if state in {"unresponsive", "external_runtime_unresponsive"}:
            actions.extend(["inspect_unresponsive_runtime", "do_not_start_second_runtime"])
        else:
            actions.append("start_supervised_isaac_runtime")
    actions.append("do_not_replay_write")
    return actions


def get_runtime_status(
    *,
    host: str = "127.0.0.1",
    port: int | None = None,
    state_file: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Combine supervisor evidence with a bounded protocol-level health probe."""
    effective_port = port if port is not None else int(os.getenv("ISAAC_MCP_PORT", "8766"))
    path = Path(state_file) if state_file is not None else default_state_file()
    state = _read_state(path)
    stored_port = state.get("port")
    stored_host = state.get("host")
    identity_status, identity_error = _identity_problem(state, host=host, port=effective_port)
    health = probe_runtime_health(host=host, port=effective_port)
    endpoint = (host, effective_port)
    current_runtime = health.get("runtime")
    if health.get("responding") and isinstance(current_runtime, dict):
        _LAST_ENDPOINT_RUNTIME[endpoint] = {**current_runtime, "observed_at": health["checked_at"]}
    runtime_identity = _LAST_ENDPOINT_RUNTIME.get(endpoint)
    if runtime_identity is None and identity_status is None:
        runtime_identity = state.get("runtime_identity")
    if runtime_identity and runtime_identity.get("log_file"):
        diagnostics = read_runtime_diagnostics(runtime_identity["log_file"], source="endpoint_capabilities")
        diagnostics["endpoint_bound"] = True
        diagnostics["runtime_process_id"] = runtime_identity.get("process_id")
    else:
        diagnostics = read_runtime_diagnostics()
        # A recent file in a version directory is useful context, not evidence
        # that this particular endpoint crashed. Never promote it to current state.
        diagnostics["endpoint_bound"] = False
    last_crash = state.get("last_crash")
    if isinstance(last_crash, dict) and not isinstance(last_crash.get("diagnostics"), dict):
        previous = read_previous_crash_diagnostics(exclude=diagnostics.get("log_path"))
        if previous is not None:
            last_crash["diagnostics"] = previous
    responding = bool(health.get("responding"))
    if identity_status is not None:
        for field in ("runtime_pid", "supervisor_pid", "launcher_pid", "kit_pid"):
            state.pop(field, None)
        state["identity_status"] = identity_status
        state["identity_error"] = identity_error
        state["stored_state_port"] = stored_port
        state["stored_state_host"] = stored_host
        if identity_status == "endpoint_mismatch":
            state["state"] = "endpoint_mismatch"
    if responding:
        state["state"] = "ready"
    elif (
        diagnostics.get("crash_detected")
        and diagnostics.get("recent")
        and diagnostics.get("endpoint_bound")
        and not health.get("port_open")
        and state.get("state")
        not in {"starting", "restarting", "restart_backoff", "stopped", "supervisor_interrupted"}
    ):
        # Kit's crash reporter can keep the launcher process alive after the
        # Extension socket disappears. Log evidence must therefore be able to
        # mark this state as crashed before process.poll() returns.
        state["state"] = "crashed"
    elif health.get("port_open") or state.get("state") == "ready":
        if state.get("state") not in {"starting", "restarting", "restart_backoff"}:
            state["state"] = "unresponsive"
    # A protocol timeout cannot distinguish a long main-thread operation from a
    # hung host. Keep that uncertainty explicit instead of asserting a crash.
    state["activity"] = (
        "responsive" if responding else
        "starting" if state.get("state") in {"starting", "restarting", "restart_backoff"} else
        "crashed" if state.get("state") in {"crashed", "recovery_failed"} else
        "busy_or_unresponsive" if health.get("port_open") else "disconnected"
    )
    state["runtime_identity"] = runtime_identity
    state["runtime_responding"] = responding
    state["health"] = health
    state["diagnostics"] = diagnostics
    state["host"] = host
    state["port"] = effective_port
    state["availability_code"] = (
        _availability_code(str(state.get("state", "unmanaged")), responding)
    )
    state["recommended_actions"] = _recommended_actions(state["availability_code"], str(state["state"]))
    return state


def runtime_unavailable_response(status: Mapping[str, Any], *, command_id: str | None = None) -> dict[str, Any]:
    code = str(status.get("availability_code", "ISAAC_RUNTIME_UNAVAILABLE"))
    state = str(status.get("state", "unmanaged"))
    message = {
        "ISAAC_RUNTIME_RECOVERING": f"Isaac Sim is recovering under the runtime supervisor (state: {state})",
        "ISAAC_RUNTIME_CRASHED": f"Isaac Sim exited unexpectedly and automatic recovery is unavailable (state: {state})",
    }.get(
        code,
        (
            "Isaac Sim or its runtime port exists but did not answer protocol health; do not start a second runtime"
            if state in {"unresponsive", "external_runtime_unresponsive"}
            else "Isaac Sim is not available; start the supervised runtime launcher"
        ),
    )
    return normalize_response(
        {
            "status": "error",
            "code": code,
            "message": message,
            "data": {"runtime": dict(status)},
            "warnings": [
                "The failed command was not replayed; read back state after recovery before retrying a write."
            ],
            "readback": {"required": True, "completed": False},
        },
        command_id=command_id,
    )


class IsaacRuntimeUnavailableError(ConnectionError):
    """Carries a stable MCP response when the extension runtime cannot be reached."""

    def __init__(self, status: Mapping[str, Any], *, command_id: str | None = None):
        self.status = dict(status)
        self.command_id = command_id
        super().__init__(runtime_unavailable_response(self.status, command_id=command_id)["message"])

    def to_response(self) -> dict[str, Any]:
        return runtime_unavailable_response(self.status, command_id=self.command_id)
