# SPDX-License-Identifier: BUSL-1.1
"""Train and evaluate the anomaly stance classifier (preregistered rule in
docs/anomaly-classifier.md). Reads abstracts and labels from the private
archive; prints aggregate metrics only; writes the model to the archive."""
from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import anomaly_classifier as ac  # noqa: E402
import arena_anomalies as aa  # noqa: E402


def baseline(text: str, query: str) -> str:
    t = aa.strip_query_echo(text, query)
    if aa.RESOLUTION_RE.search(t):
        return "resolves"
    if aa.TENSION_RE.search(aa.RESOLUTION_RE.sub(" ", t)):
        return "supports_tension"
    return "neutral"


def make_model():
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    return make_pipeline(TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True),
                         LogisticRegression(max_iter=2000, class_weight="balanced", C=2.0))


def persistence(labels: list[str]) -> float:
    n = len(labels)
    return (labels.count("supports_tension") - labels.count("resolves")) / n if n else 0.0


def main(private_dir: str) -> int:
    from scipy.stats import spearmanr
    from sklearn.metrics import f1_score
    from sklearn.model_selection import StratifiedKFold, cross_val_predict
    import joblib

    root = Path(private_dir) / "anomaly"
    abstracts = {}
    for line in (root / "abstracts.jsonl").open(encoding="utf-8"):
        r = json.loads(line)
        abstracts[r["id"]] = r
    rows = []
    for line in (root / "labels_claude.jsonl").open(encoding="utf-8"):
        lab = json.loads(line)
        a = abstracts.get(lab["id"])
        if a:
            rows.append({**a, "label": lab["label"]})
    X = [ac.mask(r["title"] + ". " + r["abstract"]) for r in rows]
    y = [r["label"] for r in rows]
    topics = [r["topic"] for r in rows]

    base = [baseline(r["title"] + ". " + r["abstract"], r["query"]) for r in rows]
    f1_base = f1_score(y, base, average="macro")

    # Leave-one-topic-out.
    loto = [None] * len(rows)
    for t in sorted(set(topics)):
        tr = [i for i, x in enumerate(topics) if x != t]
        te = [i for i, x in enumerate(topics) if x == t]
        m = make_model().fit([X[i] for i in tr], [y[i] for i in tr])
        for i, p in zip(te, m.predict([X[i] for i in te])):
            loto[i] = p
    f1_loto = f1_score(y, loto, average="macro")
    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=7)
    f1_cv = f1_score(y, cross_val_predict(make_model(), X, y, cv=skf), average="macro")

    by_true, by_pred, by_base = (collections.defaultdict(list) for _ in range(3))
    for t, yt, yp, yb in zip(topics, y, loto, base):
        by_true[t].append(yt); by_pred[t].append(yp); by_base[t].append(yb)
    tps = sorted(by_true)
    pt = [persistence(by_true[t]) for t in tps]
    pp = [persistence(by_pred[t]) for t in tps]
    pb = [persistence(by_base[t]) for t in tps]
    rho_model = spearmanr(pt, pp).correlation
    rho_base = spearmanr(pt, pb).correlation
    P = {t: persistence(by_pred[t]) for t in tps}
    control_ok = P["proton_radius_control"] < P["hubble_tension"] and P["proton_radius_control"] < P["evolving_dark_energy"]
    adopt = bool(f1_loto >= f1_base + 0.10 and control_ok)

    final = make_model().fit(X, y)
    joblib.dump(final, root / "classifier-v1.joblib")
    report = {"n": len(rows), "f1_baseline": round(f1_base, 3), "f1_leave_topic_out": round(f1_loto, 3),
              "f1_cv5": round(f1_cv, 3), "spearman_topics_model": round(float(rho_model), 3),
              "spearman_topics_baseline": round(float(rho_base), 3), "control_ok": control_ok, "adopt": adopt,
              "pred_persistence": {t: round(P[t], 2) for t in tps},
              "true_persistence": {t: round(v, 2) for t, v in zip(tps, pt)}}
    (root / "classifier-v1-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
