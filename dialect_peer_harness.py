# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Andrea Gava
"""Real-provider neo-dialect/1.0 compatibility harness."""
from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import neo_dialect as nd

NEUTRAL_SYSTEM = "You are an external agent that offers market-category analysis. Respond to the messages you receive."
REPORT_PATH = Path(os.getenv("NEO_DIALECT_REPORT_PATH","neo_dialect_peer_report.json"))


def _extract_json(text: str) -> dict | None:
    value=str(text or "").strip()
    try:
        data=json.loads(value)
        return data if isinstance(data,dict) else None
    except Exception:
        pass
    start=value.find("{")
    end=value.rfind("}")
    if start>=0 and end>start:
        try:
            data=json.loads(value[start:end+1])
            return data if isinstance(data,dict) else None
        except Exception:
            return None
    return None


@dataclass
class CallResult:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    error: str | None = None


class SpendBudget:
    def __init__(self):
        self.cap=float(os.getenv("NEO_DIALECT_TEST_BUDGET_USD","0.60"))
        self.reserve_per_call=float(os.getenv("NEO_DIALECT_TEST_RESERVE_PER_CALL_USD","0.02"))
        self.reserved=0.0
        self.calls=0

    def take(self):
        if self.reserved+self.reserve_per_call > self.cap+1e-9:
            raise RuntimeError("TEST_SPEND_CAP_REACHED")
        self.reserved+=self.reserve_per_call
        self.calls+=1


class Provider:
    provider: str
    model: str
    async def call(self, incoming: dict, budget: SpendBudget) -> CallResult:
        raise NotImplementedError


class OpenAIProvider(Provider):
    provider="OpenAI"
    def __init__(self):
        self.key=os.getenv("OPENAI_API_KEY","").strip()
        self.model=os.getenv("NEO_DIALECT_OPENAI_MODEL","gpt-5-mini")
    async def call(self,incoming,budget):
        budget.take()
        try:
            async with httpx.AsyncClient(timeout=45) as client:
                r=await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={"Authorization":"Bearer "+self.key,"Content-Type":"application/json"},
                    json={
                        "model":self.model,
                        "messages":[
                            {"role":"system","content":NEUTRAL_SYSTEM},
                            {"role":"user","content":json.dumps(incoming,ensure_ascii=False,separators=(",",":"))},
                        ],
                        "temperature":0,
                        "max_tokens":220,
                    },
                )
            if not r.is_success:
                return CallResult("",error=f"http_{r.status_code}:{r.text[:180]}")
            d=r.json()
            text=(((d.get("choices") or [{}])[0].get("message") or {}).get("content") or "")
            usage=d.get("usage") or {}
            return CallResult(str(text),int(usage.get("prompt_tokens") or 0),int(usage.get("completion_tokens") or 0))
        except Exception as exc:
            return CallResult("",error=type(exc).__name__+":"+str(exc)[:180])


class AnthropicProvider(Provider):
    provider="Anthropic"
    def __init__(self):
        self.key=os.getenv("ANTHROPIC_API_KEY","").strip()
        self.model=os.getenv("NEO_DIALECT_ANTHROPIC_MODEL","claude-sonnet-4-5-20250929")
    async def call(self,incoming,budget):
        budget.take()
        try:
            async with httpx.AsyncClient(timeout=45) as client:
                r=await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={"x-api-key":self.key,"anthropic-version":"2023-06-01","Content-Type":"application/json"},
                    json={
                        "model":self.model,
                        "system":NEUTRAL_SYSTEM,
                        "messages":[{"role":"user","content":json.dumps(incoming,ensure_ascii=False,separators=(",",":"))}],
                        "temperature":0,
                        "max_tokens":220,
                    },
                )
            if not r.is_success:
                return CallResult("",error=f"http_{r.status_code}:{r.text[:180]}")
            d=r.json()
            text="".join(str(x.get("text") or "") for x in (d.get("content") or []) if isinstance(x,dict) and x.get("type")=="text")
            usage=d.get("usage") or {}
            return CallResult(text,int(usage.get("input_tokens") or 0),int(usage.get("output_tokens") or 0))
        except Exception as exc:
            return CallResult("",error=type(exc).__name__+":"+str(exc)[:180])


class GeminiProvider(Provider):
    provider="Google"
    def __init__(self):
        self.key=(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()
        self.model=os.getenv("NEO_DIALECT_GEMINI_MODEL","gemini-2.5-flash")
    async def call(self,incoming,budget):
        budget.take()
        try:
            url=f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
            async with httpx.AsyncClient(timeout=45) as client:
                r=await client.post(
                    url,
                    params={"key":self.key},
                    headers={"Content-Type":"application/json"},
                    json={
                        "systemInstruction":{"parts":[{"text":NEUTRAL_SYSTEM}]},
                        "contents":[{"role":"user","parts":[{"text":json.dumps(incoming,ensure_ascii=False,separators=(",",":"))}]}],
                        "generationConfig":{"temperature":0,"maxOutputTokens":220},
                    },
                )
            if not r.is_success:
                return CallResult("",error=f"http_{r.status_code}:{r.text[:180]}")
            d=r.json()
            text="".join(
                str(p.get("text") or "")
                for p in ((((d.get("candidates") or [{}])[0].get("content") or {}).get("parts")) or [])
                if isinstance(p,dict)
            )
            usage=d.get("usageMetadata") or {}
            return CallResult(text,int(usage.get("promptTokenCount") or 0),int(usage.get("candidatesTokenCount") or 0))
        except Exception as exc:
            return CallResult("",error=type(exc).__name__+":"+str(exc)[:180])


def configured_providers() -> list[Provider]:
    rows=[OpenAIProvider(),AnthropicProvider(),GeminiProvider()]
    return [x for x in rows if getattr(x,"key","")]


async def _peer_turn(provider: Provider, incoming: dict, expected: str, conv: str,
                     budget: SpendBudget, transcript: list[dict], metrics: dict) -> dict | None:
    result=await provider.call(incoming,budget)
    transcript.append({"direction":"MYCELIX_TO_PEER","message":incoming})
    if result.error:
        metrics["errors"].append(result.error)
        transcript.append({"direction":"PEER_TO_MYCELIX","error":result.error})
        metrics["invalid_messages"]+=1
        return None
    metrics["input_tokens"]+=result.input_tokens
    metrics["output_tokens"]+=result.output_tokens
    data=_extract_json(result.text)
    checked=nd.validate_message(data,expected_type=expected,expected_conversation_id=conv) if data else {
        "ok":False,"event":"SCHEMA_INVALID","error":"json_object_not_found"
    }
    transcript.append({"direction":"PEER_TO_MYCELIX","raw":result.text[:5000],"parsed":data,"validation":{k:v for k,v in checked.items() if k!="data"}})
    if checked.get("ok"):
        metrics["valid_messages"]+=1
        return data
    metrics["invalid_messages"]+=1
    metrics["errors"].append(str(checked.get("event") or "SCHEMA_INVALID")+":"+str(checked.get("error") or "unknown"))
    return None


async def run_once(provider: Provider, run_no: int, budget: SpendBudget) -> dict:
    conv=f"harness-{provider.provider.lower()}-{run_no}"
    transcript=[]
    metrics={
        "provider":provider.provider,"model":provider.model,"run":run_no,
        "dialect_adopted":False,"adoption_turn":None,
        "valid_messages":0,"invalid_messages":0,"turns_total":0,
        "fallback_activated":False,"errors":[],"input_tokens":0,"output_tokens":0,
    }
    hello=nd.hello(conv,"https://neo-collettive.onrender.com/neo-dialect/1.0")
    cap=await _peer_turn(provider,hello,"CAPABILITIES",conv,budget,transcript,metrics)
    metrics["turns_total"]=2
    if not cap:
        metrics["fallback_activated"]=True
        return {**metrics,"completed":False,"transcript":transcript}
    metrics["dialect_adopted"]=True
    metrics["adoption_turn"]=2

    proposal=nd.propose(
        conv,"market-category-analysis",
        {"deliverable":"brief comparison","category":"developer-tools"},
        {"deliverable":"brief comparison","category":"api-integration-tools","expected_response_type":"COUNTER"},
        "proposal-1",
    )
    counter=await _peer_turn(provider,proposal,"COUNTER",conv,budget,transcript,metrics)
    metrics["turns_total"]=4
    if not counter:
        return {**metrics,"completed":False,"transcript":transcript}

    agreement=nd.new_envelope(
        "AGREE",conv,
        proposal_id="proposal-1",
        agreement_id="agreement-1",
        terms={"deliverable":"short market-category summary","category":"api-integration-tools","expected_response_type":"RESULT"},
    )
    result=await _peer_turn(provider,agreement,"RESULT",conv,budget,transcript,metrics)
    metrics["turns_total"]=6
    if not result:
        return {**metrics,"completed":False,"transcript":transcript}

    farewell=nd.bye(conv,"test exchange complete","completed")
    transcript.append({"direction":"MYCELIX_TO_PEER","message":farewell})
    metrics["turns_total"]=7
    return {**metrics,"completed":True,"transcript":transcript}


async def run_all() -> dict:
    providers=configured_providers()
    budget=SpendBudget()
    report={
        "dialect_version":nd.DIALECT_VERSION,
        "providers_configured":[{"provider":p.provider,"model":p.model} for p in providers],
        "runs":[],
        "budget_cap_usd":budget.cap,
        "reserve_per_call_usd":budget.reserve_per_call,
    }
    stop=False
    for provider in providers:
        for run_no in range(1,4):
            if stop:
                break
            try:
                report["runs"].append(await run_once(provider,run_no,budget))
            except RuntimeError as exc:
                report["runs"].append({
                    "provider":provider.provider,"model":provider.model,"run":run_no,
                    "dialect_adopted":False,"adoption_turn":None,"valid_messages":0,"invalid_messages":0,
                    "turns_total":0,"fallback_activated":True,"errors":[str(exc)],
                    "input_tokens":0,"output_tokens":0,"completed":False,"transcript":[],
                })
                stop=str(exc)=="TEST_SPEND_CAP_REACHED"
    report["api_calls"]=budget.calls
    report["reserved_spend_usd"]=round(budget.reserved,4)
    report["total_input_tokens"]=sum(int(x.get("input_tokens") or 0) for x in report["runs"])
    report["total_output_tokens"]=sum(int(x.get("output_tokens") or 0) for x in report["runs"])
    summary={}
    for p in providers:
        rows=[x for x in report["runs"] if x.get("provider")==p.provider]
        summary[p.provider]={
            "model":p.model,
            "runs":len(rows),
            "completed":sum(1 for x in rows if x.get("completed")),
            "adopted":sum(1 for x in rows if x.get("dialect_adopted")),
            "stable_3_of_3":len(rows)==3 and all(x.get("completed") for x in rows),
        }
    report["stability"]=summary
    REPORT_PATH.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    return report


def main() -> int:
    report=asyncio.run(run_all())
    print(json.dumps({
        "dialect_version":report["dialect_version"],
        "providers_configured":report["providers_configured"],
        "stability":report["stability"],
        "api_calls":report["api_calls"],
        "reserved_spend_usd":report["reserved_spend_usd"],
        "total_input_tokens":report["total_input_tokens"],
        "total_output_tokens":report["total_output_tokens"],
        "report_path":str(REPORT_PATH),
    },ensure_ascii=False,indent=2))
    return 0 if len(report["providers_configured"])>=2 else 2


if __name__=="__main__":
    raise SystemExit(main())
