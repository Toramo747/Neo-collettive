#!/usr/bin/env python3
# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Andrea Gava
"""Audit installed runtime dependency licenses and write a deterministic report."""

from __future__ import annotations

import argparse
import importlib.metadata as md
import re
from pathlib import Path

ALLOWLIST = ("MIT", "BSD", "Apache-2.0", "ISC", "PSF", "MPL-2.0")
EXCLUDED_DISTRIBUTIONS = {"pip", "setuptools", "wheel"}

BLOCKED_MARKERS = (
    "agpl",
    "affero general public",
    "lgpl",
    "lesser general public",
    "gnu general public",
    " gpl",
    "gpl-",
    "sspl",
    "server side public",
)


def _classifier_license(metadata: md.PackageMetadata) -> str:
    classifiers = metadata.get_all("Classifier") or []
    licenses = [x for x in classifiers if x.startswith("License ::")]
    return " | ".join(licenses)


def _canonical_license(raw: str, classifier: str) -> tuple[str, str]:
    source = " ".join(x for x in (raw, classifier) if x).strip()
    low = source.lower()
    if not source:
        return "UNKNOWN", "unknown"
    if any(marker in low for marker in BLOCKED_MARKERS):
        return source, "blocked"

    found: list[str] = []
    if re.search(r"(^|[^a-z])mit([^a-z]|$)", low) or "mit license" in low:
        found.append("MIT")
    if "bsd" in low:
        found.append("BSD")
    if "apache-2.0" in low or "apache 2.0" in low or "apache software license" in low:
        found.append("Apache-2.0")
    if re.search(r"(^|[^a-z])isc([^a-z]|$)", low):
        found.append("ISC")
    if "python software foundation" in low or "psf-2.0" in low or re.search(r"(^|[^a-z])psf([^a-z]|$)", low):
        found.append("PSF")
    if "mpl-2.0" in low or "mozilla public license 2.0" in low:
        found.append("MPL-2.0")

    unique = list(dict.fromkeys(found))
    if not unique:
        return source, "unknown"
    return " OR ".join(unique), "allowed"


def collect() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for dist in md.distributions():
        metadata = dist.metadata
        name = (metadata.get("Name") or "").strip()
        if not name:
            continue
        key = re.sub(r"[-_.]+", "-", name).lower()
        if key in EXCLUDED_DISTRIBUTIONS or key in seen:
            continue
        seen.add(key)

        raw = (metadata.get("License-Expression") or metadata.get("License") or "").strip()
        classifier = _classifier_license(metadata)
        normalized, status = _canonical_license(raw, classifier)
        rows.append(
            {
                "package": name,
                "version": dist.version,
                "license": normalized,
                "status": status,
                "raw": raw or classifier or "UNKNOWN",
            }
        )
    return sorted(rows, key=lambda x: x["package"].lower())


def render_markdown(rows: list[dict[str, str]]) -> str:
    blocked = [x for x in rows if x["status"] == "blocked"]
    unknown = [x for x in rows if x["status"] == "unknown"]
    lines = [
        "# Third-Party Runtime Licenses",
        "",
        "Generated from a clean Python 3.12 environment installed exclusively from `requirements.lock`.",
        "Build tooling (`pip`, `setuptools`, `wheel`) is excluded from the runtime inventory.",
        "",
        "Allowed license families: MIT, BSD, Apache-2.0, ISC, PSF, MPL-2.0.",
        "",
        f"- Runtime packages audited: **{len(rows)}**",
        f"- Blocked/copyleft packages (GPL/AGPL/LGPL/SSPL): **{len(blocked)}**",
        f"- Unknown/unclassified licenses: **{len(unknown)}**",
        "",
        "| Package | Version | Normalized license | Status | Metadata evidence |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        evidence = row["raw"].replace("|", "\\|").replace("\n", " ").strip()
        lines.append(
            f'| {row["package"]} | {row["version"]} | {row["license"].replace("|", "\\|")} | {row["status"].upper()} | {evidence} |'
        )
    lines.append("")
    if blocked or unknown:
        lines.extend(["## Review required", ""])
        for row in blocked + unknown:
            lines.append(f'- **{row["package"]} {row["version"]}**: {row["status"].upper()} — {row["raw"]}')
    else:
        lines.extend(["## Review required", "", "None. No blocked or unknown runtime license was detected."])
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    rows = collect()
    if args.write:
        args.write.write_text(render_markdown(rows), encoding="utf-8")
        print(f"wrote {args.write} ({len(rows)} packages)")

    problems = [x for x in rows if x["status"] != "allowed"]
    for row in problems:
        print(f'LICENSE_REVIEW_REQUIRED {row["package"]} {row["version"]}: {row["raw"]}')
    if args.check and problems:
        return 2
    print("license allowlist check passed" if not problems else "license review required")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
