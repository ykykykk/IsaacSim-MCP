"""Independent Panda and Jetbot controller tests; no mixed/Kaya GPU fixture."""

import json
import os
from pathlib import Path

from isaac_mcp.connection import IsaacConnection


def main():
    root = Path(os.environ["ISAAC_MCP_VALIDATION_ROOT"]).resolve(strict=True)
    c = IsaacConnection()
    evidence = []

    def call(name, args=None):
        result = c.send_command(name, args or {})
        assert result["status"] == "success", (name, result)
        evidence.append({"command": name, "response": result})
        return result["data"]

    runtime = call("system.get_capabilities")["runtime"]
    assert Path(runtime["log_file"]).parent == root
    assert Path(runtime["root_identifier"]).parent == root
    call("controllers.list_profiles")
    call("scene.create_physics")
    path = "/World/SingletonPanda"
    call("robots.create", {"robot_type": "frankapanda", "prim_path": path})
    call("simulation.play")
    call("simulation.pause")
    params = {"prim_path": path, "profile": "franka_parallel_gripper"}
    for command, extra, expected in [
        ("controllers.open_gripper", {}, 0.04),
        ("controllers.set_gripper_width", {"width_m": 0.03}, 0.015),
        ("controllers.close_gripper", {}, 0.0),
    ]:
        result = call(command, {**params, **extra})
        assert all(abs(value - expected) < 1e-6 for value in result["finger_targets_m"]), result
        call("simulation.step", {"num_steps": 60})
        state = call("robots.get_joint_state", {"prim_path": path, "joint_names": ["panda_finger_joint1", "panda_finger_joint2"]})
        assert all(abs(j["position"] - expected) < 0.005 for j in state["joints"]), state
    call("simulation.stop")
    call("scene.clear")
    call("scene.create_physics")
    path = "/World/SingletonJetbot"
    call("robots.create", {"robot_type": "jetbot", "prim_path": path})
    call("simulation.play")
    params = {"prim_path": path, "profile": "nvidia_jetbot_differential"}
    move = call("controllers.set_mobile_base_velocity", {**params, "forward_mps": 0.1, "yaw_radps": 0.1})
    call("simulation.pause")
    call("simulation.step", {"num_steps": 60})
    state = call("robots.get_joint_state", {"prim_path": path, "joint_names": move["joint_names"]})
    assert any(abs(j["velocity"]) > 0.01 for j in state["joints"]), state
    call("controllers.stop_mobile_base", params)
    state = call("robots.get_joint_state", {"prim_path": path, "joint_names": move["joint_names"]})
    assert all(abs(j["targets"]["velocity"]) < 1e-8 for j in state["joints"]), state
    call("simulation.stop")
    call("scene.clear")
    c.disconnect()
    (root / "controller-singletons-evidence.json").write_text(json.dumps(evidence, indent=2))
    print(json.dumps({"pass": True, "profiles": ["franka_parallel_gripper", "nvidia_jetbot_differential"]}))


if __name__ == "__main__":
    main()
