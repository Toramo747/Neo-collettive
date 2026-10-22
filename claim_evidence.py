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
    if kind == "greeting":
        return "supported"
    ev = norm(str(out.get("evidence") or ""))
    found = len(ev.split()) >= 5 and ev in norm(sources)
    if kind == "opinion":
        return "supported"
    return "supported" if found else "unsupported"




def split_sentences(body: str) -> list[str]:
    """Sentences of a draft, without the leading @mention-only fragment."""
    # 21/10: a Latin . ! ? ends a sentence only before whitespace and not as part of
    # "..." (before, "v0.99.68" and "..." were cut into fragments like "99." that the
    # checkers then failed). Chinese 。！？ end a sentence anywhere.
    parts = [s.strip() for s in re.split(r"(?<=[\u3002\uff01\uff1f])\s*|(?<=[.!?])(?<!\.\.)\s+|\n+", body or "")
             if s.strip()]
    return [p for p in parts if not re.fullmatch(r"@\S+[,:]?", p)]
