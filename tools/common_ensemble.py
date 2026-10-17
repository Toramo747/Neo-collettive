"""Ensemble experiment: can several local models together check drafts better
and cheaper than one big model alone?

Method ("one thinks, all check, the big one decides only on doubt"):
  each sentence of a draft is judged supported / unsupported against the public
  facts (docs/common-voice.md) and the message it answers.
    A  single   qwen2.5 14B judges every sentence (what the drafting mind does today)
    B  ensemble llama3.1 8B + gemma2 9B judge every sentence in parallel; when they
                agree that is the verdict, when they disagree the 14B decides
    C  vote3    majority of the three models (reference)
  Metrics against Andrea-grade labels (common/bench/claims-v1.json, private):
  recall on invented sentences, false alarms on good ones, GPU seconds.

  build   <private_dir> <kernel_dir> <kaggle_username>
  collect <private_dir> <output_json>     -> common/bench/result-<stamp>.json + counts in the log
Sentences and messages stay in the private archive and a private kernel; logs print metrics only.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SLUG = "neo-common-ensemble"
BIG = "qwen2.5:14b-instruct-q4_K_M"
SMALL = ["llama3.1:8b", "gemma2:9b"]
BENCH = "common/bench/claims-v1.json"

DRIVER = r'''
import json, os, subprocess, sys, time, threading, urllib.request
T0 = time.time()
subprocess.run("apt-get install -y -qq zstd >/dev/null 2>&1 || (apt-get update -qq && apt-get install -y -qq zstd)", shell=True, capture_output=True)
subprocess.run("curl -fsSL https://ollama.com/install.sh | sh", shell=True, check=True, capture_output=True)
os.environ["LD_LIBRARY_PATH"] = "/usr/local/nvidia/lib:/usr/local/nvidia/lib64:" + os.environ.get("LD_LIBRARY_PATH", "")
env = dict(os.environ, OLLAMA_MAX_LOADED_MODELS="3", OLLAMA_NUM_PARALLEL="2")
subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
for _ in range(60):
    try:
        urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=2); break
    except Exception:
        time.sleep(1)
for m in [BIG] + SMALL:
    subprocess.run(["ollama", "pull", m], check=True, capture_output=True)
SCHEMA = {"type": "object", "properties": {"verdict": {"type": "string", "enum": ["supported", "unsupported"]},
          "why": {"type": "string"}}, "required": ["verdict", "why"]}

def ask(model, row):
    prompt = (
        "You check one sentence of a reply that the agent neo (OSIXBAY) wants to post.\n"
        "<facts>\n" + INPUT["voice"] + "\n</facts>\n"
        "<message_it_answers>\n" + row["source_body"] + "\n</message_it_answers>\n"
        "<sentence>\n" + row["sentence"] + "\n</sentence>\n"
        "Answer 'unsupported' if the sentence states something about neo, OSIXBAY or the other agent that is NOT in "
        "the facts or the message (an invented action, process, history, result or feeling), contradicts the facts, "
        "or promises future action. Answer 'supported' if it is backed by the facts or the message, or is only a "
        "greeting, thanks or harmless opinion. The sentence may be in any language."
    )
    body = json.dumps({"model": model, "prompt": prompt, "stream": False, "format": SCHEMA,
                       "options": {"temperature": 0, "num_predict": 200}, "keep_alive": "30m"}).encode()
    t = time.time()
    try:
        req = urllib.request.Request("http://127.0.0.1:11434/api/generate", data=body,
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=300) as r:
            out = json.loads(json.loads(r.read().decode()).get("response") or "{}")
        v = out.get("verdict") if out.get("verdict") in ("supported", "unsupported") else "supported"
    except Exception:
        v = "error"
    return v, round(time.time() - t, 2)

# warm up every model once so load time is not charged to the first sentence
for m in [BIG] + SMALL:
    ask(m, INPUT["rows"][0])
res = []
for row in INPUT["rows"]:
    out = {}
    def run(m):
        out[m] = ask(m, row)
    ths = [threading.Thread(target=run, args=(m,)) for m in SMALL]
    t = time.time()
    [x.start() for x in ths]; [x.join() for x in ths]
    small_wall = round(time.time() - t, 2)
    big = ask(BIG, row)
    res.append({"n": row["n"], "big": big[0], "big_s": big[1], "small_wall_s": small_wall,
                **{m: out[m][0] for m in SMALL}})
json.dump({"results": res, "minutes": round((time.time() - T0) / 60, 1)}, open("/kaggle/working/ensemble.json", "w"))
'''


PROMPT_TAIL = (
    "Answer 'unsupported' if the sentence states something about neo, OSIXBAY or the other agent that is NOT in "
    "the facts or the message (an invented action, process, history, result or feeling), contradicts the facts, "
    "or promises future action. Answer 'supported' if it is backed by the facts or the message, or is only a "
    "greeting, thanks or harmless opinion. The sentence may be in any language."
)


EVIDENCE_SCHEMA = {"type": "object", "properties": {
    "kind": {"type": "string", "enum": ["greeting", "opinion", "claim", "promise"]},
    "evidence": {"type": "string"}}, "required": ["kind", "evidence"]}
EVIDENCE_PROMPT = (
    "Classify the sentence. kind = greeting (thanks, welcome, sign-off), opinion (a judgement with no factual "
    "content about anyone), promise (anything neo says it will do later), or claim (any statement of fact about "
    "neo, OSIXBAY, the other agent, or what someone did, does or has). "
    "For a claim, copy into 'evidence' the EXACT words (at least 5 consecutive words, copied character for "
    "character) from the facts or the message that prove it. If no such words exist, leave 'evidence' empty. "
    "Never write evidence in your own words."
)


def _norm(text: str) -> str:
    """Same normalisation as quote_verifier.norm, without its network imports (runs on bare runners)."""
    import html
    import re
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = html.unescape(text).replace("`", "").replace("\u2019", "'").replace("\u2018", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    return " ".join(text.lower().split())


def evidence_verdict(out: dict, sentence: str, sources: str) -> str:
    """Our own rule applied to the model: a claim stands only with an exact quote we can find."""
    kind = str(out.get("kind") or "claim")
    if kind == "promise":
        return "unsupported"
    if kind == "greeting":
        return "supported"
    ev = _norm(str(out.get("evidence") or ""))
    found = len(ev.split()) >= 5 and ev in _norm(sources)
    if kind == "opinion":
        return "supported"
    return "supported" if found else "unsupported"


def judge(private_dir: str, model: str, out_json: str, mode: str = "verdict") -> int:
    """Run one model over the bench against a local ollama (GitHub runner, CPU). Writes verdicts only.

    mode=verdict   the model says supported/unsupported (17/10 run: ~5-9% of inventions caught)
    mode=evidence  the model must quote exact supporting words; we check the quote ourselves
    """
    import time
    import urllib.request
    rows = json.loads((Path(private_dir) / BENCH).read_text())
    voice = (ROOT / "docs" / "common-voice.md").read_text()
    schema = {"type": "object", "properties": {"verdict": {"type": "string", "enum": ["supported", "unsupported"]}},
              "required": ["verdict"]}
    res = {}
    for r in rows:
        head = ("You check one sentence of a reply that the agent neo (OSIXBAY) wants to post.\n<facts>\n" + voice
                + "\n</facts>\n<message_it_answers>\n" + r["source_body"] + "\n</message_it_answers>\n<sentence>\n"
                + r["sentence"] + "\n</sentence>\n")
        prompt = head + (EVIDENCE_PROMPT if mode == "evidence" else PROMPT_TAIL)
        fmt = EVIDENCE_SCHEMA if mode == "evidence" else schema
        body = json.dumps({"model": model, "prompt": prompt, "stream": False, "format": fmt,
                           "options": {"temperature": 0, "num_predict": 160}, "keep_alive": "60m"}).encode()
        t = time.time()
        try:
            req = urllib.request.Request("http://127.0.0.1:11434/api/generate", data=body,
                                         headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=900) as resp:
                out = json.loads(json.loads(resp.read().decode()).get("response") or "{}")
            if mode == "evidence":
                v = evidence_verdict(out, r["sentence"], voice + "\n" + r["source_body"])
            else:
                v = out.get("verdict") if out.get("verdict") in ("supported", "unsupported") else "supported"
        except Exception:
            v = "error"
        res[str(r["n"])] = {"verdict": v, "s": round(time.time() - t, 2)}
    Path(out_json).write_text(json.dumps({"model": model, "mode": mode, "results": res}))
    print(f"::notice title=ensemble judge::{model} mode={mode} sentences={len(res)} errors={sum(x['verdict']=='error' for x in res.values())}")
    return 0


def merge(out_json: str, *files: str) -> int:
    """Combine per-model verdict files into the kernel output format (small models ran in parallel)."""
    by_model = {}
    for f in files:
        d = json.loads(Path(f).read_text())
        by_model[d["model"]] = d["results"]
    big = by_model[BIG]
    results = []
    for n, b in big.items():
        smalls = [by_model[m][n] for m in SMALL]
        results.append({"n": int(n), "big": b["verdict"], "big_s": b["s"],
                        "small_wall_s": max(x["s"] for x in smalls),
                        **{m: by_model[m][n]["verdict"] for m in SMALL}})
    Path(out_json).write_text(json.dumps({"results": sorted(results, key=lambda r: r["n"]), "minutes": None,
                                          "hardware": "github-runner-cpu"}))
    return 0


def build(private_dir: str, kernel_dir: str, username: str) -> int:
    rows = json.loads((Path(private_dir) / BENCH).read_text())
    payload = {"rows": [{k: r[k] for k in ("n", "sentence", "source_body")} for r in rows],
               "voice": (ROOT / "docs" / "common-voice.md").read_text()}
    kd = Path(kernel_dir)
    kd.mkdir(parents=True, exist_ok=True)
    (kd / "ensemble.py").write_text(
        f"import json as _json\nBIG = {BIG!r}\nSMALL = {SMALL!r}\n"
        f"INPUT = _json.loads({json.dumps(payload, ensure_ascii=False)!r})\n" + DRIVER)
    (kd / "kernel-metadata.json").write_text(json.dumps({
        "id": f"{username}/{SLUG}", "title": SLUG, "code_file": "ensemble.py", "language": "python",
        "kernel_type": "script", "is_private": True, "enable_gpu": True, "enable_internet": True,
        "dataset_sources": [], "competition_sources": [], "kernel_sources": []}))
    print(f"::notice title=ensemble::{len(rows)} sentences")
    return 0


def score(labels: dict[int, str], verdicts: dict[int, str]) -> dict:
    bad = [n for n, l in labels.items() if l == "unsupported"]
    good = [n for n, l in labels.items() if l == "supported"]
    caught = sum(verdicts.get(n) == "unsupported" for n in bad)
    false_alarms = sum(verdicts.get(n) == "unsupported" for n in good)
    errors = sum(verdicts.get(n) == "error" for n in labels)
    return {"caught": caught, "of_invented": len(bad), "recall": round(caught / len(bad), 2) if bad else None,
            "false_alarms": false_alarms, "of_good": len(good),
            "false_alarm_rate": round(false_alarms / len(good), 2) if good else None, "errors": errors}


def evaluate(rows: list[dict], results: list[dict]) -> dict:
    labels = {r["n"]: r["label"] for r in rows}
    a, b, c = {}, {}, {}
    sec = {"single": 0.0, "ensemble": 0.0, "vote3": 0.0}
    escalated = 0
    for r in results:
        n, big = r["n"], r["big"]
        s1, s2 = (r.get(m) for m in SMALL)
        a[n] = big
        sec["single"] += r["big_s"]
        if s1 == s2 and s1 != "error":
            b[n] = s1
            sec["ensemble"] += r["small_wall_s"]
        else:
            b[n] = big
            escalated += 1
            sec["ensemble"] += r["small_wall_s"] + r["big_s"]
        votes = [v for v in (big, s1, s2) if v in ("supported", "unsupported")]
        c[n] = "unsupported" if votes.count("unsupported") >= 2 else "supported"
        sec["vote3"] += max(r["small_wall_s"], r["big_s"])
    return {"single_14b": dict(score(labels, a), seconds=round(sec["single"], 1)),
            "ensemble": dict(score(labels, b), seconds=round(sec["ensemble"], 1), escalated_to_14b=escalated),
            "vote3": dict(score(labels, c), seconds=round(sec["vote3"], 1)),
            **{f"alone_{m}": score(labels, {r["n"]: r.get(m) for r in results}) for m in SMALL}}


def collect(private_dir: str, output_json: str) -> int:
    rows = json.loads((Path(private_dir) / BENCH).read_text())
    data = json.loads(Path(output_json).read_text())
    metrics = evaluate(rows, data.get("results") or [])
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = Path(private_dir) / "common" / "bench" / f"result-{stamp}.json"
    out.write_text(json.dumps({"bench": BENCH, "models": {"big": BIG, "small": SMALL}, "kernel_minutes": data.get("minutes"),
                               "hardware": data.get("hardware", "kaggle-gpu"),
                               "metrics": metrics, "results": data.get("results")}, indent=1))
    print("::notice title=ensemble metrics::" + json.dumps(metrics))
    return 0


if __name__ == "__main__":
    cmd, *args = sys.argv[1:]
    raise SystemExit({"build": build, "collect": collect, "judge": judge, "merge": merge}[cmd](*args))
