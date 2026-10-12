"""Distill the 14B deep mind into the small arena mind (Kaggle, free GPU).

Stages (each writes only to the private archive under market-intuition/distill/):
  harvest <private_dir>                      collect ~2,000 candidate need sentences
  label-build <private_dir> <kernel_dir> <user>   Kaggle kernel: 14B labels them
  label-collect <private_dir> <output_json>  store labels + split train/holdout
  train-build <private_dir> <kernel_dir> <user>   Kaggle kernel: LoRA on the 3B
Preregistered rule (docs/market-intuition-distill.md) is fixed before training.
Logs print counts only.
"""
from __future__ import annotations

import hashlib
import json
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import arena_market_intuition as ami  # noqa: E402

TEACHER = "qwen2.5:14b-instruct-q4_K_M"
STUDENT_HF = "unsloth/Qwen2.5-3B-Instruct"
MAX_CANDIDATES = 2200
HOLDOUT_FRACTION = 0.2
LABEL_SLUG = "neo-mind-distill-label"
TRAIN_SLUG = "neo-mind-distill-train"


def _dir(private_dir: str) -> Path:
    d = Path(private_dir) / "market-intuition" / "distill"
    d.mkdir(parents=True, exist_ok=True)
    return d


def harvest(private_dir: str, max_queries: int = 520, getter=ami.http_json) -> int:
    state_p = Path(private_dir) / "market-intuition" / "state.json"
    state = json.loads(state_p.read_text()) if state_p.exists() else {}
    vocab = sorted((state.get("vocabulary") or {}).items(), key=lambda kv: -kv[1])
    terms = list(dict.fromkeys(list(ami.SEED_TERMS) + list(ami.FOCUS_TERMS) + [t for t, _ in vocab[:80]]))
    phrases = list(dict.fromkeys(list(ami.PHRASES) + list(state.get("learned_phrases") or [])))
    rng = random.Random(20261012)
    plan = []
    for term in terms:
        for ph in rng.sample(phrases, min(4, len(phrases))):
            plan.append({"term": term, "phrase": ph, "source": rng.choice(("hn_comments", "hn_comments", "hn_stories"))})
    rng.shuffle(plan)
    plan = plan[:max_queries]
    out, seen, errors = [], set(), 0
    for q in plan:
        try:
            rows = ami.fetch(q, 365, getter)
        except Exception:
            errors += 1
            continue
        for row in rows:
            if row["person"] in seen:
                continue
            sent = ami.need_sentence(row, q)
            if sent:
                seen.add(row["person"])
                out.append({"id": hashlib.sha256((row["person"] + sent).encode()).hexdigest()[:16],
                            "person": row["person"], "need": sent[:300], "term": q["term"]})
        if len(out) >= MAX_CANDIDATES:
            break
        if getter is ami.http_json:
            time.sleep(0.25)
    (_dir(private_dir) / "candidates.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in out))
    print(f"::notice title=Distill harvest::queries={len(plan)} errors={errors} candidates={len(out)}")
    return 0


LABEL_DRIVER = r'''
import json, os, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor
T0 = time.time()
W = "/kaggle/working"
os.makedirs(W + "/mods", exist_ok=True)
for name, src in SOURCES.items():
    open(W + "/mods/" + name, "w").write(src)
sys.path.insert(0, W + "/mods")
subprocess.run("apt-get install -y -qq zstd >/dev/null 2>&1 || (apt-get update -qq && apt-get install -y -qq zstd)", shell=True)
subprocess.run("curl -fsSL https://ollama.com/install.sh | sh", shell=True, check=True, capture_output=True)
os.environ["LD_LIBRARY_PATH"] = "/usr/local/nvidia/lib:/usr/local/nvidia/lib64:" + os.environ.get("LD_LIBRARY_PATH", "")
os.environ["OLLAMA_NUM_PARALLEL"] = "4"
os.environ["OLLAMA_SCHED_SPREAD"] = "1"
subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
import urllib.request
for _ in range(60):
    try:
        urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=2); break
    except Exception:
        time.sleep(1)
subprocess.run(["ollama", "pull", MODEL], check=True, capture_output=True)
import arena_mind
items = INPUT["items"]
B = arena_mind.JUDGE_BATCH
batches = [items[i:i + B] for i in range(0, len(items), B)]
def run(batch):
    v = arena_mind.judge(MODEL, [x["need"] for x in batch])
    return [dict(vv, id=x["id"]) for x, vv in zip(batch, v)]
out = []
with ThreadPoolExecutor(max_workers=4) as ex:
    for res in ex.map(run, batches):
        out.extend(res)
        if len(out) % 120 < B:
            json.dump({"partial": True, "labels": out}, open(W + "/labels.json", "w"))
json.dump({"model": MODEL, "labels": out, "minutes": round((time.time() - T0) / 60, 1)}, open(W + "/labels.json", "w"))
'''


def _kernel(kd: Path, username: str, slug: str, code: str, gpu: bool = True) -> None:
    kd.mkdir(parents=True, exist_ok=True)
    (kd / "main.py").write_text(code)
    (kd / "kernel-metadata.json").write_text(json.dumps({
        "id": f"{username}/{slug}", "title": slug, "code_file": "main.py", "language": "python",
        "kernel_type": "script", "is_private": True, "enable_gpu": gpu, "enable_internet": True,
        "dataset_sources": [], "competition_sources": [], "kernel_sources": []}))


def label_build(private_dir: str, kernel_dir: str, username: str) -> int:
    cands = [json.loads(l) for l in (_dir(private_dir) / "candidates.jsonl").read_text().splitlines() if l.strip()]
    items = [{"id": c["id"], "need": c["need"]} for c in cands]
    sources = {n: (ROOT / n).read_text() for n in ("arena_mind.py", "local_llm_decoding.py")}
    code = f"MODEL = {TEACHER!r}\nSOURCES = {json.dumps(sources)}\nINPUT = {json.dumps({'items': items}, ensure_ascii=False)}\n" + LABEL_DRIVER
    _kernel(Path(kernel_dir), username, LABEL_SLUG, code)
    print(f"::notice title=Distill label::items={len(items)}")
    return 0


def label_collect(private_dir: str, output_json: str) -> int:
    d = _dir(private_dir)
    data = json.loads(Path(output_json).read_text())
    labels = {x["id"]: x for x in data.get("labels") or [] if x.get("judged")}
    cands = [json.loads(l) for l in (d / "candidates.jsonl").read_text().splitlines() if l.strip()]
    rows = [dict(c, label=labels[c["id"]]) for c in cands if c["id"] in labels]
    rng = random.Random(7)
    persons = sorted({r["person"] for r in rows})
    rng.shuffle(persons)
    hold = set(persons[: int(len(persons) * HOLDOUT_FRACTION)])
    train = [r for r in rows if r["person"] not in hold]
    test = [r for r in rows if r["person"] in hold]
    (d / "train.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in train))
    (d / "holdout.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in test))
    real = sum(1 for r in rows if r["label"].get("real_need"))
    print(f"::notice title=Distill labels::labeled={len(rows)} real={real} train={len(train)} holdout={len(test)} "
          f"partial={bool(data.get('partial'))} minutes={data.get('minutes')}")
    return 0


if __name__ == "__main__":
    cmd, *args = sys.argv[1:]
    fn = {"harvest": harvest, "label-build": label_build, "label-collect": label_collect}[cmd]
    raise SystemExit(fn(*args))
