"""Typed source commits and guarded undo; the owning plugin defines migration."""

import time
from collections import OrderedDict

from .. import usd_transactions
from ..workflow_context import context, register_reset, require_context

_plans = OrderedDict()
register_reset("source_plans", _plans.clear)


def register(registry, adapter):
    registry["workflow.preview_source_commit"] = lambda **p: _call(adapter, "preview", **p)
    registry["workflow.commit_source_changes"] = lambda **p: _call(adapter, "commit", **p)
    registry["workflow.undo_stage_transaction"] = lambda **p: _call(adapter, "undo", **p)


def _provider():
    import omni.kit.app
    if not omni.kit.app.get_app().get_extension_manager().is_extension_enabled("bauma.save_to_source"):
        raise ValueError("SOURCE_PROVIDER_UNAVAILABLE: enable bauma.save_to_source explicitly")
    from bauma.save_to_source import agent_api
    if getattr(agent_api, "API_VERSION", 0) != 1:
        raise ValueError("SOURCE_PROVIDER_UNSUPPORTED: API 1 required")
    return agent_api


def _call(adapter, action, **params):
    try:
        for key in ("save", "preview", "allow_shared"):
            if key in params and type(params[key]) is not bool:
                raise ValueError(f"{key} must be a boolean")
        import omni.timeline
        if not omni.timeline.get_timeline_interface().is_stopped():
            raise ValueError("TIMELINE_NOT_STOPPED")
        stage = adapter.get_stage()
        if stage is None:
            raise ValueError("No stage")
        if action == "undo":
            return usd_transactions.undo(stage, **params)
        provider = _provider()
        if action == "preview":
            expected = params.pop("expected_context")
            require_context(stage, expected)
            plan = provider.preview(stage, **params)
            while len(_plans) >= 16:
                _plans.popitem(last=False)
            _plans[plan["plan_id"]] = (context(stage), time.monotonic() + 600)
            return {"status": "success", "preview": True, "applied": False, "data": {**plan, "context": context(stage)}}
        token = params["plan_id"]
        item = _plans.get(token)
        if item is None or item[1] < time.monotonic():
            raise ValueError("STALE_PLAN: source commit preview expired")
        require_context(stage, item[0])
        return provider.commit(stage, **params)
    except (TypeError, ValueError) as exc:
        return {"status": "error", "code": "INVALID_WORKFLOW_REQUEST", "message": str(exc), "applied": False}
    except Exception as exc:
        return {"status": "error", "code": "WORKFLOW_OPERATION_FAILED",
                "message": f"{type(exc).__name__}: {exc}", "applied": None}
