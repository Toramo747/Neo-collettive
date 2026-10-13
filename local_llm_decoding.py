# SPDX-License-Identifier: BUSL-1.1
"""Robust decoding settings for small local LLMs (no retraining).

Observed failure (local LLM comparison, 2026-10-11): qwen2.5 0.5b produced
schema-valid JSON in only 2/4 messages; the invalid ones were repetition loops
("Un'opinione generale ... " x N) cut off by num_predict, so the JSON never
closed.  Robust decoding:
* repeat_penalty / repeat_last_n against loops;
* a larger num_predict so a valid object can close;
* maxLength on every string in the JSON schema, so the grammar itself forbids
  endless strings;
* one retry at temperature 0 with an explicit "JSON only" instruction.
"""
from __future__ import annotations

import copy
from typing import Any

BASELINE_OPTIONS = {"temperature": 0.2, "num_predict": 360, "num_ctx": 3072}
ROBUST_OPTIONS = {"temperature": 0.2, "num_predict": 512, "num_ctx": 3072,
                  "repeat_penalty": 1.18, "repeat_last_n": 256, "top_p": 0.9}
RETRY_OPTIONS = dict(ROBUST_OPTIONS, temperature=0.0)
RETRY_SUFFIX = "\n\nReturn ONLY the JSON object. Keep every string short. Do not repeat phrases."
STRING_MAX_LENGTH = 400


def bounded_schema(schema: Any, max_length: int = STRING_MAX_LENGTH) -> Any:
    """Copy of a JSON schema where every string without a bound gets maxLength."""
    s = copy.deepcopy(schema)

    def walk(node):
        if isinstance(node, dict):
            t = node.get("type")
            if (t == "string" or (isinstance(t, list) and "string" in t)) and "maxLength" not in node and "enum" not in node and "const" not in node:
                node["maxLength"] = max_length
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
    walk(s)
    return s
