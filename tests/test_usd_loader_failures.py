"""A failed USD load must not be returned as a successful prim path."""

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.fixture
def loader_module(monkeypatch):
    monkeypatch.setitem(sys.modules, "requests", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "isaacsim.core.utils.stage", SimpleNamespace(add_reference_to_stage=Mock()))
    path = Path(__file__).resolve().parents[1] / "isaac.sim.mcp_extension/isaac_sim_mcp_extension/usd.py"
    spec = importlib.util.spec_from_file_location("usd_loader_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("layer", [None, SimpleNamespace(defaultPrim="")])
def test_unresolved_asset_is_rejected_before_stage_mutation(loader_module, monkeypatch, layer):
    stage = Mock()
    monkeypatch.setattr(loader_module.omni.usd, "get_context", lambda: SimpleNamespace(get_stage=lambda: stage), raising=False)
    monkeypatch.setattr(loader_module.Sdf, "Layer", SimpleNamespace(FindOrOpen=lambda url: layer), raising=False)
    loader = object.__new__(loader_module.USDLoader)
    with pytest.raises(ValueError):
        loader._load_prim("missing.usda", "/World/Missing")
    stage.DefinePrim.assert_not_called()


def test_load_error_preserves_cause_instead_of_returning_error_dict(loader_module):
    loader = object.__new__(loader_module.USDLoader)
    cause = ValueError("invalid USD syntax")
    loader._load_prim = Mock(side_effect=cause)
    with pytest.raises(RuntimeError, match="invalid USD syntax") as error:
        loader.load_usd_from_url("broken.usda", "/World/Broken")
    assert error.value.__cause__ is cause
