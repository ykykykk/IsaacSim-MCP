"""Host and stage lifecycle identity. USD access stays on the Kit thread."""

import uuid

INSTANCE_ID = str(uuid.uuid4())
_stage_id = str(uuid.uuid4())
_stage = None
_subscription = None
_resets = {}


def register_reset(name, callback):
    _resets[name] = callback


def start():
    global _subscription
    import omni.usd

    def changed(event):
        global _stage_id, _stage
        if event.type in (int(omni.usd.StageEventType.CLOSING), int(omni.usd.StageEventType.OPENED)):
            for callback in _resets.values():
                callback()
            _stage_id = str(uuid.uuid4())
            _stage = None

    _subscription = omni.usd.get_context().get_stage_event_stream().create_subscription_to_pop(changed)


def stop():
    global _subscription, _stage
    _subscription = None
    _stage = None
    for callback in _resets.values():
        callback()


def queued_stage_id():
    # Socket threads read only this immutable token, never USD objects.
    return _stage_id


def context(stage):
    global _stage, _stage_id
    if stage != _stage:
        if _stage is not None:
            _stage_id = str(uuid.uuid4())
        _stage = stage
    return {
        "instance_id": INSTANCE_ID,
        "stage_id": _stage_id,
        "root_identifier": stage.GetRootLayer().identifier if stage else None,
        "edit_target": stage.GetEditTarget().GetLayer().identifier if stage else None,
    }


def require_context(stage, expected):
    actual = context(stage)
    if actual != expected:
        raise ValueError("STALE_CONTEXT: host, stage or edit target changed; preview again")
    return actual
