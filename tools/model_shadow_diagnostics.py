# SPDX-License-Identifier: BUSL-1.1
"""Fixed-code diagnostics for native crashes, without importing model libraries."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

STAGES = {"nli_load", "nli_inference", "llm_load", "llm_inference",
          "student_training", "evaluation", "clustering"}
EXIT_REASONS = {132: "ILLEGAL_CPU_INSTRUCTION", 139: "NATIVE_SEGMENTATION_FAULT",
                137: "PROCESS_KILLED", 124: "PROCESS_TIMEOUT"}


def write_stage(stage: str) -> None:
    target = os.getenv("MODEL_SHADOW_STAGE_PATH")
    if target and stage in STAGES:
        Path(target).write_text(json.dumps({"stage": stage}) + "\n", encoding="utf-8")


def failure_payload(exit_code: int, stage_path: Path) -> dict:
    try:
        data = json.loads(stage_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    stage = data.get("stage") if isinstance(data, dict) else None
    return {"ok": False, "reason": EXIT_REASONS.get(exit_code, "PRIVATE_BATCH_FAILED"),
            "process_exit_code": exit_code if 1 <= exit_code <= 255 else None,
            "failure_stage": stage if isinstance(stage, str) and stage in STAGES else "unknown"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exit-code", type=int, required=True)
    parser.add_argument("--stage-path", required=True)
    args = parser.parse_args()
    print(json.dumps(failure_payload(args.exit_code, Path(args.stage_path)), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
