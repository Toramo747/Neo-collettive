# SPDX-License-Identifier: BUSL-1.1
"""Stance classifier for anomaly abstracts (supports_tension / resolves / neutral).

Trained on Claude-labelled arXiv abstracts kept in the private archive
(docs/anomaly-classifier.md). Topic names are masked so the model judges the
stance of the paper, not which anomaly it is about. Optional: without the
model file the Anomaly Arena keeps cue-word scoring and reports itself
uncalibrated.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

LABELS = ("supports_tension", "resolves", "neutral")
MODEL_ENV = "ANOMALY_CLASSIFIER_MODEL"
DEFAULT_MODEL = Path("anomaly/classifier-v1.joblib")

# Topic vocabulary: masked so that "BICEP2" or "750 GeV" cannot stand in for a stance.
TOPIC_TERMS = (
    r"hubble (?:tension|constant)", r"h_?\{?0\}?", r"s_?\{?8\}?", r"sigma_?\{?8\}?", r"σ_?8",
    r"lithium(?:-7)?", r"\^\{?7\}?\s*li", r"7li", r"\$\^\{?7\}?\$li", r"neutron lifetime", r"beam", r"bottle",
    r"w[- ]boson mass", r"m_?\{?w\}?", r"cdf(?: ii)?", r"casimir", r"proton (?:charge )?radius", r"muonic hydrogen",
    r"opera", r"superluminal", r"750 ?gev", r"diphoton", r"bicep2?", r"keck", r"b[- ]modes?",
    r"muon g-?2", r"\(g-2\)_?μ?", r"g-2", r"anomalous magnetic moment", r"reactor antineutrino", r"gallium",
    r"best", r"atomki", r"x17", r"cosmic dipole", r"ellis[- &and]+baldwin", r"catwise", r"desi", r"dark energy",
    r"w_?0", r"w_?a", r"sterile neutrinos?", r"puzzle", r"anomal\w*", r"tension\w*", r"discrepanc\w*",
)
_TOPIC_RE = re.compile(r"(?<![a-z0-9])(?:" + "|".join(TOPIC_TERMS) + r")(?![a-z0-9])", re.I)


def mask(text: str) -> str:
    """Lower-case and replace topic vocabulary and numbers with placeholders."""
    t = _TOPIC_RE.sub(" topicterm ", text or "")
    t = re.sub(r"\d+(?:\.\d+)?", " num ", t)
    return " ".join(t.lower().split())


_MODEL = None


def load(path: str | os.PathLike | None = None):
    global _MODEL
    if _MODEL is not None and path is None:
        return _MODEL
    p = Path(path or os.environ.get(MODEL_ENV) or DEFAULT_MODEL)
    if not p.is_file():
        return None
    try:
        import joblib
        model = joblib.load(p)
    except Exception:
        return None
    if path is None:
        _MODEL = model
    return model


def predict(model, texts: list[str]) -> list[str]:
    if model is None or not texts:
        return []
    return [str(x) for x in model.predict([mask(t) for t in texts])]
