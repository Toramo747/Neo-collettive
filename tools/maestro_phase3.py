# SPDX-License-Identifier: BUSL-1.1
"""Maestro phase 3: matched negatives, light teacher, time-split evaluation.

1. Positives: the three-year strict pools (private archive).
2. Negatives from the same sources and years:
   - HN: random comments (time-sliced) and Show HN replies that do not
     match any demand pattern;
   - GitHub: bug/question issues with >= 5 reactions, same monthly windows;
   - Stack Exchange: superuser questions (how-to, not tool requests).
3. Leakage control: the trigger phrases used to SELECT positives and the
   issue-template words are masked in both classes, so the teacher cannot
   just relearn the selection rules.
4. Teacher: TF-IDF (word 1-2 grams) + logistic regression, trained on items
   created before the split date, tested on the last 12 months.
5. Baseline on the same test set: the production lexicon primitives
   (demand_signal_type PAIN/BUY_INTENT/PAID_DEMAND, as in the arena scorer).
6. Unlabelled NEO observations (train.jsonl): only the share the teacher
   flags, compared with the lexicon judge.  hidden.jsonl is never opened.
Outputs: dataset + metrics in the private archive; aggregate notices only.
"""
from __future__ import annotations

import json
import os
import random
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import maestro_label_census as census  # noqa: E402
from maestro_label_sample import strip_html  # noqa: E402
from maestro_label_sample_v2 import PAY_RE, SEEK_RE  # noqa: E402
from maestro_label_sample_v3 import VALID_RE  # noqa: E402
from maestro_label_pool_v4 import month_windows  # noqa: E402

SEED = 20261015
HN_SHOW_NEGATIVES = [0]
SPLIT_DAYS = 365
TEMPLATE_RE = re.compile(
    r"#+\s*|\b(feature request|feature|enhancement|bug report|bug|describe the (feature|bug|solution)|"
    r"problem statement|to reproduce|expected behaviou?r|steps to reproduce|is your feature request related to a problem|"
    r"pre-submit checks|checklist|possible solution|alternatives you've considered|additional context|"
    r"use cases?|proposal|summary|describe|the solution you'd like|shut up and|looking for|show hn|ask hn)\b", re.I)


def mask(text: str) -> str:
    text = PAY_RE.sub(" ", text)
    text = SEEK_RE.sub(" ", text)
    text = VALID_RE.sub(" ", text)
    text = TEMPLATE_RE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def epoch(created) -> float:
    if isinstance(created, (int, float)):
        return float(created)
    try:
        return datetime.fromisoformat(str(created).replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


def any_demand(text: str) -> bool:
    return bool(PAY_RE.search(text) or SEEK_RE.search(text) or VALID_RE.search(text))


def hn_negatives(client, n_random: int, n_show: int, now: int, rng: random.Random) -> list[dict]:
    out, seen = [], set()
    lo = now - 3 * 365 * 86400
    attempts = 0
    while len(out) < n_random and attempts < n_random:
        attempts += 1
        start = rng.randint(lo, now - 3600)
        try:
            hits = client.get("https://hn.algolia.com/api/v1/search_by_date", headers=census.UA, params={
                "tags": "comment", "hitsPerPage": 20,
                "numericFilters": f"created_at_i>{start},created_at_i<={start + 3600}"}).json().get("hits") or []
        except Exception:
            continue
        for h in hits[:5]:
            text = strip_html(h.get("comment_text") or "")
            if len(text) < 40 or any_demand(text) or h.get("objectID") in seen:
                continue
            seen.add(h.get("objectID"))
            out.append({"source": "hn", "text": text[:1500], "title": h.get("story_title") or "", "created": h.get("created_at_i")})
    show = []
    for page in range(20):
        if len(show) >= n_show:
            break
        try:
            data = client.get("https://hn.algolia.com/api/v1/search", headers=census.UA, params={
                "query": "", "tags": "comment", "hitsPerPage": 50, "page": page,
                "numericFilters": f"created_at_i>{lo}", "restrictSearchableAttributes": "story_title"}).json()
        except Exception:
            break
        for h in data.get("hits") or []:
            title = h.get("story_title") or ""
            text = strip_html(h.get("comment_text") or "")
            if not title.lower().startswith("show hn") or any_demand(text) or len(text) < 40:
                continue
            show.append({"source": "hn", "text": text[:1500], "title": title, "created": h.get("created_at_i")})
    HN_SHOW_NEGATIVES[0] = len(show[:n_show])
    return out + show[:n_show]


def gh_negatives(client, headers, per_month: int) -> list[dict]:
    out, seen = [], set()
    for start, end in month_windows(datetime.now(timezone.utc)):
        q = f'is:issue label:bug,question reactions:>=5 created:{start}..{end}'
        try:
            r = client.get("https://api.github.com/search/issues", headers=headers,
                           params={"q": q, "per_page": per_month, "sort": "reactions"})
            if r.status_code in (403, 429):
                time.sleep(30)
                r = client.get("https://api.github.com/search/issues", headers=headers,
                               params={"q": q, "per_page": per_month, "sort": "reactions"})
            time.sleep(2.2)
            for it in r.json().get("items") or []:
                if it.get("html_url") in seen:
                    continue
                seen.add(it.get("html_url"))
                out.append({"source": "gh", "title": it.get("title") or "",
                            "text": strip_html(it.get("body") or "")[:1500], "created": it.get("created_at")})
        except Exception:
            pass
    return out


def se_negatives(client, since: int, pages: int) -> list[dict]:
    out = []
    for page in range(1, pages + 1):
        try:
            data = client.get("https://api.stackexchange.com/2.3/questions", headers=census.UA, params={
                "site": "superuser", "fromdate": since, "pagesize": 100, "page": page,
                "order": "desc", "sort": "votes", "filter": "withbody"}).json()
        except Exception:
            break
        for q in data.get("items") or []:
            title = strip_html(q.get("title") or "")
            text = strip_html(q.get("body") or "")
            if any_demand(title + " " + text):
                continue
            out.append({"source": "se", "title": title, "text": text[:1500], "created": q.get("creation_date")})
        if not data.get("has_more"):
            break
        if data.get("backoff"):
            time.sleep(int(data["backoff"]) + 1)
    return out


def load_positives(path: Path) -> list[dict]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        src = "hn" if r["type"].startswith("hn_") else ("gh" if r["type"].startswith("gh_") else "se")
        out.append({"source": src, "type": r["type"], "title": r.get("title") or "", "text": r.get("text") or "",
                    "created": r.get("created")})
    return out


def lexicon_positive(title: str, text: str) -> bool:
    from evidence_integrity import demand_signal_type
    tags = demand_signal_type(title, text, query_role="buyer", strong_pain_only=False, seller_launch_guard=True,
                              url="", source="maestro", vendor_content_guard=True, web_buyer_voice_guard=True,
                              supply_offer_guard=True, query_echo_guard=False, query="")
    return any(t in {"PAIN", "BUY_INTENT", "PAID_DEMAND"} for t in tags)


def prf(y, p):
    tp = sum(1 for a, b in zip(y, p) if a and b)
    fp = sum(1 for a, b in zip(y, p) if not a and b)
    fn = sum(1 for a, b in zip(y, p) if a and not b)
    prec = tp / max(1, tp + fp)
    rec = tp / max(1, tp + fn)
    return round(prec, 3), round(rec, 3), round(2 * prec * rec / max(1e-9, prec + rec), 3)


def main(argv):
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score

    archive = Path(argv[1])
    pool = sorted((archive / "maestro").glob("maestro-pool-v4-*.jsonl"))[-1]
    rng = random.Random(SEED)
    now = int(time.time())
    positives = load_positives(pool)
    by_src = {s: sum(1 for p in positives if p["source"] == s) for s in ("hn", "gh", "se")}
    gh = {"Accept": "application/vnd.github+json", **census.UA}
    if os.getenv("GITHUB_TOKEN"):
        gh["Authorization"] = "Bearer " + os.environ["GITHUB_TOKEN"]
    with httpx.Client(timeout=40) as client:
        neg = (hn_negatives(client, by_src["hn"], min(400, by_src["hn"] // 3), now, rng)
               + gh_negatives(client, gh, 100)
               + se_negatives(client, now - 3 * 365 * 86400, 15))
    # Balance per source so the source itself is not a label.
    data = []
    for src in ("hn", "gh", "se"):
        pos = [p for p in positives if p["source"] == src]
        ng = [n for n in neg if n["source"] == src]
        k = min(len(pos), len(ng))
        rng.shuffle(pos)
        rng.shuffle(ng)
        data += [dict(p, y=1) for p in pos[:k]] + [dict(n, y=0) for n in ng[:k]]
    split = now - SPLIT_DAYS * 86400
    for d in data:
        # HN story titles (e.g. "Show HN") describe the thread, not the comment: excluded.
        d["masked"] = mask(d["text"] if d["source"] == "hn" else (d["title"] + " " + d["text"]))
        d["test"] = epoch(d["created"]) >= split
    train = [d for d in data if not d["test"]]
    test = [d for d in data if d["test"]]
    vec = TfidfVectorizer(ngram_range=(1, 2), min_df=3, max_features=50000, sublinear_tf=True)
    xtr = vec.fit_transform([d["masked"] for d in train])
    clf = LogisticRegression(max_iter=2000, C=2.0, class_weight="balanced")
    clf.fit(xtr, [d["y"] for d in train])
    scores = clf.predict_proba(vec.transform([d["masked"] for d in test]))[:, 1]
    y = [d["y"] for d in test]
    pred = [s >= 0.5 for s in scores]
    lex = [lexicon_positive(d["title"], d["text"]) for d in test]
    metrics = {
        "train": len(train), "test": len(test),
        "train_pos": sum(d["y"] for d in train), "test_pos": sum(y),
        "teacher_auc": round(roc_auc_score(y, scores), 3) if len(set(y)) > 1 else None,
        "teacher_prf": prf(y, pred), "lexicon_prf": prf(y, lex),
        "per_source": {},
    }
    for src in ("hn", "gh", "se"):
        idx = [i for i, d in enumerate(test) if d["source"] == src]
        ys = [y[i] for i in idx]
        if len(set(ys)) > 1:
            metrics["per_source"][src] = {
                "n": len(idx), "auc": round(roc_auc_score(ys, [scores[i] for i in idx]), 3),
                "teacher_prf": prf(ys, [pred[i] for i in idx]), "lexicon_prf": prf(ys, [lex[i] for i in idx])}
    # Unlabelled NEO observations: share flagged by teacher vs lexicon judge.
    neo = []
    tpath = archive / "train.jsonl"
    if tpath.exists():
        for line in tpath.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                neo.append(mask(str(r.get("title") or "") + " " + str(r.get("normalized_text") or "")))
    if neo:
        s = clf.predict_proba(vec.transform(neo))[:, 1]
        metrics["neo_observations"] = {"n": len(neo), "teacher_flagged": int(sum(1 for v in s if v >= 0.5)),
                                       "teacher_mean": round(float(s.mean()), 3)}
    # Calibration: 100 NEO observations labelled by Claude (label_origin=claude).
    cal_path = archive / "maestro" / "maestro_calibration_claude.jsonl"
    if cal_path.exists() and tpath.exists():
        by_id = {}
        for line in tpath.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                by_id[r.get("id")] = r
        cal = [json.loads(l) for l in cal_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        cal = [(c, by_id[c["id"]]) for c in cal if c.get("id") in by_id]
        texts = [mask(str(r.get("title") or "") + " " + str(r.get("normalized_text") or "")) for _, r in cal]
        cs = clf.predict_proba(vec.transform(texts))[:, 1]
        yb = [c["final_label"] == "buyer_tool_search" for c, _ in cal]
        lexb = [lexicon_positive(str(r.get("title") or ""), str(r.get("normalized_text") or "")) for _, r in cal]
        per_label = {}
        for (c, _), v in zip(cal, cs):
            d = per_label.setdefault(c["final_label"], [0, 0])
            d[0] += 1
            d[1] += int(v >= 0.5)
        # Best threshold for the teacher on this set, reported separately (not used for the 0.5 figures).
        metrics["calibration_claude"] = {
            "n": len(cal), "buyer_tool_search": sum(yb),
            "teacher_auc": round(roc_auc_score(yb, cs), 3) if len(set(yb)) > 1 else None,
            "teacher_prf_at_0.5": prf(yb, [v >= 0.5 for v in cs]),
            "teacher_prf_at_0.8": prf(yb, [v >= 0.8 for v in cs]),
            "lexicon_prf": prf(yb, lexb),
            "flagged_by_label": {k: f"{v[1]}/{v[0]}" for k, v in per_label.items()},
        }
    out = archive / "maestro"
    stamp = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
    (out / f"maestro-phase3-metrics-{stamp}.json").write_text(json.dumps(metrics, indent=1), encoding="utf-8")
    with (out / f"maestro-phase3-dataset-{stamp}.jsonl").open("w", encoding="utf-8") as fh:
        for d in data:
            fh.write(json.dumps({k: d[k] for k in ("source", "title", "text", "created", "y", "test")}, ensure_ascii=False) + "\n")
    terms = vec.get_feature_names_out()
    coef = clf.coef_[0]
    top = [terms[i] for i in coef.argsort()[-25:][::-1]]
    (out / f"maestro-phase3-top-terms-{stamp}.json").write_text(json.dumps({"positive": top,
        "negative": [terms[i] for i in coef.argsort()[:25]]}, indent=1), encoding="utf-8")
    print("::notice title=maestro phase3 overall::" + json.dumps({k: metrics[k] for k in
          ("train", "test", "train_pos", "test_pos", "teacher_auc", "teacher_prf", "lexicon_prf")}))
    print("::notice title=maestro phase3 per source::" + json.dumps(metrics["per_source"]))
    print("::notice title=maestro phase3 calibration (claude labels)::" + json.dumps(metrics.get("calibration_claude")))
    print("::notice title=maestro phase3 neo observations::" + json.dumps(metrics.get("neo_observations")) + f" negatives_collected={len(neg)} show_hn_negatives={HN_SHOW_NEGATIVES[0]} top_pos={top[:12]} stamp={stamp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
