"""Monotonic generation guard for the NEO_STATE_JSON checkpoint.

Every checkpoint carries ``state_generation`` = generation it was derived from
+ 1.  Before overwriting the saved checkpoint, the writer reads the saved one
back: if the saved generation is *newer* than the one this process restored
from, this process is running on stale state (stale env after a restart, or
two instances overlapping during a deploy) and must not write.

Legitimate shrinkage (retention, archiving) is unaffected: the guard compares
lineage, not evidence counts.
"""
from __future__ import annotations

from typing import Any, Callable

GUARD_FIELD = "state_generation"
WRITER_FIELD = "state_writer_id"


def state_generation_of(payload: Any) -> int:
    if not isinstance(payload, dict):
        return 0
    try:
        return max(0, int(payload.get(GUARD_FIELD) or 0))
    except (TypeError, ValueError):
        return 0


def check_write_allowed(
    loaded_generation: int,
    saved_value: str | None,
    decode: Callable[[str], Any],
    writer_id: str | None = None,
) -> dict[str, Any]:
    """Decide whether a checkpoint derived from ``loaded_generation`` may be written.

    ``saved_value`` is the raw NEO_STATE_JSON currently saved in Render (None if
    it could not be read).  Returns a status dict without any state content.
    """
    loaded = max(0, int(loaded_generation or 0))
    if saved_value is None:
        return {"allowed": True, "status": "saved_unreadable", "loaded_generation": loaded, "saved_generation": None}
    if not saved_value.strip():
        return {"allowed": True, "status": "saved_empty", "loaded_generation": loaded, "saved_generation": 0}
    try:
        saved_payload = decode(saved_value)
    except Exception:
        saved_payload = None
    if not isinstance(saved_payload, dict):
        # A corrupt saved checkpoint must not block repair writes.
        return {"allowed": True, "status": "saved_undecodable", "loaded_generation": loaded, "saved_generation": None}
    saved = state_generation_of(saved_payload)
    if saved > loaded and writer_id and saved_payload.get(WRITER_FIELD) == writer_id:
        # Our own earlier write whose response was lost: adopt it.
        return {"allowed": True, "status": "own_write_adopted", "loaded_generation": saved, "saved_generation": saved}
    if saved > loaded:
        return {"allowed": False, "status": "stale_generation_write_blocked",
                "loaded_generation": loaded, "saved_generation": saved}
    return {"allowed": True, "status": "ok", "loaded_generation": loaded, "saved_generation": saved}


def next_generation(loaded_generation: int) -> int:
    return max(0, int(loaded_generation or 0)) + 1
