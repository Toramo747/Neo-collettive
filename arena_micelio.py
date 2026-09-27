# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Andrea Gava
"""Verified shared memory for the isolated NEO Arena."""
from __future__ import annotations
import argparse, json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
import neo_dialect as nd

NAMESPACE="mycelix-arena"
QUARANTINE_THRESHOLD=0.60
FAILURE_PENALTY=0.45
DEFAULT_TTL_DAYS=30

def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()

def _parse(value: str):
    try: return datetime.fromisoformat(str(value).replace("Z","+00:00"))
    except Exception: return None

def load_json(path: Path, default: Any):
    try:
        v=json.loads(path.read_text(encoding="utf-8"))
        return v
    except Exception:
        return default

def save_json(path: Path, value: Any):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

def _sessions(root: Path) -> dict[str,dict]:
    out={}
    for path in sorted((root/"sessions").glob("*.json")):
        row=load_json(path,{})
        if isinstance(row,dict) and row.get("session_id"):
            out[str(row["session_id"])]=row
    return out

def _test_namespace_isolated(session: dict) -> bool:
    b=session.get("boundary") or {}
    return bool(
        session.get("namespace")==NAMESPACE
        and b.get("production_state_write") is False
        and b.get("tool_opportunity_influence")=="NONE"
        and b.get("commercial_evidence_influence")=="NONE"
        and b.get("seti_peer_memory_influence")=="NONE"
        and b.get("external_usage_metrics_influence")=="NONE"
        and b.get("external_agent_contact") is False
        and b.get("production_variant_promotion") is False
    )

def _test_dialect_valid(session: dict) -> bool:
    valid=[x for x in (session.get("transcript") or []) if isinstance(x,dict) and x.get("valid")]
    if not valid: return False
    cid=str(session.get("conversation_id") or "")
    for row in valid:
        msg=row.get("message")
        if not isinstance(msg,dict): return False
        if not nd.validate_message(msg,expected_conversation_id=cid).get("ok"):
            return False
    return True

def _test_reached_bye(session: dict) -> bool:
    valid=[x for x in (session.get("transcript") or []) if isinstance(x,dict) and x.get("valid")]
    return bool(valid and (valid[-1].get("message") or {}).get("type")=="BYE")

TESTS={
    "arena_namespace_isolated":_test_namespace_isolated,
    "neo_dialect_schema_valid":_test_dialect_valid,
    "session_reached_bye":_test_reached_bye,
}

def proof_ok(evidence: dict, sessions: dict[str,dict]) -> tuple[bool,str]:
    if not isinstance(evidence,dict): return False,"invalid_evidence"
    kind=str(evidence.get("kind") or "")
    if kind=="test":
        name=str(evidence.get("test") or "")
        fn=TESTS.get(name)
        if not fn: return False,"unknown_test"
        sid=str(evidence.get("session_id") or "")
        session=sessions.get(sid)
        if not session: return False,"session_missing"
        try: return bool(fn(session)),name
        except Exception: return False,name
    if kind=="url":
        # URL evidence must carry a prior read-only verification result.
        # Arena never follows arbitrary URLs itself and never contacts external agents.
        return bool(evidence.get("verified_read_only") is True),str(evidence.get("url") or "url")
    return False,"unsupported_evidence"

def _belief_id(session_id: str, suffix: str) -> str:
    return "belief-"+session_id+"-"+suffix

def seed_from_sessions(root: Path, memory: dict) -> dict:
    sessions=_sessions(root)
    beliefs=[x for x in (memory.get("beliefs") or []) if isinstance(x,dict)]
    ids={str(x.get("belief_id") or "") for x in beliefs}
    for sid,s in sessions.items():
        created=str(s.get("created_at_utc") or now_utc())
        expires=(_parse(created) or datetime.now(timezone.utc))+timedelta(days=DEFAULT_TTL_DAYS)
        candidates=[
            {
                "belief_id":_belief_id(sid,"isolation"),"text":"Arena session state is isolated in mycelix-arena and has no production, commercial, SETI peer-memory or external-usage influence.",
                "author":"SYSTEM","origin_session":sid,"type":"fact",
                "evidence":[{"kind":"test","test":"arena_namespace_isolated","session_id":sid}],
            },
            {
                "belief_id":_belief_id(sid,"dialect"),"text":"The Arena transcript is structurally valid neo-dialect/1.0 and reaches BYE.",
                "author":"SYSTEM","origin_session":sid,"type":"fact",
                "evidence":[
                    {"kind":"test","test":"neo_dialect_schema_valid","session_id":sid},
                    {"kind":"test","test":"session_reached_bye","session_id":sid},
                ],
            },
            {
                "belief_id":_belief_id(sid,"tool-utility"),"text":"MCP Compatibility Doctor would be a useful free tool for developers.",
                "author":"Scout","origin_session":sid,"type":"strategy","evidence":[],
            },
        ]
        for row in candidates:
            if row["belief_id"] in ids: continue
            row.update({
                "confidence":1.0 if row["evidence"] else 0.0,
                "last_verified_utc":None,
                "expires_utc":expires.isoformat(),
                "status":"ACTIVE" if row["evidence"] else "HYPOTHESIS",
                "verification_history":[],
            })
            beliefs.append(row); ids.add(row["belief_id"])
    memory={"schema_v":1,"namespace":NAMESPACE,"beliefs":beliefs,
            "boundary":{"production_influence":"NONE","commercial_influence":"NONE","seti_influence":"NONE","external_usage_influence":"NONE"}}
    return memory

def reverify(root: Path, memory: dict, *, at: datetime|None=None) -> dict:
    at=at or datetime.now(timezone.utc)
    sessions=_sessions(root)
    for row in memory.get("beliefs") or []:
        if not isinstance(row,dict): continue
        evidence=row.get("evidence") if isinstance(row.get("evidence"),list) else []
        if not evidence:
            row["status"]="HYPOTHESIS"; row["confidence"]=0.0
            continue
        expiry=_parse(str(row.get("expires_utc") or ""))
        results=[proof_ok(e,sessions) for e in evidence]
        ok=all(x[0] for x in results)
        history=list(row.get("verification_history") or [])
        history.append({"verified_at_utc":at.isoformat(),"ok":ok,"checks":[{"proof":name,"ok":v} for v,name in results]})
        row["verification_history"]=history[-20:]
        row["last_verified_utc"]=at.isoformat()
        if expiry and at>=expiry:
            row["status"]="EXPIRED"; row["confidence"]=0.0
        elif ok:
            row["status"]="ACTIVE"; row["confidence"]=min(1.0,max(float(row.get("confidence") or 0.0),0.85)+0.05)
        else:
            row["confidence"]=max(0.0,float(row.get("confidence") or 0.0)-FAILURE_PENALTY)
            if row["confidence"]<QUARANTINE_THRESHOLD:
                row["status"]="QUARANTINE"
    return memory

def critic_context(memory: dict) -> list[dict]:
    # Critic receives only verified facts from shared memory, never peer opinions/strategies.
    return [
        {"belief_id":x.get("belief_id"),"text":x.get("text"),"evidence":x.get("evidence"),"confidence":x.get("confidence")}
        for x in (memory.get("beliefs") or [])
        if isinstance(x,dict) and x.get("status")=="ACTIVE" and x.get("type")=="fact" and bool(x.get("evidence"))
    ]

def update_critic_private(root: Path, sessions: dict[str,dict]):
    path=root/"critic-private.json"
    private=load_json(path,{"schema_v":1,"namespace":NAMESPACE,"owner":"Critic","counterexamples":[]})
    seen={str(x.get("key") or "") for x in private.get("counterexamples") or [] if isinstance(x,dict)}
    rows=list(private.get("counterexamples") or [])
    for sid,s in sessions.items():
        for msg in s.get("transcript") or []:
            if not isinstance(msg,dict) or msg.get("actor")!="Critic" or not msg.get("valid"): continue
            m=msg.get("message") or {}
            if m.get("type")!="COUNTER": continue
            key=sid+":"+str(m.get("counter_id") or "")
            if key in seen: continue
            rows.append({"key":key,"session_id":sid,"recorded_at_utc":now_utc(),"counter":m.get("changes") or {}})
            seen.add(key)
    private["counterexamples"]=rows[-100:]
    save_json(path,private)
    return private

def sync(root: str|Path="data/arena") -> dict:
    root=Path(root)
    memory=load_json(root/"micelio.json",{"schema_v":1,"namespace":NAMESPACE,"beliefs":[]})
    memory=seed_from_sessions(root,memory)
    memory=reverify(root,memory)
    save_json(root/"micelio.json",memory)
    update_critic_private(root,_sessions(root))
    return memory

def main():
    p=argparse.ArgumentParser(); p.add_argument("--data-dir",default="data/arena")
    args=p.parse_args()
    m=sync(args.data_dir)
    counts={}
    for x in m.get("beliefs") or []:
        counts[x.get("status")]=counts.get(x.get("status"),0)+1
    print(json.dumps({"ok":True,"namespace":NAMESPACE,"counts":counts,"critic_context_count":len(critic_context(m))},ensure_ascii=False))
if __name__=="__main__": main()
