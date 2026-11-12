from __future__ import annotations

import math
import sys
import types
from typing import Any

import pytest
from isaac_sim_mcp_extension.adapters.v6 import IsaacAdapterV6
from isaac_sim_mcp_extension.adapters.v6_runtime.robots import RobotRuntime


class _RobotSpy:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self._articulations: dict[str, Any] = {}

    def __getattr__(self, name: str):
        def call(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return f"result:{name}"

        return call


def _adapter(robot_runtime: Any) -> IsaacAdapterV6:
    adapter = object.__new__(IsaacAdapterV6)
    adapter._robot_runtime = robot_runtime
    return adapter


@pytest.mark.parametrize(
    ("method", "args", "kwargs", "expected"),
    [
        ("create_xform_prim", ("/World/Robot",), {}, "result:create_xform_prim"),
        ("create_articulation", ("/World/Robot", "robot"), {}, "result:create_articulation"),
        ("_new_articulation", ("/World/Robot",), {}, "result:_new_articulation"),
        ("_runtime_articulation", ("/World/Robot",), {}, "result:_runtime_articulation"),
        ("discover_robots", (), {}, "result:discover_robots"),
        ("get_robot_joint_info", ("/World/Robot",), {}, "result:get_robot_joint_info"),
        ("set_joint_positions", ("/World/Robot", [0.1], [0]), {}, None),
        ("_set_joint_drive_targets", ("/World/Robot", [0.1], [0]), {}, None),
        ("_get_joint_names", ("/World/Robot",), {}, "result:_get_joint_names"),
        ("get_joint_positions", ("/World/Robot",), {}, "result:get_joint_positions"),
        ("get_joint_state", ("/World/Robot",), {}, "result:get_joint_state"),
        ("set_joint_command", ("/World/Robot", "position", [0.1], [0]), {}, None),
        (
            "compute_holonomic_wheel_velocities",
            ("/World/Robot", "/World/Robot/com", [0.1, 0.0, 0.0], ["wheel"]),
            {},
            "result:compute_holonomic_wheel_velocities",
        ),
        ("_drive_config_articulation", ("/World/Robot",), {}, "result:_drive_config_articulation"),
        ("get_joint_drive_config", ("/World/Robot",), {}, "result:get_joint_drive_config"),
        ("set_joint_drive_config", ("/World/Robot", {"damping": 1.0}, [0]), {}, None),
        ("get_joint_config", ("/World/Robot",), {}, "result:get_joint_config"),
    ],
)
def test_robot_facade_methods_forward_without_contract_changes(method, args, kwargs, expected) -> None:
    runtime = _RobotSpy()

    result = getattr(_adapter(runtime), method)(*args, **kwargs)

    assert result == expected
    assert runtime.calls == [(method, args, kwargs)]


def test_robot_runtime_owns_articulation_cache_but_not_motion_state() -> None:
    runtime = RobotRuntime(object(), object(), object())
    adapter = _adapter(runtime)
    marker = object()
    runtime._articulations["/World/Robot"] = marker

    assert adapter._articulations is runtime._articulations
    assert adapter._articulations["/World/Robot"] is marker
    assert "_articulations" not in adapter.__dict__
    assert not hasattr(runtime, "_motion_trajectories")
    assert not hasattr(runtime, "_motion_jobs")
    assert not hasattr(runtime, "_motion_update_subscription")


def test_robot_runtime_stop_hook_target_clears_only_articulation_cache() -> None:
    runtime = RobotRuntime(object(), object(), object())
    runtime._articulations["/World/Robot"] = object()

    runtime.clear_runtime_cache()

    assert runtime._articulations == {}


def test_robot_runtime_rejects_a_fresh_but_invalid_tensor_entity(monkeypatch) -> None:
    created = []

    class _Articulation:
        def __init__(self, paths):
            created.append(paths)

        def is_physics_tensor_entity_valid(self):
            return False

    monkeypatch.setitem(
        sys.modules,
        "isaacsim.core.experimental.prims",
        types.SimpleNamespace(Articulation=_Articulation),
    )
    runtime = RobotRuntime(types.SimpleNamespace(get_stage=lambda: object()), object(), object())
    runtime._ensure_physics_world = lambda: None

    with pytest.raises(RuntimeError, match="physics tensor entity"):
        runtime._runtime_articulation("/World/Robot")

    assert created == [["/World/Robot"], ["/World/Robot"]]


def test_robot_runtime_does_not_reuse_articulation_across_stage_identity(monkeypatch) -> None:
    created = []
    active_stage = [object()]

    class _Articulation:
        def __init__(self, paths):
            self.paths = paths
            created.append(self)

    monkeypatch.setitem(
        sys.modules,
        "isaacsim.core.experimental.prims",
        types.SimpleNamespace(Articulation=_Articulation),
    )
    runtime = RobotRuntime(types.SimpleNamespace(get_stage=lambda: active_stage[0]), object(), object())

    first = runtime._new_articulation("/World/Robot")
    active_stage[0] = object()
    second = runtime._new_articulation("/World/Robot")

    assert second is not first
    assert len(created) == 2


def test_robot_runtime_rebinds_same_path_when_usd_joint_identity_changes(monkeypatch) -> None:
    created = []

    class _Articulation:
        def __init__(self, paths):
            self.paths = paths
            self.dof_names = ["fr3_joint1"] if not created else ["panda_joint1"]
            created.append(self)

        def is_physics_tensor_entity_valid(self):
            return True

    monkeypatch.setitem(
        sys.modules,
        "isaacsim.core.experimental.prims",
        types.SimpleNamespace(Articulation=_Articulation),
    )
    stage = object()
    runtime = RobotRuntime(types.SimpleNamespace(get_stage=lambda: stage), object(), object())
    runtime._ensure_physics_world = lambda: None
    runtime._usd_joint_names = lambda _path: ["panda_joint1"]
    stale = runtime._new_articulation("/World/Robot")

    rebound = runtime._runtime_articulation("/World/Robot")

    assert stale.dof_names == ["fr3_joint1"]
    assert rebound.dof_names == ["panda_joint1"]
    assert rebound is not stale


@pytest.mark.parametrize("timeline", ["stopped", "paused", "playing"])
def test_joint_discovery_only_binds_physics_when_timeline_is_active(monkeypatch, timeline):
    root = types.SimpleNamespace(IsValid=lambda: True)
    stage = types.SimpleNamespace(GetPrimAtPath=lambda _: root)
    monkeypatch.setitem(
        sys.modules,
        "pxr",
        types.SimpleNamespace(
            Usd=types.SimpleNamespace(PrimRange=lambda _: []),
            UsdPhysics=object(),
        ),
    )
    runtime = RobotRuntime(types.SimpleNamespace(get_stage=lambda: stage), object(), object())
    runtime.get_simulation_state = lambda: {"timeline_state": timeline}
    calls = []

    def articulation(source):
        calls.append(source)
        return types.SimpleNamespace(dof_names=["joint"], num_dofs=1)

    runtime._drive_config_articulation = lambda _: articulation("usd")
    runtime._runtime_articulation = lambda _: articulation("tensor")
    result = runtime.get_robot_joint_info("/World/Robot")
    assert result["joint_names"] == ["joint"]
    assert result["num_dof"] == 1
    assert calls == ["usd" if timeline == "stopped" else "tensor"]


def test_stopped_joint_config_has_authored_radian_targets_without_measured_state(monkeypatch):
    def attr(value):
        return types.SimpleNamespace(Get=lambda: value)

    class Revolute:
        def __init__(self, prim):
            pass

        def GetLowerLimitAttr(self):
            return attr(-180.0)

        def GetUpperLimitAttr(self):
            return attr(180.0)

    joint = types.SimpleNamespace(GetName=lambda: "joint", IsA=lambda schema: schema is Revolute)
    root = types.SimpleNamespace(IsValid=lambda: True)
    drive = types.SimpleNamespace(
        GetStiffnessAttr=lambda: attr(100.0),
        GetDampingAttr=lambda: attr(10.0),
        GetTargetPositionAttr=lambda: attr(90.0),
    )
    monkeypatch.setitem(
        sys.modules,
        "pxr",
        types.SimpleNamespace(
            Usd=types.SimpleNamespace(PrimRange=lambda _: [joint]),
            UsdPhysics=types.SimpleNamespace(
                RevoluteJoint=Revolute,
                PrismaticJoint=object(),
                DriveAPI=types.SimpleNamespace(Get=lambda _prim, _axis: drive),
            ),
        ),
    )
    stage = types.SimpleNamespace(GetPrimAtPath=lambda _: root)
    runtime = RobotRuntime(types.SimpleNamespace(get_stage=lambda: stage), object(), object())
    runtime.get_simulation_state = lambda: {"timeline_state": "stopped"}
    runtime.get_joint_drive_config = lambda _: {"joints": []}
    result = runtime.get_joint_config("/World/Robot")
    assert math.isclose(result["joints"][0]["target_position"], math.pi / 2)
    assert "actual_position" not in result["joints"][0]
    assert "position_error" not in result["joints"][0]


@pytest.mark.parametrize("version", ["6.0.1", "6.1.0", "6.2.0-rc.14"])
def test_holonomic_controller_routes_version_and_reorders_named_targets(monkeypatch, version):
    calls = []
    wheels = ["wheel_b", "wheel_a", "wheel_c"]
    setup = types.SimpleNamespace(
        get_holonomic_controller_params=lambda: (
            [0.04] * 3,
            [[0, 0, 0]] * 3,
            [[1, 0, 0, 0]] * 3,
            [90] * 3,
            [1, 0, 0],
            [0, 0, 1],
        ),
        get_articulation_controller_params=lambda: wheels,
    )
    monkeypatch.setitem(
        sys.modules,
        "isaacsim.robot.experimental.wheeled_robots.robots",
        types.SimpleNamespace(HolonomicRobotUsdSetup=lambda **_: setup),
    )

    class Velocities:
        def numpy(self):
            return self

        def reshape(self, _):
            return self

        def tolist(self):
            return [1.0, 2.0, 3.0]

    class Modern:
        def __init__(self, **kwargs):
            calls.append(("modern", kwargs))

        def reset(self, *_):
            pass

        def forward(self, current, setpoint, time):
            assert setpoint.sites["linear_velocities"] == (["control_point"], [[0.1, 0.05, 0.0]])
            assert setpoint.sites["angular_velocities"] == (["control_point"], [[0.0, 0.0, 0.2]])
            return types.SimpleNamespace(joints=types.SimpleNamespace(velocity_names=wheels, velocities=Velocities()))

    class Legacy:
        def __init__(self, **kwargs):
            calls.append(("legacy", kwargs))

        def forward(self, command):
            assert command == [0.1, 0.05, 0.2]
            return [1.0, 2.0, 3.0]

    monkeypatch.setitem(
        sys.modules, "isaacsim.robot_motion.controllers", types.SimpleNamespace(HolonomicController=Modern)
    )
    monkeypatch.setitem(
        sys.modules,
        "isaacsim.robot.experimental.wheeled_robots.controllers",
        types.SimpleNamespace(HolonomicController=Legacy),
    )
    monkeypatch.setitem(
        sys.modules,
        "isaacsim.robot_motion.experimental.motion_generation",
        types.SimpleNamespace(
            RobotState=lambda **kwargs: types.SimpleNamespace(**kwargs),
            SpatialState=types.SimpleNamespace(from_name=lambda **kwargs: kwargs),
        ),
    )
    monkeypatch.setitem(sys.modules, "warp", types.SimpleNamespace(array=lambda x, **_: x, float32="float32"))
    from isaac_sim_mcp_extension.adapters.v6_runtime import robots as module

    monkeypatch.setattr(module, "np", types.SimpleNamespace(asarray=lambda x, **_: x, float64="float64"))
    stage = types.SimpleNamespace(GetPrimAtPath=lambda _: types.SimpleNamespace(IsValid=lambda: True))
    runtime = RobotRuntime(
        types.SimpleNamespace(get_stage=lambda: stage), object(), types.SimpleNamespace(isaac_version=version)
    )
    values = runtime.compute_holonomic_wheel_velocities(
        "/Robot", "/Robot/com", [0.1, 0.05, 0.2], ["wheel_a", "wheel_b", "wheel_c"]
    )
    assert values == [2.0, 1.0, 3.0]
    assert calls[0][0] == ("modern" if version.startswith("6.2") else "legacy")
