# SPDX-License-Identifier: BUSL-1.1
"""Maestro teacher: shared masking + optional shadow scoring.

The teacher (TF-IDF + logistic regression) is trained privately (see
docs/maestro.md) and stored only in the private archive.  This module lets an
arena *observe* what the teacher thinks of the hits it retrieved.  It never
changes fitness, ranking or selection: shadow only.  If no model is
available, every function is a no-op.
"""
from __future__ import annotations

import os
import re
from typing import Any

PAY_RE = re.compile(r"\b(i|we)\s*(would|'d|will|'ll)\s+(happily\s+|gladly\s+|definitely\s+)?pay\b|\btake my money\b", re.I)
SEEK_RE = re.compile(r"\b(is there|looking for|i wish there (was|were)|anyone know of|recommend)\s+(a|an|any)\s+(good\s+)?(tool|app|service|software|extension|library|saas|plugin)\b", re.I)
VALID_RE = re.compile(r"\b(looking for something like this|exactly what i (needed|was looking for)|been looking for (this|something like this)|needed this|looking for an app like this)\b", re.I)
TEMPLATE_RE = re.compile(
    r"#+\s*|\b(feature request|feature|enhancement|bug report|bug|describe the (feature|bug|solution)|"
    r"problem statement|to reproduce|expected behaviou?r|steps to reproduce|is your feature request related to a problem|"
    r"pre-submit checks|checklist|possible solution|alternatives you've considered|additional context|"
    r"use cases?|proposal|summary|describe|the solution you'd like|shut up and|looking for|show hn|ask hn)\b", re.I)
SHADOW_THRESHOLD = 0.5
_MODEL: Any = None
_LOADED = False


def mask(text: str) -> str:
    text = PAY_RE.sub(" ", str(text or ""))
    text = SEEK_RE.sub(" ", text)
    text = VALID_RE.sub(" ", text)
    text = TEMPLATE_RE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def load(path: str | None = None):
    """Load the private teacher once; None if absent or incompatible."""
    global _MODEL, _LOADED
    if _LOADED:
        return _MODEL
    _LOADED = True
    path = path or os.getenv("MAESTRO_MODEL") or ""
    if not path or not os.path.exists(path):
        return None
    try:
        import joblib
        model = joblib.load(path)
        if hasattr(model, "predict_proba"):
            _MODEL = model
    except Exception:
        _MODEL = None
    return _MODEL


def scores(model, texts: list[str]) -> list[float]:
    if model is None or not texts:
        return []
    return [float(x) for x in model.predict_proba([mask(t) for t in texts])[:, 1]]


def shadow_metrics(model, query_rows: list[dict], threshold: float = SHADOW_THRESHOLD) -> dict | None:
    """Counts only: how many retrieved hits the teacher calls real demand."""
    if model is None:
        return None
    texts, threads = [], []
    for row in query_rows or []:
        for hit in row.get("hits") or []:
            if not isinstance(hit, dict):
                continue
            title = str(hit.get("title") or hit.get("story_title") or "")
            body = re.sub(r"<[^>]+>", " ", str(hit.get("comment_text") or hit.get("story_text") or ""))
            texts.append(body if body.strip() else title)
            threads.append(str(hit.get("story_id") or hit.get("objectID") or ""))
    s = scores(model, texts)
    flagged = [i for i, v in enumerate(s) if v >= threshold]
    return {
        "scored_hits": len(s),
        "teacher_hits": len(flagged),
        "teacher_unique_threads": len({threads[i] for i in flagged if threads[i]}),
        "teacher_mean": round(sum(s) / len(s), 4) if s else 0.0,
        "threshold": threshold,
        "affects_fitness": False,
    }
