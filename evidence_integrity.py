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

PAIN_TERMS = (
    "pain","problem","manual","repetitive","time consuming","time-consuming",
    "frustrat","tired of","waste time","workaround","backlog",
)
BUY_INTENT_TERMS = (
    "looking for","need help","need a","seeking","want someone","recommend a",
    "how can i automate","request:","rfp","request for proposal",
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

STRUCTURED_PAID_SOURCES = {
    "remotive-api",
    "remoteok-api",
    "arbeitnow-api",
    "hn-jobs",
}


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


def demand_signal_type(title: str, body: str, query_role: str = "") -> list[str]:
    """Tag buyer-side demand separately from vendor/supply pricing.

    A disconfirm search result is never turned into positive commercial evidence.
    """
    text = ((title or "") + " " + (body or "")).lower()
    role = (query_role or "").strip().lower()
    if role == "disconfirm":
        return ["DISCONFIRM"]

    tags: list[str] = []
    pain = contains_any(text, PAIN_TERMS)
    intent = contains_any(text, BUY_INTENT_TERMS)
    buyer_paid = contains_any(text, BUYER_PAID_TERMS)
    supply = contains_any(text, SUPPLY_TERMS)

    if pain:
        tags.append("PAIN")
    if intent:
        tags.append("BUY_INTENT")

    # Buyer-side payment must have a buyer/hiring context. Generic vendor pricing
    # is supply/competition, not proof that a buyer is currently willing to pay.
    if buyer_paid and (intent or pain or role in {"buyer", "paid_market", "practitioner"}):
        tags.append("PAID_DEMAND")
    if supply:
        tags.append("COMPETITION")
    return tags


def problem_tail(problem_key: str) -> str:
    return str(problem_key or "").split(":", 1)[-1].strip().lower()


def canonical_problem_key(family: str, problem_key: str) -> str:
    family = str(family or "").strip()
    key = str(problem_key or "").strip()
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
    return canonical_problem_key("",pid)


def make_thesis_id(family: str, customer: str, job: str, pain: str) -> str:
    raw = "|".join([family or "", customer or "", job or "", pain or ""]).encode("utf-8", "ignore")
    return "th-" + hashlib.sha1(raw).hexdigest()[:12]


def migrate_evidence_row(row: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Idempotently quarantine pre-v2 evidence until it is re-observed by tagger v2."""
    out = dict(row or {})
    changed = False
    family = str(out.get("family") or "")
    raw_key = str(out.get("problem_key_raw") or out.get("problem_key") or (family + ":general" if family else ""))
    canonical = canonical_problem_key(family, str(out.get("problem_key") or raw_key))
    if out.get("problem_key_raw") != raw_key:
        out["problem_key_raw"] = raw_key
        changed = True
    if out.get("problem_key") != canonical:
        out["problem_key"] = canonical
        changed = True

    schema_v = int(out.get("schema_v") or 1)
    tagger_v = int(out.get("tagger_v") or 1)
    migration_v = int(out.get("migration_v") or 0)
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
        if "gate_eligible" not in out:
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
    return out, changed


def migrate_evidence_memory(rows: list[dict[str, Any]] | None) -> tuple[list[dict[str, Any]], dict[str, int]]:
    migrated: list[dict[str, Any]] = []
    changed = 0
    quarantined = 0
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        new_row, row_changed = migrate_evidence_row(row)
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
