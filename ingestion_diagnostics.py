"""Pure ingestion diagnostics for NEO/MYCELIX.

This module observes search/ingestion outcomes only. It does not change source
selection, relevance decisions, evidence tagging, or the commercial quality gate.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import logging
from typing import Any, Callable

LOGGER = logging.getLogger("mycelix.ingestion")
FUNNEL_STAGES = ("raw_received","deduped","query_relevant","family_matched","buyer_voice","commercial_signal","persisted")

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
    "brave-search": "brave",
    "brave": "brave",
    "bing": "bing-rss",
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
    batch_sources: list[str] | None = None,
) -> dict:
    """Measure raw provider rows and relevance passes without altering routing."""
    raw = Counter()
    passed = Counter()
    errors = 0
    seen = set()
    attempts = Counter()
    empty = Counter()
    source_errors = Counter()
    errors_by_source: dict[str, Counter] = defaultdict(Counter)
    batch_sources = list(batch_sources or [])
    qclass = diagnostic_query_class(meta)
    meta = meta if isinstance(meta, dict) else {}

    for index,batch in enumerate(batches or []):
        source_hint = canonical_source(batch_sources[index] if index < len(batch_sources) else "unknown")
        if source_hint=="web" and isinstance(batch,dict):
            provider_hint=canonical_source(batch.get("provider") or "")
            if provider_hint in {"brave","bing-rss","google-pse"}:
                source_hint=provider_hint
        if isinstance(batch, BaseException):
            errors += 1
            attempts[source_hint] += 1
            source_errors[source_hint] += 1
            errors_by_source[source_hint][type(batch).__name__] += 1
            continue
        if isinstance(batch, dict) and batch.get("error"):
            code=str(batch.get("error") or "exception")[:80]
            source_errors[source_hint] += 1
            errors_by_source[source_hint][code] += 1
        if isinstance(batch,dict) and batch.get("provider_fallback_reason"):
            code=str(batch.get("provider_fallback_reason") or "")[:80]
            if code and code not in {"provider_unconfigured_or_bing","empty_primary_result"}:
                source_errors[source_hint] += 1
                errors_by_source[source_hint][code] += 1
        rows = _rows_from_batch(batch)
        if source_hint != "unknown":
            attempts[source_hint] += 1
            if not rows:
                empty[source_hint] += 1
        for row in rows:
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
        "source_attempts": dict(attempts),
        "source_empty": dict(empty),
        "source_errors": dict(source_errors),
        "errors_by_source": {
            source: dict(sorted(counts.items()))
            for source,counts in sorted(errors_by_source.items())
        },
        "funnel": {
            "queries_executed": 1,
            "calls_by_source": dict(attempts),
            "errors_by_source": {
                source: dict(sorted(counts.items()))
                for source,counts in sorted(errors_by_source.items())
            },
            "raw_received": sum(raw.values()),
            "deduped": len(seen),
            "query_relevant": sum(passed.values()),
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
        self.observed_candidates_purged = 0
        self.observed_candidates_purged_by_reason = Counter()
        self.new_signal_rows = 0
        self.new_signal_rows_by_source = Counter()
        self.new_signal_rows_by_query_class = Counter()
        self.new_signal_rows_by_provider = Counter()
        self.rows_by_intent_class = Counter()
        self.buyer_signals_by_query_intent: dict[str, Counter] = defaultdict(Counter)
        self.intent_review_sample: list[dict] = []
        self.search_provider = {"name":"bing","calls_cycle":0,"calls_day":0,"errors":0,"fallbacks":0,"fallback_reasons":{}}
        self.revalidation = {"attempted":0,"promoted":0,"failed":0,"unreachable":0}
        self.source_attempts = Counter()
        self.source_empty = Counter()
        self.source_errors = Counter()
        self.errors_by_source: dict[str, Counter] = defaultdict(Counter)
        self.funnel = {
            "queries_planned":0,
            "queries_executed":0,
            "queries_skipped_by_reason":Counter(),
            "calls_by_source":Counter(),
            "errors_by_source":defaultdict(Counter),
            "raw_received":0,
            "deduped":0,
            "query_relevant":0,
            "family_matched":0,
            "buyer_voice":0,
            "commercial_signal":0,
            "persisted":0,
            "discarded_by_reason":Counter(),
        }
        self.agent_probes = {
            "probes_attempted":0,
            "agents_reached":0,
            "answers_received":0,
            "valid_answers":0,
            "rejected_answers":0,
            "timeouts":0,
        }
        self.errors = 0

    def merge_web_research(self, groups: list[dict] | None) -> None:
        if not self.enabled:
            return
        for group in groups or []:
            if not isinstance(group, dict):
                continue
            diag = group.get("ingestion_diagnostics")
            reason=str(group.get("query_skip_reason") or "")
            if reason in {"deadline","empty_plan","budget","cooldown","query_limit"}:
                self.funnel["queries_skipped_by_reason"][reason] += max(0,int(group.get("skipped_query_count",1)))
            # Deadline/exception groups previously had no diagnostic payload.
            # Retain the safe code even when no routed search completed.
            code=str(group.get("error") or "")
            if not isinstance(diag,dict) and code in {
                "web_research_deadline_exceeded","money_first_deadline_exceeded",
                "web_research_exception",
            }:
                self.funnel["errors_by_source"]["web"][code] += 1
                self.source_errors["web"] += 1
                self.errors_by_source["web"][code] += 1
                self.errors += 1
                if not reason:
                    self.funnel["queries_skipped_by_reason"]["deadline" if "deadline" in code else "exception"] += 1
            if not isinstance(diag, dict):
                continue
            self.raw.update(diag.get("raw_by_source") or {})
            self.passed.update(diag.get("query_relevance_pass_by_source") or {})
            for source, classes in (diag.get("query_relevance_pass_by_source_and_class") or {}).items():
                if isinstance(classes, dict):
                    self.passed_by_class[canonical_source(source)].update(classes)
            self.source_attempts.update(diag.get("source_attempts") or {})
            self.source_empty.update(diag.get("source_empty") or {})
            self.source_errors.update(diag.get("source_errors") or {})
            for source,codes in (diag.get("errors_by_source") or {}).items():
                if isinstance(codes,dict):
                    self.errors_by_source[canonical_source(source)].update(codes)
            funnel=diag.get("funnel") if isinstance(diag.get("funnel"),dict) else {}
            self.funnel["queries_executed"] += max(0,int(funnel.get("queries_executed") or 0))
            self.funnel["calls_by_source"].update(funnel.get("calls_by_source") or {})
            for source,codes in (funnel.get("errors_by_source") or {}).items():
                if isinstance(codes,dict):
                    self.funnel["errors_by_source"][canonical_source(source)].update(codes)
            for key in ("raw_received","deduped","query_relevant"):
                self.funnel[key] += max(0,int(funnel.get(key) or 0))
            self.errors += int(diag.get("diagnostic_errors") or 0)

    def add_raw_rows(self, rows: list[dict] | None) -> None:
        if not self.enabled:
            return
        for row in rows or []:
            if isinstance(row, dict):
                self.raw[canonical_source(row.get("source") or "unknown")] += 1
                self.funnel["raw_received"] += 1

    def record_scout_deduped(self, row: dict) -> None:
        if self.enabled and str(row.get("url") or "").strip():
            self.funnel["deduped"] += 1

    def record_scout_relevance(self, source: str, query_class: str) -> None:
        if self.enabled:
            source=canonical_source(source)
            self.funnel["query_relevant"] += 1
            self.passed[source] += 1
            self.passed_by_class[source][query_class] += 1

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
        self.funnel["discarded_by_reason"][reason] += 1

    def set_queries_planned(self, count: int) -> None:
        if self.enabled:
            self.funnel["queries_planned"]=max(0,int(count or 0))

    def record_funnel_stage(self, stage: str, count: int = 1) -> None:
        if not self.enabled or stage not in FUNNEL_STAGES:
            return
        self.funnel[stage] += max(0,int(count or 0))

    def set_agent_probes(self, payload: dict | None) -> None:
        if not self.enabled or not isinstance(payload,dict):
            return
        for key in self.agent_probes:
            self.agent_probes[key]=max(0,int(payload.get(key) or 0))

    def record_observed_candidate_purge(self, reason: str, count: int = 1) -> None:
        if not self.enabled:
            return
        n=max(0,int(count or 0))
        if not n:
            return
        reason=str(reason or "unknown")
        self.observed_candidates_purged += n
        self.observed_candidates_purged_by_reason[reason] += n

    def record_new_signal_row(self, source: str, query_class: str, provider: str = "") -> None:
        if not self.enabled:
            return
        source=canonical_source(source)
        qclass=str(query_class or "unknown")
        provider=str(provider or source or "unknown")
        self.new_signal_rows += 1
        self.new_signal_rows_by_source[source] += 1
        self.new_signal_rows_by_query_class[qclass] += 1
        self.new_signal_rows_by_provider[provider] += 1

    def record_intent_result(
        self,
        intent_class: str,
        query_intent: str,
        title: str,
        url: str,
        signal_types: list[str] | tuple[str,...] | set[str],
        source: str,
    ) -> None:
        if not self.enabled:
            return
        iclass=str(intent_class or "").strip()
        qintent=str(query_intent or "pain").strip().lower()
        tags=sorted({str(x) for x in (signal_types or []) if str(x)})
        if iclass:
            self.rows_by_intent_class[iclass] += 1
        for tag in ("BUY_INTENT","PAID_DEMAND"):
            if tag in tags:
                self.buyer_signals_by_query_intent[qintent][tag] += 1
        if len(self.intent_review_sample)<10:
            self.intent_review_sample.append({
                "title":str(title or "")[:220],
                "url":str(url or "")[:700],
                "source":canonical_source(source),
                "query_intent":qintent,
                "intent_class":iclass,
                "signal_types":tags,
            })

    def set_search_provider(self, payload: dict | None) -> None:
        if not self.enabled or not isinstance(payload,dict):
            return
        self.search_provider = {
            "name":str(payload.get("name") or "bing"),
            "calls_cycle":max(0,int(payload.get("calls_cycle") or 0)),
            "calls_day":max(0,int(payload.get("calls_day") or 0)),
            "errors":max(0,int(payload.get("errors") or 0)),
            "fallbacks":max(0,int(payload.get("fallbacks") or 0)),
            "configured_provider":str(payload.get("configured_provider") or payload.get("name") or "bing"),
            "provider_key_present":bool(payload.get("provider_key_present")),
            "fallback_used":bool(payload.get("fallback_used") or payload.get("fallbacks")),
            "fallback_reasons":{
                str(k)[:80]:max(0,int(v or 0))
                for k,v in (payload.get("fallback_reasons") or {}).items()
                if str(k).strip()
            } if isinstance(payload.get("fallback_reasons"),dict) else {},
        }

    def merge_revalidation(self, stats: dict | None) -> None:
        if not self.enabled or not isinstance(stats,dict):
            return
        for key in ("attempted","promoted","failed","unreachable"):
            self.revalidation[key] += max(0,int(stats.get(key) or 0))

    def snapshot(self) -> dict:
        if not self.enabled:
            return {"enabled": False}
        raw = dict(self.raw)
        passed = dict(self.passed)
        for source in TRACKED_SOURCES:
            raw.setdefault(source, 0)
            passed.setdefault(source, 0)
        funnel_out={
            "queries_planned":max(0,int(self.funnel["queries_planned"] or 0)),
            "queries_executed":max(0,int(self.funnel["queries_executed"] or 0)),
            "queries_skipped_by_reason":dict(sorted(self.funnel["queries_skipped_by_reason"].items())),
            "calls_by_source":dict(sorted(self.funnel["calls_by_source"].items())),
            "errors_by_source":{
                source:dict(sorted(codes.items()))
                for source,codes in sorted(self.funnel["errors_by_source"].items())
            },
            **{key:max(0,int(self.funnel[key] or 0)) for key in FUNNEL_STAGES},
            "discarded_by_reason":dict(sorted(self.funnel["discarded_by_reason"].items())),
        }
        seq=[funnel_out[key] for key in FUNNEL_STAGES]
        violations=[
            {"upstream":FUNNEL_STAGES[i],"downstream":FUNNEL_STAGES[i+1]}
            for i in range(len(FUNNEL_STAGES)-1)
            if seq[i] < seq[i+1]
        ]
        if violations:
            LOGGER.warning("funnel monotonicity violation: %s", violations)
        funnel_out["monotonicity_warnings"]=violations

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
            "observed_candidates_purged": self.observed_candidates_purged,
            "observed_candidates_purged_by_reason": dict(sorted(self.observed_candidates_purged_by_reason.items())),
            "new_signal_rows": self.new_signal_rows,
            "new_signal_rows_by_source": dict(sorted(self.new_signal_rows_by_source.items())),
            "new_signal_rows_by_query_class": dict(sorted(self.new_signal_rows_by_query_class.items())),
            "new_signal_rows_by_provider": dict(sorted(self.new_signal_rows_by_provider.items())),
            "rows_by_intent_class": dict(sorted(self.rows_by_intent_class.items())),
            "buyer_signals_by_query_intent": {
                qintent: dict(sorted(counts.items()))
                for qintent,counts in sorted(self.buyer_signals_by_query_intent.items())
            },
            "intent_review_sample": list(self.intent_review_sample),
            "search_provider": dict(self.search_provider),
            "funnel": funnel_out,
            "agent_probes": dict(self.agent_probes),
            "source_attempts": dict(sorted(self.source_attempts.items())),
            "source_empty": dict(sorted(self.source_empty.items())),
            "source_errors": dict(sorted(self.source_errors.items())),
            "revalidation": dict(self.revalidation),
            "diagnostic_errors": self.errors,
        }
