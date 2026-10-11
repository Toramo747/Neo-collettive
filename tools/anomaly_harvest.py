# SPDX-License-Identifier: BUSL-1.1
"""Anomaly classifier, phase A: harvest public arXiv abstracts for labelling.

Abstracts go only to the private archive (anomaly/abstracts.jsonl); logs show
counts only.  Besides the arena's anomalies, a few anomalies widely regarded as
resolved or faded are included, so the labels contain enough "resolves" cases.
arXiv API terms: one request every 3 seconds.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import arena_anomalies as aa  # noqa: E402

PER_QUERY = 150
EXTRA = (
    ("opera_superluminal", 'abs:OPERA AND abs:superluminal'),
    ("diphoton_750", 'abs:"750 GeV" AND abs:diphoton'),
    ("bicep2_bmodes", 'abs:BICEP2 AND (abs:"B-mode" OR abs:"B modes")'),
    ("muon_g2", 'abs:"muon g-2" OR abs:"muon anomalous magnetic moment"'),
    ("reactor_antineutrino", 'abs:"reactor antineutrino anomaly"'),
    ("gallium_anomaly", 'abs:"gallium anomaly"'),
    ("atomki_x17", 'abs:X17 AND abs:ATOMKI'),
    ("cosmic_dipole", 'abs:"cosmic dipole" OR abs:"Ellis-Baldwin"'),
)


def fetch(query: str) -> list[dict]:
    import urllib.parse
    import urllib.request
    params = urllib.parse.urlencode({"search_query": query, "sortBy": "submittedDate",
                                     "sortOrder": "descending", "max_results": PER_QUERY})
    req = urllib.request.Request(f"{aa.API}?{params}", headers={"User-Agent": "MYCELIX-anomaly-harvest/1 (research)"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return aa.parse_entries(r.read().decode("utf-8"))


def main(private_dir: str) -> int:
    out_dir = Path(private_dir) / "anomaly"
    out_dir.mkdir(parents=True, exist_ok=True)
    queries = [(aid, q) for aid, q, _why, _ctl in aa.ANOMALIES] + list(EXTRA)
    seen, rows, per = set(), [], {}
    for i, (aid, q) in enumerate(queries):
        if i:
            time.sleep(3.2)
        try:
            entries = fetch(q)
        except Exception as exc:
            per[aid] = f"error:{type(exc).__name__}"
            continue
        n = 0
        for e in entries:
            if not e["id"] or e["id"] in seen or not e["summary"]:
                continue
            seen.add(e["id"])
            rows.append({"id": e["id"], "published": e["published"][:10], "topic": aid, "query": q,
                         "title": e["title"], "abstract": e["summary"]})
            n += 1
        per[aid] = n
    with (out_dir / "abstracts.jsonl").open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print("::notice title=anomaly harvest::" + json.dumps({"abstracts": len(rows), "per_topic": per}, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
