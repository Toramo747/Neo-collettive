"""Private, dual-blind, single-topic HN review; never run in public CI.

plan: no network, no files.
collect: four bounded public queries; writes identifiable public cases only to an
explicit fresh private directory outside this repository, never to GH artifacts.
aggregate: consumes two distinct reviewer *files*, not proof of independent humans.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import hmac
import io
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from experiments.demand_pressure.file_access_audit import (
    QUERY, TOPIC, HITS_PER_QUERY, MAX_CALLS, protocol, analyze,
    SELLER_RISK, TOPIC_TYPES,
    FILE_CONTEXT,
)
from experiments.demand_pressure.hn_shadow import convert, text_of

CASE_FILE = "blind_cases.jsonl"
MAPPING_FILE = "private_machine_annotations.json"
REVIEW_FILES = ("reviewer_1.csv", "reviewer_2.csv")
REPORT_FILE = "review_aggregate.json"
ALLOWED_LABELS = frozenset(("real_problem", "not_problem", "uncertain"))
ALLOWED_SOLUTION = frozenset(("yes", "no", "uncertain"))
ALLOWED_THEMES = frozenset(("access_control", "sharing_sync", "retrieval", "other", "uncertain"))


def _private_dir(raw: str, *, create: bool = False) -> Path:
    if not raw:
        raise ValueError("--private-dir absolute path required")
    location = Path(raw).expanduser()
    if not location.is_absolute():
        raise ValueError("Review path must be absolute")
    path = location.resolve(strict=False)
    if path == ROOT or ROOT in path.parents:
        raise ValueError("Private review may not be within Git repository")
    if create:
        if path.exists() or location.is_symlink():
            raise ValueError("Private review path must not already exist")
        path.mkdir(mode=0o700, parents=True, exist_ok=False)
        os.chmod(path, 0o700)
        if os.name == "nt":
            # chmod() on Windows does not protect ACLs; fail closed.
            who = subprocess.run(["whoami", "/user", "/fo", "csv", "/nh"],
                                 capture_output=True, text=True, check=True)
            records = list(csv.reader(io.StringIO(who.stdout)))
            if len(records) != 1 or len(records[0]) < 2:
                raise ValueError("Could not determine current user SID")
            sid = records[0][1].strip()
            if not re.fullmatch(r"S-\d+(?:-\d+)+", sid):
                raise ValueError("Invalid Windows SID")
            subprocess.run(["icacls", str(path), "/inheritance:r", "/grant:r",
                            f"*{sid}:(OI)(CI)F", "*S-1-5-18:(OI)(CI)F"],
                           capture_output=True, text=True, check=True)
    elif not path.is_dir():
        raise ValueError("Private review directory does not exist")
    return path


def _new_file(path: Path, content: str) -> None:
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
        stream.write(content)
    os.chmod(path, 0o600)


def _template(case_ids: list[str]) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(("case_id", "label", "explicit_solution_request", "theme", "reason"))
    for case_id in case_ids:
        writer.writerow((case_id, "", "", "", ""))
    return out.getvalue()


def prepare_cases(batches: list[dict], *, secret: bytes) -> tuple[list[dict], dict]:
    """Select deduplicated source-backed threads, no raw network access here."""
    metrics = analyze(batches, secret=secret)
    if metrics["status"] != "MACHINE_TRIAGE_ONLY":
        raise ValueError("All provider calls must be valid")
    cases: dict[str, dict] = {}
    private_annotations = {}
    for p, batch in zip(protocol(), batches):
        for hit in batch["hits"]:
            if not isinstance(hit, dict):
                continue
            when = hit.get("created_at_i")
            if not isinstance(when, int) or isinstance(when, bool) or not p["start"] <= when < p["end"]:
                continue
            rows = convert([hit], key=secret, topic=QUERY)
            if not rows:
                continue
            obj = str(hit.get("objectID") or "")
            if not obj.isascii() or not obj.isdigit():
                continue
            thread_token = rows[0]["request_id"]
            title, body = text_of(hit)
            case_id = hmac.new(secret, ("review-case:" + thread_token).encode(), hashlib.sha256).hexdigest()[:20]
            if case_id in cases:
                continue  # one representative HN comment per discussion
            text = title + " " + body
            machine = {
                "weak_topic_overlap": __import__("discovery_v3").query_relevance(
                    title, body, QUERY, {"search_alias_used": QUERY}
                ).get("overlap", []) and len(__import__("discovery_v3").query_relevance(
                    title, body, QUERY, {"search_alias_used": QUERY}
                ).get("overlap", [])) < 2,
                "seller_risk": bool(SELLER_RISK.search(text)),
                "file_context": bool(FILE_CONTEXT.search(text)),
                "explicit_solution_request_machine": rows[0]["explicit_solution_request"],
                "themes": sorted(k for k, pattern in TOPIC_TYPES.items() if pattern.search(text)),
            }
            private_annotations[case_id] = machine
            cases[case_id] = {
                "case_id": case_id,
                "topic": TOPIC,
                "title": title,
                "body": body,
                "hn_url": "https://news.ycombinator.com/item?id=" + obj,
                "review_instructions": "Read complete discussion context before labeling; no machine labels shown.",
            }
    # Stable deterministic order prevents hidden risk flags steering reviewer order.
    selected = sorted(cases.values(), key=lambda r: r["case_id"])
    return selected, {
        "schema_v": 1, "machine_by_case": private_annotations,
        "comparison_is_exact_original_replay": False,
        "source_truncated": not metrics["source_complete"],
        "all_identifiers_private": True,
        "study_class": "RETROSPECTIVE_EXPLORATORY_NOT_VALIDATION",
    }


def write_packet(private_dir: str, cases: list[dict], mapping: dict) -> dict:
    root = _private_dir(private_dir, create=True)
    _new_file(root / CASE_FILE, "".join(json.dumps(c, sort_keys=True) + "\n" for c in cases))
    _new_file(root / MAPPING_FILE, json.dumps(mapping, sort_keys=True, indent=2) + "\n")
    for filename in REVIEW_FILES:
        _new_file(root / filename, _template([c["case_id"] for c in cases]))
    return {
        "status": "LOCAL_BLIND_REVIEW_PACKET_CREATED",
        "case_count": len(cases),
        "source_sample_complete": not mapping.get("source_truncated", True),
        "independent_human_reviews_completed": 0,
        "commercial_gate_influence": "NONE",
        "production_state_write": False,
    }


async def collect(destination: str) -> dict:
    # Validate location BEFORE making public requests.
    _private_dir(destination)
    raise AssertionError("Unreachable")


async def fetch_and_collect(destination: str) -> dict:
    if not destination:
        raise ValueError("Explicit --private-dir required")
    location = Path(destination).expanduser()
    if not location.is_absolute() or location.exists():
        raise ValueError("Choose a new absolute directory")
    _private_dir(str(location.parent))  # existing parent, outside repo
    batches = []
    async with httpx.AsyncClient(
        timeout=20, follow_redirects=False, trust_env=False,
        headers={"User-Agent": "OXIBAY-IPD-PrivateBlindReview/1.0"},
    ) as client:
        for p in protocol():
            response = await client.get(
                "https://hn.algolia.com/api/v1/search_by_date",
                params={
                    "query": QUERY, "hitsPerPage": HITS_PER_QUERY,
                    "numericFilters": f"created_at_i>={p['start']},created_at_i<{p['end']}",
                },
            )
            response.raise_for_status()
            doc = response.json()
            if not isinstance(doc, dict) or not isinstance(doc.get("hits"), list):
                raise ValueError("Provider response incomplete")
            batches.append({"ok": True, "hits": doc["hits"][:HITS_PER_QUERY]})
    cases, mapping = prepare_cases(batches, secret=secrets.token_bytes(32))
    if not cases:
        return {"status": "NO_CASES_TO_REVIEW", "case_count": 0}
    return write_packet(destination, cases, mapping)


def _review_file(file: Path, expected: set[str]) -> dict[str, dict]:
    with file.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != len(expected):
        raise ValueError("Review rows missing/duplicated")
    parsed = {}
    for row in rows:
        identity = (row.get("case_id") or "").strip()
        if identity not in expected or identity in parsed:
            raise ValueError("Reviewer case ID invalid/duplicate")
        label = (row.get("label") or "").strip().lower()
        solution = (row.get("explicit_solution_request") or "").strip().lower()
        theme = (row.get("theme") or "").strip().lower()
        if label and label not in ALLOWED_LABELS:
            raise ValueError("Invalid label")
        if solution and solution not in ALLOWED_SOLUTION:
            raise ValueError("Invalid solution-request label")
        if theme and theme not in ALLOWED_THEMES:
            raise ValueError("Invalid theme label")
        parsed[identity] = {"label": label, "solution": solution, "theme": theme}
    return parsed


def aggregate(destination: str) -> dict:
    root = _private_dir(destination)
    if (root / REPORT_FILE).exists():
        raise ValueError("Refuse overwriting an existing review aggregate")
    mapping = json.loads((root / MAPPING_FILE).read_text(encoding="utf-8"))
    if mapping.get("study_class") != "RETROSPECTIVE_EXPLORATORY_NOT_VALIDATION":
        raise ValueError("Unknown study")
    cases = mapping.get("machine_by_case")
    if not isinstance(cases, dict) or len(cases) > MAX_CALLS * HITS_PER_QUERY:
        raise ValueError("Bad private mapping")
    ids = set(cases)
    a, b = (_review_file(root / f, ids) for f in REVIEW_FILES)
    agreed = {"real_problem": 0, "not_problem": 0}
    solution_requests = 0
    pending = uncertain = disagreed = 0
    suspected_machine_false_positives = 0
    for key in sorted(ids):
        first, second = a[key], b[key]
        if not all(first[k] and second[k] for k in ("label", "solution", "theme")):
            pending += 1
        elif "uncertain" in (
            first["label"], second["label"], first["solution"], second["solution"],
            first["theme"], second["theme"]
        ):
            uncertain += 1
        elif first != second:
            disagreed += 1
        else:
            agreed[first["label"]] += 1
            solution_requests += first["solution"] == "yes" and first["label"] == "real_problem"
            suspected_machine_false_positives += first["label"] == "not_problem"
    complete = pending == uncertain == disagreed == 0 and len(ids) >= 5
    status = (
        "INCOMPLETE_REVIEW" if pending else
        "NEEDS_ADJUDICATION" if uncertain or disagreed else
        "INSUFFICIENT_CASES" if len(ids) < 5 else
        "TWO_REVIEWER_FILES_AGREE_NOT_INDEPENDENCE_PROOF"
    )
    summary = {
        "schema_v": 1, "status": status, "sample_cases": len(ids),
        "pending": pending, "uncertain": uncertain, "disagreements": disagreed,
        "agreed_real_problem": agreed["real_problem"],
        "agreed_not_problem": agreed["not_problem"],
        "agreed_explicit_solution_requests": solution_requests,
        "potential_machine_false_positives": suspected_machine_false_positives,
        "human_reviewer_identity_verified": False,
        "representative_population_precision": False,
        "complete_review_file_agreement": complete,
        "source_truncated": bool(mapping.get("source_truncated", True)),
        "commercial_proof": False, "automatic_promotion": False,
        "production_state_write": False, "source_text_in_report": False,
    }
    _new_file(root / REPORT_FILE, json.dumps(summary, sort_keys=True, indent=2) + "\n")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", nargs="?", choices=("plan", "collect", "aggregate"), default="plan")
    parser.add_argument("--private-dir")
    arguments = parser.parse_args()
    if arguments.action == "plan":
        print(json.dumps({
            "mode": "PLAN_ONLY", "network_calls": 0,
            "maximum_public_queries_if_collected": MAX_CALLS,
            "private_directory_required": True, "commercial_gate_influence": "NONE",
        }, sort_keys=True))
    elif arguments.action == "collect":
        print(json.dumps(asyncio.run(fetch_and_collect(arguments.private_dir)), sort_keys=True))
    else:
        print(json.dumps(aggregate(arguments.private_dir), sort_keys=True))


if __name__ == "__main__":
    main()
