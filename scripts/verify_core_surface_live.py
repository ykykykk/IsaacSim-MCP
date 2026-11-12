"""Supplemental 6.2 MCP acceptance on an explicitly isolated scratch host."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main() -> None:
    root = Path(os.environ["ISAAC_MCP_VALIDATION_ROOT"]).resolve(strict=True)
    evidence = {}
    server = StdioServerParameters(command=sys.executable, args=["-m", "isaac_mcp.server"], env=dict(os.environ))
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            async def call(name, args=None, *, success=True):
                result = await session.call_tool(name, args or {})
                value = json.loads(next(x.text for x in result.content if x.type == "text"))
                evidence[name] = value
                if success:
                    assert value["status"] == "success", (name, value)
                return value

            runtime = (await call("get_capabilities"))["data"]["runtime"]
            assert Path(runtime["log_file"]).resolve().parent == root
            assert all(not p["enabled"] for p in runtime["provider_capabilities"].values())
            assert Path(runtime["root_identifier"]).resolve().parent == root
            assert runtime["isaac_sim_version"].startswith("6.2.")
            await call("get_runtime_status")
            await call("get_script_policy")
            await call("list_jobs")
            await call("create_object", {"object_type": "Cube", "prim_path": "/World/CoreCube", "position": [0, 0, 2]})
            await call("clone_object", {"source_path": "/World/CoreCube", "target_path": "/World/CoreClone", "position": [2, 0, 2]})
            clone = (await call("get_prim_info", {"prim_path": "/World/CoreClone"}))["data"]
            assert clone["type"] == "Cube" and clone["transform"]["position"] == [2, 0, 2], clone
            await call("create_material", {"prim_path": "/World/CoreMaterial", "color": [0.8, 0.2, 0.1]})
            await call("get_material", {"material_path": "/World/CoreMaterial"})
            await call("apply_material", {"material_path": "/World/CoreMaterial", "target_prim_path": "/World/CoreCube"})
            await call("get_material_binding", {"target_prim_path": "/World/CoreCube", "material_purpose": "visual"})
            await call("create_light", {"prim_path": "/World/CoreLight", "intensity": 1000})
            await call("modify_light", {"prim_path": "/World/CoreLight", "intensity": 2000})
            intensity = (await call("get_typed_attribute", {"prim_path": "/World/CoreLight", "attribute": "inputs:intensity"}))["data"]
            assert intensity["value"] == 2000, intensity
            await call("set_semantic_labels", {"prim_path": "/World/CoreCube", "taxonomy": "class", "labels": ["cube"], "preview": False})
            labels = await call("get_semantic_labels", {"prim_path": "/World/CoreCube"})
            assert "cube" in json.dumps(labels)
            await call("create_physics_scene")
            await call("get_physics_params")
            await call("get_physics_state", {"prim_path": "/World/CoreCube"})
            await call("create_action_graph", {"graph_path": "/World/CoreGraph", "nodes": [{"path": "Script", "type": "omni.graph.scriptnode.ScriptNode"}]})
            code = "def compute(db):\n    return True"
            await call("edit_action_graph", {"graph_path": "/World/CoreGraph", "values": [{"attr": "Script.inputs:script", "value": code}]})
            graph = await call("get_action_graph", {"graph_path": "/World/CoreGraph", "include_values": True, "include_script_source": True})
            assert code in json.dumps(graph).replace("\\n", "\n"), graph
            fixture = root / "core-asset.usda"
            fixture.write_text('#usda 1.0\n(defaultPrim="Asset")\ndef Xform "Asset" {\n def Cube "Cube" {}\n}\n')
            await call("load_usd", {"usd_url": str(fixture), "prim_path": "/World/CoreAsset"})
            asset = (await call("get_prim_info", {"prim_path": "/World/CoreAsset/Cube"}))["data"]
            assert asset["type"] == "Cube"
            bad = root / "core-invalid.usda"
            bad.write_text("not a USD file")
            rejected = await call("load_usd", {"usd_url": str(bad), "prim_path": "/World/InvalidAsset"}, success=False)
            assert rejected["status"] == "error", rejected
            absent = await call("get_prim_info", {"prim_path": "/World/InvalidAsset"}, success=False)
            assert absent["status"] == "error", absent
            await call("list_available_robots")
            await call("refresh_robot_library")
            catalog = await call("list_nvidia_assets", {"query": "franka", "max_results": 10})
            assert catalog["data"], catalog
            await call("list_environments")
            urdf = root / "core-robot.urdf"
            urdf.write_text('<robot name="mcp_core"><link name="base"><inertial><mass value="1"/><inertia ixx="0.1" ixy="0" ixz="0" iyy="0.1" iyz="0" izz="0.1"/></inertial><visual><geometry><box size="1 1 1"/></geometry></visual><collision><geometry><box size="1 1 1"/></geometry></collision></link></robot>')
            await call("import_urdf", {"urdf_path": str(urdf), "prim_path": "/World/CoreURDF"})
            await call("get_prim_info", {"prim_path": "/World/CoreURDF"})
            await call("clear_scene")
            absent = await call("get_prim_info", {"prim_path": "/World/CoreCube"}, success=False)
            assert absent["status"] == "error"
    (root / "core-surface-evidence.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(json.dumps({"pass": True, "tools": sorted(evidence)}))


if __name__ == "__main__":
    asyncio.run(main())
