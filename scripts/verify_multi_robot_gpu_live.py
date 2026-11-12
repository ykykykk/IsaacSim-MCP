"""Guarded mixed Panda/Jetbot/Kaya GPU regression through a native MCP client."""

import asyncio
import base64
import json
import math
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from scripts.verify_camera_rgb_live import _decode_png

ROBOTS = {"frankapanda": "/World/MixedPanda", "jetbot": "/World/MixedJetbot", "kaya": "/World/MixedKaya"}
BASES = {"jetbot": "nvidia_jetbot_differential", "kaya": "nvidia_kaya_holonomic"}
CAMERA = "/World/MixedCamera"


async def main():
    root = Path(os.environ["ISAAC_MCP_VALIDATION_ROOT"]).resolve(strict=True)
    evidence = []
    server = StdioServerParameters(command=sys.executable, args=["-m", "isaac_mcp.server"], env=dict(os.environ))
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            async def call(name, args=None):
                response = await session.call_tool(name, args or {})
                value = json.loads(next(x.text for x in response.content if x.type == "text"))
                assert value["status"] == "success", (name, value)
                evidence.append({"tool": name, "response": value})
                return value["data"], response

            async def script(code):
                data, _ = await call("execute_script", {"code": code})
                return json.loads(data["stdout"].strip().splitlines()[-1])

            runtime, _ = await call("get_capabilities")
            runtime = runtime["runtime"]
            assert runtime["isaac_sim_version"].startswith("6.2.") and runtime["physics_backend"] == "physx"
            assert Path(runtime["log_file"]).parent == root
            assert Path(runtime["root_identifier"]).parent == root
            assert all(not provider["enabled"] for provider in runtime["provider_capabilities"].values())
            unexpected = await script("""
import json, omni.usd
print(json.dumps([str(p.GetPath()) for p in omni.usd.get_context().get_stage().TraverseAll()
 if str(p.GetPath()) != '/World' and not str(p.GetPath()).startswith(('/Render', '/OmniverseKit'))]))
""")
            assert not unexpected, unexpected
            try:
                await call("create_physics_scene")
                await call("transform_object", {"prim_path": "/World/groundPlane", "scale": [10, 10, 1]})
                params, _ = await call("set_physics_params", {"gpu_enabled": True, "time_step": 1 / 60})
                assert params["readback"]["usd"]["gpu_enabled"] is True, params
                assert params["readback"]["runtime"]["broadphase_type"] == "GPU", params
                for index, (robot, path) in enumerate(ROBOTS.items()):
                    await call("create_robot", {"robot_type": robot, "prim_path": path, "position": [index * 2, 0, 0]})
                    await call("get_robot_info", {"prim_path": path})
                    config, _ = await call("get_joint_config", {"prim_path": path})
                    assert all("actual_position" not in joint for joint in config["joints"]), config
                    lifecycle = await script("""
import json, omni.timeline
from isaacsim.core.simulation_manager import SimulationManager
print(json.dumps({'stopped': omni.timeline.get_timeline_interface().is_stopped(),
 'has_view': SimulationManager.get_physics_simulation_view() is not None}))
""")
                    assert lifecycle == {"stopped": True, "has_view": False}, lifecycle
                await call(
                    "create_light", {"prim_path": "/World/MixedLight", "intensity": 2500, "rotation": [315, 0, 0]}
                )
                await call("create_camera", {"prim_path": CAMERA, "position": [5, 5, 4], "resolution": [960, 640]})
                await script(f"""
import json, omni.usd
from pxr import Gf, UsdGeom
camera = UsdGeom.Xformable(omni.usd.get_context().get_stage().GetPrimAtPath({CAMERA!r}))
camera.MakeMatrixXform().Set(Gf.Matrix4d().SetLookAt(Gf.Vec3d(5, 5, 4), Gf.Vec3d(2, 0, 0.3), Gf.Vec3d(0, 0, 1)).GetInverse())
UsdGeom.Camera(camera.GetPrim()).GetFocalLengthAttr().Set(18.0)
print(json.dumps({{'camera_aimed': True}}))
""")
                await call("play_simulation")
                await call("pause_simulation")
                await call("step_simulation", {"num_steps": 60})

                async def snapshot(index):
                    poses = await script(f"""
import json, omni.usd
from pxr import Usd, UsdGeom, UsdPhysics
stage = omni.usd.get_context().get_stage()
result = {{}}
for key, path in {ROBOTS!r}.items():
 result[key] = {{str(p.GetPath()): list(UsdGeom.Xformable(p).ComputeLocalToWorldTransform(0).ExtractTranslation())
  for p in Usd.PrimRange(stage.GetPrimAtPath(path)) if p.HasAPI(UsdPhysics.RigidBodyAPI)}}
print(json.dumps(result))
""")
                    _, captured = await call(
                        "capture_camera_output", {"prim_path": CAMERA, "output_type": "rgb", "return_mode": "image"}
                    )
                    png = base64.b64decode(next(x.data for x in captured.content if x.type == "image"))
                    (root / f"mixed-frame-{index}.png").write_bytes(png)
                    return poses, png

                before, image_before = await snapshot(0)
                await call("play_simulation")
                await call(
                    "set_joint_command",
                    {
                        "prim_path": ROBOTS["frankapanda"],
                        "mode": "position",
                        "joint_names": ["panda_joint1"],
                        "values": [0.7],
                    },
                )
                commands = {}
                for robot, profile in BASES.items():
                    commands[robot], _ = await call(
                        "set_mobile_base_velocity",
                        {
                            "prim_path": ROBOTS[robot],
                            "profile": profile,
                            "forward_mps": 0.1,
                            "lateral_mps": 0.05 if robot == "kaya" else 0.0,
                            "yaw_radps": 0.1,
                        },
                    )
                await call("pause_simulation")
                await call("step_simulation", {"num_steps": 120, "observe_joints": list(ROBOTS.values())})
                panda, _ = await call(
                    "get_joint_state", {"prim_path": ROBOTS["frankapanda"], "joint_names": ["panda_joint1"]}
                )
                assert abs(panda["joints"][0]["position"] - 0.7) < 0.02, panda
                for robot, command in commands.items():
                    state, _ = await call(
                        "get_joint_state", {"prim_path": ROBOTS[robot], "joint_names": command["joint_names"]}
                    )
                    assert all(math.isfinite(j["velocity"]) for j in state["joints"]), state
                    assert any(abs(j["velocity"]) > 0.1 for j in state["joints"]), state
                after, image_after = await snapshot(1)
                displacements = {}
                for robot in BASES:
                    assert before[robot].keys() == after[robot].keys() and before[robot], robot
                    vectors = [
                        [after[robot][path][i] - value[i] for i in range(2)] for path, value in before[robot].items()
                    ]
                    distance = math.hypot(*(sum(v[i] for v in vectors) / len(vectors) for i in range(2)))
                    assert 0.02 < distance < 1.0, (robot, distance)
                    displacements[robot] = distance
                    await call("stop_mobile_base", {"prim_path": ROBOTS[robot], "profile": BASES[robot]})
                    state, _ = await call(
                        "get_joint_state", {"prim_path": ROBOTS[robot], "joint_names": commands[robot]["joint_names"]}
                    )
                    assert all(abs(j["targets"]["velocity"]) < 1e-8 for j in state["joints"]), state
                await call("step_simulation", {"num_steps": 120})
                for robot in BASES:
                    state, _ = await call(
                        "get_joint_state", {"prim_path": ROBOTS[robot], "joint_names": commands[robot]["joint_names"]}
                    )
                    assert all(abs(j["velocity"]) < 0.1 for j in state["joints"]), state
                pixels = [_decode_png(png)[3] for png in (image_before, image_after)]
                changed = sum(abs(a - b) > 15 for a, b in zip(*pixels)) / len(pixels[0])
                assert changed > 0.001, changed
                report = {
                    "pass": True,
                    "gpu_enabled": True,
                    "mobile_displacement_m": displacements,
                    "panda_joint1_rad": panda["joints"][0]["position"],
                    "changed_pixels": changed,
                    "poses_before": before,
                    "poses_after": after,
                }
            finally:
                await call("stop_simulation")
                await call("clear_scene")
                (root / "mixed-gpu-evidence.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
            (root / "mixed-gpu-result.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(json.dumps(report))


if __name__ == "__main__":
    asyncio.run(main())
