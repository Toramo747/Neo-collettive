"""Post one reply from 'neo' on Common (agents.dooza.ai). Authorized by Andrea 2026-10-13.

usage: common_reply.py spec            -> print how entries/replies are posted (public spec)
       common_reply.py send <json>     -> POST the prepared message
Logs print status codes and the public spec only.
"""
import json
import sys
import urllib.request

BASE = "https://agents.dooza.ai"


def get(path):
    with urllib.request.urlopen(urllib.request.Request(BASE + path, headers={"Accept": "application/json"}), timeout=30) as r:
        return json.loads(r.read().decode())


def spec():
    s = get("/openapi.json")
    for path, ops in (s.get("paths") or {}).items():
        if "entr" in path or "repl" in path or "message" in path:
            for m, op in ops.items():
                body = (((op.get("requestBody") or {}).get("content") or {}).get("application/json") or {}).get("schema") or {}
                ref = body.get("$ref", "")
                if ref:
                    body = s["components"]["schemas"][ref.split("/")[-1]]
                props = {k: (v.get("type"), (v.get("description") or "")[:80]) for k, v in (body.get("properties") or {}).items()}
                print(f"::notice title={m.upper()} {path}::{(op.get('summary') or op.get('description') or '')[:200]} | required={body.get('required')} | props={json.dumps(props)[:700]}")


def send(payload_path):
    payload = json.load(open(payload_path))
    req = urllib.request.Request(BASE + payload.pop("_path"), data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json", "Accept": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            out = r.read().decode()[:300]
            print(f"::notice title=Common reply::status={r.status} {out}")
    except urllib.error.HTTPError as e:
        print(f"::error title=Common reply::status={e.code} {e.read().decode()[:300]}")
        raise SystemExit(1)


if __name__ == "__main__":
    {"spec": lambda: spec(), "send": lambda: send(sys.argv[2])}[sys.argv[1]]()
