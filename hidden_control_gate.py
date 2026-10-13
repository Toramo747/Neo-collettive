# SPDX-License-Identifier: BUSL-1.1
"""Fail-closed hidden commercial holdout gate.

The holdout payload is supplied only at runtime through Render environment
configuration and is intentionally absent from the public repository.
"""
from __future__ import annotations
import json
import os

from arena_research_algorithm import evaluate_control_cases

ENV_KEY="NEO_HIDDEN_CONTROL_JSON"
REQUIRE_KEY="NEO_REQUIRE_HIDDEN_CONTROL"

def load_hidden_cases() -> list[dict]:
    raw=(os.getenv(ENV_KEY) or "").strip()
    if not raw:
        return []
    payload=json.loads(raw)
    if isinstance(payload,dict):
        rows=payload.get("cases") or []
    elif isinstance(payload,list):
        rows=payload
    else:
        raise ValueError("hidden_control_invalid_payload")
    if not isinstance(rows,list):
        raise ValueError("hidden_control_cases_not_list")
    return [x for x in rows if isinstance(x,dict)]

def evaluate_hidden_control() -> dict:
    cases=load_hidden_cases()
    required=(os.getenv(REQUIRE_KEY) or "").strip().lower() in {"1","true","yes","on"}
    if required and not cases:
        raise RuntimeError("hidden_control_required_but_missing")
    if not cases:
        return {"required":required,"cases":0,"correct":0,"ok":not required}
    result=evaluate_control_cases(cases)
    ok=bool(
        int(result.get("cases") or 0) >= 1
        and int(result.get("correct") or 0) == int(result.get("cases") or 0)
        and int(result.get("family_correct") or 0) == int(result.get("family_cases") or 0)
    )
    return {**result,"required":required,"ok":ok}

def enforce_hidden_control() -> dict:
    result=evaluate_hidden_control()
    if not result.get("ok"):
        raise RuntimeError(
            "hidden_commercial_control_failed:"
            +str(result.get("correct"))+"/"+str(result.get("cases"))
        )
    return result

def main() -> int:
    result=enforce_hidden_control()
    # Never print case text or expected labels from the hidden payload.
    print(json.dumps({
        "hidden_control_ok":True,
        "required":bool(result.get("required")),
        "cases":int(result.get("cases") or 0),
        "correct":int(result.get("correct") or 0),
    }))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
