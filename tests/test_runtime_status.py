"""Runtime-supervisor state and MCP recovery-envelope contracts."""

from __future__ import annotations

import json
import os

import pytest

from isaac_mcp import runtime_status


def test_missing_state_file_is_reported_as_unmanaged(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_status, "probe_runtime_health", lambda **_kwargs: {"responding": False})

    result = runtime_status.get_runtime_status(state_file=tmp_path / "missing.json")

    assert result["state"] == "unmanaged"
    assert result["supervised"] is False
    assert result["runtime_responding"] is False
    assert result["availability_code"] == "ISAAC_RUNTIME_UNAVAILABLE"


def test_supervisor_crash_state_is_bounded_and_exposed(tmp_path, monkeypatch):
    state_file = tmp_path / "runtime-state.json"
    state_file.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "state": "restart_backoff",
                "supervised": True,
                "attempt": 2,
                "max_restarts": 3,
                "next_restart_at": "2026-08-27T11:00:05Z",
                "last_crash": {
                    "occurred_at": "2026-08-27T11:00:03Z",
                    "exit_code": 17,
                    "was_ready": True,
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime_status, "probe_runtime_health", lambda **_kwargs: {"responding": False})

    result = runtime_status.get_runtime_status(state_file=state_file)
    response = runtime_status.runtime_unavailable_response(result, command_id="cmd-1")

    assert result["availability_code"] == "ISAAC_RUNTIME_RECOVERING"
    assert result["last_crash"]["exit_code"] == 17
    assert response["status"] == "error"
    assert response["code"] == "ISAAC_RUNTIME_RECOVERING"
    assert response["command_id"] == "cmd-1"
    assert response["data"]["runtime"]["next_restart_at"].endswith("Z")
    assert response["readback"]["required"] is True
    assert "do_not_replay_write" in response["data"]["runtime"]["recommended_actions"]


def test_live_health_overrides_stale_crash_state(tmp_path, monkeypatch):
    state_file = tmp_path / "runtime-state.json"
    state_file.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "state": "crashed",
                "supervised": True,
                "last_crash": {"exit_code": 9},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        runtime_status,
        "probe_runtime_health",
        lambda **_kwargs: {"responding": True, "checked_at": "2026-08-27T11:01:00Z"},
    )

    result = runtime_status.get_runtime_status(state_file=state_file)

    assert result["state"] == "ready"
    assert result["runtime_responding"] is True
    assert result["availability_code"] == "ISAAC_RUNTIME_READY"
    assert result["last_crash"]["exit_code"] == 9


def test_invalid_state_file_fails_closed_without_echoing_contents(tmp_path, monkeypatch):
    state_file = tmp_path / "runtime-state.json"
    state_file.write_text("token=do-not-echo", encoding="utf-8")
    monkeypatch.setattr(runtime_status, "probe_runtime_health", lambda **_kwargs: {"responding": False})

    result = runtime_status.get_runtime_status(state_file=state_file)

    assert result["state"] == "diagnostic_unavailable"
    assert result["availability_code"] == "ISAAC_RUNTIME_UNAVAILABLE"
    assert "do-not-echo" not in json.dumps(result)


def test_stale_ready_state_becomes_unresponsive_when_protocol_probe_fails(tmp_path, monkeypatch):
    state_file = tmp_path / "runtime-state.json"
    state_file.write_text(
        json.dumps({"schema_version": "1.0", "state": "ready", "supervised": True}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        runtime_status,
        "probe_runtime_health",
        lambda **_kwargs: {"responding": False, "error": "probe timed out"},
    )

    result = runtime_status.get_runtime_status(state_file=state_file)

    assert result["state"] == "unresponsive"
    assert result["availability_code"] == "ISAAC_RUNTIME_UNAVAILABLE"
    assert "inspect_unresponsive_runtime" in result["recommended_actions"]
    assert "start_supervised_isaac_runtime" not in result["recommended_actions"]


def test_explicit_endpoint_rejects_state_from_another_port(tmp_path, monkeypatch):
    state_file = tmp_path / "runtime-state.json"
    state_file.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "state": "ready",
                "supervised": True,
                "host": "127.0.0.1",
                "port": 8766,
                "launcher_pid": 123,
                "runtime_pid": 123,
                "kit_pid": 456,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime_status, "probe_runtime_health", lambda **_kwargs: {"responding": False})

    result = runtime_status.get_runtime_status(port=8767, state_file=state_file)

    assert result["state"] == "endpoint_mismatch"
    assert result["availability_code"] == "ISAAC_RUNTIME_UNAVAILABLE"
    assert result["stored_state_port"] == 8766
    assert result["port"] == 8767
    assert result["identity_error"]
    assert "launcher_pid" not in result
    assert "runtime_pid" not in result
    assert "kit_pid" not in result


@pytest.mark.parametrize(
    ("state_overrides", "expected_status"),
    [
        ({"port": None}, "identity_unverified"),
        ({"host": "127.0.0.2"}, "identity_unverified"),
        ({"updated_at": "2026-10-16T13:52:02Z"}, "identity_unverified"),
    ],
)
def test_unproven_state_identity_never_lends_pids(tmp_path, monkeypatch, state_overrides, expected_status):
    state = {
        "schema_version": "1.0",
        "state": "ready",
        "supervised": True,
        "host": "127.0.0.1",
        "port": 8767,
        "updated_at": runtime_status.utc_now(),
        "runtime_pid": 111,
        "supervisor_pid": 222,
        "launcher_pid": 333,
        "kit_pid": 444,
    }
    state.update(state_overrides)
    state_file = tmp_path / "runtime-state.json"
    state_file.write_text(json.dumps(state), encoding="utf-8")
    monkeypatch.setattr(runtime_status, "probe_runtime_health", lambda **_kwargs: {"responding": False})

    result = runtime_status.get_runtime_status(host="127.0.0.1", port=8767, state_file=state_file)

    assert result["identity_status"] == expected_status
    assert result["availability_code"] == "ISAAC_RUNTIME_UNAVAILABLE"
    assert result["identity_error"]
    for field in ("runtime_pid", "supervisor_pid", "launcher_pid", "kit_pid"):
        assert field not in result


def test_recent_kit_crash_is_available_when_runtime_socket_is_closed(tmp_path, monkeypatch):
    log_file = tmp_path / "kit_20260916_201711.log"
    log_file.write_text(
        "\n".join(
            [
                "2026-09-16T13:00:29Z [Error] [omni.physx.plugin] "
                "PhysX Internal CUDA error. Simulation cannot continue! Error code 700!",
                "2026-09-16T13:00:29Z [Error] [primdata.plugin] "
                "CUDA error 700: cudaErrorIllegalAddress token=do-not-return",
                "2026-09-16T13:00:31Z [Warning] [crash] A crash has occurred.",
                "2026-09-16T13:01:03Z [Warning] waiting for PID 61272 to exit",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("ISAAC_MCP_RUNTIME_LOG_FILE", str(log_file))
    monkeypatch.setattr(runtime_status, "probe_runtime_health", lambda **_kwargs: {"responding": False})

    result = runtime_status.get_runtime_status(state_file=tmp_path / "missing-state.json")

    assert result["state"] == "crashed"
    assert result["availability_code"] == "ISAAC_RUNTIME_CRASHED"
    assert result["diagnostics"]["primary_signature"] == "CUDA_ERROR_700"
    assert result["diagnostics"]["crash_detected"] is True
    assert "cudaErrorIllegalAddress" in result["diagnostics"]["signature_evidence"]["CUDA_ERROR_700"]
    assert result["diagnostics"]["log_path"] == str(log_file)
    serialized = json.dumps(result["diagnostics"])
    assert "do-not-return" not in serialized
    assert "[REDACTED]" in serialized


def test_non_crash_kit_error_does_not_claim_runtime_crashed(tmp_path, monkeypatch):
    log_file = tmp_path / "kit.log"
    log_file.write_text(
        "2026-09-16T13:00:00Z [Error] [extension] Optional extension was not found\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ISAAC_MCP_RUNTIME_LOG_FILE", str(log_file))
    monkeypatch.setattr(runtime_status, "probe_runtime_health", lambda **_kwargs: {"responding": False})

    result = runtime_status.get_runtime_status(state_file=tmp_path / "missing-state.json")

    assert result["state"] == "unmanaged"
    assert result["availability_code"] == "ISAAC_RUNTIME_UNAVAILABLE"
    assert result["diagnostics"]["crash_detected"] is False
    assert result["diagnostics"]["diagnostic_lines"]


def test_runtime_diagnostics_only_reads_bounded_log_tail(tmp_path, monkeypatch):
    log_file = tmp_path / "large-kit.log"
    log_file.write_bytes(b"x" * (runtime_status.MAX_LOG_SCAN_BYTES + 128) + b"\n[crash] A crash has occurred.\n")
    monkeypatch.setenv("ISAAC_MCP_RUNTIME_LOG_FILE", str(log_file))

    result = runtime_status.read_runtime_diagnostics()

    assert result["scanned_tail_bytes"] == runtime_status.MAX_LOG_SCAN_BYTES
    assert result["truncated"] is True
    assert result["crash_detected"] is True


def test_last_crash_recovers_diagnostics_from_previous_kit_session(tmp_path, monkeypatch):
    monkeypatch.delenv("ISAAC_MCP_RUNTIME_LOG_FILE", raising=False)
    monkeypatch.setattr(runtime_status.Path, "home", classmethod(lambda _cls: tmp_path))
    log_root = tmp_path / ".nvidia-omniverse" / "logs" / "Kit" / "Isaac-Sim Full" / "6.0"
    log_root.mkdir(parents=True)
    crashed_log = log_root / "kit_20260916_201711.log"
    crashed_log.write_text("[crash] A crash has occurred after CUDA error 700\n", encoding="utf-8")
    healthy_log = log_root / "kit_20260916_211041.log"
    healthy_log.write_text("runtime ready\n", encoding="utf-8")
    crashed_time = healthy_log.stat().st_mtime - 10
    os.utime(crashed_log, (crashed_time, crashed_time))
    state_file = tmp_path / "runtime-state.json"
    state_file.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "state": "ready",
                "supervised": True,
                "last_crash": {"exit_code": 3221225477},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime_status, "probe_runtime_health", lambda **_kwargs: {"responding": True})

    result = runtime_status.get_runtime_status(state_file=state_file)

    assert result["state"] == "ready"
    assert result["diagnostics"]["crash_detected"] is False
    assert result["last_crash"]["diagnostics"]["primary_signature"] == "CUDA_ERROR_700"
    assert result["last_crash"]["diagnostics"]["log_path"] == str(crashed_log)
