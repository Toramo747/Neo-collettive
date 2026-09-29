from __future__ import annotations

import re
from typing import Any


_FIELD_RE=re.compile(
    r"(?im)^\s*(agent[_ -]?id|identity|name|capabilities?|protocol|limitations?|documentation|"
    r"public[_ -]?key|ed25519(?:[_ -]?public[_ -]?key)?)\s*:\s*(.+?)\s*$"
)


def _clean(value: Any, limit: int=600) -> str:
    return " ".join(str(value or "").split())[:limit]


def parse_body_introduction(text: str) -> dict:
    """Parse body identity claims as observations, never authenticated sender data."""
    fields={}
    for match in _FIELD_RE.finditer(str(text or "")):
        key=match.group(1).lower().replace("-"," ").replace("_"," ")
        value=_clean(match.group(2))
        if not value:
            continue
        if key=="agent id":
            canonical="agent_id"
        elif key in {"capability","capabilities"}:
            canonical="capabilities"
        elif key in {"limitation","limitations"}:
            canonical="limitations"
        elif key in {"public key","ed25519","ed25519 public key"}:
            canonical="public_key"
        else:
            canonical=key.replace(" ","_")
        fields.setdefault(canonical,value)

    declared_agent_id=_clean(fields.get("agent_id"),180)
    evidence_fields=[
        name for name in ("identity","name","capabilities","protocol","limitations","documentation","public_key")
        if fields.get(name)
    ]
    intro_received=bool(declared_agent_id and len(evidence_fields)>=3)
    return {
        "declared_identity_from_body":intro_received,
        "declared_agent_id":declared_agent_id or None,
        "identity_status":"SELF_DECLARED_UNVERIFIED" if intro_received else None,
        "introduction_fields":evidence_fields,
        "declared_public_key_observation":_clean(fields.get("public_key"),600) or None,
        "trust_promoted":False,
        "admission_granted":False,
    }


def conversation_identity_key(structured_agent_id: str, thread_id: str) -> str:
    """Use only structured sender identity or the independently assigned thread."""
    structured=_clean(structured_agent_id,180)
    if structured:
        return "sender:"+structured
    return "thread:"+_clean(thread_id,180)
