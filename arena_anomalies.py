# SPDX-License-Identifier: BUSL-1.1
"""Anomaly Arena: listen to nature's signals the way NEO listens to demand.

Tracks open tensions between measurement and theory in the public physics
literature (arXiv API) and follows them over time: which ones strengthen,
which ones fade.  An "anomaly signal" is only ever an attention signal about
the literature, never a physical claim.

Per anomaly and run (window: last 180 days of arXiv submissions):
* papers           -- matching papers in the window
* tension_cues     -- abstracts stating a tension / discrepancy / anomaly
* resolution_cues  -- abstracts stating consistency / resolution / no tension
* sigma_reported   -- significances quoted in abstracts ("4.2 sigma"), median and max
* persistence      -- (tension - resolution) / papers, in [-1, 1]
* trend            -- change of persistence and median sigma vs the previous run

Controls: anomalies widely regarded as resolved (proton radius) must not look
like strengthening signals; if they do, the scoring is miscalibrated.

Read-only, public API, metadata only (ids, dates, titles).  No production
influence.  arXiv API terms: at most one request every 3 seconds.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

ARENA = "anomaly-signals"
SCORING_V = 2  # bump whenever cue scoring changes: older baselines are not comparable
API = "https://export.arxiv.org/api/query"
WINDOW_DAYS = 180
MAX_RESULTS = 200
ATOM = {"a": "http://www.w3.org/2005/Atom"}

ANOMALIES = (
    # id, arXiv query, why it matters, control (expected to fade)
    ("hubble_tension", 'abs:"Hubble tension"', "Expansion rate: local vs early-universe values disagree", False),
    ("evolving_dark_energy", 'abs:"dynamical dark energy" OR abs:"evolving dark energy"',
     "Dark energy, the 'negative pressure' of the universe, may change with time", False),
    ("s8_tension", 'abs:"S8 tension" OR abs:"S_8 tension" OR abs:"sigma_8 tension"', "Matter clumping: weak lensing vs CMB", False),
    ("neutron_lifetime", 'abs:"neutron lifetime" AND (abs:beam OR abs:bottle)', "Beam vs bottle lifetimes disagree", False),
    ("w_boson_mass", 'abs:"W boson mass" OR abs:"W-boson mass"', "CDF 2022 W mass vs other measurements", False),
    ("lithium_problem", 'abs:"lithium problem"', "Big Bang nucleosynthesis predicts more lithium than observed", False),
    ("casimir_negative_energy", 'abs:Casimir AND abs:"negative energy"', "Measured negative energy density in the lab", False),
    ("proton_radius_control", 'abs:"proton radius puzzle"', "Control: widely regarded as largely resolved", True),
)

TENSION_RE = re.compile(r"\b(tension|discrepanc\w*|anomal\w*|disagree\w*|inconsisten\w*|puzzle|deviat\w* from)\b", re.I)
RESOLUTION_RE = re.compile(r"\b(resolv\w*( the \w+)?|consistent with|in agreement|agrees? with|no (significant )?(tension|evidence|discrepancy|anomaly)|alleviat\w*|reconcil\w*|eliminat\w*)\b", re.I)
SIGMA_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:σ|sigma\b|\\sigma\b|-sigma\b|\$\\sigma\$)", re.I)

BOUNDARY = {
    "production_state_write": False,
    "production_runtime_influence": "NONE",
    "automatic_physical_claims": False,
    "promotion": "HUMAN_SCIENTIFIC_REVIEW_ONLY",
    "data": "arXiv metadata only (ids, dates, titles, abstract-derived counts)",
}


def fetch_atom(query: str, timeout: float = 30.0) -> str:
    params = urllib.parse.urlencode({"search_query": query, "sortBy": "submittedDate",
                                     "sortOrder": "descending", "max_results": MAX_RESULTS})
    req = urllib.request.Request(f"{API}?{params}", headers={"User-Agent": "MYCELIX-anomaly-arena/1 (research)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8")


def parse_entries(atom: str) -> list[dict]:
    root = ET.fromstring(atom)
    out = []
    for e in root.findall("a:entry", ATOM):
        out.append({
            "id": (e.findtext("a:id", default="", namespaces=ATOM) or "").rsplit("/", 1)[-1],
            "published": e.findtext("a:published", default="", namespaces=ATOM) or "",
            "title": " ".join((e.findtext("a:title", default="", namespaces=ATOM) or "").split()),
            "summary": " ".join((e.findtext("a:summary", default="", namespaces=ATOM) or "").split()),
        })
    return out


def strip_query_echo(text: str, query: str) -> str:
    """Remove the phrases we searched for: 'Hubble tension' must not count as a tension cue."""
    for phrase in re.findall(r'"([^"]+)"', query or ""):
        text = re.sub(re.escape(phrase), " ", text, flags=re.I)
    return text


def score(entries: list[dict], now: datetime, window_days: int = WINDOW_DAYS, query: str = "") -> dict:
    cutoff = now - timedelta(days=window_days)
    recent = []
    for e in entries:
        try:
            ts = datetime.fromisoformat(e["published"].replace("Z", "+00:00"))
        except ValueError:
            continue
        if ts >= cutoff:
            recent.append(e)
    # Negated mentions ("no tension", "resolves the discrepancy") are removed first.
    texts = [strip_query_echo(e["summary"], query) for e in recent]
    tension = sum(1 for t in texts if TENSION_RE.search(RESOLUTION_RE.sub(" ", t)))
    resolution = sum(1 for t in texts if RESOLUTION_RE.search(t))
    sigmas = [float(m) for e in recent for m in SIGMA_RE.findall(e["summary"]) if 0 < float(m) <= 20]
    n = len(recent)
    return {
        "papers": n,
        "tension_cues": tension,
        "resolution_cues": resolution,
        "persistence": round((tension - resolution) / n, 3) if n else None,
        "sigma_reported_count": len(sigmas),
        "sigma_median": round(statistics.median(sigmas), 2) if sigmas else None,
        "sigma_max": max(sigmas) if sigmas else None,
        "sample": [{"id": e["id"], "published": e["published"][:10], "title": e["title"][:140]} for e in recent[:5]],
        "window_capped": len(entries) >= MAX_RESULTS and n == len(entries),
    }


def trend(current: dict, previous: dict | None) -> dict:
    if not previous:
        return {"status": "FIRST_OBSERVATION"}
    def delta(key):
        a, b = current.get(key), previous.get(key)
        return round(a - b, 3) if isinstance(a, (int, float)) and isinstance(b, (int, float)) else None
    dp, ds = delta("persistence"), delta("sigma_median")
    if dp is None:
        status = "INSUFFICIENT_DATA"
    elif dp > 0.05 or (ds or 0) > 0.3:
        status = "STRENGTHENING"
    elif dp < -0.05 or (ds or 0) < -0.3:
        status = "FADING"
    else:
        status = "STABLE"
    return {"status": status, "persistence_delta": dp, "sigma_median_delta": ds, "papers_delta": delta("papers")}


def run(data_dir: Path, fetch=fetch_atom, now: datetime | None = None, pause: float = 3.2) -> dict:
    now = now or datetime.now(timezone.utc)
    state_path, report_path = data_dir / "state.json", data_dir / "latest.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.is_file() else {}
    previous = (state.get("last") or {}) if state.get("scoring_v") == SCORING_V else {}
    rows, errors = {}, {}
    for i, (aid, query, why, control) in enumerate(ANOMALIES):
        if i:
            time.sleep(pause)
        try:
            s = score(parse_entries(fetch(query)), now, query=query)
        except Exception as exc:
            errors[aid] = type(exc).__name__
            continue
        s.update({"why": why, "control": control, "query": query, "trend": trend(s, previous.get(aid))})
        rows[aid] = s
    controls_ok = all(r["trend"]["status"] != "STRENGTHENING" for r in rows.values() if r["control"])
    ranked = sorted((a for a in rows if not rows[a]["control"]),
                    key=lambda a: (rows[a]["persistence"] or -1, rows[a]["sigma_median"] or 0), reverse=True)
    report = {
        "schema_v": 1, "scoring_v": SCORING_V, "arena": ARENA, "generated_at_utc": now.isoformat(),
        "window_days": WINDOW_DAYS, "anomalies": rows, "errors": errors,
        "ranking_by_persistence": ranked,
        "controls_ok": controls_ok,
        "boundary": BOUNDARY,
        "disclaimer": "Literature attention signals from abstract wording and quoted significances; not physical evidence.",
    }
    history = list(state.get("history") or [])[-180:]
    history.append({"at": now.isoformat(), **{a: {"persistence": r["persistence"], "sigma_median": r["sigma_median"],
                                                  "papers": r["papers"]} for a, r in rows.items()}})
    new_state = {"schema_v": 1, "scoring_v": SCORING_V, "arena": ARENA, "last": {a: {k: r[k] for k in ("papers", "persistence", "sigma_median")}
                                                         for a, r in rows.items()} or previous,
                 "history": history}
    data_dir.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(new_state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--data-dir", default="data/arena/anomalies")
    args = p.parse_args()
    r = run(Path(args.data_dir))
    print(json.dumps({"arena": ARENA, "ranking": r["ranking_by_persistence"], "controls_ok": r["controls_ok"],
                      "errors": r["errors"]}, separators=(",", ":")))
    return 0 if len(r["errors"]) < len(ANOMALIES) else 1


if __name__ == "__main__":
    raise SystemExit(main())
