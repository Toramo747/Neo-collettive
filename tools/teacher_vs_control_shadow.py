# SPDX-License-Identifier: BUSL-1.1
"""Preregistered comparison: teacher-lineage champion vs control (lexicon) champion.

docs/maestro.md, "Teacher as real fitness". Read-only: queries HN Algolia with each
champion's genes exactly as its arena runs them, scores every arm with the SAME
scorer (arena_research_algorithm.score_hits) on training and holdout topics, and
prints aggregate counts only. Thresholds (holdout): teacher >= 1.5x control signals,
>= 5 signals, precision not lower by more than 0.05.

usage: teacher_vs_control_shadow.py [<private_dir>]   (appends the run to maestro/teacher_vs_control.jsonl)
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import arena_research_algorithm as arena  # noqa: E402

SCORER = {"min_relevance_tokens": 1}
HOLDOUT = {  # same preregistered holdout as tools/research_champion_shadow.py
    "crm lead tracking": "lead tracking",
    "employee onboarding paperwork": "onboarding paperwork",
    "pdf document extraction": "pdf extraction",
    "ecommerce inventory sync": "inventory sync",
}


def champion(path: str) -> dict:
    d = json.loads((ROOT / path).read_text())
    top = d["ranked"][0]
    return {"id": top["genome_id"], "genes": arena.clamp_genome(top["genes"]), "generation": d.get("evaluated_generation")}


def queries(genes: dict, topics: dict[str, str]) -> list[tuple[str, str]]:
    suffixes = arena.QUERY_SUFFIXES[genes["suffix_family"]][genes["query_mode"]][: genes["query_count"]]
    out = []
    for topic, compact in topics.items():
        t = compact if genes["topic_shape"] == "compact" else topic
        for s in suffixes:
            q = " ".join((t, s) if genes["term_order"] == "topic_first" else (s, t))
            q = {"need": "need " + q, "looking_for": "looking for " + q}.get(genes["query_frame"], q)
            out.append((topic, q))
    return out


async def arm(client, genes: dict, topics: dict[str, str]) -> dict:
    rows = await asyncio.gather(*[arena.fetch_hn_query(client, t, q, genes["recency_days"], genes["source_scope"])
                                  for t, q in queries(genes, topics)])
    m = arena.score_hits(SCORER, list(rows))
    m["failed_queries"] = sum(1 for r in rows if not r.get("ok"))
    return {k: m.get(k) for k in ("total_hits", "relevant_hits", "signal_hits", "unique_signal_threads",
                                  "buyer_hits", "precision", "failed_queries")}


async def run() -> dict:
    ctl = champion("data/arena/research-algorithm/latest.json")
    tea = champion("data/arena/research-algorithm-teacher/latest.json")
    training = {t: arena.TOPIC_SHAPES["compact"][t] for t in arena.TOPICS}
    res = {"at_utc": datetime.now(timezone.utc).isoformat(), "control": ctl, "teacher": tea, "results": {}}
    async with httpx.AsyncClient(timeout=20, headers={"User-Agent": "MYCELIX-teacher-shadow/1"}) as client:
        for set_name, topics in (("training", training), ("holdout", HOLDOUT)):
            for name, champ in (("control", ctl), ("teacher", tea)):
                res["results"][f"{set_name}:{name}"] = await arm(client, champ["genes"], topics)
    c, t = res["results"]["holdout:control"], res["results"]["holdout:teacher"]
    cs, ts = int(c["signal_hits"] or 0), int(t["signal_hits"] or 0)
    res["verdict"] = {
        "teacher_signals_ge_1_5x": ts >= 1.5 * cs and ts > 0,
        "teacher_signals_ge_5": ts >= 5,
        "precision_not_lower_than_0_05": float(t["precision"] or 0) >= float(c["precision"] or 0) - 0.05,
        "no_failed_queries": not (c["failed_queries"] or t["failed_queries"]),
    }
    res["verdict"]["teacher_wins_this_run"] = all(res["verdict"].values())
    return res


def main() -> int:
    res = asyncio.run(run())
    print(f"::notice title=champions::control {res['control']['id']} (gen {res['control']['generation']}) | teacher {res['teacher']['id']} (gen {res['teacher']['generation']})")
    for k, m in res["results"].items():
        print(f"::notice title=shadow {k}::" + " ".join(f"{a}={b}" for a, b in m.items()))
    print("::notice title=verdict this run::" + json.dumps(res["verdict"]))
    if len(sys.argv) > 1:
        p = Path(sys.argv[1]) / "maestro" / "teacher_vs_control.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a") as fh:
            fh.write(json.dumps(res) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
