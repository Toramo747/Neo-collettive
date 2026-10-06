# SPDX-License-Identifier: BUSL-1.1
from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timezone
from typing import Any

from gate_stability import opportunity_fingerprint, opportunity_identity

PUBLIC_ID_LENGTH = 16
ALLOWED_MISSING_CODES = frozenset({
    "specific_tool_name_and_target_user",
    "two_competitors_with_real_price",
    "dissatisfaction_signal",
    "documented_gap",
    "three_independent_source_domains",
    "monetization_score_60",
    "unknown_requirement",
})


def _hmac_id(secret: str, id_key_version: str, purpose: str, value: str) -> str:
    key = hmac.new(
        secret.encode("utf-8"),
        ("mycelix-candidate-telemetry|" + id_key_version + "|" + purpose).encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return hmac.new(key, value.encode("utf-8"), hashlib.sha256).hexdigest()[:PUBLIC_ID_LENGTH]


def _parse_utc(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


def build_candidate_telemetry(
    rows: list[dict] | None,
    gate_state: dict | None,
    *,
    secret: str,
    cycle: int,
    commit: str,
    tagger_version: str,
    observed_at_utc: str,
    first_cycle_after_deploy: bool,
    id_key_version: str="v1",
) -> list[dict]:
    if not secret:
        return []
    id_key_version = str(id_key_version or "v1")[:16]
    state = gate_state if isinstance(gate_state, dict) else {}
    candidates = state.get("candidates") if isinstance(state.get("candidates"), dict) else {}
    now = _parse_utc(observed_at_utc) or datetime.now(timezone.utc)
    out = []
    for row in list(rows or [])[:3]:
        if not isinstance(row, dict):
            continue
        private_key = opportunity_identity(row)
        candidate_state = candidates.get(private_key) if isinstance(candidates.get(private_key), dict) else {}
        first_pass = _parse_utc(candidate_state.get("first_raw_pass_utc"))
        source_rows = [x for x in (row.get("sources") or []) if isinstance(x, dict)]
        domains = {
            str(x.get("domain") or "").strip().lower()
            for x in source_rows
            if str(x.get("domain") or "").strip()
        }
        missing_codes = []
        for code in (row.get("missing") or []):
            value=str(code)
            missing_codes.append(value if value in ALLOWED_MISSING_CODES else "unknown_requirement")
        missing_codes=list(dict.fromkeys(missing_codes))
        confirmation = row.get("gate_confirmation") if isinstance(row.get("gate_confirmation"), dict) else {}
        private_fp = opportunity_fingerprint(row)
        out.append({
            "candidate_id": _hmac_id(secret, id_key_version, "candidate", private_key),
            "evidence_fingerprint": _hmac_id(secret, id_key_version, "evidence", private_fp),
            "id_key_version": id_key_version,
            "score": max(0, int(row.get("monetization_score") or 0)),
            "source_count": len(source_rows),
            "independent_domain_count": len(domains),
            "raw_gate_pass": bool(row.get("raw_gate_pass")),
            "stable_gate_pass": bool(row.get("stable_gate_pass")),
            "pass_streak": max(0, int(confirmation.get("pass_streak") or 0)),
            "fail_streak": max(0, int(confirmation.get("fail_streak") or 0)),
            "missing_codes": missing_codes[:12],
            "cycle": max(0, int(cycle or 0)),
            "commit": str(commit or "")[:64],
            "first_cycle_after_deploy": bool(first_cycle_after_deploy),
            "seconds_since_first_raw_pass": (
                max(0, int(confirmation.get("seconds_since_first_raw_pass") or 0))
                if first_pass else None
            ),
            "new_domains_since_first_pass":max(0,int(confirmation.get("new_domains_since_first_pass") or 0)),
            "tolerated_fail_cycles":max(0,int(confirmation.get("tolerated_fail_cycles") or 0)),
            "pass_ratio_in_window_ppm":max(0,min(1000000,int(float(confirmation.get("pass_ratio_in_window") or 0.0)*1000000))),
            "confirmation_blockers":[
                str(x) for x in (confirmation.get("confirmation_blockers") or [])
                if str(x) in {
                    "min_6_hours","min_2_research_cycles",
                    "evidence_fingerprint_unchanged","no_new_independent_domain",
                    "pass_ratio_below_60",
                }
            ][:8],
            "tagger_version": str(tagger_version or "")[:48],
        })
    return out
