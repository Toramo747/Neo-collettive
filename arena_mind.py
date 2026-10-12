# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Andrea Gava
"""The 'mind' of the Market Intuition Arena: a local LLM that thinks.

Requested by Andrea on 2026-10-12: give the evolutionary search a spark of
autonomy by letting it use local LLMs (Ollama, zero cost) to form its own
thoughts. Each generation the mind:

  judge   reads the candidate need sentences and decides whether a real person
          needs something, names the problem and says whether they hint at paying;
  think   looks at the judged needs, its market map (problems with how many
          different people have them), its diary and how its previous ideas
          performed, then writes an observation, a hypothesis, which problem
          each need belongs to, new search terms/phrases to try and terms to drop.

Boundaries: the model only returns short JSON strings that are sanitized and
bounded. It cannot run code, change the fitness rules, reach production or
publish anything. Everything it writes stays in the private archive.
"""
from __future__ import annotations

import json
import re
import urllib.request
from typing import Any, Callable

from local_llm_decoding import RETRY_OPTIONS, RETRY_SUFFIX, ROBUST_OPTIONS, bounded_schema

OLLAMA = "http://127.0.0.1:11434"
JUDGE_BATCH = 6
MAX_JUDGED = 24
WORD_RE = re.compile(r"^[a-z][a-z0-9 \-']{1,60}$")

JUDGE_SCHEMA = bounded_schema({
    "type": "object",
    "properties": {"verdicts": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "i": {"type": "integer"},
            "real_need": {"type": "boolean"},
            "problem": {"type": "string", "maxLength": 80},
            "would_pay": {"type": "string", "enum": ["yes", "no", "unknown"]},
        },
        "required": ["i", "real_need", "problem", "would_pay"]}}},
    "required": ["verdicts"],
}, 120)

THINK_SCHEMA = bounded_schema({
    "type": "object",
    "properties": {
        "observation": {"type": "string", "maxLength": 300},
        "hypothesis": {"type": "string", "maxLength": 300},
        "assign": {"type": "array", "items": {"type": "object", "properties": {
            "i": {"type": "integer"}, "problem": {"type": "string", "maxLength": 80}},
            "required": ["i", "problem"]}},
        "next_terms": {"type": "array", "items": {"type": "string", "maxLength": 40}},
        "next_phrases": {"type": "array", "items": {"type": "string", "maxLength": 60}},
        "abandon_terms": {"type": "array", "items": {"type": "string", "maxLength": 40}},
    },
    "required": ["observation", "hypothesis", "assign", "next_terms", "next_phrases", "abandon_terms"],
}, 300)


def ollama_generate(model: str, prompt: str, schema: dict, timeout: float = 240) -> dict | None:
    for options, suffix in ((ROBUST_OPTIONS, ""), (RETRY_OPTIONS, RETRY_SUFFIX)):
        body = json.dumps({"model": model, "prompt": prompt + suffix, "stream": False,
                           "format": schema, "options": dict(options, num_predict=700),
                           "keep_alive": "30m"}).encode()
        req = urllib.request.Request(OLLAMA + "/api/generate", data=body,
                                     headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                text = json.loads(r.read().decode()).get("response") or ""
            return json.loads(text)
        except Exception:
            continue
    return None


def available(model: str) -> bool:
    try:
        with urllib.request.urlopen(OLLAMA + "/api/tags", timeout=5) as r:
            tags = json.loads(r.read().decode())
        return any(str(m.get("name", "")).startswith(model.split(":")[0]) for m in tags.get("models") or [])
    except Exception:
        return False


def clean_label(value: Any, max_words: int = 6) -> str:
    text = re.sub(r"[^a-z0-9 \-']", " ", str(value or "").lower())
    text = " ".join(text.split()[:max_words])
    return text if WORD_RE.match(text or "") and "http" not in text else ""


def judge(model: str, needs: list[str], gen: Callable = ollama_generate) -> list[dict]:
    """One verdict per need: {real_need, problem, would_pay}. Unknown => not real."""
    out = [{"real_need": False, "problem": "", "would_pay": "unknown", "judged": False} for _ in needs]
    for start in range(0, min(len(needs), MAX_JUDGED), JUDGE_BATCH):
        batch = needs[start:start + JUDGE_BATCH]
        listing = "\n".join(f"{i}: {s[:300]}" for i, s in enumerate(batch))
        prompt = (
            "You review sentences people wrote online. For each, decide if the WRITER has a real, "
            "concrete need for a tool, service or solution (not an opinion, joke, job ad, vendor "
            "pitch or abstract debate). Name the problem in at most 6 plain words, e.g. "
            "'reconcile invoices with bank exports'. would_pay is 'yes' only if they hint at paying "
            "or buying. Return JSON {\"verdicts\":[{\"i\":0,\"real_need\":true,\"problem\":\"...\","
            "\"would_pay\":\"unknown\"}]} with one entry per sentence.\n\n" + listing)
        res = gen(model, prompt, JUDGE_SCHEMA)
        for v in (res or {}).get("verdicts") or []:
            try:
                i = int(v.get("i"))
            except Exception:
                continue
            if 0 <= i < len(batch):
                out[start + i] = {
                    "real_need": bool(v.get("real_need")),
                    "problem": clean_label(v.get("problem")),
                    "would_pay": v.get("would_pay") if v.get("would_pay") in ("yes", "no", "unknown") else "unknown",
                    "judged": True,
                }
    return out


def think(model: str, *, needs: list[dict], market_map: dict, diary: list[str],
          idea_outcomes: list[dict], stats: dict, gen: Callable = ollama_generate) -> dict:
    top_problems = sorted(market_map.items(), key=lambda kv: -kv[1].get("people", 0))[:15]
    listing = "\n".join(f"{i}: [{n.get('problem') or '?'}] {n['need'][:220]}" for i, n in enumerate(needs[:20]))
    prompt = (
        "You are the research mind of an autonomous search for real software/service markets. "
        "You find people who describe a problem in their own words. A market is a problem shared by "
        "many DIFFERENT people, ideally with hints of paying.\n"
        f"Stats of this generation: {json.dumps(stats)}\n"
        "Your market map (problem: different people, paying hints): "
        + "; ".join(f"{k}: {v.get('people', 0)} people, {v.get('pay', 0)} pay" for k, v in top_problems) + "\n"
        "Your recent diary:\n" + "\n".join("- " + d for d in diary[-5:]) + "\n"
        "How your previous ideas performed (term: new people found): "
        + ", ".join(f"{o['term']}: {o['people']}" for o in idea_outcomes[-10:]) + "\n"
        "New needs found now:\n" + (listing or "(none)") + "\n\n"
        "Return JSON: observation (what you notice), hypothesis (which market might be real and why), "
        "assign (for each need index, the problem it belongs to: reuse an existing map name if it is "
        "the same problem, else a new name of at most 6 words), next_terms (up to 3 short problem "
        "nouns to search next, e.g. 'invoice matching'), next_phrases (up to 2 short first-person "
        "phrases people use when they need help, e.g. 'we still do this by hand'), abandon_terms "
        "(terms that keep producing nothing).")
    res = gen(model, prompt, THINK_SCHEMA) or {}
    return {
        "observation": str(res.get("observation") or "")[:300],
        "hypothesis": str(res.get("hypothesis") or "")[:300],
        "assign": [{"i": int(a.get("i")), "problem": clean_label(a.get("problem"))}
                   for a in res.get("assign") or []
                   if isinstance(a, dict) and str(a.get("i", "")).lstrip("-").isdigit() and clean_label(a.get("problem"))],
        "next_terms": [t for t in (clean_label(x, 3) for x in res.get("next_terms") or []) if t][:3],
        "next_phrases": [p for p in (clean_label(x, 7) for x in res.get("next_phrases") or []) if len(p.split()) >= 2][:2],
        "abandon_terms": [t for t in (clean_label(x, 3) for x in res.get("abandon_terms") or []) if t][:3],
        "ok": bool(res),
    }
