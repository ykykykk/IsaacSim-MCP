"""Real DDS messages for TF, joints, RGB and RTX point cloud on scratch 6.2."""

import argparse
import json
import os
import subprocess
import time
from pathlib import Path


def subscriber(root):
    import rclpy
    from rclpy.qos import qos_profile_sensor_data
    from sensor_msgs.msg import Image, JointState, PointCloud2
    from tf2_msgs.msg import TFMessage

    rclpy.init()
    node = rclpy.create_node('mcp_all_publishers_acceptance')
    samples = {}

    def receive(kind, message):
        if kind == 'tf':
            value = [{'child': x.child_frame_id, 'parent': x.header.frame_id,
                      'translation': [x.transform.translation.x, x.transform.translation.y, x.transform.translation.z]}
                     for x in message.transforms]
        elif kind == 'joints':
            value = {'names': list(message.name), 'positions': list(message.position)}
        elif kind == 'rgb':
            value = {'width': message.width, 'height': message.height, 'encoding': message.encoding,
                     'bytes': len(message.data), 'unique_bytes': len(set(message.data))}
        else:
            value = {'width': message.width, 'height': message.height, 'point_step': message.point_step,
                     'bytes': len(message.data), 'fields': [x.name for x in message.fields]}
        item = samples.setdefault(kind, {'count': 0})
        item.update(last=value, count=item['count'] + 1)

    subscriptions = [node.create_subscription(cls, '/mcp_acceptance/' + kind,
        lambda msg, k=kind: receive(k, msg), qos_profile_sensor_data)
        for kind, cls in [('tf', TFMessage), ('joints', JointState), ('rgb', Image), ('points', PointCloud2)]]
    (root / 'ros-suite-ready.txt').write_text('ready')
    deadline = time.monotonic() + 40
    try:
        while time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=0.1)
            if len(samples) == 4 and all(x['count'] >= 5 for x in samples.values()):
                break
        (root / 'ros-suite-messages.json').write_text(json.dumps(samples, indent=2))
        assert len(samples) == 4 and all(x['count'] >= 5 for x in samples.values()), samples
    finally:
        for item in subscriptions:
            node.destroy_subscription(item)
        node.destroy_node()
        rclpy.shutdown()


def parent():
    from isaac_mcp.connection import IsaacConnection
    from scripts.live_camera_evidence import call_tool, capture
    from scripts.verify_ros2_workflows_live import ISAAC_ROOT, _ros_environment

    root = Path(os.environ['ISAAC_MCP_VALIDATION_ROOT']).resolve(strict=True)
    c = IsaacConnection()
    evidence = []

    def call(name, params=None):
        r = c.send_command(name, params or {})
        evidence.append({'command': name, 'response': r})
        assert r['status'] == 'success', (name, r)
        return r

    cap = call('system.get_capabilities')['data']['runtime']
    assert Path(cap['root_identifier']).parent == root and Path(cap['log_file']).parent == root
    assert cap['isaac_sim_version'].startswith('6.2.')
    call('simulation.stop')
    assert not call('ros2.list_workflows')['data']['workflows']
    process = None
    created = []
    owned_products = {}
    try:
        call('scene.create_physics')
        call('robots.create', {'robot_type': 'frankapanda', 'prim_path': '/World/RosPanda'})
        call('objects.create', {'object_type': 'Cube', 'prim_path': '/World/RosTarget', 'position': [3,0,1], 'size': 2})
        call('sensors.create_camera', {'prim_path': '/World/RosCamera', 'position': [5,5,3], 'resolution': [320,240]})
        call('sensors.create_lidar', {'prim_path': '/World/RosLidar', 'position': [0,0,1]})
        call('lighting.create', {'prim_path': '/World/RosLight', 'intensity': 2500})
        call('simulation.execute_script', {'code': """
import omni.usd
from pxr import Gf, UsdGeom
stage = omni.usd.get_context().get_stage()
UsdGeom.Xformable(stage.GetPrimAtPath('/World/RosCamera')).MakeMatrixXform().Set(
 Gf.Matrix4d().SetLookAt(Gf.Vec3d(5,5,3),Gf.Vec3d(2,0,1),Gf.Vec3d(0,0,1)).GetInverse())
"""})
        workflows = [
            ('tf', 'tf', {'target_prims': ['/World/RosTarget']}),
            ('joints', 'joint_state', {'target_prim': '/World/RosPanda'}),
            ('rgb', 'camera', {'camera_prim_path': '/World/RosCamera', 'camera_type': 'rgb'}),
            ('points', 'lidar', {'lidar_prim_path': '/World/RosLidar', 'lidar_type': 'point_cloud'})]
        for topic, kind, params in workflows:
            args = dict(params, graph_path='/World/RosGraph_' + kind,
                        topic_name='/mcp_acceptance/' + topic, domain_id=42)
            preview = call('ros2.create_' + kind + '_publisher', args)
            assert preview['data']['preview'] is True
            result = call_tool('create_ros2_publisher', {**args, 'publisher_type': kind, 'preview': False})
            evidence.append({'tool': 'create_ros2_publisher', 'response': result})
            if 'owned_render_product' in result['readback']:
                owned_products[args['graph_path']] = result['readback']['owned_render_product']
            created.append(args['graph_path'])
        ready = root / 'ros-suite-ready.txt'
        if ready.exists():
            ready.unlink()
        process = subprocess.Popen([str(ISAAC_ROOT / 'python.bat'), str(Path(__file__).resolve()),
            '--subscriber', str(root)], env=_ros_environment(), stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
        deadline = time.monotonic() + 15
        while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.1)
        assert ready.exists(), process.communicate(timeout=2)[0]
        call('simulation.play')
        output, _ = process.communicate(timeout=50)
        assert process.returncode == 0, output
        samples = json.loads((root / 'ros-suite-messages.json').read_text())
        assert any(x['translation'] == [3.0, 0.0, 1.0] for x in samples['tf']['last']), samples
        assert len(samples['joints']['last']['names']) == 9, samples
        assert len(samples['joints']['last']['positions']) == 9, samples
        assert samples['rgb']['last']['width'] == 320 and samples['rgb']['last']['unique_bytes'] > 16, samples
        assert samples['points']['last']['width'] > 0 and {'x','y','z'} <= set(samples['points']['last']['fields']), samples
        capture('/World/RosCamera', root / 'ros-publishers.png')
        call('simulation.stop')
        # Workflows must remain usable across an ordinary Stop -> Play cycle.
        (root / 'ros-suite-first-messages.json').write_text(json.dumps(samples, indent=2))
        ready.unlink()
        process = subprocess.Popen([str(ISAAC_ROOT / 'python.bat'), str(Path(__file__).resolve()),
            '--subscriber', str(root)], env=_ros_environment(), stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
        deadline = time.monotonic() + 15
        while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.1)
        assert ready.exists(), process.communicate(timeout=2)[0]
        call('simulation.play')
        output, _ = process.communicate(timeout=50)
        assert process.returncode == 0, output
        samples = json.loads((root / 'ros-suite-messages.json').read_text())
        call('simulation.stop')
        for graph in created:
            result = call('ros2.delete_workflow', {'graph_path': graph, 'preview': False})
            assert result['readback']['prim_present'] is False
            if graph in owned_products:
                assert c.send_command('scene.get_prim_info', {'prim_path': owned_products[graph]})['status'] == 'error'
        created.clear()
        assert not call('ros2.list_workflows')['data']['workflows']
        call('sensors.create_camera', {'prim_path': '/World/RosResetCamera', 'resolution': [64,64]})
        call('ros2.create_camera_publisher', {'graph_path': '/World/RosResetGraph',
            'camera_prim_path': '/World/RosResetCamera', 'preview': False, 'domain_id': 42})
        call('stage.new', {'scratch_stage': True, 'scratch_root': str(root), 'preview': False})
        reset = call('simulation.execute_script', {'code':
            'from isaac_sim_mcp_extension.handlers.ros2 import _OWNED_RENDER_PRODUCTS\nprint(len(_OWNED_RENDER_PRODUCTS))'})
        assert reset['data']['stdout'].strip() == '0', reset
        print(json.dumps({'status': 'success', 'messages': samples}, indent=2))
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
        call('simulation.stop')
        for graph in created:
            call('ros2.delete_workflow', {'graph_path': graph, 'preview': False})
        call('stage.new', {'scratch_stage': True, 'scratch_root': str(root), 'preview': False})
        (root / 'ros-suite-evidence.json').write_text(json.dumps(evidence, indent=2), encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--subscriber', type=Path)
    args = parser.parse_args()
    subscriber(args.subscriber) if args.subscriber else parent()
