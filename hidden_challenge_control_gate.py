# SPDX-License-Identifier: BUSL-1.1
from __future__ import annotations
import json
import os

from challenge_track import evaluate_public_control_cases

ENV_KEY="NEO_HIDDEN_CHALLENGE_CONTROL_JSON"
REQUIRE_KEY="NEO_REQUIRE_HIDDEN_CHALLENGE_CONTROL"

def load_hidden_challenge_cases() -> list[dict]:
    raw=(os.getenv(ENV_KEY) or "").strip()
    if not raw:
        return []
    payload=json.loads(raw)
    rows=payload.get("cases") if isinstance(payload,dict) else payload
    if not isinstance(rows,list):
        raise ValueError("hidden_challenge_control_cases_not_list")
    return [x for x in rows if isinstance(x,dict)]

def evaluate_hidden_challenge_control() -> dict:
    cases=load_hidden_challenge_cases()
    required=(os.getenv(REQUIRE_KEY) or "").strip().lower() in {"1","true","yes","on"}
    if required and not cases:
        raise RuntimeError("hidden_challenge_control_required_but_missing")
    if not cases:
        return {"required":required,"cases":0,"correct":0,"ok":not required}
    for case in cases:
        if "expect_ready" not in case:
            raise RuntimeError("hidden_challenge_label_missing")
    result=evaluate_public_control_cases(cases)
    ok=bool(int(result.get("cases") or 0)>=1 and int(result.get("correct") or 0)==int(result.get("cases") or 0))
    return {**result,"required":required,"ok":ok}

def enforce_hidden_challenge_control() -> dict:
    result=evaluate_hidden_challenge_control()
    if not result.get("ok"):
        raise RuntimeError("hidden_challenge_control_failed:"+str(result.get("correct"))+"/"+str(result.get("cases")))
    return result

if __name__=="__main__":
    result=enforce_hidden_challenge_control()
    print(json.dumps({"hidden_challenge_control_ok":True,"required":bool(result.get("required")),"cases":int(result.get("cases") or 0),"correct":int(result.get("correct") or 0)}))
