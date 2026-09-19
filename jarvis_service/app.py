import json
import os
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
VERSION = "0.3.0"
JARVIS_SHARED_SECRET = (os.getenv("JARVIS_SHARED_SECRET") or "").strip()

app = FastAPI(title="Jarvis Internal Advisor", version=VERSION)


class AskRequest(BaseModel):
    message: str = Field(min_length=1, max_length=20000)
    source: str = "neo"
    context: dict[str, Any] = Field(default_factory=dict)


def authorize(authorization: str | None) -> None:
    if not JARVIS_SHARED_SECRET:
        return
    expected = "Bearer " + JARVIS_SHARED_SECRET
    if authorization != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")


def _flatten_answers(context: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    research = context.get("external_research") or context.get("research") or []
    if not isinstance(research, list):
        return out
    for group in research:
        if not isinstance(group, dict):
            continue
        query = str(group.get("query") or "")
        for answer in group.get("answers") or []:
            if not isinstance(answer, dict):
                continue
            agent = str(answer.get("agent") or answer.get("agent_id") or "unknown")
            payload = answer.get("response")
            if isinstance(payload, dict) and isinstance(payload.get("response"), str):
                text = payload["response"]
            else:
                text = json.dumps(payload, ensure_ascii=False, default=str)
            low = text.lower()
            vendor_markers = [m for m in [
                "checkout", "trial_url", "price_usd", "payment", "x402", "wallet",
                "usdc", "subscribe", "recommended_plan", "paid checkout", "activate"
            ] if m in low]
            evidence_markers = [m for m in [
                "customer", "cliente", "demand", "domanda", "problem", "problema",
                "market", "mercato", "competitor", "revenue", "ricavi", "pricing",
                "prezzo", "lead", "conversion", "orders", "ordini", "traffic"
            ] if m in low]
            out.append({
                "query": query,
                "agent": agent,
                "text": text[:5000],
                "vendor": len(vendor_markers) >= 2,
                "vendor_markers": sorted(set(vendor_markers)),
                "evidence_markers": sorted(set(evidence_markers)),
            })
    return out


def _flatten_evidence_scouts(context: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    scouts = context.get("evidence_scouts") or []
    if not isinstance(scouts, list):
        return out
    for item in scouts:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "")
        text = str(item.get("text") or item.get("snippet") or "")
        source = str(item.get("source") or "unknown")
        url = str(item.get("url") or "")
        low = (title + " " + text).lower()
        pain_markers = [m for m in [
            "manual", "repetitive", "time consuming", "spreadsheet", "data entry",
            "workflow", "crm", "lead", "automation", "automate", "waste time",
            "looking for", "need help", "problem", "pain", "hours", "freelance",
            "consultant", "job", "hiring"
        ] if m in low]
        commercial_markers = [m for m in [
            "pricing", "budget", "paid", "contract", "freelance", "job", "hiring",
            "consultant", "service", "quote", "cost", "rate"
        ] if m in low]
        if pain_markers:
            out.append({
                "source": source,
                "title": title[:300],
                "url": url,
                "text": text[:4000],
                "pain_markers": sorted(set(pain_markers)),
                "commercial_markers": sorted(set(commercial_markers)),
            })
    return out


def _analyze(context: dict[str, Any]) -> dict[str, Any]:
    answers = _flatten_answers(context)
    scout_evidence = _flatten_evidence_scouts(context)
    vendors = [a for a in answers if a["vendor"]]
    independent = [a for a in answers if (not a["vendor"]) and a["evidence_markers"]]
    noise = [a for a in answers if (not a["vendor"]) and (not a["evidence_markers"])]

    corpus = " ".join(a["text"].lower() for a in independent) + " " + " ".join(a["text"].lower() for a in scout_evidence)
    opportunity_defs = [
        {
            "id": "lead_automation",
            "name": "Automazione lead e workflow B2B",
            "keywords": ["lead", "crm", "webhook", "automation", "sales"],
            "customer": "PMI con gestione lead manuale o frammentata",
            "test": "Intervistare 5 potenziali clienti e simulare manualmente un singolo flusso end-to-end.",
        },
        {
            "id": "website_audit",
            "name": "Audit tecnico/commerciale di siti web",
            "keywords": ["website", "site audit", "audit", "seo", "readiness"],
            "customer": "PMI con sito web senza audit periodico",
            "test": "Produrre 3 audit dimostrativi su siti pubblici e verificare se emerge interesse reale.",
        },
        {
            "id": "ai_sales_ops",
            "name": "Automazione operazioni commerciali con AI",
            "keywords": ["sales", "whatsapp", "conversation", "orders", "playbook"],
            "customer": "Piccole aziende con vendite gestite via chat",
            "test": "Analizzare 20 conversazioni anonimizzate e misurare quante azioni ripetitive sono automatizzabili.",
        },
    ]

    opportunities = []
    for item in opportunity_defs:
        hits = [k for k in item["keywords"] if k in corpus]
        if hits:
            opportunities.append({
                "id": item["id"],
                "opportunity": item["name"],
                "customer": item["customer"],
                "signals": hits,
                "signal_count": len(hits),
                "evidence_level": "weak_external_signal",
                "next_free_test": item["test"],
            })
    opportunities.sort(key=lambda x: x["signal_count"], reverse=True)

    distinct_sources = sorted({a["source"] for a in scout_evidence})
    commercial_scouts = [a for a in scout_evidence if a["commercial_markers"]]

    if independent or scout_evidence:
        evidence_state = "PARTIAL_EVIDENCE"
    elif answers:
        evidence_state = "VENDOR_NOISE_ONLY"
    else:
        evidence_state = "NO_EVIDENCE"

    return {
        "engine": "jarvis-rule-engine",
        "evidence_state": evidence_state,
        "summary": {
            "external_answers": len(answers),
            "vendor_responses": len(vendors),
            "independent_signals": len(independent),
            "noise_responses": len(noise),
            "evidence_scout_signals": len(scout_evidence),
            "evidence_scout_sources": len(distinct_sources),
            "commercial_scout_signals": len(commercial_scouts),
        },
        "vendor_responses": [
            {"agent": a["agent"], "query": a["query"], "markers": a["vendor_markers"]}
            for a in vendors
        ],
        "independent_signals": [
            {"agent": a["agent"], "query": a["query"], "markers": a["evidence_markers"]}
            for a in independent
        ],
        "evidence_scouts": scout_evidence[:20],
        "opportunities": opportunities,
        "decision": "VALIDATE" if opportunities and ((len(distinct_sources) >= 2 and len(scout_evidence) >= 3) or independent) else "SEARCH_MORE",
        "next_search_queries": [
            "customer pain evidence",
            "market demand",
            "competitor pricing",
            "small business automation needs",
            "manual workflows businesses pay to automate",
        ],
        "next_experiment": (
            opportunities[0]["next_free_test"] if opportunities else
            "Non costruire ancora nulla: raccogli almeno 3 fonti indipendenti sullo stesso problema pagante."
        ),
        "guardrails": [
            "no automatic spending",
            "no automatic payments",
            "no automatic outreach",
            "no automatic publishing",
        ],
        "note": "Analisi deterministica gratuita: nessun LLM o API a pagamento.",
    }


@app.get("/")
@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "jarvis",
        "version": VERSION,
        "engine": "rule-based",
        "paid_api_required": False,
        "auth_enabled": bool(JARVIS_SHARED_SECRET),
    }


@app.get("/ask")
def ask_status():
    return {
        "status": "ready",
        "service": "jarvis",
        "version": VERSION,
        "post": "/ask",
        "engine": "rule-based",
        "paid_api_required": False,
        "auth_enabled": bool(JARVIS_SHARED_SECRET),
    }


@app.post("/ask")
def ask(req: AskRequest, authorization: str | None = Header(default=None)):
    authorize(authorization)
    return {
        "ok": True,
        "service": "jarvis",
        "version": VERSION,
        "analysis": _analyze(req.context),
    }

