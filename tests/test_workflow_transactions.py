"""Response-envelope and failed-rollback contracts without an Isaac host."""
from types import SimpleNamespace

from isaac_sim_mcp_extension import usd_transactions
from isaac_sim_mcp_extension.handlers import stage_composition
from isaac_sim_mcp_extension.responses import normalize_response


def test_batch_preview_token_survives_transport_normalization(monkeypatch):
    monkeypatch.setattr(stage_composition, '_require_stopped', lambda _: None)
    monkeypatch.setattr(stage_composition, 'set_typed_attribute', lambda *a, **kw: {'status': 'success'})
    monkeypatch.setattr(stage_composition, '_batch_snapshot', lambda *a: {'context': {'stage_id': 'test-stage'}})
    monkeypatch.setattr(stage_composition, '_remember_plan', lambda *a: 'plan-test')
    monkeypatch.setattr(stage_composition, 'get_stage_composition', lambda *a, **kw: {'data': {}})
    result = stage_composition.apply_stage_batch(SimpleNamespace(get_stage=lambda: object()),
        [{'operation': 'set_attribute', 'prim_path': '/Test', 'attribute': 'test:value', 'type_name': 'int', 'value': 1}])
    wire = normalize_response(result)
    assert wire['data']['plan_id'] == 'plan-test'
    assert wire['data']['context']['stage_id'] == 'test-stage'


def test_failed_restore_is_partial_and_preserves_original_reason():
    layer = SimpleNamespace(identifier='test', ExportToString=lambda: 'changed', ImportFromString=lambda _: False)
    stage = SimpleNamespace(SetLoadRules=lambda _: None, SetEditTarget=lambda _: None)
    snapshot = {'layers': [{'layer': layer, 'text': 'before', 'hash': usd_transactions.digest('before')}],
                'load_rules': None, 'edit_target': None}
    result = usd_transactions.failure(stage, snapshot, ValueError('original failure'))
    assert result['status'] == 'partial'
    assert result['code'] == 'ROLLBACK_FAILED'
    assert result['message'] == 'original failure'
    assert result['readback']['rolled_back'] is False
    assert result['readback']['layers'][0]['error'] == 'USD refused layer restoration'
