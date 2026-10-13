# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Andrea Gava
"""Market inference without competitor prices (shadow).

Decision 2026-10-12 (Andrea): stop trying to validate opportunities with
competitor prices; infer the market instead from indirect signals:

  demand    distinct people/threads describing the problem in their own voice
  money     first-person willingness to pay, bounties, hiring, budgets
  market    someone already sells in this space (a paid product exists,
            no extracted price required)
  momentum  the problem recurs over time and is recent

Marketing copy, reference pages (encyclopedias, dictionaries) and bot-generated
issues are never counted as demand. This module is SHADOW ONLY: it annotates
opportunities and never changes gate_pass.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import urlparse

MARKET_INFERENCE_VERSION = 1
SHADOW_GATE_SCORE = 60
MIN_REQUESTERS = 3
MIN_DEMAND_DOMAINS = 2

REFERENCE_DOMAINS = (
    "wikipedia.org", "wiktionary.org", "dictionary.cambridge.org", "merriam-webster.com",
    "collinsdictionary.com", "dictionary.com", "investopedia.com", "britannica.com",
    "mckinsey.com", "betterup.com", "code.org", "apotheken-umschau.de",
)
BOT_RE = re.compile(
    r"\b(renovate|dependabot|dependency dashboard|this issue lists renovate|github-actions\[bot\]|"
    r"automated (pull request|issue)|ai disclosure)\b", re.I)
MARKETING_RE = re.compile(
    r"\b(sign up|get started|book a demo|start (your )?free trial|our platform|we help|"
    r"trusted by|request a demo|try it free|learn more|we('ve)? (built|made|launched|created)|show hn|introducing|launch(ed|ing)? (today|on))\b", re.I)
VOICE_RE = re.compile(
    r"\b(i|we|my team|our team|our company|me)\b[^.?!\n]{0,80}\b("
    r"need|needs|struggl\w*|spend\w*|waste\w*|hate|can't|cannot|couldn't|wish|looking for|"
    r"manually|workaround|hack(ed)? together|fed up|tired of|frustrat\w*|is there a way|how (do|can) i)\b",
    re.I)
QUESTION_RE = re.compile(
    r"\b(is there (a|an|any) (tool|app|service|way)|anyone know (of|a)|how do (i|you|we)|what do you use for)\b", re.I)
PAY_RE = re.compile(
    r"\b(i|we)\s*(would|'d|will|'ll)\s+(happily\s+|gladly\s+|definitely\s+)?pay\b|\btake my money\b|"
    r"\b(bounty|budget for|we('| a)re hiring|hire (a|someone)|freelancer|paid gig|willing to pay)\b", re.I)


def _domain_ok(domain: str) -> bool:
    d = str(domain or "").lower().strip(".")
    return bool(d) and not any(d == r or d.endswith("." + r) for r in REFERENCE_DOMAINS)


def _requester_key(url: str) -> str:
    try:
        p = urlparse(str(url or ""))
    except Exception:
        return ""
    host = (p.hostname or "").lower()
    parts = [x for x in p.path.split("/") if x]
    if host == "github.com" and len(parts) >= 2:
        return "github.com/" + parts[0].lower() + "/" + parts[1].lower()
    return host + "/" + "/".join(parts[:3]).lower()


def _parse_date(value) -> datetime | None:
    try:
        d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def classify_row(row: dict) -> str:
    """'demand' | 'supply' | 'noise' for one source row."""
    text = " ".join(str(row.get(k) or "") for k in ("title", "excerpt"))
    if not _domain_ok(row.get("domain")) or BOT_RE.search(text):
        return "noise"
    voice = bool(VOICE_RE.search(text) or QUESTION_RE.search(text) or PAY_RE.search(text))
    payment = "PAYMENT" in (row.get("signal_types") or [])
    if voice and not MARKETING_RE.search(text):
        return "demand"
    if payment or MARKETING_RE.search(text):
        return "supply"
    return "noise"


def assess(sources: list[dict], *, thesis_specific: bool, now: str | None = None) -> dict:
    now_dt = _parse_date(now) or datetime.now(timezone.utc)
    demand, supply = [], []
    noise = 0
    for row in sources or []:
        if not isinstance(row, dict):
            continue
        kind = classify_row(row)
        if kind == "demand":
            demand.append(row)
        elif kind == "supply":
            supply.append(row)
        else:
            noise += 1
    requesters = sorted({k for k in (_requester_key(r.get("url")) for r in demand) if k})
    demand_domains = sorted({str(r.get("domain") or "") for r in demand if r.get("domain")})
    money = [r for r in demand if PAY_RE.search(" ".join(str(r.get(k) or "") for k in ("title", "excerpt")))]
    sellers = sorted({str(r.get("domain") or "") for r in supply if "PAYMENT" in (r.get("signal_types") or [])})
    counters = sorted({str(r.get("domain") or "") for r in (sources or [])
                       if isinstance(r, dict) and "COUNTER" in (r.get("signal_types") or [])})
    dates = sorted(d for d in (_parse_date(r.get("date")) for r in demand) if d)
    span_days = (dates[-1] - dates[0]).days if len(dates) >= 2 else 0
    recent = any((now_dt - d).days <= 45 for d in dates)

    parts = {
        "demand": min(45, 15 * len(requesters)) + (5 if len(demand_domains) >= MIN_DEMAND_DOMAINS else 0),
        "money": min(20, 10 * len(money)),
        "market": min(15, 8 * len(sellers)),
        "momentum": (10 if span_days >= 14 else 0) + (5 if recent else 0),
        "counter": -min(20, 10 * len(counters)),
    }
    score = max(0, min(100, sum(parts.values())))
    missing = []
    if not thesis_specific:
        missing.append("specific_tool_name_and_target_user")
    if len(requesters) < MIN_REQUESTERS:
        missing.append("three_independent_requesters")
    if len(demand_domains) < MIN_DEMAND_DOMAINS:
        missing.append("two_demand_domains")
    if not money and not sellers:
        missing.append("money_or_existing_market")
    if score < SHADOW_GATE_SCORE:
        missing.append("market_score_60")
    return {
        "version": MARKET_INFERENCE_VERSION,
        "mode": "shadow",
        "score": score,
        "parts": parts,
        "shadow_gate_pass": not missing,
        "missing": missing,
        "demand_rows": len(demand),
        "independent_requesters": len(requesters),
        "demand_domains": len(demand_domains),
        "money_signals": len(money),
        "existing_sellers": len(sellers),
        "noise_rows": noise,
        "span_days": span_days,
        "recent": recent,
        "affects_gate": False,
    }
