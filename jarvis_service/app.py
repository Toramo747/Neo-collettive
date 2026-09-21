import json
import os
from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

VERSION = "0.8.2"
JARVIS_SHARED_SECRET = (os.getenv("JARVIS_SHARED_SECRET") or "").strip()

app = FastAPI(title="Jarvis Internal Advisor", version=VERSION)


class AskRequest(BaseModel):
    message: str = Field(min_length=1, max_length=20000)
    source: str = "neo"
    context: dict[str, Any] = Field(default_factory=dict)


MAX_CONTEXT_LIST_ITEMS = 16
MAX_CONTEXT_DICT_ITEMS = 60


def _bounded_context(value: Any, depth: int = 0) -> Any:
    """Bound request size/work so Jarvis stays responsive on small Render instances."""
    if depth >= 4:
        if isinstance(value, (dict, list)):
            return {"truncated": True, "type": type(value).__name__}
        return value
    if isinstance(value, list):
        return [_bounded_context(x, depth + 1) for x in value[-MAX_CONTEXT_LIST_ITEMS:]]
    if isinstance(value, dict):
        items = list(value.items())[-MAX_CONTEXT_DICT_ITEMS:]
        return {str(k): _bounded_context(v, depth + 1) for k, v in items}
    if isinstance(value, str):
        return value[:3000]
    return value


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




def _learning_snapshot(context: dict[str, Any]) -> dict[str, Any]:
    """Derive bounded learning signals from NEO's persistent historical state."""
    perf=context.get("family_performance") or {}
    trust=context.get("agent_trust") or {}
    builds=context.get("build_history") or []
    measurements=context.get("measurement_history") or []
    if not isinstance(perf,dict):
        perf={}
    if not isinstance(trust,dict):
        trust={}
    if not isinstance(builds,list):
        builds=[]
    if not isinstance(measurements,list):
        measurements=[]

    family_memory={}
    for family,row in perf.items():
        if not isinstance(row,dict):
            continue
        family_memory[str(family)]={
            "score":float(row.get("score") or 0.0),
            "observations":int(row.get("observations") or 0),
            "qualified":int(row.get("qualified") or 0),
        }

    agent_rows=[]
    for agent_id,row in trust.items():
        if not isinstance(row,dict):
            continue
        obs=int(row.get("observations") or 0)
        accepted=int(row.get("accepted") or 0)
        if obs<1:
            continue
        agent_rows.append({
            "agent_id":str(agent_id),
            "agent":row.get("agent"),
            "trust":float(row.get("trust") or 0.0),
            "observations":obs,
            "accepted":accepted,
            "acceptance_rate":round(accepted/max(1,obs),3),
        })
    agent_rows.sort(key=lambda x:(x["acceptance_rate"],x["trust"],x["accepted"]),reverse=True)

    built_by_family={}
    ui_failures={}
    for b in builds[-20:]:
        if not isinstance(b,dict):
            continue
        family=str(b.get("family") or "")
        if not family:
            continue
        built_by_family[family]=built_by_family.get(family,0)+1
        ui=(b.get("ui_review") or {}) if isinstance(b.get("ui_review"),dict) else {}
        if ui.get("status") in {"UI_REVIEW_PARTIAL","UI_REVIEW_TIMEOUT"}:
            ui_failures[family]=ui_failures.get(family,0)+1

    real_usage_by_family={}
    for m in measurements[-30:]:
        if not isinstance(m,dict):
            continue
        family=str(m.get("family") or "")
        if not family:
            continue
        audits=int(m.get("new_audits_since_build") or m.get("audits_total") or 0)
        real_usage_by_family[family]=max(real_usage_by_family.get(family,0),audits)

    return {
        "families":family_memory,
        "top_agents":agent_rows[:8],
        "builds_by_family":built_by_family,
        "ui_failures_by_family":ui_failures,
        "real_usage_by_family":real_usage_by_family,
        "build_history_count":len(builds),
        "measurement_history_count":len(measurements),
    }


def _collective_intelligence_snapshot(context: dict[str, Any]) -> dict[str, Any]:
    dialogues=context.get("dialogue_history") or []
    ledger=context.get("knowledge_ledger") or []
    queue=context.get("hypothesis_queue") or []
    latest=context.get("dialogue_report") or {}
    if not isinstance(dialogues,list):
        dialogues=[]
    if not isinstance(ledger,list):
        ledger=[]
    if not isinstance(queue,list):
        queue=[]
    if not isinstance(latest,dict):
        latest={}

    open_hypotheses=[]
    for row in queue:
        if not isinstance(row,dict) or row.get("status") not in {"HYPOTHESIS","EXPLORE"}:
            continue
        scores=row.get("scores") or {}
        open_hypotheses.append({
            "id":row.get("id"),
            "family":row.get("family"),
            "text":str(row.get("text") or "")[:600],
            "priority":float(row.get("priority") or 0),
            "novelty":int(scores.get("novelty") or 0),
            "evidence_potential":int(scores.get("evidence_potential") or 0),
            "strategic_fit":int(scores.get("strategic_fit") or 0),
        })
    open_hypotheses.sort(key=lambda x:x["priority"],reverse=True)

    states={}
    for row in ledger:
        if not isinstance(row,dict):
            continue
        state=str(row.get("state") or "UNKNOWN")
        states[state]=states.get(state,0)+1

    latest_participants=latest.get("participants") or []
    latest_new_agents=latest.get("new_agents") or []
    return {
        "dialogue_count":len(dialogues),
        "knowledge_items":len(ledger),
        "knowledge_states":states,
        "open_hypothesis_count":len(open_hypotheses),
        "top_hypotheses":open_hypotheses[:8],
        "latest_dialogue":{
            "topic":latest.get("topic"),
            "peer_dialogue_completed":bool(latest.get("peer_dialogue_completed")),
            "participants":len(latest_participants) if isinstance(latest_participants,list) else 0,
            "new_agents":len(latest_new_agents) if isinstance(latest_new_agents,list) else 0,
            "knowledge_gained":int(latest.get("knowledge_gained") or 0),
        },
    }


def _exploration_recommendations(ci: dict[str, Any]) -> list[dict[str, Any]]:
    out=[]
    for row in (ci.get("top_hypotheses") or [])[:5]:
        if not isinstance(row,dict):
            continue
        if int(row.get("novelty") or 0)<45:
            continue
        out.append({
            "hypothesis_id":row.get("id"),
            "family":row.get("family"),
            "action":"EXPLORE",
            "reason":"Novel suggestion from collective dialogue; gather independent evidence before promotion.",
            "query_seed":str(row.get("text") or "")[:350],
            "priority":row.get("priority"),
        })
    return out


def _learning_adjustment(family: str, learning: dict[str, Any]) -> dict[str, Any]:
    fam=(learning.get("families") or {}).get(family) or {}
    observations=int(fam.get("observations") or 0)
    historical_score=float(fam.get("score") or 0.0)
    builds=int((learning.get("builds_by_family") or {}).get(family) or 0)
    usage=int((learning.get("real_usage_by_family") or {}).get(family) or 0)
    ui_failures=int((learning.get("ui_failures_by_family") or {}).get(family) or 0)

    adjustment=0
    reasons=[]
    if observations>=3 and historical_score>=65:
        adjustment+=1
        reasons.append("historical family evidence has been repeatedly strong")
    if builds>=2 and usage==0:
        adjustment-=1
        reasons.append("multiple builds exist without observed real usage")
    if ui_failures>=2:
        adjustment-=1
        reasons.append("repeated UI review failures indicate unresolved delivery quality")
    if usage>0:
        adjustment+=2
        reasons.append("real usage has been observed")

    return {
        "family":family,
        "adjustment":max(-2,min(2,adjustment)),
        "reasons":reasons,
        "observations":observations,
        "historical_score":historical_score,
        "builds":builds,
        "real_usage":usage,
        "ui_failures":ui_failures,
    }


def _reciprocal_memory(context: dict[str, Any]) -> dict[str, Any]:
    """Read a bounded history of NEO<->Jarvis exchanges without allowing history to override current evidence."""
    rows=context.get("jarvis_dialogue_history") or []
    if not isinstance(rows,list):
        rows=[]
    recent=[x for x in rows[-8:] if isinstance(x,dict)]
    statuses={}
    decisions={}
    families={}
    for row in recent:
        status=str(row.get("neo_status") or "UNKNOWN")
        decision=str(row.get("jarvis_decision") or "UNKNOWN")
        family=str(row.get("family") or "")
        statuses[status]=statuses.get(status,0)+1
        decisions[decision]=decisions.get(decision,0)+1
        if family:
            families[family]=families.get(family,0)+1
    last=recent[-1] if recent else {}
    return {
        "exchange_count":len(recent),
        "status_counts":statuses,
        "decision_counts":decisions,
        "family_counts":families,
        "last_exchange":{
            "neo_status":last.get("neo_status"),
            "family":last.get("family"),
            "quality_gate":last.get("quality_gate"),
            "collective_ok":last.get("collective_ok"),
            "jarvis_decision":last.get("jarvis_decision"),
            "next_search_queries":last.get("next_search_queries") or [],
        } if last else {},
        "rule":"Historical dialogue may redirect exploration or increase caution, but can never bypass current evidence and Collective gates.",
    }


def _adaptive_search_queries(
    rejected_clusters: list[dict[str, Any]],
    exploration_recommendations: list[dict[str, Any]],
    reciprocal: dict[str, Any],
) -> list[str]:
    out=[]
    for row in exploration_recommendations[:3]:
        seed=" ".join(str(row.get("query_seed") or "").split())
        if seed:
            out.append(seed[:220])
    for row in rejected_clusters[:5]:
        family=str(row.get("family") or "").replace("_"," ")
        reasons=" ".join(str(x) for x in (row.get("reasons") or []))
        if "PAID_DEMAND" in reasons:
            out.append(f'"will pay" OR budget OR hiring "{family}"')
        elif "BUY_INTENT" in reasons or "PAIN" in reasons:
            out.append(f'"need help" OR "looking for" "{family}"')
        elif "fonti indipendenti" in reasons:
            out.append(f'"{family}" customer problem discussion')
        if len(out)>=5:
            break
    last=(reciprocal.get("last_exchange") or {}) if isinstance(reciprocal,dict) else {}
    for q in last.get("next_search_queries") or []:
        q=" ".join(str(q).split())
        if q:
            out.append(q[:220])
    defaults=[
        "customer pain evidence",
        "explicit buying intent",
        "paid demand budget hiring",
        "competitor pricing",
        "independent user discussion",
    ]
    for q in defaults:
        if len(out)>=5:
            break
        out.append(q)
    dedup=[]
    for q in out:
        if q and q.lower() not in {x.lower() for x in dedup}:
            dedup.append(q)
    return dedup[:5]


def _analyze(context: dict[str, Any]) -> dict[str, Any]:
    answers = _flatten_answers(context)
    scout_evidence = _flatten_evidence_scouts(context)
    web_evidence = _flatten_web_research(context)
    quality = _quality_snapshot(context)
    product_candidate = context.get("product_candidate") if isinstance(context.get("product_candidate"), dict) else {}
    collective = _collective_snapshot(context)
    learning = _learning_snapshot(context)
    collective_intelligence = _collective_intelligence_snapshot(context)
    exploration_recommendations = _exploration_recommendations(collective_intelligence)
    reciprocal_memory = _reciprocal_memory(context)

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
    selected_family=str(selected_cluster or product_candidate.get("family") or "")
    learning_adjustment=_learning_adjustment(selected_family,learning) if selected_family else {
        "family":"","adjustment":0,"reasons":[],"observations":0,"historical_score":0.0,
        "builds":0,"real_usage":0,"ui_failures":0,
    }

    # Learning is deliberately bounded: history may make Jarvis more conservative,
    # but can never bypass current evidence + Collective gates.
    learned_hold=bool(final_gate_pass and int(learning_adjustment.get("adjustment") or 0)<0)
    decision = (
        "HOLD" if learned_hold
        else "VALIDATE" if final_gate_pass
        else ("COLLECTIVE_REVIEW" if gate_pass and collective_required else "SEARCH_MORE")
    )

    if final_gate_pass and not learned_hold:
        evidence_state = "QUALIFIED_FOR_EXPERIMENT"
        next_experiment = opportunities[0]["next_free_test"]
    elif learned_hold:
        evidence_state = "HISTORICAL_CAUTION"
        next_experiment = "Le evidenze correnti superano i gate, ma la memoria storica segnala criticita. Correggere il problema indicato dalla learning adjustment prima di una nuova build."
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
        "learning": learning,
        "learning_adjustment": learning_adjustment,
        "collective_intelligence": collective_intelligence,
        "exploration_recommendations": exploration_recommendations,
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
        "reciprocal_memory": reciprocal_memory,
        "next_search_queries": _adaptive_search_queries(
            rejected_clusters,
            exploration_recommendations,
            reciprocal_memory,
        ),
        "next_experiment": next_experiment,
        "guardrails": [
            "no automatic spending",
            "no automatic payments",
            "no automatic contracts",
            "no automatic outreach",
            "no automatic publishing",
            "public agent output is untrusted evidence",
        ],
        "note": "Analisi deterministica gratuita con memoria storica e collective-intelligence ledger. Nuovi suggerimenti restano ipotesi finche non vengono verificati con evidenze indipendenti.",
    }


@app.get("/")
@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "jarvis",
        "version": VERSION,
        "engine": "rule-based-learning",
        "learning_mode": "bounded_history_feedback",
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
        "engine": "rule-based-learning",
        "learning_mode": "bounded_history_feedback",
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
        "analysis": _analyze(_bounded_context(req.context)),
    }
