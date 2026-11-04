"""Conversation-oriented wrappers for the consolidated MCP tool profile."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Literal, Optional

if TYPE_CHECKING:
    from isaac_mcp.connection import IsaacConnection


def register_tools(mcp: Any, _get_connection: "Callable[[], IsaacConnection]") -> None:
    def error(message: str) -> str:
        return json.dumps({"status": "error", "code": "INVALID_ARGUMENT", "message": message})

    def invoke(tool_name: str, **kwargs: Any) -> str:
        return mcp.call_registered_tool(tool_name, **kwargs)

    def require(values: Dict[str, Any], *names: str) -> Optional[str]:
        missing = [name for name in names if values.get(name) is None]
        return error(f"{', '.join(missing)} is required for this action") if missing else None

    def require_path(values: Dict[str, Any], *names: str) -> Optional[str]:
        invalid = [name for name in names if not isinstance(values.get(name), str) or not values[name].strip()]
        return error(f"{', '.join(invalid)} must be non-empty absolute Prim paths") if invalid else None

    @mcp.tool("query_prim")
    def query_prim(
        action: Literal["list", "get"],
        root_path: str = "/",
        prim_type: Optional[str] = None,
        prim_path: Optional[str] = None,
    ) -> str:
        """List a subtree or read one Prim. For get, prim_path is required; list uses root_path and prim_type.

        Args:
            action: Operation to perform; see the action-specific requirements above.
            root_path: USD root Prim path for listing.
            prim_type: Optional Prim type filter for listing.
            prim_path: USD Prim path for the selected operation.
        """
        if action == "list":
            return invoke("list_prims", root_path=root_path, prim_type=prim_type)
        invalid = require_path(locals(), "prim_path")
        return invalid or invoke("get_prim_info", prim_path=prim_path)

    @mcp.tool("semantic_labels")
    def semantic_labels(
        action: Literal["get", "set"],
        prim_path: str,
        taxonomy: Optional[str] = None,
        labels: Optional[List[str]] = None,
        overwrite: bool = False,
        preview: bool = True,
    ) -> str:
        """Read labels or set them. For set, taxonomy and labels are required; preview defaults to true.

        Args:
            action: Operation to perform; see the action-specific requirements above.
            prim_path: USD Prim path for the selected operation.
            taxonomy: Semantic taxonomy; required for set.
            labels: Semantic labels; required for set.
            overwrite: Whether existing authored data may be overwritten.
            preview: When true validate and report without applying the requested change.
        """
        if action == "get":
            return invoke("get_semantic_labels", prim_path=prim_path)
        invalid = require(locals(), "taxonomy", "labels")
        return invalid or invoke(
            "set_semantic_labels",
            prim_path=prim_path,
            taxonomy=taxonomy,
            labels=labels,
            overwrite=overwrite,
            preview=preview,
        )

    @mcp.tool("typed_attribute")
    def typed_attribute(
        action: Literal["get", "set"],
        prim_path: str,
        attribute: str,
        type_name: Optional[str] = None,
        value: Any = None,
        custom: bool = True,
        overwrite: bool = False,
        preview: bool = True,
    ) -> str:
        """Read or set a USD attribute. For set, type_name and value are required; preview defaults to true.

        Args:
            action: Operation to perform; see the action-specific requirements above.
            prim_path: USD Prim path for the selected operation.
            attribute: USD attribute name.
            type_name: Explicit USD value type; required for set.
            value: Attribute value matching type_name; required for set.
            custom: Whether a newly created attribute is custom.
            overwrite: Whether existing authored data may be overwritten.
            preview: When true validate and report without applying the requested change.
        """
        if action == "get":
            return invoke("get_typed_attribute", prim_path=prim_path, attribute=attribute)
        invalid = require(locals(), "type_name", "value")
        return invalid or invoke(
            "set_typed_attribute",
            prim_path=prim_path,
            attribute=attribute,
            type_name=type_name,
            value=value,
            custom=custom,
            overwrite=overwrite,
            preview=preview,
        )

    @mcp.tool("physics_body_config")
    def physics_body_config(
        action: Literal["get", "configure"],
        prim_path: str,
        body_type: Optional[str] = None,
        collider_enabled: Optional[bool] = None,
        approximation: Optional[str] = None,
        mass_kg: Optional[float] = None,
        density_kg_m3: Optional[float] = None,
    ) -> str:
        """Read or configure a body. Configure requires at least one configuration field; it writes body settings.

        Args:
            action: Operation to perform; see the action-specific requirements above.
            prim_path: USD Prim path for the selected operation.
            body_type: Requested rigid or static body type.
            collider_enabled: Whether to enable the collider.
            approximation: Collider approximation name.
            mass_kg: Body mass in kilograms.
            density_kg_m3: Body density in kilograms per cubic metre.
        """
        if action == "get":
            invalid = require_path(locals(), "prim_path")
            return invalid or invoke("get_physics_body", prim_path=prim_path)
        invalid = require_path(locals(), "prim_path")
        if invalid:
            return invalid
        configured = (body_type, collider_enabled, approximation, mass_kg, density_kg_m3)
        if all(value is None for value in configured):
            return error("physics_body_config(action=configure) requires at least one configuration field")
        return invoke(
            "configure_physics_body",
            prim_path=prim_path,
            body_type="dynamic" if body_type is None else body_type,
            collider_enabled=True if collider_enabled is None else collider_enabled,
            approximation=approximation,
            mass_kg=mass_kg,
            density_kg_m3=density_kg_m3,
        )

    @mcp.tool("collision_group")
    def collision_group(
        action: Literal["get", "create"],
        group_path: str,
        collider_paths: Optional[List[str]] = None,
        filtered_group_paths: Optional[List[str]] = None,
        invert_filtered_groups: bool = False,
        merge_group_name: Optional[str] = None,
    ) -> str:
        """Read or create a collision group. For create, collider_paths is required and the stage is changed.

        Args:
            action: Operation to perform; see the action-specific requirements above.
            group_path: USD collision group Prim path.
            collider_paths: Collider Prim paths; required for create.
            filtered_group_paths: Collision group paths to filter.
            invert_filtered_groups: Whether to invert the collision filter relationship.
            merge_group_name: Optional collision group merge name.
        """
        if action == "get":
            return invoke("get_collision_group", group_path=group_path)
        invalid = require(locals(), "collider_paths")
        return invalid or invoke(
            "create_collision_group",
            group_path=group_path,
            collider_paths=collider_paths,
            filtered_group_paths=filtered_group_paths,
            invert_filtered_groups=invert_filtered_groups,
            merge_group_name=merge_group_name,
        )

    @mcp.tool("physics_joint")
    def physics_joint(
        action: Literal["get", "create"],
        joint_path: str,
        joint_type: Optional[str] = None,
        body1: Optional[str] = None,
        body0: Optional[str] = None,
        axis: Optional[str] = None,
        lower_limit: Optional[float] = None,
        upper_limit: Optional[float] = None,
        local_position0: Optional[List[float]] = None,
        local_rotation0: Optional[List[float]] = None,
        local_position1: Optional[List[float]] = None,
        local_rotation1: Optional[List[float]] = None,
        collision_enabled: bool = False,
    ) -> str:
        """Read or create a joint. For create, joint_type and body1 are required and the stage is changed.

        Args:
            action: Operation to perform; see the action-specific requirements above.
            joint_path: USD joint Prim path.
            joint_type: Joint type: fixed, revolute or prismatic; required for create.
            body1: Second body Prim path; required for create.
            body0: Optional first body Prim path.
            axis: Joint axis.
            lower_limit: Lower limit in meters for prismatic or degrees for revolute joints.
            upper_limit: Upper limit in meters for prismatic or degrees for revolute joints.
            local_position0: Local position of joint frame on body0 in meters.
            local_rotation0: Local rotation of joint frame on body0 as [w, x, y, z].
            local_position1: Local position of joint frame on body1 in meters.
            local_rotation1: Local rotation of joint frame on body1 as [w, x, y, z].
            collision_enabled: Whether connected bodies may collide.
        """
        if action == "get":
            return invoke("get_physics_joint", joint_path=joint_path)
        invalid = require(locals(), "joint_type", "body1")
        return invalid or invoke(
            "create_physics_joint",
            joint_path=joint_path,
            joint_type=joint_type,
            body1=body1,
            body0=body0,
            axis=axis,
            lower_limit=lower_limit,
            upper_limit=upper_limit,
            local_position0=local_position0,
            local_rotation0=local_rotation0,
            local_position1=local_position1,
            local_rotation1=local_rotation1,
            collision_enabled=collision_enabled,
        )

    @mcp.tool("control_timeline")
    def control_timeline(action: Literal["play", "pause", "stop"]) -> str:
        """Play, pause or stop the timeline. Stop resets the scene to its spawn state.

        Args:
            action: Operation to perform; see the action-specific requirements above.
        """
        return invoke({"play": "play_simulation", "pause": "pause_simulation", "stop": "stop_simulation"}[action])

    @mcp.tool("robot_library")
    def robot_library(action: Literal["list", "refresh"] = "list") -> str:
        """List discovered robots or refresh the discovery cache; refresh triggers a new scan.

        Args:
            action: Operation to perform; see the action-specific requirements above.
        """
        return invoke("list_available_robots" if action == "list" else "refresh_robot_library")

    @mcp.tool("control_gripper")
    def control_gripper(
        action: Literal["set_width", "open", "close"],
        prim_path: str,
        profile: str,
        width_m: Optional[float] = None,
    ) -> str:
        """Set width, open or close a gripper. Set_width requires width_m and writes the command target.

        Args:
            action: Operation to perform; see the action-specific requirements above.
            prim_path: USD Prim path for the selected operation.
            profile: Exact supported controller profile name.
            width_m: Total gripper opening in metres; required for set_width.
        """
        if action == "set_width":
            invalid = require(locals(), "width_m")
            return invalid or invoke("set_gripper_width", prim_path=prim_path, profile=profile, width_m=width_m)
        return invoke(f"{action}_gripper", prim_path=prim_path, profile=profile)

    @mcp.tool("control_mobile_base_velocity")
    def control_mobile_base_velocity(
        action: Literal["set", "stop"],
        prim_path: str,
        profile: str,
        forward_mps: Optional[float] = None,
        lateral_mps: float = 0.0,
        yaw_radps: float = 0.0,
    ) -> str:
        """Set or stop a mobile base. Set requires forward_mps; stop writes zero wheel targets.

        Args:
            action: Operation to perform; see the action-specific requirements above.
            prim_path: USD Prim path for the selected operation.
            profile: Exact supported controller profile name.
            forward_mps: Forward speed in metres per second; required for set.
            lateral_mps: Lateral speed in metres per second.
            yaw_radps: Yaw rate in radians per second.
        """
        if action == "stop":
            return invoke("stop_mobile_base", prim_path=prim_path, profile=profile)
        invalid = require(locals(), "forward_mps")
        return invalid or invoke(
            "set_mobile_base_velocity",
            prim_path=prim_path,
            profile=profile,
            forward_mps=forward_mps,
            lateral_mps=lateral_mps,
            yaw_radps=yaw_radps,
        )

    @mcp.tool("motion_job")
    def motion_job(action: Literal["get", "cancel"], job_id: str) -> str:
        """Get a motion job or request cancellation; cancellation holds the last commanded position.

        Args:
            action: Operation to perform; see the action-specific requirements above.
            job_id: Opaque identifier of the job to inspect or cancel.
        """
        return invoke("get_motion_status" if action == "get" else "cancel_motion", job_id=job_id)

    @mcp.tool("material_definition")
    def material_definition(
        action: Literal["get", "create"],
        material_path: Optional[str] = None,
        material_type: str = "pbr",
        prim_path: Optional[str] = None,
        color: Optional[List[float]] = None,
        roughness: float = 0.5,
        metallic: float = 0.0,
        static_friction: float = 0.5,
        dynamic_friction: float = 0.5,
        restitution: float = 0.0,
    ) -> str:
        """Read or create a material. Get requires material_path; create writes a material to the stage.

        Args:
            action: Operation to perform; see the action-specific requirements above.
            material_path: Material Prim path; required for get or apply as applicable.
            material_type: Material type to create.
            prim_path: USD Prim path for the selected operation.
            color: Color components for the material or light.
            roughness: PBR material roughness.
            metallic: PBR material metallic value.
            static_friction: Physics material static friction.
            dynamic_friction: Physics material dynamic friction.
            restitution: Physics material restitution.
        """
        if action == "get":
            invalid = require(locals(), "material_path")
            return invalid or invoke("get_material", material_path=material_path)
        return invoke(
            "create_material",
            material_type=material_type,
            prim_path=prim_path,
            color=color,
            roughness=roughness,
            metallic=metallic,
            static_friction=static_friction,
            dynamic_friction=dynamic_friction,
            restitution=restitution,
        )

    @mcp.tool("material_binding")
    def material_binding(
        action: Literal["get", "apply"],
        target_prim_path: str,
        material_path: Optional[str] = None,
        material_purpose: Optional[str] = None,
    ) -> str:
        """Read or apply a material binding. Apply requires material_path and changes the stage.

        Args:
            action: Operation to perform; see the action-specific requirements above.
            target_prim_path: Target Prim path; used by the selected operation.
            material_path: Material Prim path; required for get or apply as applicable.
            material_purpose: Material binding purpose; defaults depend on action.
        """
        if action == "get":
            return invoke(
                "get_material_binding",
                target_prim_path=target_prim_path,
                material_purpose=material_purpose or "physics",
            )
        invalid = require(locals(), "material_path")
        return invalid or invoke(
            "apply_material",
            material_path=material_path,
            target_prim_path=target_prim_path,
            material_purpose=material_purpose or "auto",
        )

    @mcp.tool("light_config")
    def light_config(
        action: Literal["create", "modify"],
        prim_path: Optional[str] = None,
        light_type: str = "DistantLight",
        position: Optional[List[float]] = None,
        intensity: Optional[float] = None,
        color: Optional[List[float]] = None,
        rotation: Optional[List[float]] = None,
    ) -> str:
        """Create or modify a light. Modify requires prim_path; create uses intensity 1000 when omitted.

        Args:
            action: Operation to perform; see the action-specific requirements above.
            prim_path: USD Prim path for the selected operation.
            light_type: Type of light to create.
            position: Position vector for the created light.
            intensity: Light intensity; create uses 1000 when omitted.
            color: Color components for the material or light.
            rotation: Rotation vector for the created light.
        """
        if action == "modify":
            invalid = require(locals(), "prim_path")
            return invalid or invoke("modify_light", prim_path=prim_path, intensity=intensity, color=color)
        return invoke(
            "create_light",
            light_type=light_type,
            position=position,
            intensity=1000.0 if intensity is None else intensity,
            color=color,
            rotation=rotation,
            prim_path=prim_path,
        )

    @mcp.tool("query_human")
    def query_human(
        action: Literal["list", "get"],
        root_prim_path: str = "/World/Characters",
        include_external: bool = True,
        human_path: Optional[str] = None,
    ) -> str:
        """List humans or get one human. Get requires human_path.

        Args:
            action: Operation to perform; see the action-specific requirements above.
            root_prim_path: Root Prim path for listing humans.
            include_external: Whether to include external humans in the list.
            human_path: Human Prim path; required for get or human actions.
        """
        if action == "list":
            return invoke("list_humans", root_prim_path=root_prim_path, include_external=include_external)
        invalid = require(locals(), "human_path")
        return invalid or invoke("get_human", human_path=human_path)

    @mcp.tool("set_human_action")
    def set_human_action(
        action: Literal["target", "look_at", "idle"],
        human_path: str,
        target_position: Optional[List[float]] = None,
        target_prim_path: Optional[str] = None,
        speed_mps: Optional[float] = None,
        auto_brake: bool = True,
        duration_seconds: float = 0.0,
        facing_position: Optional[List[float]] = None,
        facing_prim_path: Optional[str] = None,
        preview: bool = True,
    ) -> str:
        """Preview or issue a target, look_at or idle action. Target and look_at require exactly one of target_position and target_prim_path; idle may specify one facing target. Preview defaults to true.

        Args:
            action: Operation to perform; see the action-specific requirements above.
            human_path: Human Prim path; required for get or human actions.
            target_position: Target position vector; choose with the target Prim path according to the action.
            target_prim_path: Target Prim path; used by the selected operation.
            speed_mps: Target movement speed in metres per second.
            auto_brake: Whether to brake automatically at the target.
            duration_seconds: Look-at duration in seconds; zero means indefinite.
            facing_position: Optional facing position for idle.
            facing_prim_path: Optional facing Prim path for idle.
            preview: When true validate and report without applying the requested change.
        """
        if action == "target":
            return invoke(
                "set_human_target",
                human_path=human_path,
                target_position=target_position,
                target_prim_path=target_prim_path,
                speed_mps=speed_mps,
                auto_brake=auto_brake,
                preview=preview,
            )
        if action == "look_at":
            return invoke(
                "set_human_look_at",
                human_path=human_path,
                target_position=target_position,
                target_prim_path=target_prim_path,
                duration_seconds=duration_seconds,
                preview=preview,
            )
        return invoke(
            "set_human_idle",
            human_path=human_path,
            facing_position=facing_position,
            facing_prim_path=facing_prim_path,
            preview=preview,
        )

    @mcp.tool("create_ros2_publisher")
    def create_ros2_publisher(
        publisher_type: Literal["clock", "tf", "joint_state", "camera", "lidar"],
        graph_path: Optional[str] = None,
        topic_name: Optional[str] = None,
        node_namespace: str = "",
        domain_id: Optional[int] = None,
        qos_profile: Optional[str] = None,
        preview: bool = True,
        reset_on_stop: bool = True,
        target_prims: Optional[List[str]] = None,
        parent_prim: Optional[str] = None,
        static_publisher: bool = False,
        target_prim: Optional[str] = None,
        camera_prim_path: Optional[str] = None,
        lidar_prim_path: Optional[str] = None,
        render_product_path: Optional[str] = None,
        frame_id: Optional[str] = None,
        camera_type: str = "rgb",
        lidar_type: str = "point_cloud",
        use_system_time: bool = False,
    ) -> str:
        """Preview or create a ROS 2 publisher. Clock has a default graph_path; other types require graph_path. TF requires target_prims, joint_state target_prim, camera camera_prim_path, lidar lidar_prim_path. Preview defaults to true.

        Args:
            publisher_type: ROS 2 publisher type; determines the required target fields.
            graph_path: Action Graph Prim path. Clock uses a default when omitted; all other publisher types require this path.
            topic_name: ROS 2 topic name; defaults depend on publisher_type.
            node_namespace: ROS 2 node namespace.
            domain_id: Optional ROS 2 domain ID.
            qos_profile: QoS profile; default depends on publisher_type.
            preview: When true validate and report without applying the requested change.
            reset_on_stop: Whether the clock resets on stop.
            target_prims: Target Prim paths; required for TF publisher.
            parent_prim: Optional parent Prim for TF publisher.
            static_publisher: Whether the TF publisher is static.
            target_prim: Target Prim path; required for joint_state publisher.
            camera_prim_path: Camera Prim path; required for camera publisher.
            lidar_prim_path: LiDAR Prim path; required for lidar publisher.
            render_product_path: Optional render product path.
            frame_id: ROS 2 frame identifier; default depends on publisher_type.
            camera_type: Camera output type.
            lidar_type: LiDAR output type.
            use_system_time: Whether to use system time for timestamps.
        """
        if publisher_type == "clock":
            return invoke(
                "create_ros2_clock_publisher",
                graph_path=graph_path or "/World/ROS2Clock",
                topic_name=topic_name or "/clock",
                node_namespace=node_namespace,
                domain_id=domain_id,
                qos_profile=qos_profile or "default",
                reset_on_stop=reset_on_stop,
                preview=preview,
            )
        invalid = require(locals(), "graph_path")
        if invalid:
            return invalid
        if publisher_type == "tf":
            invalid = require(locals(), "target_prims")
            return invalid or invoke(
                "create_ros2_tf_publisher",
                graph_path=graph_path,
                target_prims=target_prims,
                parent_prim=parent_prim,
                topic_name=topic_name or "/tf",
                node_namespace=node_namespace,
                domain_id=domain_id,
                qos_profile=qos_profile or "default",
                static_publisher=static_publisher,
                preview=preview,
            )
        if publisher_type == "joint_state":
            invalid = require(locals(), "target_prim")
            return invalid or invoke(
                "create_ros2_joint_state_publisher",
                graph_path=graph_path,
                target_prim=target_prim,
                topic_name=topic_name or "/joint_states",
                node_namespace=node_namespace,
                domain_id=domain_id,
                qos_profile=qos_profile or "default",
                preview=preview,
            )
        if publisher_type == "camera":
            invalid = require(locals(), "camera_prim_path")
            return invalid or invoke(
                "create_ros2_camera_publisher",
                graph_path=graph_path,
                camera_prim_path=camera_prim_path,
                render_product_path=render_product_path,
                topic_name=topic_name or "/camera/image_raw",
                frame_id=frame_id or "sim_camera",
                camera_type=camera_type,
                node_namespace=node_namespace,
                domain_id=domain_id,
                qos_profile=qos_profile or "sensor_data",
                use_system_time=use_system_time,
                preview=preview,
            )
        invalid = require(locals(), "lidar_prim_path")
        return invalid or invoke(
            "create_ros2_lidar_publisher",
            graph_path=graph_path,
            lidar_prim_path=lidar_prim_path,
            render_product_path=render_product_path,
            topic_name=topic_name or "/lidar/points",
            frame_id=frame_id or "sim_lidar",
            lidar_type=lidar_type,
            node_namespace=node_namespace,
            domain_id=domain_id,
            qos_profile=qos_profile or "sensor_data",
            use_system_time=use_system_time,
            preview=preview,
        )

    @mcp.tool("sdg_job_control")
    def sdg_job_control(action: Literal["get", "cancel"], job_id: str, preview: bool = True) -> str:
        """Read or cancel a Replicator SDG job. Cancel defaults to preview only.

        Args:
            action: Operation to perform; see the action-specific requirements above.
            job_id: Opaque identifier of the job to inspect or cancel.
            preview: When true validate and report without applying the requested change.
        """
        if action == "get":
            return invoke("get_sdg_job_status", job_id=job_id)
        return invoke("cancel_sdg_job", job_id=job_id, preview=preview)

    @mcp.tool("job_control")
    def job_control(action: Literal["get", "cancel"], job_id: str) -> str:
        """Read or request cancellation of a managed job. Check its returned state after cancellation.

        Args:
            action: Operation to perform; see the action-specific requirements above.
            job_id: Opaque identifier of the job to inspect or cancel.
        """
        return invoke("get_job_status" if action == "get" else "cancel_job", job_id=job_id)

    @mcp.tool("query_action_graph")
    def query_action_graph(
        action: Literal["list", "get"],
        root_path: str = "/World",
        include_disabled: bool = True,
        graph_path: Optional[str] = None,
        include_values: bool = False,
        include_script_source: bool = False,
    ) -> str:
        """List graphs or inspect one. Get requires graph_path; source and values are optional.

        Args:
            action: Operation to perform; see the action-specific requirements above.
            root_path: USD root Prim path for listing.
            include_disabled: Whether to include disabled Action Graphs.
            graph_path: Action Graph Prim path; required for get and unused for list.
            include_values: Whether to include graph attribute values.
            include_script_source: Whether to include ScriptNode source.
        """
        if action == "list":
            return invoke("list_action_graphs", root_path=root_path, include_disabled=include_disabled)
        invalid = require(locals(), "graph_path")
        return invalid or invoke(
            "get_action_graph",
            graph_path=graph_path,
            include_values=include_values,
            include_script_source=include_script_source,
        )

    @mcp.tool("action_graph_connection")
    def action_graph_connection(
        action: Literal["connect", "disconnect"],
        graph_path: str,
        source_attr: str,
        target_attr: str,
        preview: bool = True,
    ) -> str:
        """Preview or connect/disconnect a graph edge. Preview defaults to true.

        Args:
            action: Operation to perform; see the action-specific requirements above.
            graph_path: Action Graph Prim path; required for connect and disconnect.
            source_attr: Source graph output attribute path.
            target_attr: Target graph input attribute path.
            preview: When true validate and report without applying the requested change.
        """
        return invoke(
            f"{action}_action_graph",
            graph_path=graph_path,
            source_attr=source_attr,
            target_attr=target_attr,
            preview=preview,
        )

    @mcp.tool("script_node_source")
    def script_node_source(
        action: Literal["configure", "reload"],
        graph_path: str,
        node_path: str = "ScriptNode",
        mode: Optional[str] = None,
        inline_script: Optional[str] = None,
        script_file: Optional[str] = None,
        preview: bool = True,
    ) -> str:
        """Preview or configure/reload a ScriptNode. Configure defaults to inline mode; supply source for the selected mode. Preview defaults to true.

        Args:
            action: Operation to perform; see the action-specific requirements above.
            graph_path: Action Graph Prim path; required for configure and reload.
            node_path: ScriptNode path within the graph.
            mode: Script source mode; configure defaults to inline.
            inline_script: Inline Python source when using inline mode.
            script_file: Script source file path when using file mode.
            preview: When true validate and report without applying the requested change.
        """
        if action == "configure":
            return invoke(
                "configure_script_node",
                graph_path=graph_path,
                node_path=node_path,
                mode=mode or "inline",
                inline_script=inline_script,
                script_file=script_file,
                preview=preview,
            )
        return invoke(
            "reload_script_node",
            graph_path=graph_path,
            node_path=node_path,
            mode=mode,
            inline_script=inline_script,
            script_file=script_file,
            preview=preview,
        )
