"""MCP-only live regression: refuses non-verifier hosts and populated stages."""
import argparse
import json
import tempfile
from pathlib import Path

from isaac_mcp.connection import IsaacConnection


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--scratch-root', type=Path, required=True)
    args = parser.parse_args()
    scratch = args.scratch_root.resolve(strict=True)
    c = IsaacConnection(host='127.0.0.1', port=args.port)
    checks = []
    assets = Path(tempfile.mkdtemp(prefix="fixture-", dir=scratch))

    def call(name, params=None, success=True):
        result = c.send_command(name, params or {})
        if success:
            assert result['status'] == 'success', (name, result)
        return result

    def script(code):
        prefix = f"from pxr import Usd, UsdGeom, Sdf\nimport omni.usd\nstage = omni.usd.get_context().get_stage()\nsub = Sdf.Layer.Find({str(assets / 'sub.usda')!r})\n"
        result = call('simulation.execute_script', {'code': prefix + code})['data']
        assert not result.get('stderr'), result
        return result.get('stdout', '').strip()

    runtime = call('system.get_capabilities')['data']['runtime']
    assert runtime['isaac_sim_version'].startswith('6.2.')
    assert runtime['extension_code_version'] == '0.7.0'
    assert all(p['enabled'] is False for p in runtime['provider_capabilities'].values())
    assert Path(runtime['log_file']).resolve().parent == scratch, 'Refuse a non-verifier host'
    composition = call('stage.get_composition')['data']
    assert composition['root_layer']['anonymous'], 'Refuse a file-backed user stage'
    assert all(p.startswith('/Render') or p in {'/OmniverseKit_Persp', '/OmniverseKit_Front', '/OmniverseKit_Top', '/OmniverseKit_Right'} for p in composition['prim_paths']), 'Refuse a populated stage'
    checks.append('isolated_identity_and_no_external_providers')
    guard = {'scratch_stage': True, 'scratch_root': str(scratch), 'preview': False}
    call('stage.new', guard)
    try:
        script(f'''from pxr import Usd, UsdGeom, Sdf
import omni.usd
stage = omni.usd.get_context().get_stage()
UsdGeom.Xform.Define(stage, '/World')
UsdGeom.Xform.Define(stage, '/World/Probe')
stage.SetDefaultPrim(stage.GetPrimAtPath('/World'))
sub = Sdf.Layer.CreateNew({str(assets / 'sub.usda')!r})
Sdf.CreatePrimInLayer(sub, '/World/Probe')
sub.Save()
extra = Sdf.Layer.CreateNew({str(assets / 'extra.usda')!r})
extra.Save()
stage.GetRootLayer().subLayerPaths.append(sub.identifier)
stage.SetEditTarget(sub)
''')
        attr = {'operation': 'set_attribute', 'prim_path': '/World/Probe', 'attribute': 'mcp:value', 'type_name': 'int', 'value': 7}
        ops = [{'operation': 'edit_sublayer', 'action': 'add', 'layer_path': str(assets / 'extra.usda')}, attr]
        snapshot_code = "print([layer.ExportToString() for layer in (stage.GetRootLayer(), stage.GetSessionLayer(), sub)])"
        before = script(snapshot_code)
        plan = call('stage.apply_batch', {'operations': ops})['data']
        assert plan['plan_id'] and plan['context']['stage_id']
        assert script(snapshot_code) == before
        applied = call('stage.apply_batch', {'operations': ops, 'plan_id': plan['plan_id'], 'preview': False})
        transaction = applied['data']['transaction_id']
        value = call('stage.get_attribute', {'prim_path': '/World/Probe', 'attribute': 'mcp:value', 'include_source': True})['data']
        assert value['value'] == 7
        assert Path(value['source']['opinions'][0]['layer']) == assets / 'sub.usda'
        call('workflow.undo_stage_transaction', {'transaction_id': transaction, 'preview': True})
        call('workflow.undo_stage_transaction', {'transaction_id': transaction, 'preview': False})
        assert script(snapshot_code) == before
        checks.append('preview_apply_multilayer_undo_and_attribute_source')
        stale = call('stage.apply_batch', {'operations': [attr]})['data']['plan_id']
        script("stage.GetPrimAtPath('/World/Probe').CreateAttribute('mcp:other', Sdf.ValueTypeNames.Int).Set(3)")
        rejected = call('stage.apply_batch', {'operations': [attr], 'plan_id': stale, 'preview': False}, False)
        assert rejected['code'] == 'STALE_PLAN', rejected
        checks.append('stale_plan_rejected')
        before_failure = script(snapshot_code)
        bad = [ops[0], {**attr, 'value': 'not-an-integer'}]
        failed = call('stage.apply_batch', {'operations': bad, 'preview': False}, False)
        assert failed['code'] == 'BATCH_ROLLED_BACK' and failed['readback']['rolled_back'], failed
        assert script(snapshot_code) == before_failure
        checks.append('second_operation_failure_restores_all_touched_layers')
        script('''from isaac_sim_mcp_extension import usd_transactions as tx
path = Sdf.Path('/World/Probe.mcp:temporary')
snapshot = tx.capture(stage, properties=[(sub, path)])
stage.GetPrimAtPath('/World/Probe').CreateAttribute('mcp:temporary', Sdf.ValueTypeNames.Int).Set(9)
assert tx.restore(stage, snapshot)['rolled_back']
assert not sub.GetPropertyAtPath(path)
''')
        checks.append('property_snapshot_restore')
        page = call('stage.get_composition', {'root_path': '/World', 'limit': 1})['data']
        assert page['truncated'] and page['next_offset'] == 1
        page2 = call('stage.get_composition', {'root_path': '/World', 'offset': 1, 'limit': 1})['data']
        assert page2['prim_paths'] == ['/World/Probe']
        checks.append('bounded_composition_pagination')
        output = assets / 'saved.usda'
        call('stage.save_as', {**guard, 'path': str(output)})
        assert output.is_file()
        old_context = call('stage.get_composition')['data']['context']
        call('stage.open', {**guard, 'path': str(output)})
        reopened = call('stage.get_composition', {'root_path': '/World'})['data']
        assert reopened['context']['stage_id'] != old_context['stage_id']
        assert '/World/Probe' in reopened['prim_paths']
        expired = call('stage.apply_batch', {'operations': [attr], 'plan_id': stale, 'preview': False}, False)
        assert expired['code'] == 'STALE_PLAN'
        checks.append('guarded_save_reopen_and_stage_identity_reset')
    finally:
        call('stage.new', guard)
        state = call('simulation.get_state')['data']
        assert state['timeline_state'] == 'stopped'
        c.disconnect()
    report = {'status': 'passed', 'runtime': runtime, 'checks': checks, 'cleanup': 'empty stopped stage; scratch files retained'}
    (scratch / 'live-report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
