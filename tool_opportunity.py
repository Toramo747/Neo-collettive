# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Andrea Gava
"""Evidence-grounded commercial tool opportunity ranking.

This module deliberately separates market evidence from the legacy human-help
gate. Every scored signal must carry a public URL and observation timestamp.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import urlparse

TOOL_OPPORTUNITY_SCHEMA_VERSION = 2

CATEGORY_CONFIGS = {
    "ai_tools": {
        "title": "A2A Delivery Verifier",
        "target_user": "teams operating A2A/MCP agents in production",
        "problem": "Teams need focused AI/agent utilities with clearer capability boundaries, pricing and interoperability.",
        "aliases": ["AI agent tool", "AI assistant SaaS", "agent automation"],
        "build_days": 6,
        "distribution": "Product Hunt + MCP/A2A registries + direct web",
    },
    "developer_tools": {
        "title": "CI Failure Replay",
        "target_user": "software teams debugging CI/CD and developer-tool failures",
        "problem": "Developers pay for tools that remove friction in debugging, testing, code review and delivery workflows.",
        "aliases": ["developer tool", "code review tool", "developer productivity"],
        "build_days": 7,
        "distribution": "VS Code Marketplace + GitHub + Product Hunt",
    },
    "integration_api": {
        "title": "Webhook Contract Monitor",
        "target_user": "integration teams maintaining APIs, webhooks and SaaS connectors",
        "problem": "Businesses buy integration tooling when existing connectors are costly, incomplete or difficult to operate.",
        "aliases": ["API integration tool", "workflow integration SaaS", "webhook automation"],
        "build_days": 8,
        "distribution": "MCP Registry + integration marketplaces + direct web",
    },
    "analytics_tools": {
        "title": "Report Drift Monitor",
        "target_user": "operations and analytics teams producing recurring business reports",
        "problem": "Teams pay for analytics and reporting tools but still report gaps in workflow, data access and pricing.",
        "aliases": ["analytics SaaS", "reporting tool", "dashboard software"],
        "build_days": 7,
        "distribution": "Product Hunt + direct SaaS + extension marketplaces",
    },
    "customer_support": {
        "title": "Support Reply Triage",
        "target_user": "support teams handling repetitive ticket and inbox triage",
        "problem": "Support teams pay for ticketing, triage and knowledge tools while seeking lower-cost or better integrated alternatives.",
        "aliases": ["customer support software", "helpdesk SaaS", "support automation tool"],
        "build_days": 8,
        "distribution": "Product Hunt + SaaS directories + direct web",
    },
    "cybersecurity_tools": {
        "title": "MCP Session Audit Logger",
        "target_user": "security teams auditing MCP/agent interactions and operational controls",
        "problem": "Security teams buy focused operational tools when suites are expensive, noisy or miss a concrete workflow.",
        "aliases": ["security operations tool", "cybersecurity SaaS", "security automation"],
        "build_days": 9,
        "distribution": "Security communities + GitHub + direct SaaS",
    },
    "productivity_tools": {
        "title": "Workflow Handoff Cleaner",
        "target_user": "small teams moving repetitive work between productivity tools",
        "problem": "Users pay for focused productivity automation when broad suites leave repetitive work or integration gaps.",
        "aliases": ["productivity tool", "workflow productivity SaaS", "automation app"],
        "build_days": 5,
        "distribution": "Product Hunt + Chrome Web Store + direct web",
    },
    "marketing_seo": {
        "title": "SEO Change Guard",
        "target_user": "marketing teams monitoring SEO workflow changes and regressions",
        "problem": "Marketing teams buy recurring tooling and frequently compare price, limits and missing workflow features.",
        "aliases": ["SEO software", "marketing automation tool", "content marketing SaaS"],
        "build_days": 7,
        "distribution": "Product Hunt + Chrome Web Store + direct SaaS",
    },
}

PAYMENT_MARKERS = (
    "pricing", "subscription", "paid plan", "pro plan", "per month",
    "/month", "/mo", "monthly", "annual plan", "purchase", "payment required",
    "payment_required", "x402", "starts at", "free trial",
)
DISSATISFACTION_MARKERS = (
    "too expensive", "expensive", "overpriced", "missing feature", "feature request",
    "doesn't support", "does not support", "wish it", "limitation", "limited",
    "alternative to", "looking for alternative", "frustrating", "frustration",
    "broken", "bug", "pain point", "cancelled because", "canceled because",
)
COUNTER_MARKERS = (
    "open source", "free forever", "completely free", "no cost", "free alternative",
    "self-hosted free", "self hosted free",
)
PRICE_RE = re.compile(
    r"(?:[$€£]\s?\d+(?:[.,]\d+)?)|"
    r"\b(?:USD|EUR|GBP)\s+\d+(?:[.,]\d+)?\b|"
    r"\b\d+(?:[.,]\d+)?\s?(?:USD|EUR|GBP)(?:\s*/\s*(?:mo|month|yr|year))?",
    re.I,
)


def _utc(value: str | None = None) -> str:
    if value:
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
        except Exception:
            pass
    return datetime.now(timezone.utc).isoformat()


def _domain(url: str) -> str:
    try:
        return (urlparse(str(url or "")).hostname or "").lower().removeprefix("www.")
    except Exception:
        return ""


def _family_from_text(text: str) -> str:
    low=str(text or "").lower()
    terms={
        "ai_tools":("ai agent","agentic","llm","ai assistant","artificial intelligence"),
        "developer_tools":("developer","code review","debug","testing","devops","ide","vscode"),
        "integration_api":("api integration","webhook","connector","integration","mcp server"),
        "analytics_tools":("analytics","dashboard","reporting","business intelligence"),
        "customer_support":("customer support","helpdesk","ticketing","support automation"),
        "cybersecurity_tools":("cybersecurity","security operations","soc ","vulnerability","security automation"),
        "productivity_tools":("productivity","task automation","workflow productivity"),
        "marketing_seo":("seo","marketing automation","content marketing","keyword"),
    }
    scores={k:sum(1 for x in values if x in low) for k,values in terms.items()}
    best=max(scores.items(),key=lambda kv:kv[1])
    return best[0] if best[1] else "productivity_tools"


FAMILY_RELEVANCE_MARKERS = {
    "ai_tools": ("ai","agent","a2a","mcp","llm"),
    "developer_tools": ("developer","code","coding","debug","test","testing","ci","vscode","devops"),
    "integration_api": ("api","integration","webhook","connector","mcp"),
    "analytics_tools": ("analytics","report","reporting","dashboard","business intelligence","bi "),
    "customer_support": ("customer support","support","helpdesk","ticket","inbox"),
    "cybersecurity_tools": ("security","cybersecurity","vulnerability","soc","audit","mcp"),
    "productivity_tools": ("productivity","workflow","automation","task"),
    "marketing_seo": ("seo","marketing","keyword","content marketing"),
}


def _row_relevant_to_family(row: dict, family: str) -> bool:
    text=(" ".join([
        str(row.get("title") or ""),
        str(row.get("excerpt") or ""),
        str(row.get("url") or ""),
    ])).lower()
    return any(marker in text for marker in FAMILY_RELEVANCE_MARKERS.get(family, ()))


def _competitor_price_row(row: dict, family: str) -> bool:
    if not bool(row.get("real_price")):
        return False
    if str(row.get("coverage_source") or "") not in {"pricing_pages","extension_marketplaces"}:
        return False
    return _row_relevant_to_family(row,family)


def market_query_plan(cycle: int, count: int = 10) -> list[dict]:
    """Rotate five tool categories and query public market surfaces without login scraping."""
    keys=list(CATEGORY_CONFIGS)
    offset=max(0,int(cycle or 0)) % len(keys)
    ordered=keys[offset:]+keys[:offset]
    selected=ordered[:5]
    rows=[]
    for idx,family in enumerate(selected):
        cfg=CATEGORY_CONFIGS[family]
        alias=cfg["aliases"][max(0,int(cycle or 0)+idx) % len(cfg["aliases"])]
        rows.append({
            "query":f'"{alias}" pricing subscription',
            "class":"tool_market",
            "role":"tool_pricing",
            "family":family,
            "query_intent":"payment_signal",
        })
        surface=idx % 3
        if surface==0:
            query=f'site:producthunt.com "{alias}"'
            role="product_hunt"
        elif surface==1:
            query=f'site:marketplace.visualstudio.com "{alias}"'
            role="extension_marketplace"
        else:
            query=f'site:chromewebstore.google.com "{alias}"'
            role="extension_marketplace"
        rows.append({
            "query":query,
            "class":"tool_market",
            "role":role,
            "family":family,
            "query_intent":"market_activity",
        })
    return rows[:max(4,min(int(count or 10),10))]


def market_scout_terms(cycle: int, count: int = 6) -> list[dict]:
    plan=market_query_plan(cycle,10)
    out=[]
    seen=set()
    for row in plan:
        family=str(row.get("family") or "")
        if family in seen:
            continue
        seen.add(family)
        cfg=CATEGORY_CONFIGS[family]
        out.append({"family":family,"term":cfg["aliases"][0]})
        if len(out)>=max(1,int(count or 1)):
            break
    return out


def seti_market_catalog(candidates: dict | None, interviews: dict | None) -> list[dict]:
    """Convert verified current Agent Cards or historical contacted A2A endpoints into market observations."""
    candidates=candidates if isinstance(candidates,dict) else {}
    interviews=interviews if isinstance(interviews,dict) else {}
    out=[]
    keys=list(dict.fromkeys([*candidates.keys(),*interviews.keys()]))
    for key in keys:
        candidate=candidates.get(key) if isinstance(candidates.get(key),dict) else {}
        prior=interviews.get(key) if isinstance(interviews.get(key),dict) else {}
        prior_endpoint=str(prior.get("endpoint") or prior.get("agent_card_url") or "").strip()
        card_url=str(candidate.get("agent_card_url") or "").strip()
        candidate_url=str(candidate.get("url") or "").strip()
        explicit_candidate=bool(
            card_url
            or "/.well-known/agent-card" in candidate_url.lower()
            or "/.well-known/agent.json" in candidate_url.lower()
            or candidate_url.lower().rstrip("/").endswith(("/a2a","/a2a/v1","/a2a/jsonrpc"))
        )
        if prior_endpoint:
            url=prior_endpoint
        elif explicit_candidate:
            url=card_url or candidate_url
        else:
            continue
        if not url.startswith("https://"):
            continue

        state=str(prior.get("followup_state") or "").upper()
        peer_class=str(prior.get("peer_class") or "").upper()
        reason=str(prior.get("reason") or "").upper()
        if state=="PAYMENT_BLOCKED" or peer_class=="PAYMENT_REQUIRED" or reason=="PAYMENT_REQUIRED":
            pricing="PAYMENT_REQUIRED"
        elif state=="AUTH_BLOCKED" or peer_class=="AUTH_REQUIRED" or reason=="AUTH_REQUIRED":
            pricing="AUTH"
        elif int(prior.get("http_status") or 0)==200:
            pricing="FREE_OR_UNPRICED"
        else:
            pricing="UNKNOWN"
        capabilities=[]
        for value in (
            candidate.get("title"),candidate.get("description"),candidate.get("snippet"),
            prior.get("capability_excerpt"),prior.get("response_excerpt"),
        ):
            if str(value or "").strip():
                capabilities.append(str(value).strip()[:300])
        out.append({
            "candidate":"SETI-"+str(key)[:8],
            "url":url,
            "observed_at_utc":_utc(str(prior.get("last_attempt_utc") or prior.get("interviewed_at_utc") or candidate.get("last_seen_utc") or "")),
            "category":"ai_tools",
            "capabilities":capabilities[:4],
            "pricing_model":pricing,
            "http_status":prior.get("http_status"),
            "payment_performed":False,
            "historical_interview_only":not bool(candidate),
        })
    return out


def _source_row(raw: dict, family: str, observed_at: str) -> dict | None:
    url=str(raw.get("url") or raw.get("source_url") or "").strip()
    domain=_domain(url)
    if not url.startswith(("https://","http://")) or not domain:
        return None
    title=str(raw.get("title") or raw.get("source_title") or domain).strip()[:240]
    text=str(raw.get("text") or raw.get("snippet") or raw.get("description") or title).strip()[:1600]
    low=(title+" "+text).lower()
    signal_types=[]
    price_match=PRICE_RE.search(title+" "+text)
    explicit_payment_required=("payment_required" in low or "payment required" in low)
    if price_match or explicit_payment_required:
        signal_types.append("PAYMENT")
    if any(x in low for x in DISSATISFACTION_MARKERS):
        signal_types.extend(["DISSATISFACTION","GAP"])
    if (
        domain=="producthunt.com"
        or domain=="marketplace.visualstudio.com"
        or domain=="chromewebstore.google.com"
        or str(raw.get("source") or "").startswith("mcp-registry")
        or any(x in low for x in ("launch","launched","trending","popular","new release"))
    ):
        signal_types.append("TREND")
    if any(x in low for x in COUNTER_MARKERS):
        signal_types.append("COUNTER")
    return {
        "family":family,
        "url":url[:1200],
        "domain":domain,
        "date":_utc(str(raw.get("date") or raw.get("observed_at_utc") or observed_at)),
        "source":str(raw.get("source") or "public_web")[:80],
        "title":title,
        "excerpt":text[:500],
        "signal_types":sorted(set(signal_types)),
        "price":price_match.group(0)[:80] if price_match else ("PAYMENT_REQUIRED" if explicit_payment_required else None),
        "real_price":bool(price_match),
        "payment_required":bool(explicit_payment_required and not price_match),
        "vendor":str(raw.get("vendor") or "").strip()[:120] or None,
        "coverage_source":str(raw.get("coverage_source") or "").strip()[:80] or None,
    }


def analyze_tool_opportunities(
    web_research: list[dict] | None,
    scouts: list[dict] | None,
    seti_catalog: list[dict] | None,
    query_meta: dict[str,dict] | None = None,
    now_utc: str | None = None,
    source_diagnostics: dict | None = None,
) -> dict:
    """Build and rank TOOL_OPPORTUNITY theses from URL-grounded public signals only."""
    observed_at=_utc(now_utc)
    query_meta=query_meta or {}
    source_diagnostics=source_diagnostics if isinstance(source_diagnostics,dict) else {}
    coverage_names=("seti","mcp_registry","extension_marketplaces","pricing_pages","github_issues","product_hunt")
    coverage={name:{"records_read":0,"errors":[],"payment_signals_real_price":0,"payment_required_signals":0,"dissatisfaction_signals":0} for name in coverage_names}
    for name,diag in source_diagnostics.items():
        if name not in coverage or not isinstance(diag,dict):
            continue
        coverage[name]["errors"]=[str(x)[:240] for x in (diag.get("errors") or [])[:12]]
    by_family={k:[] for k in CATEGORY_CONFIGS}

    for group in web_research or []:
        if not isinstance(group,dict):
            continue
        query=" ".join(str(group.get("query") or "").split()).lower()
        meta=query_meta.get(query) or {}
        family=str(meta.get("family") or "")
        for item in group.get("results") or []:
            if not isinstance(item,dict):
                continue
            chosen=family or _family_from_text(str(item.get("title") or "")+" "+str(item.get("snippet") or ""))
            role=str(meta.get("role") or "")
            coverage_source=("pricing_pages" if role=="tool_pricing" else "product_hunt" if role=="product_hunt" else "extension_marketplaces" if role=="extension_marketplace" else "")
            enriched=dict(item)
            enriched["coverage_source"]=coverage_source
            row=_source_row(enriched,chosen,observed_at)
            if row and chosen in by_family:
                if _row_relevant_to_family(row,chosen):
                    by_family[chosen].append(row)
                if coverage_source in coverage:
                    coverage[coverage_source]["records_read"]+=1

    for item in scouts or []:
        if not isinstance(item,dict):
            continue
        family=str(item.get("family") or "") or _family_from_text(str(item.get("title") or "")+" "+str(item.get("text") or ""))
        enriched=dict(item)
        source_low=str(item.get("source") or "").lower()
        coverage_source="mcp_registry" if source_low.startswith("mcp-registry") else "github_issues" if "github-issues" in source_low else ""
        enriched["coverage_source"]=coverage_source
        row=_source_row(enriched,family,observed_at)
        if row and family in by_family:
            if _row_relevant_to_family(row,family):
                by_family[family].append(row)
            if coverage_source in coverage:
                coverage[coverage_source]["records_read"]+=1

    for item in seti_catalog or []:
        if not isinstance(item,dict):
            continue
        url=str(item.get("url") or "")
        if not url:
            continue
        pricing=str(item.get("pricing_model") or "UNKNOWN")
        raw={
            "url":url,
            "title":str(item.get("candidate") or "SETI Agent Card"),
            "text":" ".join(item.get("capabilities") or [])+(" "+pricing if pricing=="PAYMENT_REQUIRED" else ""),
            "source":"seti-agent-card",
            "coverage_source":"seti",
            "observed_at_utc":item.get("observed_at_utc") or observed_at,
        }
        row=_source_row(raw,"ai_tools",observed_at)
        if row:
            if pricing=="PAYMENT_REQUIRED" and "PAYMENT" not in row["signal_types"]:
                row["signal_types"].append("PAYMENT")
                row["price"]="PAYMENT_REQUIRED"
            row["seti_candidate"]=item.get("candidate")
            row["payment_performed"]=False
            by_family["ai_tools"].append(row)
            coverage["seti"]["records_read"]+=1

    opportunities=[]
    for family,cfg in CATEGORY_CONFIGS.items():
        unique={}
        for row in by_family[family]:
            unique.setdefault(row["url"],row)
        sources=list(unique.values())
        payments=[x for x in sources if "PAYMENT" in x["signal_types"]]
        real_payments=[x for x in payments if _competitor_price_row(x,family)]
        dissatisfaction=[x for x in sources if "DISSATISFACTION" in x["signal_types"]]
        gaps=[x for x in sources if "GAP" in x["signal_types"]]
        trends=[x for x in sources if "TREND" in x["signal_types"]]
        counters=[x for x in sources if "COUNTER" in x["signal_types"]]

        def seller_key(row: dict) -> str:
            vendor=str(row.get("vendor") or "").strip().lower()
            return ("vendor:"+vendor) if vendor else ("domain:"+str(row.get("domain") or "").strip().lower())
        payment_keys=sorted({seller_key(x) for x in payments if seller_key(x)})
        real_payment_keys=sorted({seller_key(x) for x in real_payments if seller_key(x)})
        payment_domains=sorted({x["domain"] for x in payments})
        dissatisfaction_domains=sorted({x["domain"] for x in dissatisfaction})
        gap_domains=sorted({x["domain"] for x in gaps})
        trend_domains=sorted({x["domain"] for x in trends})
        counter_domains=sorted({x["domain"] for x in counters})
        source_domains=sorted({x["domain"] for x in sources})

        score=min(50,(len(real_payment_keys)*25))
        score+=min(30,len(dissatisfaction_domains)*15)
        score+=min(10,len(gap_domains)*10)
        score+=min(10,len(trend_domains)*5)
        score-=min(20,len(counter_domains)*10)
        score=max(0,min(100,score))

        existing_tools=[]
        seen_sellers=set()
        for row in real_payments:
            key=seller_key(row)
            if not key or key in seen_sellers:
                continue
            seen_sellers.add(key)
            existing_tools.append({
                "tool":row["title"][:120],
                "vendor":row.get("vendor"),
                "domain":row["domain"],
                "price":row.get("price"),
                "url":row["url"],
                "date":row["date"],
            })

        documented_gaps=[
            {"gap":x["excerpt"][:260],"url":x["url"],"date":x["date"]}
            for x in gaps[:5]
        ]
        payment_signals=[
            {
                "url":x["url"],"date":x["date"],"domain":x["domain"],"price":x.get("price"),
                "source":x["source"],"coverage_source":x.get("coverage_source"),
                "real_competitor_price":_competitor_price_row(x,family),
            }
            for x in payments[:8]
        ]
        dissatisfaction_signals=[
            {"url":x["url"],"date":x["date"],"domain":x["domain"],"excerpt":x["excerpt"][:260]}
            for x in dissatisfaction[:8]
        ]
        trend_signals=[
            {"url":x["url"],"date":x["date"],"domain":x["domain"],"source":x["source"]}
            for x in trends[:8]
        ]
        counter_signals=[
            {"url":x["url"],"date":x["date"],"domain":x["domain"],"excerpt":x["excerpt"][:260]}
            for x in counters[:8]
        ]
        thesis_specific=bool(str(cfg.get("title") or "").strip() and str(cfg.get("target_user") or "").strip())
        gate_pass=bool(
            thesis_specific
            and len(real_payment_keys)>=2
            and len(dissatisfaction_domains)>=1
            and len(gap_domains)>=1
            and len(source_domains)>=3
            and len(existing_tools)>=2
            and score>=60
        )
        missing=[]
        if not thesis_specific: missing.append("specific_tool_name_and_target_user")
        if len(real_payment_keys)<2: missing.append("two_independent_real_price_competitors")
        if len(existing_tools)<2: missing.append("two_competitors_with_real_price")
        if len(dissatisfaction_domains)<1: missing.append("dissatisfaction_signal")
        if len(gap_domains)<1: missing.append("documented_gap")
        if len(source_domains)<3: missing.append("three_independent_source_domains")
        if len(existing_tools)<2: missing.append("two_existing_paid_tools")
        if score<60: missing.append("monetization_score_60")

        opportunity={
            "schema_v":TOOL_OPPORTUNITY_SCHEMA_VERSION,
            "type":"TOOL_OPPORTUNITY",
            "family":family,
            "title":cfg["title"],
            "tool_name":cfg["title"],
            "target_user":cfg["target_user"],
            "problem":cfg["problem"],
            "existing_tools":existing_tools[:6],
            "documented_gaps":documented_gaps,
            "payment_signals":payment_signals,
            "dissatisfaction_signals":dissatisfaction_signals,
            "trend":(
                f"{len(trend_signals)} verifiable market-activity signals across {len(trend_domains)} domains"
                if trend_signals else "Insufficient verified trend evidence"
            ),
            "trend_signals":trend_signals,
            "counter_signals":counter_signals,
            "feasibility":{"estimated_build_days":cfg["build_days"],"basis":"bounded MVP estimate; not part of monetization score"},
            "distribution_channel":cfg["distribution"],
            "sources":sources[:16],
            "monetization_score":score,
            "score_rule":"URL-grounded payment + dissatisfaction + gap + trend signals minus URL-grounded counter-signals only",
            "gate_pass":gate_pass,
            "gate_rule":"specific tool + target user + >=2 independent payment sellers/domains + >=2 competitors with real price+URL + documented gap + dissatisfaction + >=3 source domains + score >=60",
            "missing":missing,
        }
        opportunities.append(opportunity)

    for family_rows in by_family.values():
        for row in family_rows:
            src=str(row.get("coverage_source") or "")
            if src not in coverage:
                continue
            if "PAYMENT" in row.get("signal_types",[]):
                if row.get("real_price"):
                    coverage[src]["payment_signals_real_price"]+=1
                elif row.get("payment_required"):
                    coverage[src]["payment_required_signals"]+=1
            if "DISSATISFACTION" in row.get("signal_types",[]):
                coverage[src]["dissatisfaction_signals"]+=1

    for name,diag in source_diagnostics.items():
        if name in coverage and isinstance(diag,dict):
            coverage[name]["records_read"]=max(
                int(coverage[name].get("records_read") or 0),
                int(diag.get("records_read") or 0),
            )
            coverage[name]["requests"]=int(diag.get("requests") or 0)

    opportunities.sort(
        key=lambda x:(int(x["gate_pass"]),int(x["monetization_score"]),len(x["payment_signals"]),len(x["sources"])),
        reverse=True,
    )
    top5=opportunities[:5]
    transcripts=[build_council_transcript(x) for x in top5]
    return {
        "schema_v":TOOL_OPPORTUNITY_SCHEMA_VERSION,
        "generated_at_utc":observed_at,
        "mode":"tool_commercial_demand",
        "top5":top5,
        "top_gate_pass":bool(top5 and top5[0].get("gate_pass")),
        "council_transcripts":transcripts,
        "seti_market_catalog":[dict(x) for x in (seti_catalog or [])][:32],
        "source_coverage":coverage,
        "gate_rule":"The top specific tool opportunity alone may authorize build, only with >=2 independent payment sellers/domains, >=2 competitors with real price+URL, and the documented quality conditions.",
    }


def build_council_transcript(opportunity: dict) -> dict:
    """Readable deterministic debate. Critic explicitly searches the collected contrary evidence."""
    title=str(opportunity.get("title") or "Tool opportunity")
    payments=opportunity.get("payment_signals") or []
    gaps=opportunity.get("documented_gaps") or []
    counters=opportunity.get("counter_signals") or []
    gate=bool(opportunity.get("gate_pass"))
    messages=[
        {
            "role":"Scout",
            "text":f"Collected {len(opportunity.get('sources') or [])} URL-grounded sources; {len(payments)} payment signals and {len(opportunity.get('dissatisfaction_signals') or [])} dissatisfaction signals.",
        },
        {
            "role":"Analyst",
            "text":f"Monetization score {int(opportunity.get('monetization_score') or 0)}/100. Existing paid-tool evidence: {len(opportunity.get('existing_tools') or [])}; documented gaps: {len(gaps)}.",
        },
        {
            "role":"Critic",
            "text":(
                f"Active falsification found {len(counters)} contrary/free/open-source signals. "
                + ("Gate blockers: "+", ".join(opportunity.get("missing") or [])+"." if opportunity.get("missing") else "No gate blocker remains in the collected evidence.")
            ),
        },
        {
            "role":"Builder-planner",
            "text":f"Bounded MVP estimate: {(opportunity.get('feasibility') or {}).get('estimated_build_days')} days. Distribution: {opportunity.get('distribution_channel')}. No spending or payment is authorized.",
        },
    ]
    return {
        "opportunity":title,
        "family":opportunity.get("family"),
        "decision":"PROCEED_TO_JARVIS" if gate else "HOLD",
        "gate_pass":gate,
        "messages":messages,
        "external_peer_policy":"Only SETI-admitted peers may participate; unadmitted peers are excluded.",
    }


def opportunity_candidate(opportunity: dict | None) -> dict:
    row=opportunity if isinstance(opportunity,dict) else {}
    if not row or not row.get("gate_pass"):
        return {
            "status":"WAITING_FOR_DEMAND",
            "message":"Top TOOL_OPPORTUNITY has not passed the commercial tool gate.",
            "opportunity":row,
        }
    return {
        "status":"PILOT_READY",
        "family":row.get("family"),
        "problem_key":"tool_opportunity:"+re.sub(r"[^a-z0-9]+","_",str(row.get("tool_name") or row.get("title") or "unknown").lower()).strip("_"),
        "name":row.get("title"),
        "offer":row.get("problem"),
        "price":"not set; no payment action authorized",
        "delivery":"bounded MVP",
        "payment":"disabled until human approval",
        "evidence":row,
    }
