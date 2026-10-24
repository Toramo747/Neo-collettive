# SPDX-License-Identifier: BUSL-1.1
"""Security audit of a public MCP server before an agent connects to it (24/10, draft, paid via x402).

Input: the result of mcp_endpoint_verifier.verify_endpoint(..., full_tools=True), which reads initialize and
tools/list only (never calls a remote tool, never forwards credentials). This module judges what was declared:

  poisoning     hidden instructions in tool descriptions or parameter schemas (the "tool poisoning" attack):
                prompt-injection evidence, tool-poisoning phrases, invisible characters
  shadowing     a tool that tells the model how to use *other* tools or servers
  capabilities  what the tools can do: run code, touch files, send data out, move money, delete, handle secrets
  annotations   readOnlyHint/destructiveHint that contradict what the description says
  transport     TLS/reachability/schema errors reported by the verifier
  fingerprint   sha256 of the canonical tool list, so a later audit shows a silent change ("rug pull")

Output: risk score 0-100, grade A-F, findings with evidence. Rule-based evidence, not a verdict on intent.
"""
from __future__ import annotations

import hashlib
import json
import re

import prompt_injection_scan as pis

POISON = [r"<\s*important\s*>", r"\bbefore (using|calling) (this|any) tool\b", r"\b(do not|don't|never) (tell|mention|inform|show)\b[^.]{0,40}\buser\b",
          r"~/\.(ssh|aws|cursor|config|gnupg)\b", r"\bid_rsa\b", r"\bmcp\.json\b", r"\b(pass|include|send|put)\b[^.]{0,60}\b(contents? of|full conversation|chat history|all previous messages)\b",
          r"\bsidenote\b", r"\bthe user (must|should) not (see|know)\b", r"\bsecretly\b", r"\bwithout (asking|telling|confirmation)\b"]
SHADOW = [r"\bwhen (using|calling) (the )?\w+ tool\b", r"\binstead of (the|using) \w+\b", r"\b(all|any) other tools?\b",
          r"\bother (mcp )?servers?\b", r"\bthis tool (must|should) (always )?be (called|used) (first|before)\b"]
CAPS = {
    "code_execution": r"\b(exec(ute)?|shell|bash|command line|run[_ ]?(code|command|script)|eval|subprocess|terminal)\b",
    "filesystem": r"\b(read|write|delete|list)[_ ]?(file|dir(ectory)?|folder)s?\b|\bfile ?path\b|\bfilesystem\b",
    "network_egress": r"\b(http request|fetch (a |any )?url|webhook|send[_ ]?(email|message|sms)|post to|upload)\b",
    "payments": r"\b(transfer|send (funds|money|usdc|eth)|sign[_ ]?transaction|private key|wallet|approve (token|spending))\b",
    "destructive": r"\b(delete|drop|truncate|destroy|wipe|remove)[_ ]?(all|table|database|records?|files?|users?)?\b",
    "secrets": r"\b(api[_ ]?key|password|token|secret|credential)s?\b",
}
CAP_WEIGHT = {"code_execution": 15, "filesystem": 8, "network_egress": 8, "payments": 15, "destructive": 8, "secrets": 6}


def fingerprint(tools: list[dict]) -> str:
    canon = sorted(({"n": t.get("name"), "d": t.get("description"), "s": t.get("input_schema")} for t in tools), key=lambda x: str(x["n"]))
    return hashlib.sha256(json.dumps(canon, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def audit(verified: dict, previous_fingerprint: str | None = None) -> dict:
    tl = ((verified.get("checks") or {}).get("tools_list") or {})
    tools = tl.get("full_tools") or []
    findings: list[dict] = []
    caps: dict[str, list[str]] = {}
    score = 0
    for t in tools:
        name = t.get("name") or "?"
        desc, schema = str(t.get("description") or ""), str(t.get("input_schema") or "")
        text = desc + "\n" + schema
        inj = pis.scan(text)
        if inj["level"] in ("medium", "high"):
            findings.append({"severity": "high", "type": "poisoning", "tool": name,
                             "evidence": "; ".join(f["type"] + ": " + f["evidence"] for f in inj["findings"][:3])[:400]})
            score += 35 if inj["level"] == "high" else 20
        for p in POISON:
            m = re.search(p, text, re.I)
            if m:
                findings.append({"severity": "high", "type": "poisoning", "tool": name, "evidence": text[max(0, m.start() - 40):m.end() + 60].replace("\n", " ")[:200]})
                score += 30
                break
        for p in SHADOW:
            m = re.search(p, desc, re.I)
            if m:
                findings.append({"severity": "medium", "type": "shadowing", "tool": name, "evidence": desc[max(0, m.start() - 40):m.end() + 60][:200]})
                score += 15
                break
        if len(desc) > 3000:
            findings.append({"severity": "low", "type": "long_description", "tool": name, "evidence": f"{len(desc)} chars: room to hide instructions"})
            score += 3
        found = [c for c, p in CAPS.items() if re.search(p, name + " " + text, re.I)]
        for c in found:
            caps.setdefault(c, []).append(name)
        ann = t.get("annotations") or {}
        if ann.get("readOnlyHint") is True and {"destructive", "code_execution", "payments"} & set(found):
            findings.append({"severity": "medium", "type": "annotation_mismatch", "tool": name,
                             "evidence": f"declares readOnlyHint but describes {sorted({'destructive','code_execution','payments'} & set(found))}"})
            score += 10
    for c, names in caps.items():
        score += CAP_WEIGHT[c]
        findings.append({"severity": "info", "type": "capability", "capability": c, "tools": names[:10]})
    errs = verified.get("errors") or []
    if errs:
        findings.append({"severity": "medium", "type": "transport", "evidence": ", ".join(map(str, errs))[:200]})
        score += 10
    fp = fingerprint(tools) if tools else None
    changed = bool(previous_fingerprint and fp and previous_fingerprint != fp)
    if changed:
        findings.append({"severity": "medium", "type": "changed_since_last_audit", "evidence": "tool definitions differ from the previous audit we signed"})
        score += 15
    score = min(100, score)
    grade = "A" if score < 10 else "B" if score < 25 else "C" if score < 45 else "D" if score < 70 else "F"
    if not tools:
        grade = "unknown"
    return {"ok": True, "url": (verified.get("input") or {}).get("url"), "live": verified.get("live"),
            "tool_count": len(tools), "risk_score": score, "grade": grade,
            "findings": sorted(findings, key=lambda f: ["high", "medium", "low", "info"].index(f["severity"]))[:60],
            "capabilities": {c: len(n) for c, n in caps.items()}, "tools_fingerprint": fp,
            "changed_since_last_audit": changed if previous_fingerprint else None,
            "method": "initialize + tools/list only; no remote tool was called, no credentials were sent",
            "note": "Rule-based evidence, not a verdict on intent. Keep the fingerprint: a later audit with a different one means the tools changed."}
