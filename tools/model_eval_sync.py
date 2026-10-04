# SPDX-License-Identifier: BUSL-1.1
from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from hidden_control_gate import load_hidden_cases
from model_archive import (
    HIDDEN_EVAL_PATH,
    control_cases_to_model_eval,
    hidden_eval_key,
)
from self_traffic_auth import make_self_traffic_proof


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(
        "".join(json.dumps(row,ensure_ascii=False,separators=(",",":"))+"\n" for row in rows),
        encoding="utf-8",
    )


def _public_cases() -> list[dict]:
    payload=json.loads((ROOT/"data/arena/research-algorithm/control_cases.json").read_text(encoding="utf-8"))
    return control_cases_to_model_eval(list(payload.get("cases") or []),hidden=False)


def _hidden_cases_from_render(secret: str) -> list[dict]:
    proof=make_self_traffic_proof(hidden_eval_key(secret),HIDDEN_EVAL_PATH)
    req=urllib.request.Request(
        "https://neo-collettive.onrender.com"+HIDDEN_EVAL_PATH,
        headers={
            "X-MYCELIX-Self-Traffic":"github-actions-model-shadow",
            "X-NEO-Model-Hidden-Proof":proof,
        },
    )
    with urllib.request.urlopen(req,timeout=45) as response:
        payload=json.loads(response.read(1024*1024+1))
    rows=payload.get("cases")
    if payload.get("ok") is not True or not isinstance(rows,list):
        raise ValueError("invalid_hidden_eval")
    return [row for row in rows if isinstance(row,dict)]


def main() -> int:
    target=Path(sys.argv[1])
    public_rows=_public_cases()
    _write_jsonl(target/"public.jsonl",public_rows)
    secret=os.environ.get("NEO_HEARTBEAT_TOKEN","").strip()
    hidden_rows=_hidden_cases_from_render(secret) if secret else []
    _write_jsonl(target/"hidden.jsonl",hidden_rows)
    print(json.dumps({
        "public_cases":len(public_rows),
        "hidden_cases":len(hidden_rows),
        "hidden_source":"render_runtime" if hidden_rows else "unavailable",
    },separators=(",",":")))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
