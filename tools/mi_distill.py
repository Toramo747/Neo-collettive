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


def _voice_sentence(row: dict) -> str:
    if ami.mi.classify_row(row) != "demand":
        return ""
    for sent in ami.SENT_SPLIT.split(row.get("title", "") + ". " + row.get("excerpt", "")):
        if 30 <= len(sent) <= 300 and (ami.mi.VOICE_RE.search(sent) or ami.mi.QUESTION_RE.search(sent) or ami.mi.PAY_RE.search(sent)):
            return sent.strip()
    return ""


def _archive_v1(private_dir: str) -> None:
    """v2 (2026-10-16): keep the v1 data apart; it may train but never evaluate v2."""
    d = _dir(private_dir)
    v1 = d / "v1"
    if v1.exists() or not (d / "candidates.jsonl").exists():
        return
    v1.mkdir()
    for name in ("candidates.jsonl", "train.jsonl", "holdout.jsonl", "eval_report.json", "spot_check_for_andrea.jsonl"):
        if (d / name).exists():
            (d / name).rename(v1 / name)


def _v1_rows(private_dir: str) -> list[dict]:
    v1 = _dir(private_dir) / "v1"
    rows = []
    for name in ("train.jsonl", "holdout.jsonl"):
        p = v1 / name
        if p.exists():
            rows += [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
    return rows


def harvest(private_dir: str, max_queries: int = 900, getter=ami.http_json) -> int:
    _archive_v1(private_dir)
    state_p = Path(private_dir) / "market-intuition" / "state.json"
    state = json.loads(state_p.read_text()) if state_p.exists() else {}
    vocab = sorted((state.get("vocabulary") or {}).items(), key=lambda kv: -kv[1])
    terms = list(dict.fromkeys(list(ami.SEED_TERMS) + list(ami.FOCUS_TERMS) + [t for t, _ in vocab[:80]]))
    phrases = list(dict.fromkeys(list(ami.PHRASES) + list(state.get("learned_phrases") or [])))
    rng = random.Random(20261012)
    plan = []
    for term in terms:
        for ph in rng.sample(phrases, min(8, len(phrases))):
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
            kind = "arena_candidate"
            if not sent:
                # Broader pool: any first-person need/question sentence, so the
                # student also learns what is NOT a real need (the teacher decides).
                sent, kind = _voice_sentence(row), "voice_sentence"
            if sent:
                seen.add(row["person"])
                out.append({"id": hashlib.sha256((row["person"] + sent).encode()).hexdigest()[:16],
                            "person": row["person"], "need": sent[:300], "term": q["term"], "kind": kind})
        if len(out) >= MAX_CANDIDATES:
            break
        if getter is ami.http_json:
            time.sleep(0.25)
    (_dir(private_dir) / "candidates.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in out))
    arena = sum(1 for x in out if x["kind"] == "arena_candidate")
    print(f"::notice title=Distill harvest::queries={len(plan)} errors={errors} candidates={len(out)} arena_like={arena}")
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
    code = (f"import json as _json\nMODEL = {TEACHER!r}\nSOURCES = _json.loads({json.dumps(sources)!r})\n"
            f"INPUT = _json.loads({json.dumps({'items': items}, ensure_ascii=False)!r})\n" + LABEL_DRIVER)
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
    prior = _v1_rows(private_dir)
    prior_people = {r["person"] for r in prior}
    # Held-out people are fresh: never seen by v1 training or v1 evaluation.
    persons = sorted({r["person"] for r in rows} - prior_people)
    rng.shuffle(persons)
    hold = set(persons[: int(len(persons) * HOLDOUT_FRACTION)])
    seen_ids = {r["id"] for r in rows}
    train = [r for r in rows if r["person"] not in hold]
    train += [r for r in prior if r["person"] not in hold and r.get("id") not in seen_ids]
    test = [r for r in rows if r["person"] in hold]
    (d / "train.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in train))
    (d / "holdout.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in test))
    real = sum(1 for r in rows if r["label"].get("real_need"))
    print(f"::notice title=Distill labels::labeled={len(rows)} real={real} train={len(train)} v1_reused={len(train) - sum(1 for r in rows if r['person'] not in hold)} holdout={len(test)} "
          f"partial={bool(data.get('partial'))} minutes={data.get('minutes')}")
    return 0


TRAIN_DRIVER = r'''
import json, os, random, subprocess, sys, time
T0 = time.time()
W = "/kaggle/working"
subprocess.run("pip install -q unsloth", shell=True, check=True)
from unsloth import FastLanguageModel
from datasets import Dataset
from trl import SFTTrainer, SFTConfig
model, tok = FastLanguageModel.from_pretrained(STUDENT, max_seq_length=1536, load_in_4bit=True)
model = FastLanguageModel.get_peft_model(model, r=16, lora_alpha=16, lora_dropout=0,
    target_modules=["q_proj","k_proj","v_proj","o_proj","gate_proj","up_proj","down_proj"],
    use_gradient_checkpointing="unsloth", random_state=7)
rows = INPUT["train"]
rng = random.Random(7)
texts = []
for rep in range(4):                      # 4 different groupings of the same sentences
    order = rows[:]
    rng.shuffle(order)
    for i in range(0, len(order), 6):
        batch = order[i:i + 6]
        prompt = PROMPT_HEAD + "\n".join(f"{j}: {r['need'][:300]}" for j, r in enumerate(batch))
        target = json.dumps({"verdicts": [{"i": j, "real_need": bool(r["label"].get("real_need")),
                  "problem": r["label"].get("problem") or "", "would_pay": r["label"].get("would_pay") or "unknown"}
                  for j, r in enumerate(batch)]}, ensure_ascii=False)
        msgs = [{"role": "user", "content": prompt}, {"role": "assistant", "content": target}]
        texts.append(tok.apply_chat_template(msgs, tokenize=False))
ds = Dataset.from_dict({"text": texts})
trainer = SFTTrainer(model=model, tokenizer=tok, train_dataset=ds, args=SFTConfig(
    dataset_text_field="text", max_seq_length=1536, per_device_train_batch_size=2,
    gradient_accumulation_steps=4, num_train_epochs=2, learning_rate=2e-4, warmup_steps=10,
    logging_steps=10, optim="adamw_8bit", seed=7, output_dir=W + "/out", report_to="none", fp16=True))
stats = trainer.train()
model.save_pretrained_gguf(W + "/student", tok, quantization_method="q4_k_m")
json.dump({"examples": len(texts), "train_loss": float(stats.training_loss),
           "minutes": round((time.time() - T0) / 60, 1)}, open(W + "/train.json", "w"))
'''


def train_build(private_dir: str, kernel_dir: str, username: str) -> int:
    d = _dir(private_dir)
    train = [json.loads(l) for l in (d / "train.jsonl").read_text().splitlines() if l.strip()]
    import arena_mind
    head = arena_mind.judge_prompt(["X"]).rsplit("\n\n", 1)[0] + "\n\n"
    code = (f"STUDENT = {STUDENT_HF!r}\nPROMPT_HEAD = {head!r}\n"
            f"import json as _json\nINPUT = _json.loads({json.dumps({'train': [{'need': r['need'], 'label': r['label']} for r in train]}, ensure_ascii=False)!r})\n"
            + TRAIN_DRIVER)
    _kernel(Path(kernel_dir), username, TRAIN_SLUG, code)
    print(f"::notice title=Distill train::sentences={len(train)}")
    return 0


if __name__ == "__main__":
    cmd, *args = sys.argv[1:]
    fn = {"harvest": harvest, "label-build": label_build, "label-collect": label_collect,
          "train-build": train_build}[cmd]
    raise SystemExit(fn(*args))
