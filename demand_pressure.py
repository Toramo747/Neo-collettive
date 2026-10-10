"""Indice di Pressione della Domanda (IPD): offline, observational and fail-closed.

One invocation measures a single opaque problem cohort. This module does not
read runtime state, touch the commercial gate, fetch content, or persist data.
Only numeric aggregates and fixed enumerations are returned.
"""
from __future__ import annotations

from collections import defaultdict
from math import isfinite, log1p
import re

SCHEMA_V = 1
WEEK_SECONDS = 7 * 24 * 3600
MAX_WEEKS = 4
OPAQUE_ID = re.compile(r"^[a-f0-9]{32,64}$")
DEMAND_TAGS = frozenset({"PAIN", "BUY_INTENT", "PAID_DEMAND"})
WEIGHTS = {
    "request_volume": 35,
    "growth": 25,
    "recurrence": 20,
    "source_diversity": 15,
    "explicit_solution_request": 5,
}


def _opaque(value: object) -> str:
    text = str(value or "").strip().lower()
    return text if OPAQUE_ID.fullmatch(text) else ""


def _epoch(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    timestamp = float(value)
    return timestamp if isfinite(timestamp) and timestamp > 0 else None


def _valid_exposure(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def demand_pressure_index(
    observations: list[dict] | None,
    *,
    now_epoch: float,
    exposure_current: int | None = None,
    exposure_previous: int | None = None,
    sampling_comparable: bool = False,
) -> dict:
    """Calculate a 0-100 *observational* index; never classify commercial proof.

    Required on each source-screened row: opaque HMAC-like request_id,
    created_at_epoch from the ORIGINAL source publication (not first_seen),
    source_screened=True, and an existing positive demand_signal_tag.
    The caller must supply one problem cohort and must exclude vendor offers,
    own traffic and agents. No raw text/URL, source IDs or requester IDs are
    exported. actor_hmac counts as independently verified only if the caller
    explicitly supplies independent_requester_verified=True; that flag is not
    cryptographic proof of separate humans.
    """
    now = _epoch(now_epoch)
    if now is None:
        raise ValueError("now_epoch must be a positive finite number")

    groups: dict[str, list[dict]] = defaultdict(list)
    supplied = 0
    excluded = 0
    for row in observations or []:
        supplied += 1
        if not isinstance(row, dict):
            excluded += 1
            continue
        req = _opaque(row.get("request_id"))
        when = _epoch(row.get("created_at_epoch"))
        if (
            not req or when is None
            or not (0 <= now - when < MAX_WEEKS * WEEK_SECONDS)
            or row.get("source_screened") is not True
            or str(row.get("demand_signal_tag") or "") not in DEMAND_TAGS
            or row.get("vendor_offer") is not False
            or row.get("self_traffic") is not False
            or row.get("agent_origin") is not False
        ):
            excluded += 1
            continue
        groups[req].append(row)

    weekly = [0] * MAX_WEEKS
    actors = set()
    domains = set()
    explicit = 0
    anonymous_threads = 0
    # One source request can be crawled many times; group by stable opaque ID.
    # Conflicting duplicates do not increase identity/source or explicit credit.
    for duplicates in groups.values():
        born = min(float(r["created_at_epoch"]) for r in duplicates)
        week = int((now - born) // WEEK_SECONDS)
        weekly[week] += 1
        identities = {
            _opaque(r.get("actor_hmac")) for r in duplicates
            if r.get("independent_requester_verified") is True
        }
        identities.discard("")
        actor = next(iter(identities)) if len(identities) == 1 and all(
            r.get("independent_requester_verified") is True
            and _opaque(r.get("actor_hmac")) in identities
            for r in duplicates
        ) else ""
        if actor:
            actors.add(actor)
        else:
            anonymous_threads += 1
        origins = {str(r.get("origin_domain") or "").strip().lower() for r in duplicates}
        origins.discard("")
        if len(origins) == 1 and all(str(r.get("origin_domain") or "").strip().lower() in origins for r in duplicates):
            domains.update(origins)
        if all(r.get("explicit_solution_request") is True for r in duplicates):
            explicit += 1

    n = len(groups)
    volume = min(100, round(100 * log1p(n) / log1p(50))) if n else 0
    recurrence = 25 * sum(1 for count in weekly if count > 0)
    diversity = min(100, max(0, len(domains) - 1) * 34)
    explicit_component = round(100 * explicit / n) if n else 0

    growth_status = "EXPOSURE_MISSING"
    growth = 0
    growth_percent = None
    if sampling_comparable and _valid_exposure(exposure_current) and _valid_exposure(exposure_previous):
        current_rate = weekly[0] / exposure_current
        previous_rate = weekly[1] / exposure_previous
        if previous_rate == 0:
            growth_status = "EMERGING" if weekly[0] else "NO_OBSERVATIONS"
            growth = min(100, 25 * weekly[0])
        else:
            growth_status = "MEASURED"
            growth_percent = round(100 * (current_rate / previous_rate - 1), 1)
            growth = min(100, max(0, round(50 * (current_rate / previous_rate - 1))))

    components = {
        "request_volume": volume,
        "growth": growth,
        "recurrence": recurrence,
        "source_diversity": diversity,
        "explicit_solution_request": explicit_component,
    }
    score = round(sum(components[key] * WEIGHTS[key] for key in WEIGHTS) / 100)
    if n < 3:
        evidence_status = "TOO_FEW_THREADS"
    elif len(actors) < 2:
        evidence_status = "IDENTITY_NOT_VERIFIED"
    elif growth_status == "EXPOSURE_MISSING":
        evidence_status = "TREND_NOT_MEASURABLE"
    else:
        evidence_status = "EXPLORATORY_ONLY"

    return {
        "schema_v": SCHEMA_V,
        "mode": "shadow_only",
        "ipd_score": score,
        "components": components,
        "component_weights": dict(WEIGHTS),
        "unique_request_threads": n,
        "verified_requester_tokens": len(actors),
        "unverified_request_threads": anonymous_threads,
        "origin_domains": len(domains),
        "explicit_solution_threads": explicit,
        "weekly_request_threads_newest_first": weekly,
        "source_rows_received": supplied,
        "source_rows_excluded": excluded,
        "growth_status": growth_status,
        "growth_percent": growth_percent,
        "evidence_status": evidence_status,
        "commercial_gate_influence": "NONE",
        "automatic_promotion": False,
    }
