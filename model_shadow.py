# SPDX-License-Identifier: BUSL-1.1
from __future__ import annotations

import base64
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

try:
    import numpy as np
except Exception:  # dependency-lock rollout may briefly precede the audited lock commit
    np = None

MODEL_SHADOW_SCHEMA_V = 1
DEFAULT_ARTIFACT_PATH = "runtime/model-shadow/student.json"
_ALLOWED_LABELS = (
    "buyer_tool_search",
    "vendor_offer",
    "manual_recurring_work",
    "job_posting",
    "other",
)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def stable_case_id(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()[:24]


def validate_split_separation(train_ids: set[str], public_ids: set[str], hidden_ids: set[str]) -> dict:
    overlaps = {
        "train_public": sorted(train_ids & public_ids),
        "train_hidden": sorted(train_ids & hidden_ids),
        "public_hidden": sorted(public_ids & hidden_ids),
    }
    if any(overlaps.values()):
        raise ValueError("model_shadow_split_overlap")
    return {
        "train": len(train_ids),
        "public": len(public_ids),
        "hidden": len(hidden_ids),
        "disjoint": True,
    }


def validate_hidden_origins(cases: list[dict]) -> None:
    for row in cases or []:
        if not isinstance(row, dict):
            continue
        origin = str(row.get("label_origin") or "")
        if origin != "human":
            raise ValueError("hidden_label_must_be_human")


def _feature_index(ngram: str, dimension: int) -> int:
    raw = hashlib.blake2b(ngram.encode("utf-8"), digest_size=8, person=b"neo-ngrm").digest()
    return int.from_bytes(raw, "little", signed=False) % dimension


def hashed_char_ngrams(text: str, dimension: int, ngram_min: int = 3, ngram_max: int = 5):
    if np is None:
        raise RuntimeError("numpy_unavailable")
    dimension = max(128, int(dimension))
    normalized = " ".join(str(text or "").lower().split())
    vec = np.zeros(dimension, dtype=np.float32)
    if not normalized:
        return vec
    padded = "^" + normalized + "$"
    for n in range(max(1, ngram_min), max(ngram_min, ngram_max) + 1):
        if len(padded) < n:
            continue
        for i in range(len(padded) - n + 1):
            vec[_feature_index(padded[i:i+n], dimension)] += 1.0
    norm = float(np.linalg.norm(vec))
    if norm > 0:
        vec /= norm
    return vec


def _decode_f32(encoded: str, shape: tuple[int, ...]):
    if np is None:
        raise RuntimeError("numpy_unavailable")
    raw = base64.b64decode(str(encoded or "").encode("ascii"), validate=True)
    arr = np.frombuffer(raw, dtype="<f4")
    expected = math.prod(shape)
    if arr.size != expected:
        raise ValueError("student_artifact_shape_mismatch")
    return arr.reshape(shape)


class StudentModel:
    def __init__(self, payload: dict):
        if np is None:
            raise RuntimeError("numpy_unavailable")
        self.version = str(payload.get("version") or "")
        self.feature_dim = max(128, _safe_int(payload.get("feature_dim"), 32768))
        self.ngram_min = max(1, _safe_int(payload.get("ngram_min"), 3))
        self.ngram_max = max(self.ngram_min, _safe_int(payload.get("ngram_max"), 5))
        self.labels = tuple(str(x) for x in (payload.get("labels") or []))
        if not self.labels or any(x not in _ALLOWED_LABELS for x in self.labels):
            raise ValueError("student_artifact_labels")
        self.weights = _decode_f32(str(payload.get("weights_f32_b64") or ""), (len(self.labels), self.feature_dim))
        self.bias = _decode_f32(str(payload.get("bias_f32_b64") or ""), (len(self.labels),))
        self.artifact_sha256 = str(payload.get("artifact_sha256") or "")
        canonical=dict(payload)
        canonical.pop("artifact_sha256",None)
        observed_sha=hashlib.sha256(
            json.dumps(canonical,sort_keys=True,separators=(",",":")).encode("utf-8")
        ).hexdigest()
        if not self.artifact_sha256 or observed_sha != self.artifact_sha256:
            raise ValueError("student_artifact_sha256_mismatch")
        self.training_manifest_sha256 = str(payload.get("training_manifest_sha256") or "")
        self.mode = "shadow"

    def predict(self, text: str) -> dict:
        x = hashed_char_ngrams(text, self.feature_dim, self.ngram_min, self.ngram_max)
        logits = self.weights @ x + self.bias
        logits = logits - float(np.max(logits))
        probs = np.exp(logits)
        probs = probs / max(float(np.sum(probs)), 1e-12)
        idx = int(np.argmax(probs))
        return {
            "label": self.labels[idx],
            "confidence": round(float(probs[idx]), 6),
            "version": self.version,
        }


def load_student(path: str | None = None) -> StudentModel | None:
    artifact_path = Path(path or os.getenv("NEO_STUDENT_ARTIFACT_PATH") or DEFAULT_ARTIFACT_PATH)
    if not artifact_path.is_file():
        return None
    try:
        payload = json.loads(artifact_path.read_text(encoding="utf-8"))
        if str(payload.get("mode") or "") != "shadow":
            return None
        if not bool(payload.get("trained")):
            return None
        return StudentModel(payload)
    except Exception:
        return None


def empty_shadow_metrics() -> dict:
    return {
        "schema_v": MODEL_SHADOW_SCHEMA_V,
        "mode": "shadow",
        "student_available": False,
        "observed": 0,
        "agreement": 0,
        "disagreement": 0,
        "agreement_rate_ppm": 0,
        "lexicon_positive": 0,
        "student_positive": 0,
        "student_low_confidence": 0,
        "student_version_code": "",
    }


def _positive(label: str) -> bool:
    return str(label or "") in {"buyer_tool_search", "manual_recurring_work"}


def update_shadow_metrics(
    metrics: dict | None,
    *,
    lexicon_label: str,
    student_prediction: dict | None,
    confidence_threshold: float = 0.70,
) -> dict:
    out = dict(empty_shadow_metrics())
    if isinstance(metrics, dict):
        for key in out:
            if key in metrics:
                out[key] = metrics[key]
    if not isinstance(student_prediction, dict):
        return out
    label = str(student_prediction.get("label") or "")
    confidence = float(student_prediction.get("confidence") or 0.0)
    if label not in _ALLOWED_LABELS:
        return out
    out["student_available"] = True
    out["observed"] = _safe_int(out.get("observed")) + 1
    if _positive(lexicon_label):
        out["lexicon_positive"] = _safe_int(out.get("lexicon_positive")) + 1
    if _positive(label):
        out["student_positive"] = _safe_int(out.get("student_positive")) + 1
    if confidence < float(confidence_threshold):
        out["student_low_confidence"] = _safe_int(out.get("student_low_confidence")) + 1
    if label == str(lexicon_label or ""):
        out["agreement"] = _safe_int(out.get("agreement")) + 1
    else:
        out["disagreement"] = _safe_int(out.get("disagreement")) + 1
    observed=max(1,_safe_int(out.get("observed")))
    out["agreement_rate_ppm"] = int(_safe_int(out.get("agreement")) * 1_000_000 / observed)
    out["student_version_code"] = str(student_prediction.get("version") or "")[:32]
    return out


def public_shadow_projection(metrics: dict | None) -> dict:
    src = metrics if isinstance(metrics, dict) else {}
    return {
        "schema_v": MODEL_SHADOW_SCHEMA_V,
        "mode": "shadow",
        "student_available": bool(src.get("student_available")),
        "observed": max(0, _safe_int(src.get("observed"))),
        "agreement": max(0, _safe_int(src.get("agreement"))),
        "disagreement": max(0, _safe_int(src.get("disagreement"))),
        "agreement_rate_ppm": max(0, min(1_000_000, _safe_int(src.get("agreement_rate_ppm")))),
        "lexicon_positive": max(0, _safe_int(src.get("lexicon_positive"))),
        "student_positive": max(0, _safe_int(src.get("student_positive"))),
        "student_low_confidence": max(0, _safe_int(src.get("student_low_confidence"))),
        "student_version_code": str(src.get("student_version_code") or "")[:32],
    }
