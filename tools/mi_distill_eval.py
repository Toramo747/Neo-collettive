"""Preregistered evaluation of the distilled small mind (see docs/market-intuition-distill.md).

usage: mi_distill_eval.py <private_dir> <base_model> <student_model>
Runs on the GitHub runner with Ollama (CPU). Writes the full report and a
20-sentence spot-check sample for Andrea to the private archive; logs counts only.
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import arena_mind  # noqa: E402


def metrics(pred: list[bool], gold: list[bool]) -> dict:
    tp = sum(p and g for p, g in zip(pred, gold))
    fp = sum(p and not g for p, g in zip(pred, gold))
    fn = sum((not p) and g for p, g in zip(pred, gold))
    neg = sum(1 for g in gold if not g)
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    return {"n": len(gold), "f1": round(f1, 4), "precision": round(prec, 4), "recall": round(rec, 4),
            "fpr": round(fp / neg, 4) if neg else 0.0, "agreement": round(sum(p == g for p, g in zip(pred, gold)) / max(1, len(gold)), 4)}


def decide(base: dict, student: dict) -> dict:
    c1 = student["f1"] >= base["f1"] + 0.10
    c2 = student["fpr"] <= base["fpr"]
    return {"f1_gain_ok": c1, "fpr_ok": c2, "machine_pass": c1 and c2,
            "human_spot_check": "PENDING (>=15 of 20 must be real needs to Andrea)"}


def run(private_dir: str, base_model: str, student_model: str, gen=arena_mind.ollama_generate) -> dict:
    d = Path(private_dir) / "market-intuition" / "distill"
    hold = [json.loads(l) for l in (d / "holdout.jsonl").read_text().splitlines() if l.strip()]
    needs = [r["need"] for r in hold]
    gold = [bool(r["label"].get("real_need")) for r in hold]
    arena_mind.MAX_JUDGED = len(needs)
    out = {}
    preds = {}
    for name, model in (("base", base_model), ("student", student_model)):
        v = arena_mind.judge(model, needs, gen=gen)
        preds[name] = v
        out[name] = metrics([bool(x.get("real_need")) for x in v], gold)
        out[name]["schema_valid_rate"] = round(sum(1 for x in v if x.get("judged")) / max(1, len(v)), 4)
    out["decision"] = decide(out["base"], out["student"])
    rng = random.Random(12)
    pos = [i for i, x in enumerate(preds["student"]) if x.get("real_need")]
    sample = [{"n": k + 1, "need": hold[i]["need"], "student_problem": preds["student"][i].get("problem")}
              for k, i in enumerate(rng.sample(pos, min(20, len(pos))))]
    (d / "eval_report.json").write_text(json.dumps(out, indent=1))
    (d / "spot_check_for_andrea.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in sample))
    print("::notice title=Distill eval::" + json.dumps({k: out[k] for k in ("base", "student", "decision")}, separators=(",", ":")))
    return out


if __name__ == "__main__":
    run(*sys.argv[1:4])
