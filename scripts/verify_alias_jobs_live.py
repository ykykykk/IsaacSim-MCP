"""Consolidated gripper/mobile/motion/SDG/managed-job integration acceptance."""

import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main():
    root = Path(os.environ["ISAAC_MCP_VALIDATION_ROOT"]).resolve(strict=True)
    evidence = []
    server = StdioServerParameters(command=sys.executable, args=["-m", "isaac_mcp.server"], env=dict(os.environ, ISAAC_MCP_TOOL_PROFILE="consolidated"))
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as s:
            await s.initialize()
            names = {t.name for t in (await s.list_tools()).tools}
            assert "control_gripper" in names and "open_gripper" not in names

            async def call(name, args=None):
                response = await s.call_tool(name, args or {})
                value = json.loads(next(x.text for x in response.content if x.type == "text"))
                assert value["status"] in {"success", "cancelled"}, (name, value)
                evidence.append({"tool": name, "response": value})
                return value["data"]

            cap = (await call("get_capabilities"))["runtime"]
            assert Path(cap["log_file"]).parent == root
            assert Path(cap["root_identifier"]).parent == root
            await call("create_physics_scene")
            await call("create_robot", {"robot_type": "frankapanda", "prim_path": "/World/AliasPanda"})
            await call("control_timeline", {"action": "play"})
            await call("control_timeline", {"action": "pause"})
            for action in ("open", "set_width", "close"):
                await call("control_gripper", {"action": action, "prim_path": "/World/AliasPanda", "profile": "franka_parallel_gripper", "width_m": 0.03})
            home = [0, -0.57, 0, -2.81, 0, 3.037, 0.741]
            plan = await call("plan_joint_trajectory", {"prim_path": "/World/AliasPanda", "start_joint_positions": home, "goal_joint_positions": [0.05, *home[1:]], "planner": "cspace"})
            motion = await call("execute_trajectory", {"trajectory_id": plan["trajectory_id"]})
            await call("motion_job", {"action": "get", "job_id": motion["job_id"]})
            cancelled = await call("motion_job", {"action": "cancel", "job_id": motion["job_id"]})
            assert cancelled["state"] == "cancelled", cancelled
            await call("control_timeline", {"action": "stop"})
            await call("clear_scene")
            await call("create_physics_scene")
            await call("create_robot", {"robot_type": "jetbot", "prim_path": "/World/AliasJetbot"})
            await call("control_timeline", {"action": "play"})
            await call("control_mobile_base_velocity", {"action": "set", "prim_path": "/World/AliasJetbot", "profile": "nvidia_jetbot_differential", "forward_mps": 0.1})
            stopped = await call("control_mobile_base_velocity", {"action": "stop", "prim_path": "/World/AliasJetbot", "profile": "nvidia_jetbot_differential"})
            assert stopped["stopped"]
            await call("control_timeline", {"action": "stop"})
            await call("clear_scene")
            await call("create_camera", {"prim_path": "/World/AliasCamera", "resolution": [64, 48]})
            job = await call("create_sdg_job", {"camera_prim_path": "/World/AliasCamera", "frame_count": 1, "annotations": ["rgb"], "preview": False})
            await call("sdg_job_control", {"action": "get", "job_id": job["job_id"]})
            await call("sdg_job_control", {"action": "cancel", "job_id": job["job_id"], "preview": False})
            await call("delete_sdg_job", {"job_id": job["job_id"], "delete_artifacts": True, "preview": False})
            fixture = root / "alias-asset.usda"
            fixture.write_text('#usda 1.0\n(defaultPrim="Asset")\ndef Xform "Asset" {}\n')
            job = await call("start_job", {"command_type": "assets.load_usd", "params": {"usd_url": str(fixture), "prim_path": "/World/AliasAsset"}})
            await call("job_control", {"action": "get", "job_id": job["job_id"]})
            await call("job_control", {"action": "cancel", "job_id": job["job_id"]})
            await call("delete_sensor", {"prim_path": "/World/AliasCamera"})
            await call("clear_scene")
    (root / "alias-jobs-evidence.json").write_text(json.dumps(evidence, indent=2))
    print(json.dumps({"pass": True, "profile": "consolidated", "tool_count": len(names)}))


if __name__ == "__main__":
    asyncio.run(main())
