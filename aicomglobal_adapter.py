"""Strict read-only AICOMGLOBAL A2A adapter used by MYCELIX SETI."""

from __future__ import annotations
import json, urllib.error, urllib.request, uuid, re
from typing import Any

AICOMGLOBAL_A2A_URL="https://aicomglobal.com/a2a"
READ_ONLY_SKILLS=frozenset({
    "aicom_list_services","aicom_search_offerings","aicom_get_offering",
    "aicom_agora_browse","aicom_channels","aicom_channel_read",
    "aicom_experiment_info","aicom_experiment_browse","aicom_experiment_get",
    "aicom_read_oasis","aicom_get_reflection","aicom_chronicle_read",
    "aicom_x402_index","aicom_watch_status",
})
WRITE_OR_PAID_MARKERS=("x402","usdc","wallet","price","paid","buy","purchase","subscription","$")

class AicomglobalAdapterError(RuntimeError): pass

def build_message_send(skill:str,input_data:dict[str,Any]|None=None)->dict[str,Any]:
    skill=str(skill or "").strip()
    if skill not in READ_ONLY_SKILLS:
        raise ValueError(f"skill_not_read_only:{skill}")
    data={} if input_data is None else input_data
    if not isinstance(data,dict): raise TypeError("input_data_must_be_object")
    return {"jsonrpc":"2.0","id":str(uuid.uuid4()),"method":"message/send","params":{"message":{
        "role":"user","parts":[{"kind":"data","data":{"skill":skill,"input":data}}],
        "messageId":str(uuid.uuid4()),"kind":"message"}}}

def _walk(value:Any,out:list[Any],depth:int=0)->None:
    if depth>10:return
    if isinstance(value,list):
        for x in value:_walk(x,out,depth+1)
    elif isinstance(value,dict):
        if any(k in value for k in ("signals","results","channels","experiments","services","messages")):
            out.append(value)
        for x in value.values():_walk(x,out,depth+1)
    elif isinstance(value,str):
        s=value.strip()
        if s[:1] in "[{":
            try:_walk(json.loads(s),out,depth+1)
            except Exception:pass

def extract_result(payload:dict[str,Any])->dict[str,Any]:
    if not isinstance(payload,dict): raise TypeError("payload_must_be_object")
    if payload.get("error"):
        e=payload["error"]
        raise AicomglobalAdapterError("a2a_error:"+str((e or {}).get("code") if isinstance(e,dict) else "")+":"+str((e or {}).get("message") if isinstance(e,dict) else e))
    result=payload.get("result")
    if result is None: raise AicomglobalAdapterError("missing_result")
    decoded=[];_walk(result,decoded)
    state=None
    if isinstance(result,dict):
        st=result.get("status")
        state=(st or {}).get("state") if isinstance(st,dict) else result.get("state")
    return {"ok":True,"state":state,"decoded":decoded,"result":result}

def call_read_only(skill:str,input_data:dict[str,Any]|None=None,*,timeout:float=20.0)->dict[str,Any]:
    raw=json.dumps(build_message_send(skill,input_data),ensure_ascii=False).encode()
    req=urllib.request.Request(AICOMGLOBAL_A2A_URL,data=raw,headers={
        "Content-Type":"application/json","Accept":"application/json",
        "User-Agent":"MYCELIX-aicomglobal-readonly/0.99.16"},method="POST")
    try:
        with urllib.request.urlopen(req,timeout=max(1.0,min(float(timeout),30.0))) as r:
            body=r.read(262144)
            if len(body)>=262144: raise AicomglobalAdapterError("response_too_large")
            payload=json.loads(body.decode("utf-8","replace"))
    except urllib.error.HTTPError as e:
        raise AicomglobalAdapterError(f"http_{e.code}") from e
    except urllib.error.URLError as e:
        raise AicomglobalAdapterError("network_error:"+type(e.reason).__name__) from e
    except json.JSONDecodeError as e:
        raise AicomglobalAdapterError("invalid_json_response") from e
    return extract_result(payload)

def first_collection(result:dict[str,Any],key:str)->list[dict]:
    for node in result.get("decoded") or []:
        rows=node.get(key) if isinstance(node,dict) else None
        if isinstance(rows,list):
            return [x for x in rows if isinstance(x,dict)]
    return []

def explicit_https_urls(text:str)->list[str]:
    seen=[];out=[]
    for u in re.findall(r"https://[^\s<>\"']+",str(text or "")):
        u=u.rstrip(".,);]")
        if u not in seen:
            seen.append(u);out.append(u)
    return out[:8]

def classify_listing(row:dict[str,Any])->str:
    blob=json.dumps(row,ensure_ascii=False).lower()
    price=str(row.get("priceTerms") or row.get("price_terms") or "").lower()
    if price and price not in {"free","$0","0","free (oauth / github pat; standard api scopes)"}:
        return "PAID_ONLY"
    if any(m in blob for m in WRITE_OR_PAID_MARKERS) and "free" not in blob:
        return "PAID_ONLY"
    if "executor_unavailable" in blob or "accepting_work\":false" in blob:
        return "EXECUTOR_OFFLINE"
    return "READY_READONLY"
