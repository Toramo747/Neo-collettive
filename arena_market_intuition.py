# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Andrea Gava
"""Market Intuition Arena: an open-ended, self-evolving search for real markets.

Every run is one generation. A population of search genomes (pain phrase x
problem term x source x time window) queries free public sources, and each hit
is classified with market_inference (demand / supply / noise). Fitness rewards
NEW independent people describing a problem in their own voice, willingness to
pay, and problems that recur across several people (a "market").

Self-evolution:
  * each genome carries its own mutation rate (log-normal self-adaptation);
  * the vocabulary of problem terms is LEARNED: words that keep appearing in
    demand from different people are added and reinforced, unused words decay,
    so the search can wander into markets nobody seeded;
  * a novelty archive (hashed) means re-finding the same people earns little;
  * stagnation raises immigration.

Isolation: no production state, gate, evidence memory or provider budget is
touched. State and discoveries live ONLY in the private directory passed on the
command line; the public log gets aggregate numbers and generic terms only.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import random
import re
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import market_inference as mi

ARENA_ID = "market-intuition"
VERSION = 2
POPULATION = 8
ELITES = 2
QUERIES_PER_GENOME = 4
HITS_PER_QUERY = 50
SE_QUERY_CAP = 6          # Stack Exchange anonymous quota is 300/day per IP
VOCAB_CAP = 240
ARCHIVE_CAP = 20000
STAGNATION_WINDOW = 6
USER_AGENT = "MYCELIX-market-intuition-arena/1 (public read-only research)"

PHRASES = (
    "is there a tool", "is there an app", "i wish there was", "looking for a tool",
    "we spend hours", "manually every", "would pay for", "any alternative to",
    "tired of", "how do you handle", "our workaround", "hate doing",
    "what do you use for", "is there a better way", "takes forever",
)
SEED_TERMS = (
    "invoices", "spreadsheet", "scheduling", "inventory", "reporting", "compliance",
    "onboarding", "backups", "receipts", "contracts", "timesheets", "crm", "emails",
    "pdf", "translation", "payroll", "bookings", "shipping", "dashboards", "migration",
    "expenses", "meetings", "documentation", "customer support", "recruiting",
    "accounting", "tax", "permissions", "monitoring", "data entry", "quotes", "leads",
)
SOURCES = ("hn_comments", "hn_stories", "se_softwarerecs", "se_superuser", "se_webapps", "se_stackoverflow")
SE_SITES = {"se_softwarerecs": "softwarerecs", "se_superuser": "superuser",
            "se_webapps": "webapps", "se_stackoverflow": "stackoverflow"}
STOPWORDS = set("""
about above after again against also always another anyone anything around because been before being
below between both cannot could does doing done down during each else even every from further have having
here into just know like make many might more most much need needs never only other ours over really same
should some such than that their them then there these they thing things this those through under until
very want what when where which while will with without would your yours just still able using used use
didn doesn isn wasn couldn wouldn shouldn aren haven hasn weren won https http www com
think though right everything anything nothing something idea course first running going giving
always actually probably maybe pretty sure kind sort point problem problems issue issues question questions
thing case cases part place years people person user users guys stuff while since until until against
other another again agree true false fine okay yeah sense reason point lot lots little bit much more less
tool tools app apps software something someone thanks hello please better best good great looking wish
work works working time hours every manually would there year years month months week weeks today people
""".split())
BOUNDARY = {
    "production_state_write": False,
    "commercial_gate_influence": "NONE",
    "commercial_evidence_influence": "NONE",
    "search_provider_budget_influence": "NONE",
    "promotion": "MANUAL_REVIEW_ONLY",
    "public_output": "AGGREGATES_AND_GENERIC_TERMS_ONLY",
}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def h(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", "replace")).hexdigest()[:16]


def clean(value: Any) -> str:
    text = re.sub(r"<[^>]+>", " ", html.unescape(str(value or "")))
    return re.sub(r"\s+", " ", text).strip()


# ---------------------------------------------------------------- genomes
def clamp(g: dict) -> dict:
    g = dict(g)
    g["phrases"] = [p for p in g.get("phrases", []) if p in PHRASES][:2] or [PHRASES[0]]
    g["terms"] = [str(t)[:40] for t in g.get("terms", []) if str(t).strip()][:2] or [SEED_TERMS[0]]
    g["sources"] = [s for s in g.get("sources", []) if s in SOURCES][:2] or ["hn_comments"]
    g["recency_days"] = int(min(365, max(14, int(g.get("recency_days", 120)))))
    g["mutation_rate"] = float(min(0.6, max(0.05, float(g.get("mutation_rate", 0.25)))))
    return g


def random_genome(rng: random.Random, vocab: dict[str, float], gid: str) -> dict:
    return clamp({
        "id": gid,
        "phrases": rng.sample(PHRASES, 2),
        "terms": sample_terms(rng, vocab, 2),
        "sources": rng.sample(SOURCES, 2),
        "recency_days": rng.choice((30, 60, 120, 240, 365)),
        "mutation_rate": rng.uniform(0.15, 0.4),
    })


def sample_terms(rng: random.Random, vocab: dict[str, float], k: int) -> list[str]:
    items = list(vocab.items())
    out: list[str] = []
    for _ in range(k * 6):
        if len(out) >= k or not items:
            break
        total = sum(max(w, 0.01) for _, w in items)
        r = rng.uniform(0, total)
        acc = 0.0
        for term, w in items:
            acc += max(w, 0.01)
            if acc >= r:
                if term not in out:
                    out.append(term)
                break
    return out or [rng.choice(SEED_TERMS)]


def mutate(parent: dict, rng: random.Random, vocab: dict[str, float], gid: str) -> dict:
    g = clamp(parent)
    # log-normal self-adaptation of the genome's own mutation rate
    rate = g["mutation_rate"] * math.exp(rng.gauss(0, 0.3))
    g["mutation_rate"] = rate
    g = clamp(g)
    rate = g["mutation_rate"]
    if rng.random() < rate:
        g["phrases"][rng.randrange(len(g["phrases"]))] = rng.choice(PHRASES)
    if rng.random() < rate * 1.5:
        g["terms"][rng.randrange(len(g["terms"]))] = sample_terms(rng, vocab, 1)[0]
    if rng.random() < rate:
        g["sources"][rng.randrange(len(g["sources"]))] = rng.choice(SOURCES)
    if rng.random() < rate:
        g["recency_days"] = int(g["recency_days"] * math.exp(rng.gauss(0, 0.5)))
    g["id"] = gid
    g["parent"] = parent.get("id")
    return clamp(g)


def crossover(a: dict, b: dict, rng: random.Random, gid: str) -> dict:
    return clamp({
        "id": gid, "parent": f"{a.get('id')}x{b.get('id')}",
        "phrases": [rng.choice(a["phrases"]), rng.choice(b["phrases"])],
        "terms": [rng.choice(a["terms"]), rng.choice(b["terms"])],
        "sources": [rng.choice(a["sources"]), rng.choice(b["sources"])],
        "recency_days": rng.choice((a["recency_days"], b["recency_days"])),
        "mutation_rate": (a["mutation_rate"] + b["mutation_rate"]) / 2,
    })


def build_queries(g: dict) -> list[dict]:
    out = []
    for i in range(QUERIES_PER_GENOME):
        out.append({
            "phrase": g["phrases"][i % len(g["phrases"])],
            "term": g["terms"][(i // len(g["phrases"])) % len(g["terms"])],
            "source": g["sources"][i % len(g["sources"])],
        })
    return out


# ---------------------------------------------------------------- fetching
def http_json(url: str, timeout: float = 20.0) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json",
                                               "Accept-Encoding": "identity"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def fetch(q: dict, recency_days: int, getter=http_json) -> list[dict]:
    # Broad retrieval, strict filtering: the need sentence check does precision.
    text = f"{q['term']} {q['phrase']}"
    since = int(time.time()) - recency_days * 86400
    src = q["source"]
    if src.startswith("hn_"):
        tags = "comment" if src == "hn_comments" else "story"
        url = ("https://hn.algolia.com/api/v1/search_by_date?" + urllib.parse.urlencode({
            "query": text, "tags": tags, "hitsPerPage": HITS_PER_QUERY,
            "numericFilters": f"created_at_i>{since}"}))
        data = getter(url)
        rows = []
        for hit in data.get("hits") or []:
            body = clean(hit.get("comment_text") or hit.get("story_text") or "")
            title = clean(hit.get("title") or hit.get("story_title") or "")
            thread = str(hit.get("story_id") or hit.get("objectID") or "")
            rows.append({
                "url": f"https://news.ycombinator.com/item?id={hit.get('objectID')}",
                "domain": "news.ycombinator.com", "title": title, "excerpt": body[:1500],
                "date": hit.get("created_at"), "person": "hn:" + h(str(hit.get("author") or thread)),
                "thread": "hn:" + thread, "signal_types": [],
            })
        return rows
    site = SE_SITES[src]
    url = ("https://api.stackexchange.com/2.3/search/advanced?" + urllib.parse.urlencode({
        "q": q["term"], "site": site, "sort": "creation", "order": "desc", "pagesize": min(HITS_PER_QUERY, 30),
        "fromdate": since, "filter": "withbody"}))
    data = getter(url)
    rows = []
    for item in data.get("items") or []:
        owner = item.get("owner") or {}
        rows.append({
            "url": str(item.get("link") or ""), "domain": f"{site}.stackexchange.com",
            "title": clean(item.get("title")), "excerpt": clean(item.get("body"))[:1500],
            "date": datetime.fromtimestamp(int(item.get("creation_date") or 0), timezone.utc).isoformat(),
            "person": "se:" + h(str(owner.get("user_id") or owner.get("display_name") or item.get("question_id"))),
            "thread": f"se:{site}:{item.get('question_id')}", "signal_types": [],
            "score": int(item.get("score") or 0), "views": int(item.get("view_count") or 0),
        })
    return rows


# ---------------------------------------------------------------- scoring
def words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z][a-z\-]{4,13}", text.lower()) if w not in STOPWORDS]


SENT_SPLIT = re.compile(r"(?<=[.!?\n])\s+")


def term_re(term: str) -> re.Pattern:
    parts = [re.escape(p) for p in str(term).lower().split()]
    stem = r"\s+".join(parts)
    return re.compile(r"\b" + stem + r"(s|es)?\b", re.I)


def need_sentence(row: dict, q: dict) -> str:
    """The sentence where a person expresses a need ABOUT the genome's term.

    v2 (2026-10-12): v1 accepted any hit the source returned; HN Algolia does
    not require every word, so 'crm' hits were mostly unrelated chatter and
    fitness rewarded volume. Now the pain/question signal and the term must sit
    in the same sentence, and the hit must also pass market_inference demand.
    """
    if mi.classify_row(row) != "demand":
        return ""
    text = (row.get("title", "") + ". " + row.get("excerpt", ""))
    tre = term_re(q["term"])
    phrase = q["phrase"].lower()
    for sent in SENT_SPLIT.split(text):
        if len(sent) > 400 or not tre.search(sent):
            continue
        low = sent.lower()
        if phrase in low or mi.VOICE_RE.search(sent) or mi.QUESTION_RE.search(sent) or mi.PAY_RE.search(sent):
            return sent.strip()
    return ""


def evaluate(g: dict, hits_by_query: list[tuple[dict, list[dict]]], archive: set[str]) -> dict:
    total = 0
    demand = []
    for q, hits in hits_by_query:
        for row in hits:
            total += 1
            sent = need_sentence(row, q)
            if sent:
                demand.append((q, dict(row, need=sent)))
    people = {row["person"] for _, row in demand}
    novel = {p for p in people if p not in archive}
    money = {row["person"] for _, row in demand if mi.PAY_RE.search(row["need"])}
    by_term: dict[str, set[str]] = defaultdict(set)
    for q, row in demand:
        by_term[q["term"]].add(row["person"])
    markets = sorted(t for t, p in by_term.items() if len(p) >= 3)
    precision = len(demand) / total if total else 0.0
    # capped per genome so farming one loose query cannot dominate
    fitness = (10 * min(len(novel), 12) + 2 * min(len(people) - len(novel), 10) + 15 * len(money)
               + 20 * len(markets) + 60 * precision)
    return {
        "fitness": round(fitness, 3), "hits": total, "demand_hits": len(demand),
        "people": len(people), "novel_people": len(novel), "money_people": len(money),
        "markets": markets, "precision": round(precision, 4),
        "_demand": demand, "_novel": novel,
    }


def learn_vocab(vocab: dict[str, float], demand: list[tuple[dict, dict]], used_terms: set[str]) -> dict[str, float]:
    """Reinforce words that recur in the NEED sentences of different people; decay the rest."""
    new = {t: w * 0.97 for t, w in vocab.items()}
    for t in used_terms:
        new[t] = new.get(t, 0.5)
    people_by_word: dict[str, set[str]] = defaultdict(set)
    for q, row in demand:
        for w in set(words(row.get("need", ""))):
            if w not in q["phrase"] and w not in q["term"]:
                people_by_word[w].add(row["person"])
    for w, ppl in people_by_word.items():
        if len(ppl) >= 2:
            new[w] = new.get(w, 0.3) + 0.25 * len(ppl)
    for t in SEED_TERMS:
        new.setdefault(t, 0.2)
    ranked = sorted(new.items(), key=lambda kv: kv[1], reverse=True)[:VOCAB_CAP]
    return {t: round(w, 4) for t, w in ranked}


# ---------------------------------------------------------------- generation
def run_generation(state: dict, getter=http_json, seed: int | None = None) -> tuple[dict, dict, list[dict]]:
    gen = int(state.get("generation") or 0) + 1
    rng = random.Random(seed if seed is not None else int(time.time()) ^ gen)
    vocab = dict(state.get("vocabulary") or {t: 1.0 for t in SEED_TERMS})
    archive = set(state.get("archive") or [])
    pop = [clamp(g) for g in state.get("population") or []] or [
        random_genome(rng, vocab, f"g{gen}-r{i}") for i in range(POPULATION)]

    se_used = 0
    errors = Counter()
    results = []
    for g in pop:
        pairs = []
        for q in build_queries(g):
            if q["source"].startswith("se_"):
                if se_used >= SE_QUERY_CAP:
                    q = dict(q, source="hn_comments")
                else:
                    se_used += 1
            try:
                pairs.append((q, fetch(q, g["recency_days"], getter)))
            except Exception as exc:
                errors[q["source"] + ":" + type(exc).__name__] += 1
                pairs.append((q, []))
            time.sleep(0.2 if getter is http_json else 0)
        results.append((g, evaluate(g, pairs, archive)))

    results.sort(key=lambda x: x[1]["fitness"], reverse=True)
    all_demand = [d for _, r in results for d in r["_demand"]]
    vocab = learn_vocab(vocab, all_demand, {t for g, _ in results for t in g["terms"]})
    new_people = set().union(*(r["_novel"] for _, r in results)) if results else set()
    archive_list = (list(state.get("archive") or []) + sorted(new_people - archive))[-ARCHIVE_CAP:]

    history = list(state.get("history") or [])
    best = results[0][1] if results else {"fitness": 0}
    stagnant = (len(history) >= STAGNATION_WINDOW and
                all(x["novel_people"] == 0 for x in history[-STAGNATION_WINDOW:]))
    immigrants = 3 if stagnant else 1

    nxt = [dict(g, id=g["id"]) for g, _ in results[:ELITES]]
    def tourney() -> dict:
        a, b = rng.sample(results, 2) if len(results) > 1 else (results[0], results[0])
        return (a if a[1]["fitness"] >= b[1]["fitness"] else b)[0]
    i = 0
    while len(nxt) < POPULATION - immigrants:
        child = crossover(tourney(), tourney(), rng, f"g{gen}-c{i}") if rng.random() < 0.4 else tourney()
        nxt.append(mutate(child, rng, vocab, f"g{gen}-m{i}"))
        i += 1
    while len(nxt) < POPULATION:
        nxt.append(random_genome(rng, vocab, f"g{gen}-r{len(nxt)}"))

    market_people: dict[str, set[str]] = defaultdict(set)
    for q, row in all_demand:
        market_people[q["term"]].add(row["person"])
    cumulative = dict(state.get("market_totals") or {})
    for term, ppl in market_people.items():
        cumulative[term] = int(cumulative.get(term, 0)) + len(ppl - archive)
    summary = {
        "generation": gen, "at_utc": now_utc().isoformat(),
        "best_fitness": best["fitness"], "best_genome": results[0][0]["id"] if results else None,
        "mean_fitness": round(sum(r["fitness"] for _, r in results) / max(1, len(results)), 3),
        "hits": sum(r["hits"] for _, r in results),
        "demand_hits": sum(r["demand_hits"] for _, r in results),
        "novel_people": len(new_people), "archive_size": len(archive_list),
        "money_people": sum(r["money_people"] for _, r in results),
        "markets_this_gen": sorted({m for _, r in results for m in r["markets"]}),
        "mean_mutation_rate": round(sum(g["mutation_rate"] for g in nxt) / len(nxt), 4),
        "vocab_size": len(vocab), "learned_terms": sum(1 for t in vocab if t not in SEED_TERMS),
        "stagnant": stagnant, "se_queries": se_used, "errors": dict(errors),
    }
    history.append(summary)
    champion = state.get("champion") or {}
    if results and best["fitness"] > float(champion.get("fitness") or 0):
        champion = {"genome": results[0][0], "fitness": best["fitness"], "generation": gen}
    new_state = {
        "arena_id": ARENA_ID, "version": VERSION, "generation": gen, "population": nxt,
        "vocabulary": vocab, "archive": archive_list, "history": history[-2000:],
        "champion": champion, "market_totals": dict(sorted(cumulative.items(), key=lambda kv: -kv[1])[:200]),
        "boundary": BOUNDARY,
    }
    discoveries = [{
        "generation": gen, "term": q["term"], "phrase": q["phrase"], "source": q["source"],
        "url": row["url"], "title": row["title"][:200], "need": row["need"][:400], "excerpt": row["excerpt"][:600],
        "date": row.get("date"), "person": row["person"],
        "money": bool(mi.PAY_RE.search(row["need"])),
    } for q, row in all_demand if row["person"] in new_people]
    return new_state, summary, discoveries


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--private-dir", required=True)
    args = ap.parse_args()
    base = Path(args.private_dir) / ARENA_ID
    base.mkdir(parents=True, exist_ok=True)
    state_path = base / "state.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    new_state, summary, discoveries = run_generation(state)
    state_path.write_text(json.dumps(new_state, ensure_ascii=False, indent=1))
    with (base / "discoveries.jsonl").open("a") as fh:
        for d in discoveries:
            fh.write(json.dumps(d, ensure_ascii=False) + "\n")
    with (base / "history.jsonl").open("a") as fh:
        fh.write(json.dumps(summary) + "\n")
    top_markets = list(new_state["market_totals"].items())[:5]
    public = {k: summary[k] for k in ("generation", "best_fitness", "mean_fitness", "hits", "demand_hits",
                                      "novel_people", "archive_size", "money_people", "mean_mutation_rate",
                                      "vocab_size", "learned_terms", "stagnant")}
    public["errors"] = sum(summary["errors"].values())
    public["markets_with_3plus_people"] = len(summary["markets_this_gen"])
    print("::notice title=Market Intuition gen " + str(summary["generation"]) + "::" +
          json.dumps(public, separators=(",", ":")))
    print("::notice title=Market Intuition top problem terms::" +
          ", ".join(f"{t} ({n})" for t, n in top_markets))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
