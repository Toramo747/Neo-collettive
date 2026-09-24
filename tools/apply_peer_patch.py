"""One-shot, hash-pinned integration. No gate/policy edits or history resets."""
import ast
import hashlib
from pathlib import Path

p=Path('cloud_mcp.py')
raw=p.read_bytes()
expected='ea3506c383ee5ea1315fa64f9f972ffbc1086e6d'
actual=hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
if actual!=expected:
    raise SystemExit('Application changed; refusing patch: '+actual)
s=raw.decode('utf-8')

def once(text,old,new):
    if text.count(old)!=1:
        raise RuntimeError('Expected one anchor, found '+str(text.count(old))+': '+old[:90])
    return text.replace(old,new,1)

def edit_function(name,transform):
    global s
    nodes=[x for x in ast.parse(s).body if isinstance(x,(ast.FunctionDef,ast.AsyncFunctionDef)) and x.name==name]
    if len(nodes)!=1:
        raise RuntimeError('Function missing: '+name)
    n=nodes[0]
    lines=s.splitlines(keepends=True)
    old=''.join(lines[n.lineno-1:n.end_lineno])
    replacement=transform(old)
    ast.parse(replacement)
    s=''.join(lines[:n.lineno-1])+replacement.rstrip()+'\n'+''.join(lines[n.end_lineno:])

s=once(s,'import asyncio\n','import asyncio\nimport a2a_peer as peer_a2a\n')
s=once(s,'VERSION = "0.93.0"','VERSION = "0.94.0"')

def patch_transport(f):
    anchor='async def _ask_a2a_transport(agent: dict, question: str) -> dict:\n'
    return once(f,anchor,anchor+'''    if agent.get("_peer_interface"):
        interface = peer_a2a.Interface(**agent["_peer_interface"])
        answer = await peer_a2a.exchange_peer(
            interface, question, agent.get("_peer_context"), agent.get("_peer_budget")
        )
        answer["agent"] = agent.get("name") or "SETI peer"
        answer["agent_id"] = agent.get("id") or agent.get("agent_id") or ""
        if answer.get("quality_ok"):
            answer["quality_ok"], answer["quality_reason"] = _quality_check(answer, question)
        return answer
''')
edit_function('_ask_a2a_transport',patch_transport)
edit_function('_seti_resolve_interview_endpoint',lambda f:'''async def _seti_resolve_interview_endpoint(candidate: dict, eligibility: dict, budget=None) -> dict:
    """Negotiate an explicit same-origin JSON-RPC interface; do not guess v1 URLs."""
    return await peer_a2a.resolve_peer(candidate, eligibility, budget)
''')

def patch_interview(f):
    f=once(f,'    results=[]\n','    results=[]\n    peer_budget=peer_a2a.RequestBudget(limit=9)\n')
    a=f.index('        key=lambda kv:(')
    b=f.index('        reverse=True,',a)
    f=f[:a]+'        key=lambda kv:peer_a2a.peer_priority(kv[1],interviews.get(kv[0]) or {}),\n'+f[b:]
    f=once(f,'resolved=await _seti_resolve_interview_endpoint(candidate,eligibility)','resolved=await _seti_resolve_interview_endpoint(candidate,eligibility,peer_budget)')
    f=once(f,'            {"name":"SETI candidate "+key[:8],"url":endpoint},','''            {"name":"SETI candidate "+key[:8],"url":endpoint,
             "_peer_interface":resolved["interface"],
             "_peer_context":prior.get("peer_context"),"_peer_budget":peer_budget},''')
    needle='"reason":resolved.get("reason"),'
    if f.count(needle)!=3:
        raise RuntimeError('Resolution telemetry anchors changed')
    f=f.replace(needle,needle+'\n                "post_started":False,"peer_state":"RESOLUTION_FAILED",')
    f=once(f,'            "prompt":interview_prompt[:3000],','''            "prompt":(interview_prompt[:3000] if answer.get("rpc_method") in {"SendMessage","message/send"}
                      else str(prior.get("last_prompt") or "")),''')
    marker='        attempt_history=list(prior.get("attempt_history") or [])'
    f=once(f,marker,'''        for field in ("protocol_version","protocol_ok","peer_state","post_started","http_response_received","delivery_unknown","rpc_method"):
            attempt_entry[field]=answer.get(field)
'''+marker)
    f=once(f,'        interviews[key]=interview\n','''        interview.update({
            "peer_interface":resolved["interface"],
            "peer_context":answer.get("peer_context") or prior.get("peer_context") or {},
            "last_prompt":attempt_entry["prompt"],
            **{field:answer.get(field) for field in ("protocol_version","protocol_ok","peer_state","post_started","http_response_received","delivery_unknown","rpc_method")},
        })
        interviews[key]=interview
''')
    f=once(f,'                "interview_score":int(quality.get("score") or 0),','''                "peer_interface":resolved["interface"],
                "interview_score":int(quality.get("score") or 0),''')
    f=once(f,'            "transport":answer.get("transport"),\n        })','''            "transport":answer.get("transport"),
            **{field:answer.get(field) for field in ("protocol_ok","peer_state","post_started","http_response_received","delivery_unknown","rpc_method")},
        })''')
    f=once(f,'        "attempted_count":len(results),','''        "attempted_count":len(results),
        "post_started_count":sum(1 for x in results if x.get("post_started")),
        "message_post_started_count":sum(1 for x in results if x.get("post_started") and x.get("rpc_method") in {"message/send","SendMessage"}),
        "http_response_count":sum(1 for x in results if x.get("http_response_received")),
        "protocol_response_count":sum(1 for x in results if x.get("protocol_ok")),
        "delivery_unknown_count":sum(1 for x in results if x.get("delivery_unknown")),
        "target_request_attempts":peer_budget.used,
        "request_budget_limit":peer_budget.limit,''')
    return f
edit_function('_seti_interview_one_candidate',patch_interview)

def patch_admitted(f):
    return once(f,'            "_seti_admitted":True,','            "_seti_admitted":True,\n            "_peer_interface":row.get("peer_interface"),')
edit_function('_seti_admitted_agent_details',patch_admitted)

def patch_cycle(f):
    f=once(f,'"messages_sent":bool(interview_result.get("attempted")),','''"messages_sent":bool(interview_result.get("message_post_started_count")),
            "message_delivery_not_guaranteed":True,''')
    f=once(f,'"target_http_requests":bool(interview_result.get("attempted")),','"target_http_requests":bool(interview_result.get("target_request_attempts")),')
    f=once(f,'"active_probe":bool(interview_result.get("attempted")),','"active_probe":bool(interview_result.get("target_request_attempts")),')
    f=once(f,'"interview_attempted_count":interview_result.get("attempted_count",0),','''"interview_attempted_count":interview_result.get("attempted_count",0),
                "interview_post_started_count":interview_result.get("post_started_count",0),
                "interview_message_post_started_count":interview_result.get("message_post_started_count",0),
                "interview_http_response_count":interview_result.get("http_response_count",0),
                "interview_protocol_response_count":interview_result.get("protocol_response_count",0),
                "interview_delivery_unknown_count":interview_result.get("delivery_unknown_count",0),
                "interview_request_budget":interview_result.get("request_budget_limit",9),''')
    return f
edit_function('_seti_cycle_if_due',patch_cycle)

def patch_public(f):
    return once(f,'            "http_status":raw.get("http_status"),','''            "http_status":raw.get("http_status"),
            "protocol_version":raw.get("protocol_version"),
            "peer_state":raw.get("peer_state"),
            "post_started":bool(raw.get("post_started")),
            "http_response_received":bool(raw.get("http_response_received")),''')
edit_function('_public_seti_interviews',patch_public)

def patch_private(f):
    f=once(f,'        rows.append({','        eligibility=interview_candidate_eligibility(candidate)\n        rows.append({')
    return once(f,'            "http_status":interview.get("http_status"),','''            "http_status":interview.get("http_status"),
            "protocol_version":interview.get("protocol_version"),
            "peer_state":interview.get("peer_state"),
            "peer_context":interview.get("peer_context") or {},
            "post_started":bool(interview.get("post_started")),''')
edit_function('_private_seti_console_payload',patch_private)
ast.parse(s)
p.write_text(s,encoding='utf-8')
print('Patch applied to cloud_mcp.py; policies, gates and history unchanged.')
