from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable


def _as_epoch(value: Any) -> float:
    text=str(value or "").strip()
    if not text:
        return 0.0
    try:
        dt=datetime.fromisoformat(text.replace("Z","+00:00"))
        if dt.tzinfo is None:
            dt=dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).timestamp()
    except Exception:
        return 0.0


def state_freshness(payload: dict | None) -> tuple[int,float]:
    if not isinstance(payload,dict):
        return (0,0.0)
    try:
        cycles=max(0,int(payload.get("cycles_completed") or 0))
    except Exception:
        cycles=0
    timestamp=max(
        _as_epoch(payload.get("state_saved_at_utc")),
        _as_epoch(payload.get("last_finished_utc")),
        _as_epoch(payload.get("last_started_utc")),
    )
    return (cycles,timestamp)


def select_freshest_state(
    candidates: Iterable[tuple[str,dict | None]],
) -> tuple[str,dict | None,dict]:
    """Select the most advanced durable state, never merely the first source.

    Cycles are monotonic and therefore dominate freshness. Timestamps break ties.
    Source priority only breaks exact ties to prefer the fuller local/render payload
    over the repository projection.
    """
    source_priority={"local_snapshot":3,"render_env":2,"repo_snapshot":1}
    valid=[]
    for source,payload in candidates:
        if not isinstance(payload,dict) or not payload:
            continue
        cycles,timestamp=state_freshness(payload)
        valid.append((cycles,timestamp,source_priority.get(source,0),source,payload))

    if not valid:
        return ("fresh",None,{"candidates":0,"selected_cycles":0,"selected_timestamp":0.0})

    selected=max(valid,key=lambda row:(row[0],row[1],row[2]))
    cycles,timestamp,_,source,payload=selected
    return (
        source,
        payload,
        {
            "candidates":len(valid),
            "selected_cycles":cycles,
            "selected_timestamp":timestamp,
            "candidate_freshness":{
                row[3]:{"cycles":row[0],"timestamp":row[1]}
                for row in valid
            },
        },
    )
