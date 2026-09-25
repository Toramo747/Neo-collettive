"""Evidence-integrity primitives for NEO/MYCELIX.

Pure-stdlib by design so the critical tagger/migration logic can be regression-tested
without importing the web runtime.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

EVIDENCE_SCHEMA_VERSION = 2
TAGGER_VERSION = 3

LEGACY_GENERIC_TAILS = {
    "llm",
    "agentic",
    "generative_ai",
    "ai_assistant",
    "ai_tool",
    "ai_tools",
    "ai_automation",
    "integration_platform",
}
NON_QUALIFIABLE_TAILS = {"generic_technology", "general", "technology_seed"}

TRACKING_QUERY_KEYS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "utm_id", "gclid", "fbclid", "msclkid", "mc_cid", "mc_eid",
}

MULTITENANT_SUFFIXES = (
    "substack.com",
    "medium.com",
    "notion.site",
    "github.io",
    "wordpress.com",
    "blogspot.com",
)

FAMILY_TERMS = [
    ("cybersecurity_tools", ("cybersecurity","security assessment","vulnerability management","phishing analysis","soc automation","security automation")),
    ("developer_tools", ("developer tool","developer productivity","api debugging","code review tool","devops tool","devops","software developer workflow")),
    ("integration_api", ("api integration","webhook","integration platform","connect saas","system integration")),
    ("ai_tools", ("ai assistant","ai tool","llm","generative ai","ai automation","agentic")),
    ("micro_saas", ("micro saas","niche saas","small saas","vertical saas")),
    ("ecommerce_tools", ("ecommerce","shopify","woocommerce","catalog automation","order operations")),
    ("marketing_seo", ("seo","marketing automation","content optimization","keyword research","ad campaign")),
    ("analytics_tools", ("analytics dashboard","business intelligence","data analytics","automated reporting","reporting dashboard")),
    ("compliance_tools", ("compliance reporting","audit evidence","gdpr workflow","iso 27001","regulatory reporting")),
    ("finance_ops", ("invoice workflow","expense reporting","accounts payable","bookkeeping automation","finance operations")),
    ("hr_tools", ("hr workflow","employee onboarding","recruiting operations","applicant tracking","leave management")),
    ("education_tools", ("education software","teacher admin","learning platform","training platform","course workflow")),
    ("creator_tools", ("creator tool","newsletter automation","podcast workflow","video creator","digital creator")),
    ("productivity_tools", ("productivity tool","knowledge management","team productivity","note taking","task workflow")),
    ("local_business_tools", ("appointment booking","quote preparation","local business software","booking admin","service business")),
    ("document_processing", ("document parser","extracting it from pdf","pdf extraction","form filling","document processing","ocr workflow")),
    ("manual_data_entry", ("manual data entry","data entry")),
    ("spreadsheet_process", ("spreadsheet","excel","google sheets","manual process","csv cleanup")),
    ("crm_lead_ops", ("crm","lead management","sales ops","lead qualification","follow up","follow-up")),
    ("website_audit", ("website audit","site audit","technical audit","accessibility audit","broken link audit","website qa")),
    ("it_hygiene", ("it inventory","patch reporting","security hygiene","asset inventory")),
    ("customer_support", ("customer support","support triage","faq workflow","support ticket")),
    ("data_cleanup", ("data cleanup","duplicate data","csv cleanup","deduplication")),
    ("content_tools", ("content repurposing","catalog description","localization workflow","content workflow")),
    ("workflow_automation", ("workflow automation","automating","automation","repetitive task","manual workflow","back office","reporting automation")),
]

FAMILY_RELEVANCE_TERMS = {
    "spreadsheet_process": ("spreadsheet","excel","google sheets","csv","manual process"),
    "workflow_automation": ("workflow automation","manual workflow","repetitive task","back office","automation"),
    "crm_lead_ops": ("crm","lead management","sales ops","lead qualification","follow up"),
    "website_audit": ("website audit","site audit","accessibility audit","website qa","broken link"),
    "developer_tools": ("developer","developer tool","developer workflow","devops","deployment","ci/cd","code review","api debugging"),
    "integration_api": ("api","api integration","webhook","integration platform","system integration"),
    "ai_tools": ("ai assistant","ai tool","llm","generative ai","agentic"),
    "micro_saas": ("micro saas","niche saas","vertical saas"),
    "ecommerce_tools": ("ecommerce","shopify","woocommerce","catalog","order operations"),
    "marketing_seo": ("seo","marketing automation","keyword research","ad campaign"),
    "analytics_tools": ("analytics","business intelligence","reporting dashboard","data analytics"),
    "compliance_tools": ("compliance","audit evidence","gdpr","iso 27001","regulatory reporting"),
    "finance_ops": ("invoice","accounts payable","bookkeeping","expense reporting","finance operations"),
    "hr_tools": ("hr ","human resources","employee","onboarding","recruiting","applicant tracking","payroll"),
    "education_tools": ("education","teacher","learning platform","training platform","course workflow"),
    "creator_tools": ("creator","newsletter","podcast","video creator"),
    "productivity_tools": ("productivity","knowledge management","task workflow","note taking"),
    "local_business_tools": ("appointment","booking","quote preparation","local business","service business"),
    "document_processing": ("document","pdf","ocr","form","invoice"),
    "manual_data_entry": ("manual data entry","data entry","rekey","re-key"),
    "it_hygiene": ("it inventory","asset inventory","patch","endpoint inventory","security hygiene"),
    "customer_support": ("customer support","support ticket","shared inbox","customer email"),
    "data_cleanup": ("data cleanup","duplicate data","deduplication","csv cleanup"),
    "content_tools": ("content repurposing","content workflow","catalog description","localization"),
    "cybersecurity_tools": ("cybersecurity","security assessment","vulnerability","phishing","soc","security automation"),
}

PAIN_TERMS = (
    "pain","problem","manual","repetitive","time consuming","time-consuming",
    "frustrat","tired of","waste time","workaround","backlog",
)
STRONG_PAIN_TERMS = (
    "pain","manual","repetitive","time consuming","time-consuming",
    "frustrat","tired of","waste time","workaround","backlog",
)
BUY_INTENT_TERMS = (
    "looking for","need help","need a","need to hire","looking to hire","hire someone",
    "seeking","want someone","recommend a","how can i automate",
    "request:","rfp","request for proposal",
)
BUYER_PAID_TERMS = (
    "budget","will pay","paid job","fixed-price","fixed price","hourly",
    "per hour","hiring","hire someone","hire a","freelance","freelancer",
    "contractor","seeking contractor","quote requested","request a quote",
)
SUPPLY_TERMS = (
    "pricing","price","subscription","plans","book a call","book a demo",
    "enterprise","free trial","one-time purchase","per month","per year",
)

LAUNCH_TITLE_MARKERS = (
    "show hn:","launch hn:","introducing ","announcing ","we built ","i built ",
)

GENERIC_WEB_SOURCES = {"brave-search","google-pse","bing-rss-free","web"}
VENDOR_PATH_MARKERS = ("/blog/","/solutions/","/challenges/","/services/","/resources/")
SUPPLY_OFFER_PATH_MARKERS = ("/services/","/hire/","/freelancers/","/experts/","/talent/")
SUPPLY_OFFER_TERMS = (
    "hire our","hire one of our","our freelancers","our freelancer","our experts",
    "our expert","we offer","we provide","book a call","book a demo",
    "get a quote from us","start a free trial","start free trial","try us free",
)
GIG_MARKET_DOMAINS = (
    "fiverr.com","upwork.com","freelancer.com","guru.com","peopleperhour.com","toptal.com",
)
COMMUNITY_DOMAINS = (
    "reddit.com","news.ycombinator.com","stackoverflow.com","serverfault.com",
    "superuser.com","stackexchange.com",
)
BUYER_VOICE_PHRASES = (
    "i need","we need","i'm looking","i am looking","we're looking","we are looking",
    "our team spends","our team spend","we spend","i spend","we are struggling",
    "we're struggling","i am struggling","i'm struggling","we struggle","i struggle",
    "we manually","i manually","we have to","i have to","can anyone","does anyone",
    "has anyone","any recommendations","what do you use","how do i","how can i",
    "how do we","how can we","looking for help",
)

STRUCTURED_PAID_SOURCES = {
    "remotive-api",
    "remoteok-api",
    "arbeitnow-api",
    "hn-jobs",
}


def is_launch_title(title: str) -> bool:
    """Return True for seller-authored product launch titles.

    Launch copy is useful market context, but it is supply-side evidence and must
    never be treated as buyer pain by the commercial gate.
    """
    low=" ".join(str(title or "").split()).strip().lower()
    return any(low.startswith(marker) for marker in LAUNCH_TITLE_MARKERS)


def generic_web_source(source: str) -> bool:
    return (source or "").strip().lower() in GENERIC_WEB_SOURCES


def buyer_voice_present(title: str, body: str) -> bool:
    text=" ".join(((title or "")+" "+(body or "")).lower().split())
    if any(contains_term(text,phrase) for phrase in BUYER_VOICE_PHRASES):
        return True
    # Direct buyer-style questions are acceptable even when the source does not
    # use a first-person phrase verbatim.
    return bool(re.search(
        r"(?:^|[.!?]\s)(?:how|what|which|anyone|does anyone|can anyone|is there|are there)\b[^?]{0,180}\?",
        text,
        flags=re.I,
    ))


def first_person_buyer_voice_present(title: str, body: str) -> bool:
    text=" ".join(((title or "")+" "+(body or "")).lower().split())
    if not re.search(r"\b(?:i|we|our|my)\b",text):
        return False
    return bool(re.search(
        r"\b(?:i|we|our|my)\b[^.!?]{0,140}\b(?:need|looking|seeking|want|hire|pay|budget|replace|switch|automate)\b",
        text,
        flags=re.I,
    ))


def _marker_survives_query_echo(marker: str, title: str, body: str, query: str) -> bool:
    if not contains_term(query or "",marker):
        return True
    if contains_term(title or "",marker):
        return True
    for sentence in re.split(r"(?<=[.!?])\s+",str(body or "")):
        if contains_term(sentence,marker) and first_person_buyer_voice_present("",sentence):
            return True
    return False


def community_context(url: str, source: str = "") -> bool:
    source_low=(source or "").strip().lower()
    if source_low in {"hn-algolia-routed","hackernews","stackexchange-routed","github-issues-routed","github-issues"}:
        return True
    try:
        parts=urlsplit(str(url or ""))
        host=(parts.hostname or "").lower().strip(".")
        path=(parts.path or "").lower()
    except Exception:
        host=""
        path=""
    if any(host==d or host.endswith("."+d) for d in COMMUNITY_DOMAINS):
        return True
    return any(marker in path for marker in ("/forum/","/forums/","/questions/","/discussion/","/discussions/","/thread/","/threads/"))


def vendor_content_indicators(title: str, body: str, url: str, source: str = "") -> dict[str, bool]:
    low=" ".join(str(title or "").lower().split())
    try:
        path=(urlsplit(str(url or "")).path or "").lower()
    except Exception:
        path=""
    marketing_title=bool(
        re.search(r"^(?:how to\b|using\b.+\bto\b|reduce\b)",low)
        or re.search(r"\b\d+\s+(?:simple\s+)?(?:ways|fixes|tips|steps)\b",low)
        or " is slowing down your team" in low
    )
    marketing_path=any(marker in path for marker in VENDOR_PATH_MARKERS)
    buyer_voice=buyer_voice_present(title,body)
    return {
        "marketing_title":marketing_title,
        "marketing_path":marketing_path,
        "buyer_voice":buyer_voice,
        "community":community_context(url,source),
    }


def is_vendor_content(title: str, body: str, url: str, source: str = "") -> bool:
    if not generic_web_source(source):
        return False
    flags=vendor_content_indicators(title,body,url,source)
    if flags["community"]:
        return False
    score=int(flags["marketing_title"])+int(flags["marketing_path"])+int(not flags["buyer_voice"])
    return score>=2


def is_supply_offer(title: str, body: str, url: str, source: str = "") -> bool:
    """Detect seller-side service/product offers returned by generic web search."""
    if not generic_web_source(source):
        return False
    text=" ".join(((title or "")+" "+(body or "")).lower().split())
    try:
        parts=urlsplit(str(url or ""))
        host=(parts.hostname or "").lower().strip(".")
        path=(parts.path or "").lower()
    except Exception:
        host=""
        path=""
    strong_phrase=(
        any(contains_term(text,term) for term in SUPPLY_OFFER_TERMS)
        or bool(re.search(r"\btry\s+[a-z0-9][a-z0-9 .+_-]{0,60}\s+(?:for\s+)?free(?:\s+trial)?\b",text,re.I))
    )
    path_offer=any(marker in path for marker in SUPPLY_OFFER_PATH_MARKERS)
    gig_market=any(host==d or host.endswith("."+d) for d in GIG_MARKET_DOMAINS)
    first_person=first_person_buyer_voice_present(title,body)
    if strong_phrase:
        return True
    if path_offer and not first_person:
        return True
    if gig_market and not first_person and (
        contains_term(text,"hire")
        or contains_term(text,"freelancer")
        or contains_term(text,"expert")
    ):
        return True
    return False


def generic_web_pain_allowed(title: str, body: str, url: str, source: str = "") -> bool:
    if not generic_web_source(source):
        return True
    return bool(community_context(url,source) or buyer_voice_present(title,body))


def structured_paid_source(source: str, query_role: str = "") -> bool:
    """True only for explicit job-market feeds routed by a paid-market query."""
    return (
        (query_role or "").strip().lower() == "paid_market"
        and (source or "").strip().lower() in STRUCTURED_PAID_SOURCES
    )


def _term_regex(term: str) -> re.Pattern[str]:
    value = re.escape((term or "").strip().lower())
    return re.compile(r"(?<!\w)" + value + r"(?!\w)", re.IGNORECASE)


def contains_term(text: str, term: str) -> bool:
    if not text or not term:
        return False
    return bool(_term_regex(term).search(text))


def contains_any(text: str, terms: tuple[str, ...] | list[str]) -> bool:
    return any(contains_term(text, term) for term in terms)


def find_term_positions(text: str, term: str, limit: int = 8) -> list[tuple[int, int]]:
    if not text or not term:
        return []
    return [(m.start(), m.end()) for m in _term_regex(term).finditer(text)][:max(0, limit)]


def commercial_family(text: str) -> str:
    low = (text or "").lower()
    for family, terms in FAMILY_TERMS:
        if contains_any(low, terms):
            return family
    return "other"


def family_relevance_terms(family: str) -> tuple[str, ...]:
    family=str(family or "").strip()
    base=next((terms for name,terms in FAMILY_TERMS if name==family),())
    extra=FAMILY_RELEVANCE_TERMS.get(family,())
    return tuple(dict.fromkeys(tuple(base)+tuple(extra)))


def family_text_matches(family: str, text: str) -> bool:
    return contains_any((text or "").lower(), family_relevance_terms(family))


def is_self_contamination(url: str, source: str = "", text: str = "") -> bool:
    try:
        parts=urlsplit(str(url or ""))
        host=(parts.hostname or "").lower().strip(".")
        path=(parts.path or "").strip("/")
    except Exception:
        host=""
        path=""
    if host=="neo-collettive.onrender.com" or host.endswith(".neo-collettive.onrender.com"):
        return True
    if host=="github.com" and path:
        owner=path.split("/",1)[0].lower()
        if owner=="toramo747":
            return True
    source_low=str(source or "").lower()
    source_markers=("peer-a2a","peer_a2a","a2a-peer","a2a_peer","agent-chat","agent_chat","agent-dialogue","agent_dialogue","jarvis-dialogue","jarvis_dialogue")
    if any(marker in source_low for marker in source_markers):
        return True
    text_low=str(text or "").lower()
    self_text_markers=(
        "identity: chatgpt-research-session-",
        "round 2/3 — methodology",
        "falsify one market-facing differentiator",
        "first paid ai-assisted content-operation offer",
        "mycelix runtime snapshot",
    )
    if any(marker in text_low for marker in self_text_markers):
        return True
    return False


def demand_signal_type(
    title: str,
    body: str,
    query_role: str = "",
    strong_pain_only: bool = False,
    seller_launch_guard: bool = False,
    url: str = "",
    source: str = "",
    vendor_content_guard: bool = False,
    web_buyer_voice_guard: bool = False,
    supply_offer_guard: bool = False,
    query_echo_guard: bool = False,
    query: str = "",
) -> list[str]:
    """Tag buyer-side demand separately from vendor/supply pricing.

    A disconfirm search result is never turned into positive commercial evidence.
    """
    text = ((title or "") + " " + (body or "")).lower()
    role = (query_role or "").strip().lower()
    if role == "disconfirm":
        return ["DISCONFIRM"]

    tags: list[str] = []
    seller_launch = bool(seller_launch_guard and is_launch_title(title))
    vendor_content = bool(vendor_content_guard and is_vendor_content(title,body,url,source))
    supply_offer = bool(supply_offer_guard and is_supply_offer(title,body,url,source))
    generic_web = generic_web_source(source)
    buyer_voice_ok = bool(
        not web_buyer_voice_guard
        or not generic_web
        or generic_web_pain_allowed(title,body,url,source)
    )
    positive_guard_ok = bool(
        not seller_launch
        and not vendor_content
        and not supply_offer
        and buyer_voice_ok
    )

    pain_markers = STRONG_PAIN_TERMS if strong_pain_only else PAIN_TERMS
    pain = contains_any(text,pain_markers)
    intent_markers=[
        marker for marker in BUY_INTENT_TERMS
        if contains_term(text,marker)
        and (
            not query_echo_guard
            or not generic_web
            or _marker_survives_query_echo(marker,title,body,query)
        )
    ]
    paid_markers=[
        marker for marker in BUYER_PAID_TERMS
        if contains_term(text,marker)
        and (
            not query_echo_guard
            or not generic_web
            or _marker_survives_query_echo(marker,title,body,query)
        )
    ]
    intent=bool(intent_markers)
    buyer_paid=bool(paid_markers)
    supply = contains_any(text, SUPPLY_TERMS)

    if pain and positive_guard_ok:
        tags.append("PAIN")
    if intent and positive_guard_ok:
        tags.append("BUY_INTENT")

    # Buyer-side payment must have a buyer/hiring context and survive all generic-web guards.
    # Generic vendor pricing remains COMPETITION only.
    if buyer_paid and positive_guard_ok and (intent or pain or role in {"buyer","paid_market","practitioner"}):
        tags.append("PAID_DEMAND")
    if supply:
        tags.append("COMPETITION")
    return tags


GENERIC_CUSTOMER_SEGMENTS = {"buyers"}


def problem_tail(problem_key: str) -> str:
    return str(problem_key or "").split(":", 1)[-1].strip().lower()


def _strip_generic_customer(problem_key: str) -> str:
    """Remove planner-only customer placeholders from a concrete problem identity."""
    key=str(problem_key or "").strip()
    parts=key.split(":")
    if len(parts)<3 or parts[1].strip().lower() not in GENERIC_CUSTOMER_SEGMENTS:
        return key
    family=parts[0]
    job=":".join(parts[2:]).strip()
    while job.lower().startswith("buyers_"):
        remainder=job[len("buyers_"):]
        if not remainder:
            break
        job=remainder
    return family+":"+job if job else key


def problem_job_tail(problem_key: str) -> str:
    """Return only the job portion, never a customer:job composite."""
    key=_strip_generic_customer(problem_key)
    parts=key.split(":")
    if len(parts)>=3:
        return ":".join(parts[2:]).strip().lower()
    return problem_tail(key)


def problem_customer_segment(problem_key: str) -> str:
    """Return a real customer segment from family:customer:job, never a generic placeholder."""
    key=_strip_generic_customer(problem_key)
    parts=key.split(":")
    if len(parts)<3:
        return ""
    customer=parts[1].strip().lower()
    return "" if customer in GENERIC_CUSTOMER_SEGMENTS else customer


def canonical_problem_key(family: str, problem_key: str) -> str:
    family = str(family or "").strip()
    key = _strip_generic_customer(str(problem_key or "").strip())
    tail = problem_tail(key)
    if not family:
        return key
    if not key:
        return family + ":general"
    if tail in LEGACY_GENERIC_TAILS:
        return family + ":generic_technology"
    return key if ":" in key else family + ":" + tail


def gate_eligible_problem_key(problem_key: str) -> bool:
    tail = problem_tail(problem_key)
    return bool(tail and tail not in NON_QUALIFIABLE_TAILS and tail not in LEGACY_GENERIC_TAILS)


def canonical_url(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    try:
        parts = urlsplit(raw)
        scheme = (parts.scheme or "https").lower()
        host = (parts.hostname or "").lower()
        if host.startswith("www."):
            host = host[4:]
        port = parts.port
        netloc = host
        if port and not ((scheme == "https" and port == 443) or (scheme == "http" and port == 80)):
            netloc = f"{host}:{port}"
        path = parts.path or "/"
        if path != "/":
            path = path.rstrip("/")
        query = urlencode([
            (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
            if k.lower() not in TRACKING_QUERY_KEYS
        ])
        return urlunsplit((scheme, netloc, path, query, ""))
    except Exception:
        return raw.lower().split("#", 1)[0].rstrip("/")


def canonical_domain(host: str) -> str:
    value = (host or "").strip().lower().rstrip(".")
    for prefix in ("www.", "m.", "old."):
        if value.startswith(prefix):
            value = value[len(prefix):]
            break
    for suffix in MULTITENANT_SUFFIXES:
        if value == suffix or value.endswith("." + suffix):
            return suffix
    return value


def safe_slug(value: str, max_len: int = 64) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", (value or "").lower()).strip("_")
    return (s or "unknown")[:max_len]


def make_problem_id(family: str, customer: str, job: str) -> str:
    return f"{safe_slug(family,32)}:{safe_slug(customer,40)}:{safe_slug(job,72)}"


def thesis_attributed_problem_key(
    observed_problem_key: str,
    problem_id: str = "",
    thesis_id: str = "",
    relevance_score: int = 0,
    overlap_count: int = 0,
    require_family_match: bool = False,
) -> str:
    """Use thesis identity only for strongly relevant results from an internal thesis probe.

    This changes attribution, not qualification thresholds: weak/ambiguous results stay
    in their observed generic/problem-signature bucket.
    """
    observed=str(observed_problem_key or "").strip()
    pid=str(problem_id or "").strip()
    tid=str(thesis_id or "").strip()
    if not pid or not tid:
        return observed
    if int(relevance_score or 0) < 55 or int(overlap_count or 0) < 2:
        return observed
    if pid.count(":") < 2:
        return observed
    if require_family_match:
        observed_family=observed.split(":",1)[0].strip().lower()
        thesis_family=pid.split(":",1)[0].strip().lower()
        if observed_family and thesis_family and observed_family!=thesis_family:
            return observed
    return canonical_problem_key("",pid)


def make_thesis_id(family: str, customer: str, job: str, pain: str) -> str:
    raw = "|".join([family or "", customer or "", job or "", pain or ""]).encode("utf-8", "ignore")
    return "th-" + hashlib.sha1(raw).hexdigest()[:12]


def _legacy_derived_problem_remap(problem_key: str, sibling_problem_keys: list[str] | tuple[str,...] | set[str]) -> str:
    """Map one truncated family:customer_job key to a unique family:customer:job sibling."""
    key=str(problem_key or "").strip()
    parts=key.split(":")
    if len(parts)!=2:
        return key
    family,tail=parts
    matches=[]
    for candidate in sibling_problem_keys or []:
        cand=canonical_problem_key("",str(candidate or "").strip())
        cparts=cand.split(":")
        if len(cparts)!=3 or cparts[0]!=family:
            continue
        customer,job=cparts[1],cparts[2]
        prefix=customer+"_"
        if not tail.startswith(prefix):
            continue
        remainder=tail[len(prefix):]
        if remainder and job.startswith(remainder):
            matches.append(cand)
    unique=sorted(set(matches))
    return unique[0] if len(unique)==1 else key


def migrate_evidence_row(
    row: dict[str, Any],
    sibling_problem_keys: list[str] | tuple[str,...] | set[str] = (),
    enforce_family_match: bool = False,
    strong_pain_only: bool = False,
    seller_launch_guard: bool = False,
    vendor_content_guard: bool = False,
    web_buyer_voice_guard: bool = False,
    supply_offer_guard: bool = False,
    query_echo_guard: bool = False,
) -> tuple[dict[str, Any], bool]:
    """Idempotently quarantine pre-v2 evidence until it is re-observed by tagger v2."""
    out = dict(row or {})
    changed = False
    family = str(out.get("family") or "")
    raw_key = str(out.get("problem_key_raw") or out.get("problem_key") or (family + ":general" if family else ""))
    raw_canonical = canonical_problem_key(raw_key.split(":",1)[0] if ":" in raw_key else family, raw_key)
    current = canonical_problem_key(family, str(out.get("problem_key") or raw_key))
    raw_family = raw_canonical.split(":",1)[0].strip().lower() if raw_canonical else ""
    current_family = current.split(":",1)[0].strip().lower() if current else ""
    reverted = bool(
        enforce_family_match
        and out.get("thesis_bound")
        and raw_family
        and current_family
        and raw_family != current_family
    )
    if reverted:
        family=raw_family
        canonical=raw_canonical
        if out.get("family") != family:
            out["family"]=family
            changed=True
        if out.get("thesis_bound") is not False:
            out["thesis_bound"]=False
            changed=True
        if out.get("attribution_reverted") != "family_mismatch":
            out["attribution_reverted"]="family_mismatch"
            changed=True
    else:
        canonical = _legacy_derived_problem_remap(current, sibling_problem_keys)
    if out.get("problem_key_raw") != raw_key:
        out["problem_key_raw"] = raw_key
        changed = True
    if out.get("problem_key") != canonical:
        out["problem_key"] = canonical
        changed = True

    schema_v = int(out.get("schema_v") or 1)
    tagger_v = int(out.get("tagger_v") or 1)
    migration_v = int(out.get("migration_v") or 0)
    if strong_pain_only and "PAIN" in set(out.get("signal_types") or []):
        text=(str(out.get("title") or "")+" "+str(out.get("snippet") or "")).lower()
        if not contains_any(text,STRONG_PAIN_TERMS):
            out["signal_types"]=[x for x in (out.get("signal_types") or []) if x!="PAIN"]
            changed=True
    if schema_v < EVIDENCE_SCHEMA_VERSION or tagger_v < TAGGER_VERSION:
        # Preserve the original tagger version: quarantine means "not revalidated".
        if migration_v < EVIDENCE_SCHEMA_VERSION or out.get("quarantine_reason") != "legacy_unverified_tagger_v1":
            out["schema_v"] = EVIDENCE_SCHEMA_VERSION
            out["tagger_v"] = tagger_v
            out["gate_eligible"] = False
            out["quarantine_reason"] = "legacy_unverified_tagger_v1"
            out["migration_v"] = EVIDENCE_SCHEMA_VERSION
            changed = True
    else:
        if reverted:
            signals=set(out.get("signal_types") or [])
            eligible=bool(
                gate_eligible_problem_key(canonical)
                and bool({"PAIN","BUY_INTENT","PAID_DEMAND"} & signals)
                and "DISCONFIRM" not in signals
            )
            reason=None if eligible else (
                "disconfirm" if "DISCONFIRM" in signals
                else "generic_or_nonconcrete_problem" if not gate_eligible_problem_key(canonical)
                else "nonpositive_signal"
            )
            if out.get("gate_eligible") != eligible:
                out["gate_eligible"]=eligible
                changed=True
            if out.get("quarantine_reason") != reason:
                out["quarantine_reason"]=reason
                changed=True
        elif "gate_eligible" not in out:
            out["gate_eligible"] = gate_eligible_problem_key(canonical)
            changed = True
        if "DISCONFIRM" in set(out.get("signal_types") or []):
            if out.get("gate_eligible") is not False or out.get("quarantine_reason") != "disconfirm":
                out["gate_eligible"] = False
                out["quarantine_reason"] = "disconfirm"
                changed = True
        if out.get("migration_v") != EVIDENCE_SCHEMA_VERSION:
            out["migration_v"] = EVIDENCE_SCHEMA_VERSION
            changed = True

    supply_offer=bool(
        supply_offer_guard
        and is_supply_offer(
            str(out.get("title") or ""),
            str(out.get("snippet") or ""),
            str(out.get("url") or ""),
            str(out.get("source") or ""),
        )
    )
    if supply_offer:
        signals=[
            x for x in (out.get("signal_types") or [])
            if x not in {"PAIN","BUY_INTENT","PAID_DEMAND"}
        ]
        if out.get("signal_types") != signals:
            out["signal_types"]=signals
            changed=True
        if out.get("strong_markers"):
            out["strong_markers"]=[]
            changed=True
        if out.get("context_type") != "supply_offer":
            out["context_type"]="supply_offer"
            changed=True
        if out.get("signal_reverted") != "supply_offer":
            out["signal_reverted"]="supply_offer"
            changed=True
        if out.get("gate_eligible") is not False:
            out["gate_eligible"]=False
            changed=True
        reason="disconfirm" if "DISCONFIRM" in set(signals) else "supply_offer"
        if out.get("quarantine_reason") != reason:
            out["quarantine_reason"]=reason
            changed=True

    # Generic vendor-authored solution/SEO content is useful market context but is
    # not buyer demand and must never contribute an independent gate domain.
    vendor_content=bool(
        vendor_content_guard
        and is_vendor_content(
            str(out.get("title") or ""),
            str(out.get("snippet") or ""),
            str(out.get("url") or ""),
            str(out.get("source") or ""),
        )
    )
    if vendor_content and not supply_offer:
        signals=[
            x for x in (out.get("signal_types") or [])
            if x not in {"PAIN","BUY_INTENT","PAID_DEMAND"}
        ]
        if out.get("signal_types") != signals:
            out["signal_types"]=signals
            changed=True
        if out.get("strong_markers"):
            out["strong_markers"]=[]
            changed=True
        if out.get("context_type") != "vendor_content":
            out["context_type"]="vendor_content"
            changed=True
        if out.get("signal_reverted") != "vendor_content":
            out["signal_reverted"]="vendor_content"
            changed=True
        if out.get("gate_eligible") is not False:
            out["gate_eligible"]=False
            changed=True
        reason="disconfirm" if "DISCONFIRM" in set(signals) else "vendor_content"
        if out.get("quarantine_reason") != reason:
            out["quarantine_reason"]=reason
            changed=True

    # Generic web positive demand requires buyer voice or a community/Q&A context.
    buyer_voice_missing=bool(
        web_buyer_voice_guard
        and generic_web_source(str(out.get("source") or ""))
        and bool({"PAIN","BUY_INTENT","PAID_DEMAND"} & set(out.get("signal_types") or []))
        and not generic_web_pain_allowed(
            str(out.get("title") or ""),
            str(out.get("snippet") or ""),
            str(out.get("url") or ""),
            str(out.get("source") or ""),
        )
    )
    if buyer_voice_missing and not vendor_content and not supply_offer:
        signals=[
            x for x in (out.get("signal_types") or [])
            if x not in {"PAIN","BUY_INTENT","PAID_DEMAND"}
        ]
        if out.get("signal_types") != signals:
            out["signal_types"]=signals
            changed=True
        if out.get("strong_markers"):
            out["strong_markers"]=[]
            changed=True
        if out.get("signal_reverted") != "web_buyer_voice_missing":
            out["signal_reverted"]="web_buyer_voice_missing"
            changed=True
        if out.get("gate_eligible") is not False:
            out["gate_eligible"]=False
            changed=True
        reason="disconfirm" if "DISCONFIRM" in set(signals) else "web_buyer_voice_missing"
        if out.get("quarantine_reason") != reason:
            out["quarantine_reason"]=reason
            changed=True

    # Seller-authored launches are supply-side context, never buyer demand. Preserve
    # the row for market context/audit, but remove positive demand and exclude its domain from
    # every gate calculation. This migration is intentionally idempotent.
    if seller_launch_guard and is_launch_title(str(out.get("title") or "")):
        signals=[
            x for x in (out.get("signal_types") or [])
            if x not in {"PAIN","BUY_INTENT","PAID_DEMAND"}
        ]
        if out.get("signal_types") != signals:
            out["signal_types"]=signals
            changed=True
        if out.get("strong_markers"):
            out["strong_markers"]=[]
            changed=True
        if out.get("context_type") != "product_launch":
            out["context_type"]="product_launch"
            changed=True
        if out.get("signal_reverted") != "seller_launch":
            out["signal_reverted"]="seller_launch"
            changed=True
        if out.get("gate_eligible") is not False:
            out["gate_eligible"]=False
            changed=True
        launch_reason="disconfirm" if "DISCONFIRM" in set(signals) else "seller_launch"
        if out.get("quarantine_reason") != launch_reason:
            out["quarantine_reason"]=launch_reason
            changed=True
    return out, changed


def migrate_evidence_memory(
    rows: list[dict[str, Any]] | None,
    enforce_family_match: bool = False,
    strong_pain_only: bool = False,
    seller_launch_guard: bool = False,
    vendor_content_guard: bool = False,
    web_buyer_voice_guard: bool = False,
    supply_offer_guard: bool = False,
    query_echo_guard: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    source_rows=[row for row in (rows or []) if isinstance(row,dict)]
    sibling_problem_keys=[
        canonical_problem_key(str(row.get("family") or ""),str(row.get("problem_key") or ""))
        for row in source_rows
        if str(row.get("problem_key") or "").strip()
    ]
    migrated: list[dict[str, Any]] = []
    changed = 0
    quarantined = 0
    for row in source_rows:
        new_row, row_changed = migrate_evidence_row(
            row,
            sibling_problem_keys,
            enforce_family_match=enforce_family_match,
            strong_pain_only=strong_pain_only,
            seller_launch_guard=seller_launch_guard,
            vendor_content_guard=vendor_content_guard,
            web_buyer_voice_guard=web_buyer_voice_guard,
            supply_offer_guard=supply_offer_guard,
            query_echo_guard=query_echo_guard,
        )
        if row_changed:
            changed += 1
        if not bool(new_row.get("gate_eligible")):
            quarantined += 1
        migrated.append(new_row)
    return migrated, {
        "schema_v": EVIDENCE_SCHEMA_VERSION,
        "tagger_v": TAGGER_VERSION,
        "rows": len(migrated),
        "changed": changed,
        "quarantined": quarantined,
    }
