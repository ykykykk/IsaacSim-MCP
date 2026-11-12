"""The provider's public builder, not legacy request_rebuild, owns tracked jobs."""

from types import SimpleNamespace
from unittest.mock import Mock

from isaac_sim_mcp_extension.handlers import mpm


def test_rebuild_uses_tracked_non_authoring_builder(monkeypatch):
    stage = object()
    cfg = SimpleNamespace(validate=Mock(), to_json=lambda: '{}')
    queued = {'job_id': 'mpm-test', 'state': 'queued', 'terminal': False}
    ext = SimpleNamespace(request_build=Mock(return_value=queued))
    api = SimpleNamespace(API_VERSION=2, request_rebuild=Mock())
    monkeypatch.setattr(mpm, '_plugin', lambda: (api, 'config', object, ext))
    monkeypatch.setattr(mpm, '_configuration', lambda *a: (stage, None, {}, cfg, 'revision'))
    monkeypatch.setattr(mpm, '_require_idle', lambda _: None)
    monkeypatch.setattr(mpm, 'context', lambda _: {'stage_id': 'scratch'})
    adapter = SimpleNamespace(get_simulation_state=lambda: {'engine': 'physx'})
    result = mpm._dispatch(adapter, 'request_rebuild', 'scratch.usda', '/Test', 'revision', preview=False)
    assert result['status'] == 'success'
    assert result['job_id'] == 'mpm-test' and result['completed'] is False
    ext.request_build.assert_called_once_with(
        cfg, author=False, context={'stage_id': 'scratch'}, authored_hash='revision')
    api.request_rebuild.assert_not_called()

