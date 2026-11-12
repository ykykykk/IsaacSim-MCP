"""MCP-only configuration and domain isolation regressions."""
import json

import pytest
from mcp.server.fastmcp import FastMCP

from isaac_mcp.config import KEYS, resolve
from isaac_mcp.tool_inventory import tool_names
from isaac_mcp.tools import register_all_tools


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    for key in KEYS.values():
        monkeypatch.delenv(key, raising=False)
    path = tmp_path / 'config.json'
    path.write_text('{}', encoding='utf-8')
    monkeypatch.setenv('ISAAC_MCP_CONFIG', str(path))
    return path


def test_config_precedence(isolated, monkeypatch):
    isolated.write_text(json.dumps({'port': 9121}), encoding='utf-8')
    assert resolve()['port'] == 9121
    monkeypatch.setenv('ISAAC_MCP_PORT', '9122')
    assert resolve()['port'] == 9122
    assert resolve(port=9123)['port'] == 9123
    assert resolve(port=9123)['sources']['port'] == 'argument'


@pytest.mark.parametrize('port', [0, 65536, True, 'bad'])
def test_config_rejects_invalid_port(isolated, port):
    with pytest.raises((ValueError, TypeError)):
        resolve(port=port)


def test_config_rejects_unknown_keys(isolated):
    isolated.write_text('{"secret": "not-accepted"}', encoding='utf-8')
    with pytest.raises(ValueError, match='Unknown keys'):
        resolve()


def test_domains_filter_actual_registration(monkeypatch):
    monkeypatch.setenv('ISAAC_MCP_TOOL_PROFILE', 'legacy')
    monkeypatch.setenv('ISAAC_MCP_TOOL_DOMAINS', 'scene,physics')
    mcp = FastMCP('mcp-only-contract')
    register_all_tools(mcp, lambda: None)
    tools = {tool.name: tool for tool in mcp._tool_manager.list_tools()}
    assert set(tools) == set(tool_names('legacy'))
    assert 'get_capabilities' in tools
    assert 'apply_stage_batch' in tools
    assert 'request_mpm_rebuild' not in tools
    assert tools['get_capabilities'].annotations.readOnlyHint is True
    assert tools['apply_stage_batch'].annotations.readOnlyHint is False
    assert mcp.tool_domains == ['core', 'physics', 'scene']


def test_unknown_domains_fail_before_use(monkeypatch):
    monkeypatch.setenv('ISAAC_MCP_TOOL_DOMAINS', 'not-a-domain')
    with pytest.raises(ValueError):
        register_all_tools(FastMCP('bad-domain'), lambda: None)
