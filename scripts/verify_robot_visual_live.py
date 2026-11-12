"""Single-Panda legacy joint controls with two native MCP images and read-back."""

import asyncio
import base64
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from scripts.verify_camera_rgb_live import _decode_png


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
                return value, response

            cap, _ = await call("get_capabilities")
            assert Path(cap["data"]["runtime"]["log_file"]).parent == root
            assert Path(cap["data"]["runtime"]["root_identifier"]).parent == root
            await call("load_environment", {"environment": "grid"})
            await call("create_physics_scene")
            await call("spawn_nvidia_asset", {"asset_key": "frankapanda", "prim_path": "/World/VisualPanda"})
            await call("create_light", {"prim_path": "/World/VisualLight", "intensity": 2500, "rotation": [315, 0, 0]})
            await call("create_camera", {"prim_path": "/World/VisualCamera", "position": [2, 2, 1.7], "rotation": [65, 0, 135], "resolution": [640, 480]})
            states = []
            images = []
            for index, target in enumerate((0.0, 0.7)):
                await call("set_joint_positions", {"prim_path": "/World/VisualPanda", "joint_positions": [target, -0.57, 0, -2.81, 0, 3.037, 0.741, 0.04, 0.04]})
                await call("step_simulation", {"num_steps": 120, "observe_joints": ["/World/VisualPanda"]})
                state, _ = await call("get_joint_positions", {"prim_path": "/World/VisualPanda"})
                states.append(state["data"])
                _, image_result = await call("capture_camera_output", {"prim_path": "/World/VisualCamera", "output_type": "rgb", "return_mode": "image"})
                image = next(x for x in image_result.content if x.type == "image")
                png = base64.b64decode(image.data)
                (root / f"robot-frame-{index}.png").write_bytes(png)
                images.append(png)
            assert states[0] != states[1], states
            assert abs(states[1]["joint_positions"][0] - 0.7) < 0.02, states
            pixels = [_decode_png(png)[3] for png in images]
            changed = sum(abs(a - b) > 15 for a, b in zip(*pixels)) / len(pixels[0])
            assert changed > 0.05, f"Camera pose did not follow joint motion: changed fraction {changed}"
            await call("stop_simulation")
            await call("delete_sensor", {"prim_path": "/World/VisualCamera"})
            await call("clear_scene")
    (root / "robot-visual-evidence.json").write_text(json.dumps(evidence, indent=2))
    print(json.dumps({"pass": True, "joint_states": states, "images": ["robot-frame-0.png", "robot-frame-1.png"]}))


if __name__ == "__main__":
    asyncio.run(main())
