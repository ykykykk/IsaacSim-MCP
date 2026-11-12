"""Consolidated-profile integration and optional-provider boundaries on a scratch host."""

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
    env = dict(os.environ, ISAAC_MCP_TOOL_PROFILE="full")
    server = StdioServerParameters(command=sys.executable, args=["-m", "isaac_mcp.server"], env=env)
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as s:
            await s.initialize()

            async def call(name, args=None, success=True):
                response = await s.call_tool(name, args or {})
                value = json.loads(next(x.text for x in response.content if x.type == "text"))
                evidence.append({"tool": name, "response": value})
                if success:
                    assert value["status"] in {"success", "cancelled"}, (name, value)
                return value

            cap = (await call("get_capabilities"))["data"]["runtime"]
            assert Path(cap["log_file"]).parent == root
            assert Path(cap["root_identifier"]).parent == root
            assert all(not p["enabled"] for p in cap["provider_capabilities"].values())
            await call("control_timeline", {"action": "stop"})
            await call("create_object", {"object_type": "Cube", "prim_path": "/World/ProfileCube"})
            await call("query_prim", {"action": "get", "prim_path": "/World/ProfileCube"})
            await call("query_prim", {"action": "list", "root_path": "/World"})
            await call("typed_attribute", {"action": "set", "prim_path": "/World/ProfileCube", "attribute": "mcp:checked", "type_name": "int", "value": 17, "preview": False})
            assert (await call("typed_attribute", {"action": "get", "prim_path": "/World/ProfileCube", "attribute": "mcp:checked"}))["data"]["value"] == 17
            await call("semantic_labels", {"action": "set", "prim_path": "/World/ProfileCube", "taxonomy": "class", "labels": ["cube"], "preview": False})
            await call("semantic_labels", {"action": "get", "prim_path": "/World/ProfileCube"})
            await call("physics_body_config", {"action": "configure", "prim_path": "/World/ProfileCube", "body_type": "dynamic", "mass_kg": 1})
            await call("physics_body_config", {"action": "get", "prim_path": "/World/ProfileCube"})
            await call("collision_group", {"action": "create", "group_path": "/World/ProfileGroup", "collider_paths": ["/World/ProfileCube"]})
            await call("collision_group", {"action": "get", "group_path": "/World/ProfileGroup"})
            await call("get_collision_group", {"group_path": "/World/ProfileGroup"})
            await call("physics_joint", {"action": "create", "joint_path": "/World/ProfileJoint", "joint_type": "fixed", "body1": "/World/ProfileCube"})
            await call("physics_joint", {"action": "get", "joint_path": "/World/ProfileJoint"})
            await call("get_physics_joint", {"joint_path": "/World/ProfileJoint"})
            await call("material_definition", {"action": "create", "prim_path": "/World/ProfileMat"})
            await call("material_definition", {"action": "get", "material_path": "/World/ProfileMat"})
            await call("material_binding", {"action": "apply", "target_prim_path": "/World/ProfileCube", "material_path": "/World/ProfileMat"})
            await call("material_binding", {"action": "get", "target_prim_path": "/World/ProfileCube", "material_purpose": "visual"})
            await call("light_config", {"action": "create", "prim_path": "/World/ProfileLight"})
            await call("light_config", {"action": "modify", "prim_path": "/World/ProfileLight", "intensity": 1700})
            await call("robot_library", {"action": "list"})
            await call("robot_library", {"action": "refresh"})
            await call("create_action_graph", {"graph_path": "/World/ProfileGraph", "nodes": [{"path": "Tick", "type": "omni.graph.action.OnTick"}, {"path": "ScriptNode", "type": "omni.graph.scriptnode.ScriptNode"}]})
            await call("query_action_graph", {"action": "list"})
            await call("query_action_graph", {"action": "get", "graph_path": "/World/ProfileGraph"})
            for action in ("connect", "disconnect"):
                await call("action_graph_connection", {"action": action, "graph_path": "/World/ProfileGraph", "source_attr": "Tick.outputs:tick", "target_attr": "ScriptNode.inputs:execIn", "preview": False})
            await call("script_node_source", {"action": "configure", "graph_path": "/World/ProfileGraph", "inline_script": "def compute(db):\n    return True", "preview": False})
            await call("script_node_source", {"action": "reload", "graph_path": "/World/ProfileGraph", "preview": False})
            await call("query_human", {"action": "list"})
            await call("list_humans")
            await call("get_navmesh_status", success=False)
            await call("get_ros2_status")
            await call("list_ros2_workflows")
            ros = await call("create_ros2_publisher", {"publisher_type": "clock", "preview": False}, success=False)
            assert ros["status"] != "success", ros
            for name, args in [
                ("get_mpm_status", {}), ("list_mpm_configs", {}),
                ("get_mpm_config", {"expected_stage": cap["root_identifier"], "prim_path": "/World/ProfileCube"}),
                ("update_mpm_config", {"expected_stage": cap["root_identifier"], "prim_path": "/World/ProfileCube", "expected_config_sha256": "missing", "changes": {"foo": 1}}),
                ("request_mpm_rebuild", {"expected_stage": cap["root_identifier"], "prim_path": "/World/ProfileCube", "expected_config_sha256": "missing"}),
            ]:
                result = await call(name, args, success=False)
                assert result["status"] == "error" and result["code"] == "MPM_EXTENSION_DISABLED", result
            after = (await call("get_capabilities"))["data"]["runtime"]
            assert after["provider_capabilities"] == cap["provider_capabilities"]
            composition = (await call("get_stage_composition"))["data"]
            for name, args in [
                ("preview_source_commit", {"expected_context": composition["context"], "prim_path": "/World/ProfileCube", "attributes": ["mcp:checked"]}),
                ("commit_source_changes", {"plan_id": "no-provider-plan"}),
            ]:
                result = await call(name, args, success=False)
                assert result["status"] == "error" and "SOURCE_PROVIDER_UNAVAILABLE" in result["message"], result
            keys = await call("execute_script", {"code": "import os, json\nprint(json.dumps({k: bool(os.environ.get(k)) for k in ('NVIDIA_API_KEY', 'ARK_API_KEY', 'BEAVER3D_MODEL')}))"})
            configured = json.loads(keys["data"]["stdout"].strip())
            for name, available in [("search_usd", configured["NVIDIA_API_KEY"]), ("generate_3d", configured["ARK_API_KEY"] and configured["BEAVER3D_MODEL"])]:
                if not available:
                    result = await call(name, {"text_prompt": "test cube"}, success=False)
                    assert result["status"] == "error" and "not set" in result["message"], result
            await call("clear_scene")
    (root / "profiles-evidence.json").write_text(json.dumps(evidence, indent=2))
    print(json.dumps({"pass": True, "calls": len(evidence), "provider_mutation": False}))


if __name__ == "__main__":
    asyncio.run(main())
