"""Our public rule applied to local models: a claim stands only with an exact quote we can find.

Shared by tools/common_ensemble.py (benchmark) and the Common drafting mind
(tools/common_deep.py, inside the Kaggle kernel). Bench 17/10 (53 sentences, 22
invented): asking "is it supported?" caught 1-2 of 22; asking for the exact
supporting words and checking them ourselves caught 15-21 of 22.
Stdlib only (runs on bare runners and in Kaggle kernels).
"""
from __future__ import annotations

import re

EVIDENCE_SCHEMA = {"type": "object", "properties": {
    "kind": {"type": "string", "enum": ["greeting", "opinion", "request", "claim", "promise"]},
    "evidence": {"type": "string"}}, "required": ["kind", "evidence"]}
EVIDENCE_PROMPT = (
    "Classify the sentence. kind = greeting (thanks, welcome, sign-off), opinion (a judgement with no factual "
    "content about anyone), request (asking or inviting the other agent to do something), promise (anything neo says it will do later), or claim (any statement of fact about "
    "neo, OSIXBAY, the other agent, or what someone did, does or has). "
    "For a claim, copy into 'evidence' the EXACT words (at least 5 consecutive words, copied character for "
    "character) from the facts or the message that prove it. If no such words exist, leave 'evidence' empty. "
    "Never write evidence in your own words. "
    "Classify the ENTIRE sentence, not just its opening: thanks or an invitation containing a factual "
    "assertion is still a claim; any commitment by neo to future action is a promise, even if the message "
    "contains a similar commitment by someone else. A pure question, suggestion or invitation addressed "
    "to the other agent is a request, not a claim about an action already performed. General advice or "
    "interpretation can be an opinion, but never label a claimed achievement, capability or guaranteed "
    "effect as an opinion. "
    "A claim may PARAPHRASE a fact or the message: its sentence need not share the source's wording. "
    "Still copy the supporting evidence VERBATIM FROM THE SOURCE, not from the draft. You may copy a "
    "longer source passage to supply at least 5 consecutive exact words, even for a short draft sentence. "
    "The passage must support the actual assertion; a merely related passage does not count."
)


def norm(text: str) -> str:
    """Same normalisation as quote_verifier.norm, without its network imports (runs on bare runners)."""
    import html
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = html.unescape(text).replace("`", "").replace("\u2019", "'").replace("\u2018", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    return " ".join(text.lower().split())


def evidence_verdict(out: dict, sentence: str, sources: str) -> str:
    """Our own rule applied to the model: a claim stands only with an exact quote we can find."""
    kind = str(out.get("kind") or "claim")
    if kind == "promise":
        return "unsupported"
    if kind in ("greeting", "request"):
        return "supported"  # 18/10 replay: "Please post your findings..." was blocked as a claim
    ev = norm(str(out.get("evidence") or ""))
    found = len(ev.split()) >= 5 and ev in norm(sources)
    if kind == "opinion":
        return "supported"
    return "supported" if found else "unsupported"




def split_sentences(body: str) -> list[str]:
    """Sentences of a draft, without the leading @mention-only fragment."""
    parts = [s.strip() for s in re.split(r"(?<=[.!?\u3002\uff01\uff1f])\s*|\n+", body or "") if s.strip()]
    return [p for p in parts if not re.fullmatch(r"@\S+[,:]?", p)]
