"""Bounded, layer-specific in-memory transactions. Never saves files."""

import hashlib
import time
import uuid
from collections import OrderedDict
from pathlib import Path

from .workflow_context import context, require_context, register_reset

MAX_BYTES = 128 * 1024 * 1024
TTL_SECONDS = 600
_undo = OrderedDict()
register_reset("usd_transactions", _undo.clear)


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def disk_stamp(layer):
    if not layer.realPath:
        return None
    stat = Path(layer.realPath).stat()
    return (stat.st_mtime_ns, stat.st_size)


def _property_text(layer, path):
    from pxr import Sdf
    if not layer.GetPropertyAtPath(path):
        return None
    copy = Sdf.Layer.CreateAnonymous()
    Sdf.CreatePrimInLayer(copy, path.GetPrimPath())
    if not Sdf.CopySpec(layer, path, copy, path):
        raise RuntimeError(f"Cannot snapshot property: {path}")
    return copy.ExportToString()


def _record_text(record):
    if "path" in record:
        return _property_text(record["layer"], record["path"])
    return record["layer"].ExportToString()


def _hash(text):
    return digest(text) if text is not None else None


def capture(stage, layers=None, properties=None):
    if stage is None:
        raise ValueError("No stage")
    if properties is not None:
        records, size = [], 0
        for layer, path in properties:
            text = _property_text(layer, path)
            size += len(text.encode("utf-8")) if text is not None else 0
            if size > MAX_BYTES:
                raise ValueError("Property transaction exceeds memory budget")
            records.append({"layer": layer, "path": path, "text": text, "hash": _hash(text)})
        return {"layers": records, "bytes": size, "context": context(stage),
                "edit_target": stage.GetEditTarget(), "load_rules": stage.GetLoadRules()}
    if layers is None:
        layers = [stage.GetRootLayer(), stage.GetSessionLayer(), stage.GetEditTarget().GetLayer()]
    records, size = [], 0
    for layer in dict.fromkeys(layers):
        text = layer.ExportToString()
        size += len(text.encode("utf-8"))
        if size > MAX_BYTES:
            raise ValueError(f"Transaction snapshot exceeds {MAX_BYTES} bytes at {layer.identifier}; no edit applied")
        records.append({"layer": layer, "text": text, "hash": digest(text)})
    return {"layers": records, "bytes": size, "context": context(stage),
            "edit_target": stage.GetEditTarget(), "load_rules": stage.GetLoadRules()}


def require_unchanged(stage, snapshot):
    require_context(stage, snapshot["context"])
    for record in snapshot["layers"]:
        if _hash(_record_text(record)) != record["hash"]:
            raise ValueError(f"STALE_PLAN: layer changed: {record['layer'].identifier}")
    if stage.GetLoadRules().GetRules() != snapshot["load_rules"].GetRules():
        raise ValueError("STALE_PLAN: payload load rules changed")


def restore(stage, snapshot):
    results = []
    for record in snapshot["layers"]:
        layer = record["layer"]
        try:
            if _hash(_record_text(record)) != record["hash"]:
                if "path" in record:
                    from pxr import Sdf
                    path = record["path"]
                    if record["text"] is None:
                        spec = layer.GetPropertyAtPath(path)
                        if spec:
                            spec.owner.RemoveProperty(spec)
                    else:
                        copy = Sdf.Layer.CreateAnonymous()
                        if not copy.ImportFromString(record["text"]) or not Sdf.CopySpec(copy, path, layer, path):
                            raise RuntimeError("USD refused property restoration")
                elif not layer.ImportFromString(record["text"]):
                    raise RuntimeError("USD refused layer restoration")
                if _hash(_record_text(record)) != record["hash"]:
                    raise RuntimeError("Layer restoration read-back differs")
            results.append({"layer": layer.identifier, "restored": True})
        except Exception as exc:
            results.append({"layer": layer.identifier, "restored": False, "error": str(exc)})
    try:
        stage.SetLoadRules(snapshot["load_rules"])
        stage.SetEditTarget(snapshot["edit_target"])
    except Exception as exc:
        results.append({"stage_state": True, "restored": False, "error": str(exc)})
    return {"rolled_back": all(item["restored"] for item in results), "layers": results}


def failure(stage, snapshot, error, code="USD_EDIT_FAILED"):
    rollback = restore(stage, snapshot)
    return {"status": "error" if rollback["rolled_back"] else "partial",
            "code": code if rollback["rolled_back"] else "ROLLBACK_FAILED",
            "message": str(error), "readback": rollback}


def retain(stage, snapshot):
    now = time.monotonic()
    for key in list(_undo):
        if _undo[key]["expires"] < now:
            _undo.pop(key)
    while _undo and (len(_undo) >= 8 or sum(x["before"]["bytes"] for x in _undo.values()) + snapshot["bytes"] > MAX_BYTES):
        _undo.popitem(last=False)
    token = "usd-" + uuid.uuid4().hex
    _undo[token] = {"before": snapshot, "after": [
        (r, _hash(_record_text(r)), r["layer"].dirty, disk_stamp(r["layer"]))
        for r in snapshot["layers"]], "rules": stage.GetLoadRules().GetRules(), "expires": now + TTL_SECONDS}
    return token


def undo(stage, transaction_id, preview=True):
    item = _undo.get(transaction_id)
    if item is None or item["expires"] < time.monotonic():
        _undo.pop(transaction_id, None)
        raise ValueError("Transaction not found or expired")
    require_context(stage, item["before"]["context"])
    if stage.GetLoadRules().GetRules() != item["rules"]:
        raise ValueError("Payload state changed after transaction")
    for record, fingerprint, dirty, stamp in item["after"]:
        layer = record["layer"]
        if _hash(_record_text(record)) != fingerprint or layer.dirty != dirty or disk_stamp(layer) != stamp:
            raise ValueError(f"Layer edited or saved after transaction: {layer.identifier}")
    if preview:
        return {"status": "success", "preview": True, "applied": False, "transaction_id": transaction_id}
    result = restore(stage, item["before"])
    _undo.pop(transaction_id)
    return {"status": "success" if result["rolled_back"] else "partial",
            "code": "TRANSACTION_UNDONE" if result["rolled_back"] else "ROLLBACK_FAILED",
            "readback": result, "saved": False}
