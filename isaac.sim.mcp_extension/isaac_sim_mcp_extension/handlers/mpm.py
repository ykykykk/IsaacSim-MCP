"""Guarded bridge to the optional sany.granular_mpm extension, not another solver."""

import hashlib
import json
from functools import partial

from .. import usd_transactions as transactions
from ..workflow_context import context


class MPMRequestError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def register(registry, adapter):
    for action in ("get_status", "get_config", "update_config", "request_rebuild", "list_configs"):
        registry[f"mpm.{action}"] = partial(_dispatch, adapter, action)


def _plugin():
    import omni.kit.app

    manager = omni.kit.app.get_app().get_extension_manager()
    if not manager.is_extension_enabled("sany.granular_mpm"):
        raise MPMRequestError("MPM_EXTENSION_DISABLED", "Enable sany.granular_mpm first; it is never auto-enabled by a tool")
    from sany.granular_mpm import agent_api
    from sany.granular_mpm.config import CONFIG_ATTR, ScenarioConfig
    from sany.granular_mpm.extension import GranularMPMExtension

    ext = GranularMPMExtension.instance
    if ext is None:
        raise MPMRequestError("MPM_EXTENSION_NOT_READY", "MPM extension has not finished starting")
    return agent_api, CONFIG_ATTR, ScenarioConfig, ext


def _configuration(adapter, expected_stage, prim_path, attr_name, config_type):
    from pxr import Sdf

    stage = adapter.get_stage()
    if stage is None or stage.GetRootLayer().identifier != expected_stage:
        raise MPMRequestError("MPM_STAGE_CHANGED", "Stage identity differs; read get_mpm_status again")
    path = Sdf.Path(prim_path)
    if not path.IsAbsolutePath() or not path.IsPrimPath() or path == Sdf.Path.absoluteRootPath:
        raise ValueError("prim_path must be an absolute prim path, not a property or pseudo-root")
    prim = stage.GetPrimAtPath(path)
    attr = prim.GetAttribute(attr_name) if prim else None
    if not attr or not attr.HasAuthoredValueOpinion() or attr.GetTypeName() != Sdf.ValueTypeNames.String:
        raise MPMRequestError("MPM_CONFIG_NOT_FOUND", f"No authored string {attr_name} at {prim_path}")
    text = attr.Get()
    authored = json.loads(text)
    if not isinstance(authored, dict):
        raise ValueError("MPM config must be a JSON object")
    cfg = config_type.from_json(text)
    cfg.prim_path = prim_path
    return stage, attr, authored, cfg, hashlib.sha256(text.encode("utf-8")).hexdigest()


def _require_idle(ext):
    import omni.timeline

    if not omni.timeline.get_timeline_interface().is_stopped():
        raise MPMRequestError("TIMELINE_NOT_STOPPED", "Stop simulation explicitly before changing or rebuilding MPM")
    if ext._building or ext._pending_config is not None:
        raise MPMRequestError("MPM_BUILD_BUSY", "A material build is running or queued; read status instead of resubmitting")


def _dispatch(adapter, action, expected_stage=None, prim_path=None,
              expected_config_sha256=None, changes=None, preview=True, offset=0, limit=50):
    try:
        api, attr_name, config_type, ext = _plugin()
        if action == "get_status":
            return {"status": "success", **api.status(), "context": context(adapter.get_stage())}
        if action == "list_configs":
            if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
                raise ValueError("offset must be non-negative; limit must be 1..100")
            stage = adapter.get_stage()
            if stage is None:
                raise ValueError("No stage")
            rows, found = [], 0
            for prim in stage.Traverse():
                item = prim.GetAttribute(attr_name)
                if item and item.HasAuthoredValueOpinion():
                    if found >= offset:
                        rows.append({"prim_path": str(prim.GetPath())})
                    found += 1
                    if len(rows) > limit:
                        break
            return {"status": "success", "context": context(stage), "configs": rows[:limit],
                    "next_offset": offset + limit if len(rows) > limit else None,
                    "scope": "loaded active prims only; payloads are not auto-loaded"}
        stage, attr, authored, cfg, revision = _configuration(
            adapter, expected_stage, prim_path, attr_name, config_type,
        )
        snapshot = {
            "stage": expected_stage, "prim_path": prim_path,
            "authored_config": authored, "effective_config": json.loads(cfg.to_json()),
            "config_sha256": revision,
        }
        if action == "get_config":
            snapshot.update(_config_sources(stage, attr, cfg, ext, config_type))
            return {"status": "success", **snapshot}
        if not isinstance(preview, bool):
            raise ValueError("preview must be boolean")
        if not expected_config_sha256 or expected_config_sha256 != revision:
            raise MPMRequestError("MPM_CONFIG_CHANGED", "Configuration revision differs; read get_mpm_config again")
        _require_idle(ext)
        if action == "update_config":
            if not isinstance(changes, dict) or not changes:
                raise ValueError("changes must be a non-empty object")
            unknown = changes.keys() - (config_type.__dataclass_fields__.keys() - {"prim_path"})
            if unknown:
                raise ValueError(f"Unknown or protected fields: {sorted(unknown)}")
            proposed = {**authored, **changes}
            text = json.dumps(proposed, ensure_ascii=False, allow_nan=False, sort_keys=True)
            cfg = config_type.from_json(text)
            cfg.prim_path = prim_path
            cfg.validate()
            result = {"status": "success", "preview": preview, "applied": False,
                      "stage": expected_stage, "prim_path": prim_path,
                      "changes": changes, "effective_config": json.loads(cfg.to_json()),
                      "requires_rebuild": True, "saved": False}
            if preview:
                return result
            from pxr import Usd

            layer = stage.GetSessionLayer()
            if not layer.permissionToEdit:
                raise MPMRequestError("MPM_SESSION_READ_ONLY", "Session layer is not editable")
            before = transactions.capture(stage, properties=[(layer, attr.GetPath())])
            try:
                with Usd.EditContext(stage, layer):
                    if not attr.Set(text):
                        raise RuntimeError("USD refused the MPM configuration edit")
                if attr.Get() != text:
                    raise RuntimeError("MPM configuration read-back differs")
            except Exception as exc:
                return transactions.failure(stage, before, exc, "MPM_CONFIG_WRITE_FAILED")
            result["transaction_id"] = transactions.retain(stage, before)
            result.update(applied=True, config_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                          readback={"authored_config": json.loads(attr.Get()), "layer": layer.identifier})
            return result
        cfg.validate()
        if adapter.get_simulation_state().get("engine") != "physx":
            raise MPMRequestError("MPM_BACKEND_UNSUPPORTED", "This particle extension requires the PhysX host backend")
        if preview:
            return {"status": "success", "preview": True, "applied": False, **snapshot}
        # The plugin's asynchronous builder remains the sole owner of the material.
        if getattr(api, "API_VERSION", 0) < 2:
            raise MPMRequestError("MPM_API_VERSION_UNSUPPORTED", "MPM provider API 2 is required for tracked non-authoring builds")
        queued = ext.request_build(cfg, author=False, context=context(stage), authored_hash=revision)
        return {"status": "success", "preview": False, "applied": True,
                "job_id": queued["job_id"], "data": queued,
                "readback": queued, "saved": False, "completed": False,
                "message": "Rebuild queued, not completed; read get_mpm_status"}
    except MPMRequestError as exc:
        return {"status": "error", "code": exc.code, "message": str(exc), "applied": False}
    except (ValueError, TypeError) as exc:
        return {"status": "error", "code": "INVALID_MPM_CONFIG", "message": str(exc), "applied": False}
    except Exception as exc:
        return {"status": "error", "code": "MPM_OPERATION_FAILED",
                "message": f"{type(exc).__name__}: {exc}", "applied": None}


def _config_sources(stage, attr, cfg, ext, config_type):
    from pxr import Sdf

    def effective(text):
        parsed = config_type.from_json(text)
        parsed.prim_path = cfg.prim_path
        return json.loads(parsed.to_json())

    current = json.loads(cfg.to_json())
    runtime = json.loads(ext.runtime.config.to_json()) if ext.runtime and ext.runtime.config.prim_path == cfg.prim_path else None
    layers = []
    specs = [spec for spec in attr.GetPropertyStack() if spec.HasInfo("default")]
    for spec in specs[:16]:
        layer = spec.layer
        disk_value = None
        if layer.realPath and not layer.anonymous:
            disk_layer = Sdf.Layer.OpenAsAnonymous(layer.realPath)
            if disk_layer is None:
                raise RuntimeError("Cannot read owning layer on disk: " + layer.realPath)
            disk_spec = disk_layer.GetAttributeAtPath(spec.path)
            if disk_spec and disk_spec.HasInfo("default"):
                disk_value = json.loads(disk_spec.default)
        layers.append({"layer": layer.identifier, "spec_path": str(spec.path), "dirty": bool(layer.dirty),
                       "session": layer == stage.GetSessionLayer(), "authored_config": json.loads(spec.default),
                       "disk_config": disk_value})
    persistent = next((item for item in layers if not item["session"]), None)
    disk_effective = effective(json.dumps(persistent["disk_config"])) if persistent and persistent["disk_config"] is not None else None
    requires_save = disk_effective != current
    return {"context": context(stage), "layer_configs": layers, "sources_truncated": len(specs) > 16,
            "runtime_config": runtime, "requires_rebuild": runtime != current,
            "requires_save": requires_save, "differences": {
                "runtime_fields": sorted(key for key in current if runtime is None or current[key] != runtime.get(key)),
                "disk_fields": sorted(key for key in current if disk_effective is None or current[key] != disk_effective.get(key))}}
