# SPDX-License-Identifier: BUSL-1.1
"""Maestro v2 evaluation (preregistered in docs/maestro-v2.md). Private data in,
aggregate metrics out. hidden.jsonl is never opened."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from maestro_teacher import mask  # noqa: E402

SEED = 20261015
EMBED_MODEL = "BAAI/bge-small-en-v1.5"


def load(archive: Path):
    ds = sorted((archive / "maestro").glob("maestro-phase3-dataset-*.jsonl"))[-1]
    web = [json.loads(l) for l in ds.read_text(encoding="utf-8").splitlines() if l.strip()]
    for d in web:
        d["masked"] = mask(d["text"] if d["source"] == "hn" else (d["title"] + " " + d["text"]))
    by_id = {}
    for l in (archive / "train.jsonl").read_text(encoding="utf-8").splitlines():
        if l.strip():
            r = json.loads(l)
            by_id[r.get("id")] = r

    def neo(path):
        out = []
        for l in path.read_text(encoding="utf-8").splitlines():
            if l.strip():
                c = json.loads(l)
                r = by_id.get(c.get("id"))
                if r is not None:
                    out.append((mask(str(r.get("title") or "") + " " + str(r.get("normalized_text") or "")),
                                int(c["final_label"] == "buyer_tool_search"), c["id"]))
        return out
    cal = neo(archive / "maestro" / "maestro_calibration_claude.jsonl")
    cal_ids = {c[2] for c in cal}
    dom = [d for d in neo(archive / "maestro" / "maestro_train_claude.jsonl") if d[2] not in cal_ids]
    return web, dom, cal, ds.name


class Embedder:
    def __init__(self):
        from sentence_transformers import SentenceTransformer
        self.m = SentenceTransformer(EMBED_MODEL, device="cpu")
        self.cache = {}

    def __call__(self, texts):
        todo = [t for t in dict.fromkeys(texts) if t not in self.cache]
        if todo:
            vecs = self.m.encode([t[:2000] for t in todo], batch_size=64, normalize_embeddings=True, show_progress_bar=False)
            self.cache.update(zip(todo, vecs))
        return np.vstack([self.cache[t] for t in texts])


def fit_predict(arm, emb, tr_x, tr_y, tr_w, te_x):
    from scipy.sparse import csr_matrix, hstack
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    clf = LogisticRegression(max_iter=3000, C=2.0, class_weight="balanced")
    if arm == "V1":
        v = TfidfVectorizer(ngram_range=(1, 2), min_df=3, max_features=60000, sublinear_tf=True)
        clf.fit(v.fit_transform(tr_x), tr_y, sample_weight=tr_w)
        return clf.predict_proba(v.transform(te_x))[:, 1]
    if arm == "V2":
        clf.fit(emb(tr_x), tr_y, sample_weight=tr_w)
        return clf.predict_proba(emb(te_x))[:, 1]
    v = TfidfVectorizer(ngram_range=(1, 2), min_df=3, max_features=60000, sublinear_tf=True)
    xtr = hstack([v.fit_transform(tr_x), csr_matrix(emb(tr_x))]).tocsr()
    clf.fit(xtr, tr_y, sample_weight=tr_w)
    return clf.predict_proba(hstack([v.transform(te_x), csr_matrix(emb(te_x))]).tocsr())[:, 1]


def main(archive_dir: str) -> int:
    from sklearn.metrics import roc_auc_score
    from sklearn.model_selection import StratifiedKFold
    archive = Path(archive_dir)
    web, dom, cal, dsname = load(archive)
    emb = Embedder()
    arms = ("V1", "V2", "V2H")
    res = {a: {} for a in arms}
    wtr = [d for d in web if not d["test"]]
    wte = [d for d in web if d["test"]]
    dx, dy = [t for t, _, _ in dom], [y for _, y, _ in dom]
    for a in arms:  # 1. web time split
        s = fit_predict(a, emb, [d["masked"] for d in wtr] + dx, [d["y"] for d in wtr] + dy,
                        [1.0] * len(wtr) + [5.0] * len(dx), [d["masked"] for d in wte])
        res[a]["web_time_split_auc"] = round(float(roc_auc_score([d["y"] for d in wte], s)), 4)
    folds = list(StratifiedKFold(n_splits=5, shuffle=True, random_state=SEED).split(dx, dy))
    for a in arms:  # 2. in-domain CV
        oof = np.zeros(len(dx))
        for tr_i, te_i in folds:
            s = fit_predict(a, emb, [d["masked"] for d in web] + [dx[i] for i in tr_i],
                            [d["y"] for d in web] + [dy[i] for i in tr_i],
                            [1.0] * len(web) + [5.0] * len(tr_i), [dx[i] for i in te_i])
            oof[te_i] = s
        res[a]["in_domain_cv_auc"] = round(float(roc_auc_score(dy, oof)), 4)
    cx, cy = [t for t, _, _ in cal], [y for _, y, _ in cal]
    for a in arms:  # 3. calibration
        s = fit_predict(a, emb, [d["masked"] for d in web] + dx, [d["y"] for d in web] + dy,
                        [1.0] * len(web) + [5.0] * len(dx), cx)
        res[a]["calibration_auc"] = round(float(roc_auc_score(cy, s)), 4)
    v1, v2 = res["V1"], res["V2"]
    adopt = bool(v2["web_time_split_auc"] >= v1["web_time_split_auc"] + 0.02
                 and v2["in_domain_cv_auc"] >= v1["in_domain_cv_auc"] + 0.02
                 and v2["calibration_auc"] >= v1["calibration_auc"] - 0.03)
    report = {"dataset": dsname, "web_train": len(wtr), "web_test": len(wte), "in_domain": len(dx),
              "in_domain_pos": sum(dy), "calibration": len(cx), "calibration_pos": sum(cy),
              "embed_model": EMBED_MODEL, "arms": res, "adopt_v2": adopt}
    out = archive / "maestro" / "maestro-v2-evaluation.json"
    out.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    if adopt:
        import joblib
        from sklearn.linear_model import LogisticRegression
        x = [d["masked"] for d in web] + dx + cx
        y = [d["y"] for d in web] + dy + cy
        w = [1.0] * len(web) + [5.0] * (len(dx) + len(cx))
        clf = LogisticRegression(max_iter=3000, C=2.0, class_weight="balanced").fit(emb(x), y, sample_weight=w)
        joblib.dump({"kind": "embedding_lr", "embed_model": EMBED_MODEL, "clf": clf}, archive / "maestro" / "teacher-v2.joblib")
    print("::notice title=maestro v2 evaluation::" + json.dumps({k: report[k] for k in report if k != "dataset"}, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
