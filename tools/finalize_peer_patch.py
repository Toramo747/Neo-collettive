"""Finalize isolated peer patch; no network, no gate or state mutation."""
import ast
import hashlib
from pathlib import Path

def once(text,old,new):
    if text.count(old)!=1:
        raise RuntimeError('Patch anchor changed: '+old[:90])
    return text.replace(old,new,1)

p=Path('a2a_peer.py')
raw=p.read_bytes()
sha=hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
if sha!='c49023e7168ef0dc1f2c38518a67c55828b1816a':
    raise SystemExit('Peer source changed; refusing to patch '+sha)
s=raw.decode()
s=once(s,'        if state == "AUTH_REQUIRED":\n            base["peer_state"] = "AUTH_REQUIRED"','        if state in {"AUTH_REQUIRED", "PAYMENT_REQUIRED"}:\n            base["peer_state"] = state')
s=once(s,'        base.update(protocol_ok=parsed["protocol_ok"], peer_state=parsed["state"], response={"text": parsed["text"]})','''        refusal = explicit_peer_refusal(parsed["text"]) if parsed["protocol_ok"] else None
        if refusal:
            parsed["state"] = refusal
        base.update(protocol_ok=parsed["protocol_ok"], peer_state=parsed["state"], response={"text": parsed["text"]})''')
s=once(s,'        if parsed["protocol_ok"]:\n            base["peer_context"]','        if parsed["protocol_ok"] or parsed["state"] in {"AUTH_REQUIRED", "PAYMENT_REQUIRED"}:\n            base["peer_context"]')
s+='''

def explicit_peer_refusal(text: str) -> str | None:
    """Recognize an explicit refusal, including the observed JSON-as-text envelope.

    A peer's payment claim is not an independently verified price. It is still a
    stop condition. General research mentioning payments does not trigger this.
    """
    value=str(text or "").strip()
    try:
        data=json.loads(value)
    except (ValueError,TypeError):
        data=None
    if isinstance(data,dict):
        fields=[k for k in ("output","text","response") if isinstance(data.get(k),str)]
        if len(fields)==1:
            value=data[fields[0]].strip()
    match=re.match(r"^(PAYMENT_REQUIRED|AUTH_REQUIRED)\\b",value,re.I)
    return match[1].upper() if match else None
'''
ast.parse(s)
p.write_text(s)

w=Path('.github/workflows/neo-render-deploy.yml')
t=w.read_text()
t=once(t,'      - "cloud_mcp.py"\n','      - "cloud_mcp.py"\n      - "a2a_peer.py"\n      - "test_a2a_peer.py"\n      - "test_peer_refusal.py"\n      - "inbound_security.py"\n      - "test_inbound_security.py"\n      - "venture_measurement.py"\n      - "test_venture_measurement.py"\n')
t=once(t,'test_agent_chat.py test_runtime_boundary.py','test_agent_chat.py test_runtime_boundary.py test_a2a_peer.py test_peer_refusal.py test_inbound_security.py test_venture_measurement.py')
w.write_text(t)
print('Explicit peer refusal stops future POSTs; deployment CI now runs peer, security and measurement tests.')
