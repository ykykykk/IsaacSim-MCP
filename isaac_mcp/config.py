"""One configuration contract for CLI launchers and the MCP process."""

import argparse
import json
import os
from pathlib import Path

KEYS = {"host": "ISAAC_MCP_HOST", "port": "ISAAC_MCP_PORT", "isaac_root": "ISAACSIM_ROOT",
        "tool_profile": "ISAAC_MCP_TOOL_PROFILE", "tool_domains": "ISAAC_MCP_TOOL_DOMAINS"}
DEFAULTS = {"host": "127.0.0.1", "port": 8766, "isaac_root": None,
            "tool_profile": "legacy", "tool_domains": "all"}


def resolve(**overrides):
    path = Path(os.getenv("ISAAC_MCP_CONFIG", str(Path(__file__).resolve().parents[1] / "config.local.json")))
    values = dict(DEFAULTS)
    sources = {key: "default" for key in values}
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict) or data.keys() - KEYS.keys():
            raise ValueError("Unknown keys in MCP config; expected " + ", ".join(KEYS))
        values.update(data)
        sources.update({key: str(path) for key in data})
    elif os.getenv("ISAAC_MCP_CONFIG"):
        raise FileNotFoundError(path)
    for key, env in KEYS.items():
        if env in os.environ:
            values[key], sources[key] = os.environ[env], "environment"
        if overrides.get(key) is not None:
            values[key], sources[key] = overrides[key], "argument"
    if isinstance(values["port"], bool):
        raise ValueError("port must be an integer")
    values["port"] = int(values["port"])
    if not 1 <= values["port"] <= 65535:
        raise ValueError("port must be 1..65535")
    if not values["host"]:
        raise ValueError("host must not be empty")
    return {**values, "sources": sources}


def apply_environment():
    effective = resolve()
    for key, env in KEYS.items():
        if effective[key] is not None:
            os.environ[env] = str(effective[key])
    return effective


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int)
    parser.add_argument("--host")
    parser.add_argument("--isaac-root")
    args = parser.parse_args()
    print(json.dumps(resolve(**vars(args))))
