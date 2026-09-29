from __future__ import annotations

import argparse
import json
from pathlib import Path


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def build_train(source: Path, manifest: Path, out: Path) -> dict:
    held = set(json.loads(manifest.read_text(encoding="utf-8"))["holdout_ids"])
    rows = load_jsonl(source)
    train = [r for r in rows if r["id"] not in held]
    out.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in train), encoding="utf-8")
    counts = {}
    for row in train:
        label = row["proposed_label"]
        counts[label] = counts.get(label, 0) + 1
    return {"source_cases": len(rows), "train_cases": len(train), "counts": counts}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    summary = build_train(Path(args.source), Path(args.manifest), Path(args.out))
    print(
        "source_cases=%d train_cases=%d counts=%s"
        % (summary["source_cases"], summary["train_cases"], json.dumps(summary["counts"], sort_keys=True))
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
