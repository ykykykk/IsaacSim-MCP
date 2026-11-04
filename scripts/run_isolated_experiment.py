"""Run one future isolated experiment through :mod:`isaac_mcp.experiment_dispatcher`."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from isaac_mcp.connection import IsaacConnection
from isaac_mcp.experiment_dispatcher import ExperimentDispatcher, owned_output_root, owned_runtime_status_reader


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fail-closed isolated Isaac experiment dispatcher")
    parser.add_argument("--spec", type=Path, required=True, help="strict UTF-8 JSON experiment specification")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8767)
    parser.add_argument("--runtime-state-file", type=Path, help="owned supervisor state for this exact host/port")
    args = parser.parse_args(argv)
    try:
        spec = json.loads(args.spec.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "error", "code": "SPEC_READ_FAILED", "message": str(exc)}))
        return 2
    def runtime_status_reader():
        if args.runtime_state_file is None:
            return {"port": args.port, "identity_status": "unknown: no owned runtime state file supplied"}
        return owned_runtime_status_reader(
            host=args.host,
            port=args.port,
            state_file=args.runtime_state_file,
        )()

    result = ExperimentDispatcher(
        IsaacConnection(host=args.host, port=args.port),
        owned_output_root(),
        runtime_status_reader=runtime_status_reader,
    ).run(spec)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "application_accepted" else 2


if __name__ == "__main__":
    raise SystemExit(main())
