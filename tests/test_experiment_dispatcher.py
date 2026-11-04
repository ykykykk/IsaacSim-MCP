"""Offline contracts for the one-shot isolated experiment dispatcher."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from isaac_mcp.experiment_dispatcher import ExperimentDispatcher, owned_runtime_status_reader


class FakeConnection:
    def __init__(self, *, metadata=None, result=None, dispatch_error: Exception | None = None):
        self.metadata = metadata or {"default_prim": "/World", "up_axis": "Z", "meters_per_unit": 1.0}
        self.result = result or {"status": "success", "code": "OK"}
        self.dispatch_error = dispatch_error
        self.calls: list[tuple[str, object, dict[str, object]]] = []

    def send_command(self, command: str, params=None, **kwargs):
        self.calls.append((command, params, kwargs))
        if command == "system.get_capabilities":
            return {"status": "success", "data": {"extension": {"command_names": ["simulation.execute_script"]}}}
        if command == "scene.get_info":
            return {"status": "success", "data": {"stage_path": r"C:\scratch\run.usda"}}
        if command == "simulation.get_state":
            return {"status": "success", "data": {"timeline_state": "stopped", "current_time": 0.0}}
        if command == "scene.get_prim_info":
            return {"status": "error", "code": "PRIM_NOT_FOUND", "message": f"Prim not found: {params['prim_path']}"}
        if command == "stage.get_composition":
            return {
                "status": "success",
                "data": {
                    "root_layer": {"identifier": r"C:\scratch\run.usda"},
                    "layer_stack": [{"identifier": "anon:session"}],
                    "prim_paths": ["/World"],
                    "metadata": self.metadata,
                },
            }
        if command == "simulation.execute_script":
            if self.dispatch_error:
                raise self.dispatch_error
            return {**self.result, "command_id": self.result.get("command_id", kwargs["command_id"])}
        raise AssertionError(command)


def _spec(source: Path, *, hash_value: str | None = None) -> dict:
    return {
        "run_id": "a" * 32,
        "source_path": str(source),
        "frozen_sha256": hash_value or hashlib.sha256(source.read_bytes()).hexdigest(),
        "allow_commands": ["simulation.execute_script"],
        "dispatch": {"command": "simulation.execute_script", "params": {"timeout_s": 1}},
        "expected_result": {"status": "success", "code": "OK"},
        "preflight": {
            "expected_stage_path": r"C:\scratch\run.usda",
            "scratch_root": r"C:\scratch",
            "root_layer": r"C:\scratch\run.usda",
            "session_layer": "anon:session",
            "paths": ["/World"],
            "metadata": {"default_prim": "/World", "up_axis": "Z", "meters_per_unit": 1.0},
            "time_seconds": 0,
            "time_tolerance": 0,
        },
    }


def _trace(result: dict) -> dict:
    return json.loads(Path(result["trace_path"]).read_text(encoding="utf-8"))


def test_dispatcher_preserves_chinese_crlf_source_bytes_and_records_transport_windows(tmp_path: Path):
    source = tmp_path / "實驗.py"
    raw = "# 中文\r\nprint('保留')\r\n".encode("utf-8")
    source.write_bytes(raw)
    connection = FakeConnection()

    result = ExperimentDispatcher(connection, tmp_path / "owned", runtime_status_reader=lambda: {}).run(_spec(source))

    assert result["status"] == "application_accepted"
    forwarded = [call for call in connection.calls if call[0] == "simulation.execute_script"]
    assert len(forwarded) == 1
    assert forwarded[0][1]["code"].encode("utf-8") == raw
    trace = _trace(result)
    assert trace["source"]["sha256"] == hashlib.sha256(raw).hexdigest()
    assert trace["started_at"].endswith("Z") and "." in trace["started_at"]
    assert trace["ended_at"].endswith("Z") and trace["elapsed_ms"] >= 0
    assert all("started_at" in event and "ended_at" in event for event in trace["events"] if event["event"] == "transport_call")


def test_dispatcher_rejects_hash_mismatch_before_any_runtime_call(tmp_path: Path):
    source = tmp_path / "source.py"
    source.write_text("print('changed')\n", encoding="utf-8")
    connection = FakeConnection()

    result = ExperimentDispatcher(connection, tmp_path / "owned", runtime_status_reader=lambda: {}).run(
        _spec(source, hash_value="0" * 64)
    )

    assert result["status"] == "rejected"
    assert result["code"] == "FROZEN_SOURCE_HASH_MISMATCH"
    assert connection.calls == []
    assert _trace(result)["events"][-1]["event"] == "rejection"


def test_dispatcher_rejects_missing_guard_evidence_without_forwarding(tmp_path: Path):
    source = tmp_path / "source.py"
    source.write_text("print('ok')\n", encoding="utf-8")
    connection = FakeConnection(metadata={"default_prim": "/World"})

    result = ExperimentDispatcher(connection, tmp_path / "owned", runtime_status_reader=lambda: {}).run(_spec(source))

    assert result["status"] == "rejected"
    assert result["code"] == "PREFLIGHT_MISMATCH"
    assert not [call for call in connection.calls if call[0] == "simulation.execute_script"]
    observed = _trace(result)["events"][-1]["observed"]
    assert "metadata" in observed["mismatches"]


def test_dispatcher_records_dispatch_exception_and_does_not_report_success(tmp_path: Path):
    source = tmp_path / "source.py"
    source.write_text("print('ok')\n", encoding="utf-8")
    connection = FakeConnection(dispatch_error=RuntimeError("socket closed after send"))

    result = ExperimentDispatcher(connection, tmp_path / "owned", runtime_status_reader=lambda: {}).run(_spec(source))

    assert result["status"] == "error"
    assert result["code"] == "DISPATCH_EXCEPTION"
    trace = _trace(result)
    assert trace["ended_at"].endswith("Z")
    assert trace["events"][-1]["event"] == "error"
    assert any(event["event"] == "transport_call" and event["raw_result"] is None for event in trace["events"])


def test_dispatcher_rejects_requested_kit_pid_and_reused_run_id(tmp_path: Path):
    source = tmp_path / "source.py"
    source.write_text("print('ok')\n", encoding="utf-8")
    spec = _spec(source)
    spec["preflight"]["kit_pid"] = 123
    connection = FakeConnection()
    dispatcher = ExperimentDispatcher(connection, tmp_path / "owned", runtime_status_reader=lambda: {})

    rejected = dispatcher.run(spec)
    assert rejected["code"] == "KIT_PID_IDENTITY_UNAVAILABLE"
    spec["preflight"].pop("kit_pid")
    spec["run_id"] = "b" * 32
    accepted = dispatcher.run(spec)
    reused = dispatcher.run(spec)
    assert accepted["status"] == "application_accepted"
    assert reused["code"] == "RUN_ID_ALREADY_EXISTS"


def test_dispatcher_refuses_pid_provenance_from_a_different_port(tmp_path: Path):
    source = tmp_path / "source.py"
    source.write_text("print('ok')\n", encoding="utf-8")
    connection = FakeConnection()
    connection.port = 8767
    result = ExperimentDispatcher(
        connection,
        tmp_path / "owned",
        runtime_status_reader=lambda: {"port": 8766, "launcher_pid": 1, "runtime_pid": 1},
    ).run(_spec(source))

    identity = _trace(result)["preflight"]["identity"]
    assert result["status"] == "application_accepted"
    assert identity["launcher_pid"] is None
    assert "does not match" in identity["launcher_pid_provenance"]


def test_owned_state_reader_rejects_real_wrong_port_state_before_status_normalizes_it(tmp_path: Path):
    state = tmp_path / "runtime-state.json"
    state.write_text(json.dumps({"schema_version": "1.0", "port": 8766, "launcher_pid": 99}), encoding="utf-8")

    result = owned_runtime_status_reader(host="127.0.0.1", port=8767, state_file=state)()

    assert result["port"] == 8766
    assert "does not match" in result["identity_error"]


def test_dispatcher_rejects_command_id_or_status_oracle_bypasses_before_forwarding(tmp_path: Path):
    source = tmp_path / "source.py"
    source.write_text("print('ok')\n", encoding="utf-8")
    conflicting = _spec(source)
    conflicting["expected_result"]["command_id"] = "other"
    connection = FakeConnection()
    result = ExperimentDispatcher(connection, tmp_path / "owned-a", runtime_status_reader=lambda: {}).run(conflicting)
    assert result["code"] == "EXPECTED_COMMAND_ID_CONFLICT"
    assert not [call for call in connection.calls if call[0] == "simulation.execute_script"]

    missing_status = _spec(source)
    missing_status["run_id"] = "c" * 32
    missing_status["expected_result"] = {"code": "OK"}
    result = ExperimentDispatcher(connection, tmp_path / "owned-b", runtime_status_reader=lambda: {}).run(missing_status)
    assert result["code"] == "DISPATCH_CONFIG_INVALID"
    assert not [call for call in connection.calls if call[0] == "simulation.execute_script"]


def test_dispatcher_rejects_downstream_command_id_mismatch_as_application_result(tmp_path: Path):
    source = tmp_path / "source.py"
    source.write_text("print('ok')\n", encoding="utf-8")
    connection = FakeConnection(result={"status": "success", "code": "OK", "command_id": "downstream"})

    result = ExperimentDispatcher(connection, tmp_path / "owned", runtime_status_reader=lambda: {}).run(_spec(source))

    assert result["status"] == "application_rejected"
    assert "command_id" in _trace(result)["application"]["mismatches"]


def test_cli_invokes_dispatcher_and_returns_nonzero_before_connection_on_bad_hash(tmp_path: Path):
    source = tmp_path / "source.py"
    source.write_text("print('no forward')\n", encoding="utf-8")
    spec = _spec(source, hash_value="0" * 64)
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    environment = {**os.environ, "ISAAC_MCP_EXPERIMENT_OUTPUT_ROOT": str(tmp_path / "owned")}

    completed = subprocess.run(
        [sys.executable, "scripts/run_isolated_experiment.py", "--spec", str(spec_path)],
        cwd=Path(__file__).parents[1],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 2
    assert json.loads(completed.stdout)["code"] == "FROZEN_SOURCE_HASH_MISMATCH"
