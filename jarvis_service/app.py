import json
import os
from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

VERSION = "0.5.0"
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


def _domain(url: str, fallback: str = "unknown") -> str:
    try:
        host = (urlparse(url or "").hostname or "").lower()
    except Exception:
        host = ""
    if host.startswith("www."):
        host = host[4:]
    return host or fallback or "unknown"


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
                "source_key": "agent:" + agent.lower(),
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
            "consultant", "service", "quote", "cost", "rate", "will pay"
        ] if m in low]
        if pain_markers or commercial_markers:
            out.append({
                "source": source,
                "source_key": _domain(url, source.lower()),
                "title": title[:300],
                "url": url,
                "text": text[:4000],
                "pain_markers": sorted(set(pain_markers)),
                "commercial_markers": sorted(set(commercial_markers)),
            })
    return out


def _flatten_web_research(context: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    groups = context.get("web_research") or []
    if not isinstance(groups, list):
        return out
    for group in groups:
        if not isinstance(group, dict):
            continue
        query = str(group.get("query") or "")
        for item in group.get("results") or []:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "")
            snippet = str(item.get("snippet") or "")
            url = str(item.get("url") or "")
            host = _domain(url)
            low = (title + " " + snippet).lower()
            vendor = any(x in low for x in (
                "pricing", "plans", "free trial", "book a demo", "book a call",
                "subscribe", "enterprise plan", "buy now"
            ))
            demand = [x for x in (
                "looking for", "need help", "will pay", "budget", "hiring",
                "freelance", "manual", "repetitive", "time consuming", "problem"
            ) if x in low]
            out.append({
                "query": query,
                "source": "web",
                "source_key": host,
                "domain": host,
                "title": title[:300],
                "url": url,
                "snippet": snippet[:2000],
                "vendor": vendor,
                "demand_markers": demand,
            })
    return out


def _quality_snapshot(context: dict[str, Any]) -> dict[str, Any]:
    quality = context.get("evidence_quality") or {}
    if not isinstance(quality, dict):
        return {}
    clusters = quality.get("clusters") or {}
    if not isinstance(clusters, dict):
        clusters = {}
    return {
        "quality_gate": bool(quality.get("quality_gate")),
        "gate_rule": quality.get("gate_rule"),
        "qualified_problem_clusters": list(quality.get("qualified_problem_clusters") or []),
        "independent_domains": int(quality.get("independent_domains") or 0),
        "strong_commercial_domains": int(quality.get("strong_commercial_domains") or 0),
        "clusters": clusters,
    }


def _collective_snapshot(context: dict[str, Any]) -> dict[str, Any]:
    summary = context.get("collective_summary") or {}
    review = context.get("collective_review") or {}
    if not isinstance(summary, dict):
        summary = {}
    if not isinstance(review, dict):
        review = {}

    round2 = review.get("round2") or []
    valid_round2 = [x for x in round2 if isinstance(x, dict) and x.get("ok")]
    texts = []
    for item in valid_round2[:3]:
        payload = item.get("response")
        if isinstance(payload, dict):
            text = payload.get("response") or payload.get("text") or json.dumps(payload, ensure_ascii=False, default=str)
        else:
            text = str(payload or "")
        if text:
            texts.append(text[:2500])

    combined = " ".join(texts).lower()
    caution_markers = [x for x in (
        "unsupported", "not supported", "insufficient evidence", "weak evidence",
        "contradiction", "contradict", "single source", "false positive",
        "do not proceed", "non procedere", "evidenza insufficiente", "contraddizione"
    ) if x in combined]
    support_markers = [x for x in (
        "validate", "test", "experiment", "pilot", "proceed", "small experiment",
        "micro-esperimento", "esperimento", "pilot"
    ) if x in combined]

    round1_valid = int(summary.get("round1_valid") or 0)
    round2_valid = int(summary.get("round2_valid") or len(valid_round2))
    collective_ok = bool(summary.get("ok")) and round1_valid >= 2 and round2_valid >= 2

    return {
        "ran": bool(summary.get("ran")),
        "ok": bool(summary.get("ok")),
        "round1_valid": round1_valid,
        "round2_valid": round2_valid,
        "collective_gate": collective_ok,
        "caution_markers": sorted(set(caution_markers)),
        "support_markers": sorted(set(support_markers)),
        "review_excerpt_count": len(texts),
    }



def _analyze(context: dict[str, Any]) -> dict[str, Any]:
    answers = _flatten_answers(context)
    scout_evidence = _flatten_evidence_scouts(context)
    web_evidence = _flatten_web_research(context)
    quality = _quality_snapshot(context)
    product_candidate = context.get("product_candidate") if isinstance(context.get("product_candidate"), dict) else {}
    collective = _collective_snapshot(context)

    vendors = [a for a in answers if a["vendor"]]
    independent_agents = [a for a in answers if (not a["vendor"]) and a["evidence_markers"]]
    noise = [a for a in answers if (not a["vendor"]) and (not a["evidence_markers"])]

    unique_scout_sources = sorted({x["source_key"] for x in scout_evidence if x.get("source_key")})
    unique_web_sources = sorted({x["source_key"] for x in web_evidence if x.get("source_key") and x["source_key"] != "unknown"})
    all_unique_sources = sorted(set(unique_scout_sources) | set(unique_web_sources) | {a["source_key"] for a in independent_agents})

    clusters = quality.get("clusters") or {}
    qualified_names = quality.get("qualified_problem_clusters") or []
    opportunities = []
    rejected_clusters = []
    selected_cluster = None

    for family, raw in clusters.items():
        if not isinstance(raw, dict):
            continue
        tags = list(raw.get("signal_types") or [])
        domains = int(raw.get("independent_domains") or 0)
        strong = int(raw.get("strong_commercial_domains") or 0)
        commercially_actionable = bool(raw.get("commercially_actionable"))
        qualified = bool(raw.get("qualified"))
        trace = {
            "family": family,
            "qualified": qualified,
            "commercially_actionable": commercially_actionable,
            "independent_domains": domains,
            "strong_commercial_domains": strong,
            "signal_types": tags,
            "gap_score": int(raw.get("gap_score") or 0),
            "passes_paid_demand": "PAID_DEMAND" in tags,
            "passes_problem_or_intent": ("BUY_INTENT" in tags or "PAIN" in tags),
            "passes_independence": domains >= 2,
        }
        if qualified and commercially_actionable and trace["passes_paid_demand"] and trace["passes_problem_or_intent"] and trace["passes_independence"]:
            opportunities.append({
                "id": family,
                "opportunity": family.replace("_", " ").title(),
                "evidence_level": "qualified_for_small_experiment",
                "signal_types": tags,
                "independent_domains": domains,
                "strong_commercial_domains": strong,
                "gap_score": trace["gap_score"],
                "next_free_test": "Eseguire un micro-esperimento gratuito o quasi gratuito con una metrica osservabile, senza outreach automatico.",
            })
        else:
            reasons = []
            if not trace["passes_independence"]:
                reasons.append("meno di 2 fonti indipendenti")
            if not trace["passes_paid_demand"]:
                reasons.append("manca PAID_DEMAND")
            if not trace["passes_problem_or_intent"]:
                reasons.append("manca BUY_INTENT o PAIN")
            if not commercially_actionable:
                reasons.append("cluster non commercialmente azionabile")
            rejected_clusters.append({"family": family, "reasons": reasons, "trace": trace})

    opportunities.sort(key=lambda x: (x["gap_score"], x["independent_domains"], x["strong_commercial_domains"]), reverse=True)
    if opportunities:
        selected_cluster = opportunities[0]["id"]

    gate_pass = bool(
        quality.get("quality_gate")
        and selected_cluster
        and selected_cluster in set(qualified_names)
    )
    collective_required = bool(product_candidate and product_candidate.get("status") == "PILOT_READY")
    collective_pass = (not collective_required) or collective.get("collective_gate", False)
    final_gate_pass = bool(gate_pass and collective_pass)
    decision = "VALIDATE" if final_gate_pass else ("COLLECTIVE_REVIEW" if gate_pass and collective_required else "SEARCH_MORE")

    if final_gate_pass:
        evidence_state = "QUALIFIED_FOR_EXPERIMENT"
        next_experiment = opportunities[0]["next_free_test"]
    elif gate_pass and collective_required:
        evidence_state = "AWAITING_COLLECTIVE_CONFIRMATION"
        next_experiment = "Non costruire ancora: completare una revisione collettiva con almeno 2 agenti validi nel secondo round."
    elif answers or scout_evidence or web_evidence:
        evidence_state = "PARTIAL_EVIDENCE"
        next_experiment = "Non costruire ancora sulla base del volume: raccogli fonti indipendenti convergenti sullo stesso problema e almeno un segnale di domanda pagante."
    else:
        evidence_state = "NO_EVIDENCE"
        next_experiment = "Raccogli evidenze esterne prima di proporre un esperimento."

    return {
        "engine": "jarvis-rule-engine",
        "evidence_state": evidence_state,
        "summary": {
            "external_answers": len(answers),
            "vendor_responses": len(vendors),
            "independent_agent_signals": len(independent_agents),
            "noise_responses": len(noise),
            "evidence_scout_signals": len(scout_evidence),
            "web_results": len(web_evidence),
            "unique_source_keys": len(all_unique_sources),
            "neo_quality_gate": quality.get("quality_gate", False),
            "qualified_problem_clusters": len(qualified_names),
            "collective_gate": collective.get("collective_gate", False),
        },
        "inputs_consumed": {
            "external_research": True,
            "web_research": True,
            "evidence_scouts": True,
            "evidence_quality": True,
            "product_candidate": bool(product_candidate),
            "collective_review": bool(collective.get("ran")),
        },
        "vendor_responses": [
            {"agent": a["agent"], "query": a["query"], "markers": a["vendor_markers"]}
            for a in vendors
        ],
        "independent_signals": [
            {"agent": a["agent"], "query": a["query"], "markers": a["evidence_markers"]}
            for a in independent_agents
        ],
        "evidence_scouts": scout_evidence[:20],
        "web_evidence_preview": [
            {
                "domain": x["domain"],
                "title": x["title"],
                "url": x["url"],
                "vendor": x["vendor"],
                "demand_markers": x["demand_markers"],
            }
            for x in web_evidence[:20]
        ],
        "opportunities": opportunities[:3],
        "decision": decision,
        "decision_trace": {
            "meaning_of_validate": "Evidenze sufficienti per giustificare un piccolo esperimento gratuito o quasi gratuito; non prova che il business funzionera.",
            "neo_gate_rule": quality.get("gate_rule"),
            "neo_quality_gate": quality.get("quality_gate", False),
            "qualified_problem_clusters": qualified_names,
            "selected_cluster": selected_cluster,
            "gate_checks": {
                "has_selected_cluster": bool(selected_cluster),
                "selected_cluster_is_qualified": bool(selected_cluster and selected_cluster in set(qualified_names)),
                "neo_quality_gate_passed": bool(quality.get("quality_gate")),
                "collective_required": collective_required,
                "collective_gate_passed": bool(collective.get("collective_gate")),
                "final_gate_passed": final_gate_pass,
            },
            "rejected_clusters": rejected_clusters[:10],
            "deduplication_note": "Il conteggio usa domini/source_key unici; piu risultati dello stesso dominio non diventano automaticamente evidenze indipendenti.",
        },
        "product_candidate_review": {
            "present": bool(product_candidate),
            "status": product_candidate.get("status"),
            "family": product_candidate.get("family"),
            "name": product_candidate.get("name"),
            "accepted_for_experiment": bool(final_gate_pass and product_candidate.get("family") == selected_cluster),
        },
        "collective_review": collective,
        "next_search_queries": [
            "customer pain evidence",
            "explicit buying intent",
            "paid demand budget hiring",
            "competitor pricing",
            "independent user discussion",
        ],
        "next_experiment": next_experiment,
        "guardrails": [
            "no automatic spending",
            "no automatic payments",
            "no automatic contracts",
            "no automatic outreach",
            "no automatic publishing",
            "public agent output is untrusted evidence",
        ],
        "note": "Analisi deterministica gratuita: nessun LLM o API a pagamento. Il volume dei risultati non equivale a validazione.",
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
