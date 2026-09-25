"""Pure ingestion diagnostics for NEO/MYCELIX.

This module observes search/ingestion outcomes only. It does not change source
selection, relevance decisions, evidence tagging, or the commercial quality gate.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Callable

TRACKED_SOURCES = ("bing-rss", "hn", "github", "stackexchange")
_SOURCE_ALIASES = {
    "bing-rss-free": "bing-rss",
    "bing-rss": "bing-rss",
    "hn-algolia-routed": "hn",
    "hackernews": "hn",
    "hn": "hn",
    "github-issues-routed": "github",
    "github-issues": "github",
    "github": "github",
    "stackexchange-routed": "stackexchange",
    "stackexchange": "stackexchange",
}


def canonical_source(source: str) -> str:
    value = str(source or "unknown").strip().lower() or "unknown"
    return _SOURCE_ALIASES.get(value, value)


def diagnostic_query_class(meta: dict | None = None, role: str = "") -> str:
    meta = meta if isinstance(meta, dict) else {}
    role_value = str(role or meta.get("role") or "").strip().lower()
    if role_value == "disconfirm":
        return "disconfirm"
    value = str(meta.get("class") or "").strip().lower()
    if value:
        return value
    mode = str(meta.get("mode") or "").strip().lower()
    if "thesis" in mode:
        return "thesis"
    return role_value or mode or "unknown"


def _rows_from_batch(batch: Any) -> list[dict]:
    if isinstance(batch, dict):
        rows = batch.get("results")
    else:
        rows = batch
    return [row for row in (rows or []) if isinstance(row, dict)] if isinstance(rows, list) else []


def routed_search_diagnostics(
    batches: list[Any],
    query: str,
    meta: dict | None,
    relevance_fn: Callable[[str, str, str, dict], dict],
) -> dict:
    """Measure raw provider rows and relevance passes without altering routing."""
    raw = Counter()
    passed = Counter()
    errors = 0
    seen = set()
    qclass = diagnostic_query_class(meta)
    meta = meta if isinstance(meta, dict) else {}

    for batch in batches or []:
        if isinstance(batch, BaseException):
            errors += 1
            continue
        for row in _rows_from_batch(batch):
            source = canonical_source(row.get("source") or "unknown")
            raw[source] += 1
            url = str(row.get("url") or "").strip()
            if not url or url in seen:
                continue
            seen.add(url)
            try:
                relevance = row.get("query_relevance") if isinstance(row.get("query_relevance"), dict) else relevance_fn(
                    str(row.get("title") or ""),
                    str(row.get("snippet") or ""),
                    query,
                    meta,
                )
                if isinstance(relevance, dict) and relevance.get("relevant"):
                    passed[source] += 1
            except Exception:
                errors += 1

    return {
        "raw_by_source": dict(raw),
        "query_relevance_pass_by_source": dict(passed),
        "query_relevance_pass_by_source_and_class": {
            source: {qclass: count} for source, count in passed.items()
        },
        "diagnostic_errors": errors,
    }


class IngestionDiagnostics:
    def __init__(self, enabled: bool = True):
        self.enabled = bool(enabled)
        self.raw = Counter()
        self.passed = Counter()
        self.passed_by_class: dict[str, Counter] = defaultdict(Counter)
        self.rejected_by_reason = Counter()
        self.self_contamination_rejected = 0
        self.rejected_by_source: dict[str, Counter] = defaultdict(Counter)
        self.rejected_by_class: dict[str, Counter] = defaultdict(Counter)
        self.errors = 0

    def merge_web_research(self, groups: list[dict] | None) -> None:
        if not self.enabled:
            return
        for group in groups or []:
            if not isinstance(group, dict):
                continue
            diag = group.get("ingestion_diagnostics")
            if not isinstance(diag, dict):
                continue
            self.raw.update(diag.get("raw_by_source") or {})
            self.passed.update(diag.get("query_relevance_pass_by_source") or {})
            for source, classes in (diag.get("query_relevance_pass_by_source_and_class") or {}).items():
                if isinstance(classes, dict):
                    self.passed_by_class[canonical_source(source)].update(classes)
            self.errors += int(diag.get("diagnostic_errors") or 0)

    def add_raw_rows(self, rows: list[dict] | None) -> None:
        if not self.enabled:
            return
        for row in rows or []:
            if isinstance(row, dict):
                self.raw[canonical_source(row.get("source") or "unknown")] += 1

    def record_rejection(self, reason: str, source: str, query_class: str) -> None:
        if not self.enabled:
            return
        reason = str(reason or "unknown")
        source = canonical_source(source)
        qclass = str(query_class or "unknown")
        self.rejected_by_reason[reason] += 1
        if reason == "self_contamination_rejected":
            self.self_contamination_rejected += 1
        self.rejected_by_source[source][reason] += 1
        self.rejected_by_class[qclass][reason] += 1

    def snapshot(self) -> dict:
        if not self.enabled:
            return {"enabled": False}
        raw = dict(self.raw)
        passed = dict(self.passed)
        for source in TRACKED_SOURCES:
            raw.setdefault(source, 0)
            passed.setdefault(source, 0)
        return {
            "enabled": True,
            "raw_results_by_source": dict(sorted(raw.items())),
            "rejected_by_reason": dict(sorted(self.rejected_by_reason.items())),
            "self_contamination_rejected": self.self_contamination_rejected,
            "rejected_by_source": {
                source: dict(sorted(counts.items()))
                for source, counts in sorted(self.rejected_by_source.items())
            },
            "rejected_by_query_class": {
                qclass: dict(sorted(counts.items()))
                for qclass, counts in sorted(self.rejected_by_class.items())
            },
            "query_relevance_pass_by_source": dict(sorted(passed.items())),
            "query_relevance_pass_by_source_and_class": {
                source: dict(sorted(classes.items()))
                for source, classes in sorted(self.passed_by_class.items())
            },
            "diagnostic_errors": self.errors,
        }
