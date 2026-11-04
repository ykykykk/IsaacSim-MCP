"""Offline checks for visible tool descriptions and unchanged parameter contracts."""
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from isaac_mcp.tools import _wrap_tool, register_all_tools


def test_descriptions_reach_real_registered_schema(monkeypatch):
    monkeypatch.setenv("ISAAC_MCP_TOOL_PROFILE", "consolidated")
    mcp = FastMCP("metadata-contract")
    register_all_tools(mcp, lambda: None)
    tools = {tool.name: tool for tool in mcp._tool_manager.list_tools()}
    query = tools["query_prim"]
    assert "prim_path is required" in query.description
    properties = query.parameters["properties"]
    assert "required for this action" not in properties["prim_path"]["description"]
    assert properties["prim_path"]["description"]
    assert query.parameters["required"] == ["action"]
    assert properties["root_path"]["default"] == "/"
    assert properties["command_id"]["description"]
    assert "Returns:" in query.description
    ros = tools["create_ros2_publisher"]
    assert "camera_prim_path" in ros.description
    assert ros.parameters["properties"]["preview"]["default"] is True
    assert "description" in ros.parameters["properties"]["camera_prim_path"]
    expected_paths = {
        "create_ros2_publisher": "Action Graph Prim path. Clock uses a default when omitted; all other publisher types require this path.",
        "query_action_graph": "Action Graph Prim path; required for get and unused for list.",
        "action_graph_connection": "Action Graph Prim path; required for connect and disconnect.",
        "script_node_source": "Action Graph Prim path; required for configure and reload.",
    }
    for name, description in expected_paths.items():
        assert tools[name].parameters["properties"]["graph_path"]["description"] == description


def test_existing_annotated_metadata_and_defaults_are_preserved():
    def example(value: Annotated[int, Field(ge=1, description="original")] = 2):
        """Example.

        Args:
            value: A conflicting description must not replace the existing field.
        """
        return value

    mcp = FastMCP("annotated-contract")
    mcp.tool()(_wrap_tool(example))
    prop = mcp._tool_manager.list_tools()[0].parameters["properties"]["value"]
    assert prop["description"] == "original"
    assert prop["minimum"] == 1
    assert prop["default"] == 2


def test_executed_tool_descriptions_cover_distinct_parameter_semantics(monkeypatch):
    monkeypatch.setenv("ISAAC_MCP_TOOL_PROFILE", "full")
    mcp = FastMCP("executed-tool-descriptions")
    register_all_tools(mcp, lambda: None)
    tools = {tool.name: tool for tool in mcp._tool_manager.list_tools()}
    binding = tools["get_material_binding"].parameters["properties"]["target_prim_path"]["description"]
    assert "material binding" in binding
    assert "target_position" not in binding
    index = tools["edit_sublayer"].parameters["properties"]["index"]["description"]
    assert "Insertion" in index and "Remove uses layer_path" in index
    joint = tools["physics_joint"].parameters["properties"]
    assert "[w, x, y, z]" in joint["local_rotation1"]["description"]
    assert "degrees" in joint["lower_limit"]["description"]
    assert "root layer" in tools["save_stage_as"].description
    assert "LIDAR_FRAME_NOT_READY" in tools["get_lidar_point_cloud"].description
