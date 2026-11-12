"""Opt-in real-provider acceptance, restricted to an isolated scratch host."""

import asyncio
import base64
import json
import os
import sys
import time
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main():
    root = Path(os.environ['ISAAC_MCP_VALIDATION_ROOT']).resolve(strict=True)
    source = root / ('source-bridge-' + str(time.time_ns()) + '.usda')
    evidence = []
    server = StdioServerParameters(command=sys.executable, args=['-m', 'isaac_mcp.server'], env=dict(os.environ))
    async with stdio_client(server) as (read, write), ClientSession(read, write) as session:
        await session.initialize()

        async def call(name, args=None, *, error=False):
            response = await session.call_tool(name, args or {})
            value = json.loads(next(x.text for x in response.content if x.type == 'text'))
            evidence.append({'tool': name, 'response': value})
            assert value['status'] == ('error' if error else 'success'), (name, value)
            return value, response

        async def script(code):
            setup = 'import json, omni.usd\nfrom pxr import Usd\nstage = omni.usd.get_context().get_stage()\n'
            value, _ = await call('execute_script', {'code': setup + code})
            return json.loads(value['data']['stdout'].strip().splitlines()[-1])

        cap, _ = await call('get_capabilities')
        runtime = cap['data']['runtime']
        assert runtime['isaac_sim_version'].startswith('6.2.')
        assert Path(runtime['log_file']).parent == root
        assert Path(runtime['root_identifier']).parent == root
        assert all(x['enabled'] for x in runtime['provider_capabilities'].values())
        await call('stop_simulation')
        initial = await script("""
import json, omni.usd
stage = omni.usd.get_context().get_stage()
print(json.dumps([str(p.GetPath()) for p in stage.TraverseAll()
 if str(p.GetPath()) != '/World' and not str(p.GetPath()).startswith(('/Render', '/OmniverseKit'))]))
""")
        assert not initial, initial
        try:
            fixture = await script(f"""
import json, omni.usd
from pxr import Usd, UsdGeom, Sdf
from sany.granular_mpm.config import ScenarioConfig, EmitterConfig, CONFIG_ATTR
stage = omni.usd.get_context().get_stage()
owner = Usd.Stage.CreateNew({str(source)!r})
p = UsdGeom.Xform.Define(owner, '/Asset').GetPrim()
owner.SetDefaultPrim(p)
p.CreateAttribute('mcp_test:value', Sdf.ValueTypeNames.Float).Set(1.0)
p.CreateAttribute('mcp_test:untouched', Sdf.ValueTypeNames.String).Set('keep')
owner.GetRootLayer().Save()
asset = stage.DefinePrim('/World/SourceBridge', 'Xform')
asset.GetReferences().AddReference({str(source)!r})
with Usd.EditContext(stage, stage.GetSessionLayer()):
 asset.GetAttribute('mcp_test:value').Set(2.0)
cfg = ScenarioConfig(prim_path='/World/MPMBridge', voxel_size=0.1, particle_spacing=0.05,
 domain_lo=[-0.5,-0.5,-0.2], domain_hi=[0.5,0.5,1.0], max_iterations=4,
 emitters=[EmitterConfig(kind='box', lo=(-0.1,-0.1,0.1), hi=(0.1,0.1,0.3))])
cfg.validate()
stage.DefinePrim(cfg.prim_path, 'Xform').CreateAttribute(CONFIG_ATTR, Sdf.ValueTypeNames.String).Set(cfg.to_json())
print(json.dumps({{'stage': stage.GetRootLayer().identifier}}))
""")
            before_bytes = source.read_bytes()
            status, _ = await call('get_mpm_status')
            assert status['data']['build'] == 'not_built', status
            configs, _ = await call('list_mpm_configs')
            assert configs['data']['configs'] == [{'prim_path': '/World/MPMBridge'}], configs
            params = {'expected_stage': fixture['stage'], 'prim_path': '/World/MPMBridge'}
            config, _ = await call('get_mpm_config', params)
            context = config['data']['context']
            save_args = {'expected_context': context, 'prim_path': '/World/SourceBridge',
                         'attributes': ['mcp_test:value']}
            preview, _ = await call('preview_source_commit', save_args)
            assert source.read_bytes() == before_bytes
            plan = preview['data']['plan_id']
            committed, _ = await call('commit_source_changes', {'plan_id': plan})
            assert committed['data']['saved'] is True
            saved_bytes, saved_mtime = source.read_bytes(), source.stat().st_mtime_ns
            assert saved_bytes != before_bytes
            repeated, _ = await call('commit_source_changes', {'plan_id': plan})
            assert repeated['data']['replayed'] is True
            assert source.stat().st_mtime_ns == saved_mtime and source.read_bytes() == saved_bytes
            values = await script(f"""
from pxr import Sdf
stage = omni.usd.get_context().get_stage()
disk = Sdf.Layer.OpenAsAnonymous({str(source)!r})
print(json.dumps({{'value': disk.GetAttributeAtPath('/Asset.mcp_test:value').default,
 'untouched': disk.GetAttributeAtPath('/Asset.mcp_test:untouched').default,
 'session_default': stage.GetSessionLayer().GetAttributeAtPath('/World/SourceBridge.mcp_test:value').HasInfo('default')}}))
""")
            assert values == {'value': 2.0, 'untouched': 'keep', 'session_default': False}, values
            await script("""
from pxr import Usd
stage = omni.usd.get_context().get_stage()
with Usd.EditContext(stage, stage.GetSessionLayer()):
 stage.GetPrimAtPath('/World/SourceBridge').GetAttribute('mcp_test:value').Set(3.0)
print(json.dumps({'changed': True}))
""")
            config, _ = await call('get_mpm_config', params)
            save_args['expected_context'] = config['data']['context']
            stale, _ = await call('preview_source_commit', save_args)
            await script("""
with Usd.EditContext(stage, stage.GetSessionLayer()):
 stage.GetPrimAtPath('/World/SourceBridge').GetAttribute('mcp_test:value').Set(4.0)
print(json.dumps({'changed': True}))
""")
            await call('commit_source_changes', {'plan_id': stale['data']['plan_id']}, error=True)
            assert source.read_bytes() == saved_bytes
            config, _ = await call('get_mpm_config', params)
            patch = {**params, 'expected_config_sha256': config['data']['config_sha256'],
                     'changes': {'max_iterations': 5}}
            preview, _ = await call('update_mpm_config', patch)
            assert preview['data']['applied'] is False
            updated, _ = await call('update_mpm_config', {**patch, 'preview': False})
            assert updated['readback']['authored_config']['max_iterations'] == 5
            await call('update_mpm_config', {**patch, 'preview': False}, error=True)
            await call('undo_stage_transaction', {'transaction_id': updated['data']['transaction_id'], 'preview': False})
            config, _ = await call('get_mpm_config', params)
            assert config['data']['config_sha256'] == patch['expected_config_sha256']
            request = {**params, 'expected_config_sha256': config['data']['config_sha256']}
            await call('request_mpm_rebuild', request)
            queued, _ = await call('request_mpm_rebuild', {**request, 'preview': False})
            job_id = queued['data']['job_id']
            deadline = time.monotonic() + 180
            while True:
                job, _ = await call('get_job_status', {'job_id': job_id})
                if job['data']['terminal']:
                    assert job['data']['state'] == 'succeeded', job
                    break
                assert time.monotonic() < deadline, job
                await asyncio.sleep(0.5)
            status, _ = await call('get_mpm_status')
            assert status['data']['build'] == 'ready', status
            assert 0 < status['data']['runtime']['particles'] < 1000, status
            assert status['data']['timeline'] == 'stopped'
            config, _ = await call('get_mpm_config', params)
            assert config['data']['requires_rebuild'] is False
            await call('create_light', {'prim_path': '/World/BridgeLight', 'intensity': 2500})
            await call('create_camera', {'prim_path': '/World/BridgeCamera', 'position': [1,1,1], 'resolution': [640,480]})
            await script("""
from pxr import Gf, UsdGeom
p = stage.GetPrimAtPath('/World/BridgeCamera')
UsdGeom.Xformable(p).MakeMatrixXform().Set(Gf.Matrix4d().SetLookAt(Gf.Vec3d(1,1,0.8), Gf.Vec3d(0,0,0.15), Gf.Vec3d(0,0,1)).GetInverse())
print(json.dumps({'aimed': True}))
""")
            await call('play_simulation')
            for index in range(2):
                await asyncio.sleep(0.5)
                _, image = await call('capture_camera_output', {'prim_path': '/World/BridgeCamera', 'output_type': 'rgb', 'return_mode': 'image'})
                (root / f'mpm-bridge-{index}.png').write_bytes(base64.b64decode(next(x.data for x in image.content if x.type == 'image')))
                status, _ = await call('get_mpm_status')
                assert not status['data']['runtime']['error'], status
            await call('stop_simulation')
            assert source.read_bytes() == saved_bytes
        finally:
            await call('stop_simulation')
            # Close this exact disposable stage; provider handles runtime teardown.
            await call('new_stage', {'scratch_stage': True, 'scratch_root': str(root), 'preview': False})
            (root / 'provider-bridges-evidence.json').write_text(json.dumps(evidence, indent=2), encoding='utf-8')
    print(json.dumps({'status': 'success', 'calls': len(evidence), 'source_file': str(source)}))


if __name__ == '__main__':
    asyncio.run(main())
