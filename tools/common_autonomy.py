"""Earned autonomy for the Common drafting mind (shadow mode).

The mind never posts by itself today. This tool measures, per reply category,
whether its drafts would have been safe to post: each draft Andrea judged is in
the private experience log (tools/common_experience.py) as approved (posted
essentially as drafted), rewritten, rejected or not_used. A category becomes
ELIGIBLE only on a measured record; it becomes ENABLED only when Andrea switches
it on in docs/autonomy-policy.json. Categories that carry promises, money or
commitments can never be enabled.

  status <private_dir>                 -> table per category (counts only, no text)
  shadow <private_dir> <drafts_json>   -> marks each ready draft would_autopost true/false (recorded, never posted)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "docs" / "autonomy-policy.json"
NEVER = {"commitment"}            # promises/deadlines/partnerships stay with Andrea forever
JUDGED = {"approved", "rewritten", "rejected"}


def policy() -> dict:
    return json.loads(POLICY.read_text())


def _experience(private_dir: str) -> list[dict]:
    p = Path(private_dir) / "common" / "experience.jsonl"
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.exists() else []


def _draft_category(private_dir: str) -> dict[tuple, str]:
    """(draft_file, message_id) -> category, from the stored drafts."""
    out = {}
    for f in (Path(private_dir) / "common" / "drafts").glob("2*.json"):
        for d in json.loads(f.read_text()).get("drafts") or []:
            out[(f.name, d.get("id"))] = str(d.get("category") or "other")
    return out


def scorecard(private_dir: str) -> dict[str, dict]:
    pol = policy()
    cats = _draft_category(private_dir)
    by: dict[str, list[str]] = {}
    for r in _experience(private_dir):
        if r.get("verdict") not in JUDGED or not r.get("draft_file"):
            continue
        cat = cats.get((r["draft_file"], r.get("message_id")), "other")
        by.setdefault(cat, []).append(r["verdict"])
    out = {}
    for cat in sorted(set(by) | set(pol["categories"])):
        v = by.get(cat, [])
        rule = pol["categories"].get(cat, {})
        n, approved = len(v), v.count("approved")
        recent = v[-pol["recent_window"]:]
        rate = round(approved / n, 2) if n else 0.0
        eligible = (cat not in NEVER and n >= pol["min_cases"] and rate >= pol["min_approved_rate"]
                    and "rejected" not in recent)
        out[cat] = {"judged": n, "approved": approved, "rewritten": v.count("rewritten"),
                    "rejected": v.count("rejected"), "approved_rate": rate, "eligible": eligible,
                    "enabled": bool(rule.get("enabled")) and eligible and cat not in NEVER}
    return out


def status(private_dir: str) -> int:
    card = scorecard(private_dir)
    print("::notice title=autonomy scorecard::" + json.dumps(card, sort_keys=True))
    return 0


def would_autopost(draft: dict, card: dict) -> bool:
    cat = str(draft.get("category") or "other")
    return (draft.get("status") == "ready" and not draft.get("issues")
            and bool(card.get(cat, {}).get("enabled")))


def shadow(private_dir: str, drafts_json: str) -> int:
    """Shadow mode: record what the mind WOULD post on its own; nothing is posted."""
    card = scorecard(private_dir)
    p = Path(drafts_json)
    data = json.loads(p.read_text())
    for d in data.get("drafts") or []:
        d["would_autopost"] = would_autopost(d, card)
        d["autonomy_category_eligible"] = bool(card.get(str(d.get("category") or "other"), {}).get("eligible"))
    data["autonomy_mode"] = "shadow"
    p.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    print("::notice title=autonomy shadow::" + json.dumps({
        "drafts": len(data.get("drafts") or []),
        "would_autopost": sum(bool(d.get("would_autopost")) for d in data.get("drafts") or [])}))
    return 0


if __name__ == "__main__":
    cmd, *args = sys.argv[1:]
    raise SystemExit({"status": status, "shadow": shadow}[cmd](*args))
