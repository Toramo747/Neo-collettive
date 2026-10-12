"""Deep mind for the Market Intuition Arena, run on a free Kaggle GPU.

  build   <private_dir> <kernel_dir> <kaggle_username>  -> private Kaggle kernel
  collect <private_dir> <output_json> <minutes>         -> deep_inbox/<stamp>.json
  quota   <private_dir>                                  -> exit 1 if weekly cap reached

The kernel embeds arena_mind.py + local_llm_decoding.py and the queued need
sentences (already public text, people only as hashes). Nothing is printed to
the GitHub log except counts.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL = "qwen2.5:14b-instruct-q4_K_M"
SLUG = "neo-market-mind"
MAX_ITEMS = 200
WEEKLY_CAP_MINUTES = 25 * 60

DRIVER = r'''
import json, os, subprocess, sys, time
T0 = time.time()
W = "/kaggle/working"
os.makedirs(W + "/mods", exist_ok=True)
for name, src in SOURCES.items():
    open(W + "/mods/" + name, "w").write(src)
sys.path.insert(0, W + "/mods")
subprocess.run("curl -fsSL https://ollama.com/install.sh | sh", shell=True, check=True, capture_output=True)
subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
for _ in range(60):
    try:
        import urllib.request; urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=2); break
    except Exception:
        time.sleep(1)
subprocess.run(["ollama", "pull", MODEL], check=True, capture_output=True)
import arena_mind
arena_mind.MAX_JUDGED = len(INPUT["items"])
items = INPUT["items"]
verdicts = arena_mind.judge(MODEL, [x["need"] for x in items])
out_verdicts = [dict(v, person=x["person"]) for x, v in zip(items, verdicts) if v.get("judged")]
real = [dict(x, need=x["need"], problem=v.get("problem")) for x, v in zip(items, verdicts) if v.get("real_need")]
mm = INPUT["market_map"]
thought = arena_mind.think(MODEL, needs=real, market_map=mm, diary=INPUT["diary"],
                           idea_outcomes=INPUT["idea_log"], stats={"judged": len(items), "real": len(real)})
for a in thought.get("assign") or []:
    if 0 <= a["i"] < len(real):
        for v in out_verdicts:
            if v["person"] == real[a["i"]]["person"]:
                v["problem"] = a["problem"]
names = sorted(set(list(mm) + [v["problem"] for v in out_verdicts if v.get("real_need") and v.get("problem")]))
thought["merges"] = arena_mind.consolidate(MODEL, names)
json.dump({"model": MODEL, "verdicts": out_verdicts, "thought": thought,
           "kernel_minutes": round((time.time() - T0) / 60, 1)}, open(W + "/deep.json", "w"))
'''


def build(private_dir: str, kernel_dir: str, username: str) -> int:
    state = json.loads((Path(private_dir) / "market-intuition" / "state.json").read_text())
    items = [{"person": x["person"], "need": x["need"]} for x in (state.get("deep_queue") or [])][-MAX_ITEMS:]
    if not items:
        print("::notice title=Deep mind::queue empty, nothing to do")
        return 3
    mm = {k: {"people": v.get("people", 0), "pay": v.get("pay", 0)} for k, v in (state.get("market_map") or {}).items()}
    payload = {"items": items, "market_map": mm, "diary": (state.get("diary") or [])[-8:],
               "idea_log": (state.get("idea_log") or [])[-15:]}
    sources = {n: (ROOT / n).read_text() for n in ("arena_mind.py", "local_llm_decoding.py")}
    kd = Path(kernel_dir)
    kd.mkdir(parents=True, exist_ok=True)
    (kd / "mind.py").write_text(
        f"MODEL = {MODEL!r}\nSOURCES = {json.dumps(sources)}\nINPUT = {json.dumps(payload, ensure_ascii=False)}\n" + DRIVER)
    (kd / "kernel-metadata.json").write_text(json.dumps({
        "id": f"{username}/{SLUG}", "title": SLUG, "code_file": "mind.py", "language": "python",
        "kernel_type": "script", "is_private": True, "enable_gpu": True, "enable_internet": True,
        "dataset_sources": [], "competition_sources": [], "kernel_sources": []}))
    print(f"::notice title=Deep mind::queued {len(items)} needs, {len(mm)} mapped problems")
    return 0


def _week() -> str:
    y, w, _ = datetime.now(timezone.utc).isocalendar()
    return f"{y}-W{w:02d}"


def quota(private_dir: str) -> int:
    p = Path(private_dir) / "market-intuition" / "deep_usage.json"
    usage = json.loads(p.read_text()) if p.exists() else {}
    used = float(usage.get(_week(), 0))
    print(f"::notice title=Deep mind quota::{used:.0f} of {WEEKLY_CAP_MINUTES} GPU minutes used this week")
    return 1 if used >= WEEKLY_CAP_MINUTES else 0


def collect(private_dir: str, output_json: str, minutes: str) -> int:
    base = Path(private_dir) / "market-intuition"
    data = json.loads(Path(output_json).read_text())
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    data["run_id"] = stamp
    data["minutes"] = float(minutes)
    (base / "deep_inbox").mkdir(parents=True, exist_ok=True)
    (base / "deep_inbox" / f"{stamp}.json").write_text(json.dumps(data, ensure_ascii=False))
    p = base / "deep_usage.json"
    usage = json.loads(p.read_text()) if p.exists() else {}
    usage[_week()] = round(float(usage.get(_week(), 0)) + float(minutes), 1)
    p.write_text(json.dumps(usage))
    v = data.get("verdicts") or []
    print("::notice title=Deep mind result::" + json.dumps({
        "judged": len(v), "real": sum(1 for x in v if x.get("real_need")),
        "merges": len((data.get("thought") or {}).get("merges") or []),
        "kernel_minutes": data.get("kernel_minutes"), "wall_minutes": float(minutes)}))
    return 0


if __name__ == "__main__":
    cmd, *args = sys.argv[1:]
    raise SystemExit({"build": build, "collect": collect, "quota": quota}[cmd](*args))
