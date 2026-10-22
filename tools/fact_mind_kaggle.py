#!/usr/bin/env python3
"""Run the fact-card mind replay on Kaggle's free GPU with a bigger model (trial, 22/10).

  python tools/fact_mind_kaggle.py build <replay.json> <kernel_dir> <kaggle_user> [model]
  python tools/fact_mind_kaggle.py collect <out.json> <private_dir>

The kernel installs ollama, pulls the model, and runs both modes on the same messages:
compose (the model writes cited sentences) and extract (the model only picks fact cards).
The code check is the same as on GitHub. Results go only to the private archive.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SLUG = "neo-fact-mind"
MODEL = "gemma4:31b,qwen3.8:27b"  # 22/10 pm: newer 2026 models at normal quality (Andrea: better models, not bigger)
NUM_CTX = "8192"  # prompts are under 2,000 tokens; a smaller window leaves GPU memory for the model

DRIVER = r'''
import json, os, subprocess, sys, time
T0 = time.time()
W = "/kaggle/working"
os.makedirs(W + "/mods", exist_ok=True)
for name, src in SOURCES.items():
    open(W + "/mods/" + name, "w").write(src)
sys.path.insert(0, W + "/mods")
gpu = subprocess.run("nvidia-smi --query-gpu=name,memory.total --format=csv,noheader", shell=True, capture_output=True, text=True).stdout.strip()
subprocess.run("apt-get install -y -qq zstd >/dev/null 2>&1 || (apt-get update -qq && apt-get install -y -qq zstd)", shell=True, capture_output=True)
subprocess.run("curl -fsSL https://ollama.com/install.sh | sh", shell=True, check=True, capture_output=True)
os.environ["LD_LIBRARY_PATH"] = "/usr/local/nvidia/lib:/usr/local/nvidia/lib64:" + os.environ.get("LD_LIBRARY_PATH", "")
subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
import urllib.request
for _ in range(60):
    try:
        urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=2); break
    except Exception:
        time.sleep(1)
os.environ["FACT_MIND_NUM_CTX"] = NUM_CTX
import fact_mind as fm
from difflib import SequenceMatcher
runs = []
for model in [m.strip() for m in MODEL.split(",") if m.strip()]:
    t = time.time()
    p = subprocess.run(["ollama", "pull", model], capture_output=True, text=True)
    out = {"model": model, "gpu": gpu, "pull_minutes": round((time.time() - t) / 60, 1)}
    if p.returncode != 0:
        out["pull_error"] = (p.stderr or p.stdout)[-300:]
        runs.append(out); continue
    for mode in ("compose", "extract"):
        os.environ["FACT_MIND_MODE"] = mode
        res = []
        for it in INPUT:
            d = fm.draft_one(it, model)
            d.update({"message_id": it["message_id"], "agent": it["agent"], "reply_file": it["reply_file"], "target": it["target"],
                      "similarity": round(SequenceMatcher(None, d.get("body") or "", it["target"] or "").ratio(), 2)})
            res.append(d)
        out[mode] = res
    out["kernel_minutes"] = round((time.time() - t) / 60, 1)
    runs.append(out)
    subprocess.run(["ollama", "rm", model], capture_output=True)  # free disk for the next model
json.dump({"runs": runs, "kernel_minutes": round((time.time() - T0) / 60, 1)}, open(W + "/fact_mind.json", "w"), ensure_ascii=False)
'''


def build(replay_json: str, kernel_dir: str, user: str, model: str = MODEL) -> int:
    items = json.loads(Path(replay_json).read_text())
    sources = {n: (ROOT / p).read_text() for n, p in (("fact_mind.py", "tools/fact_mind.py"),
                                                       ("fact_cards.py", "tools/fact_cards.py"),
                                                       ("claim_evidence.py", "claim_evidence.py"))}
    kd = Path(kernel_dir)
    kd.mkdir(parents=True, exist_ok=True)
    (kd / "run.py").write_text(
        f"import json as _json\nMODEL = {model!r}\nNUM_CTX = {NUM_CTX!r}\n"
        f"SOURCES = _json.loads({json.dumps(sources)!r})\n"
        f"INPUT = _json.loads({json.dumps(items, ensure_ascii=False)!r})\n" + DRIVER)
    (kd / "kernel-metadata.json").write_text(json.dumps({
        "id": f"{user}/{SLUG}", "title": SLUG, "code_file": "run.py", "language": "python",
        "kernel_type": "script", "is_private": True, "enable_gpu": True, "enable_internet": True,
        "dataset_sources": [], "competition_sources": [], "kernel_sources": []}))
    print(f"::notice title=fact mind kaggle::built kernel for {len(items)} messages, model {model}")
    return 0


def collect(out_json: str, private_dir: str) -> int:
    d = json.loads(Path(out_json).read_text())
    runs = d.get("runs") or [d]
    tag = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = Path(private_dir) / "common" / "factmind" / f"kaggle-{tag}.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(d, ensure_ascii=False, indent=1))
    for run in runs:
        if run.get("pull_error"):
            print(f"::warning title=fact mind kaggle::model {run.get('model')} could not be pulled")
            continue
        for mode in ("compose", "extract"):
            r = [x for x in run.get(mode) or [] if not x.get("error")]
            print(f"::notice title=fact mind {mode}::model={run.get('model')} messages={len(run.get(mode) or [])} errors={len(run.get(mode) or []) - len(r)} "
                  f"ready={sum(bool(x.get('ready')) for x in r)} minutes={run.get('kernel_minutes')} gpu_count={len((run.get('gpu') or '').splitlines())}")
    return 0


if __name__ == "__main__":
    a = sys.argv
    if len(a) >= 5 and a[1] == "build":
        sys.exit(build(a[2], a[3], a[4], a[5] if len(a) > 5 else MODEL))
    if len(a) == 4 and a[1] == "collect":
        sys.exit(collect(a[2], a[3]))
    print(__doc__)
    sys.exit(2)
