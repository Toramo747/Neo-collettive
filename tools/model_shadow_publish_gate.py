from __future__ import annotations

import argparse
import json
from pathlib import Path


REQUIRED_TRUE = (
    "batch_complete",
    "student_available",
    "promotion_eligible",
    "student_not_worse_public",
    "student_not_worse_hidden",
    "promotion_requires_manual_approval",
)


def publishable(metrics: dict, student: dict) -> bool:
    """Allow publishing a newly evaluated artifact only as a shadow observer."""
    return (
        isinstance(metrics, dict)
        and metrics.get("mode") == "shadow"
        and all(metrics.get(key) is True for key in REQUIRED_TRUE)
        and metrics.get("batch_idle") is False
        and isinstance(student, dict)
        and student.get("schema_v") == 1
        and student.get("mode") == "shadow"
        and student.get("trained") is True
        and bool(student.get("weights_f32_b64"))
        and bool(student.get("artifact_sha256"))
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--metrics", required=True)
    parser.add_argument("--student", required=True)
    parser.add_argument("--github-output", required=True)
    args = parser.parse_args()

    metrics_path = Path(args.metrics)
    student_path = Path(args.student)
    try:
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
        student = json.loads(student_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        metrics, student = {}, {}

    allowed = publishable(metrics, student)
    reason = "all_shadow_quality_checks_passed" if allowed else "quality_gate_not_satisfied"
    with Path(args.github_output).open("a", encoding="utf-8") as output:
        output.write(f"publishable={str(allowed).lower()}\n")
    print(json.dumps({
        "publishable": allowed,
        "reason": reason,
        "mode": "shadow",
        "production_promotion": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
