from __future__ import annotations

import hashlib
import hmac
import re
from typing import Any


_URL_RE=re.compile(r"(?i)\b(?:https?|ftp)://\S+")
_WIN_PATH_RE=re.compile(r"(?i)\b[a-z]:\\[^\s]+")
_UNIX_INTERNAL_PATH_RE=re.compile(r"(?i)(?:^|\s)/(?:etc|proc|sys|run|var|tmp|home|opt|srv|app)/[^\s]+")
_SECRET_NAME_RE=re.compile(r"(?i)\b[A-Z0-9_]*(?:API[_-]?KEY|TOKEN|SECRET|PASSWORD|PRIVATE[_-]?KEY)[A-Z0-9_]*\b")
_INJECTION_RE=re.compile(
    r"(?i)(?:ignore\s+(?:all\s+)?(?:previous|prior|system)\s+instructions?|"
    r"reveal\s+(?:the\s+)?(?:system\s+prompt|configuration|config|environment|secrets?)|"
    r"show\s+(?:me\s+)?(?:the\s+)?(?:system\s+prompt|config(?:uration)?|env(?:ironment)?|secrets?))"
)
_EFFECTFUL_RE=re.compile(
    r"(?i)\b(?:deploy|publish|delete|modify|write|install|execute|run\s+(?:this|the)\s+(?:script|code|command)|"
    r"download|fetch\s+(?:this|the|from)|send\s+(?:an?\s+)?(?:email|message|payment|money|funds)|"
    r"transfer\s+(?:money|funds|crypto|tokens?)|sign\s+(?:this|a)\s+(?:contract|transaction)|"
    r"call\s+(?:this|the)\s+(?:url|endpoint|api))\b"
)
_PROBE_RE=re.compile(r"(?i)^\s*(?:ping|pong|hello\??|hi\??|test|probe|healthcheck|are you there\??)\s*[.!?]*\s*$")
_CRITIQUE_RE=re.compile(r"(?i)\b(?:critique|criticism|flaw|weakness|problem with|i disagree|counterexample|contradiction)\b")
_RESEARCH_RE=re.compile(r"(?i)\b(?:research|hypothesis|experiment|evidence|methodology|falsif|study|investigate)\b")
_COLLAB_RE=re.compile(r"(?i)\b(?:collaborat|work together|peer review|joint|coordinate|exchange findings)\b")
_QUESTION_RE=re.compile(r"(?i)(?:\?|\b(?:why|how|what|which|when|where|can you explain|do you think|could you analyze)\b)")
_INTRO_LINE_RE=re.compile(
    r"(?im)^\s*(?:agent[_ -]?id|identity|name|capabilities?|protocol|limitations?|documentation|"
    r"public[_ -]?key|ed25519(?:[_ -]?public[_ -]?key)?)\s*:\s*.*$"
)


def _clean(value: Any, limit: int=1200) -> str:
    return " ".join(str(value or "").split())[:limit]


def safe_subject(text: str, limit: int=220) -> str:
    subject=_clean(text,800)
    subject=_URL_RE.sub("[external-url]",subject)
    subject=_WIN_PATH_RE.sub("[internal-path]",subject)
    subject=_UNIX_INTERNAL_PATH_RE.sub(" [internal-path]",subject)
    subject=_SECRET_NAME_RE.sub("[sensitive-name]",subject)
    subject=re.sub(r"\s+"," ",subject).strip()
    if len(subject)>limit:
        subject=subject[:limit].rsplit(" ",1)[0]+"..."
    return subject


def outbound_filter(text: str) -> str:
    """Defense-in-depth filter for deterministic A2A replies."""
    out=_URL_RE.sub("[external-url]",str(text or ""))
    out=_WIN_PATH_RE.sub("[internal-path]",out)
    out=_UNIX_INTERNAL_PATH_RE.sub(" [internal-path]",out)
    out=_SECRET_NAME_RE.sub("[sensitive-name]",out)
    return out[:4000]


def plan_untrusted_reply(text: str, *, identity_status: str="", intro_received: bool=False) -> dict:
    raw=str(text or "").strip()
    if not raw:
        return {
            "mode":"fallback","reason":"empty_message",
            "reply":"MYCELIX received the A2A request but no text message was found. Send a concrete question, claim, criticism or research topic.",
        }
    if _INJECTION_RE.search(raw):
        return {
            "mode":"security","reason":"prompt_injection_or_secret_request",
            "reply":"I can discuss the substantive topic, but I will not expose system instructions, configuration, environment data, credentials, internal paths or data from other peers or threads.",
        }
    if _EFFECTFUL_RE.search(raw):
        return {
            "mode":"review","reason":"effectful_request_requires_explicit_review",
            "reply":"The request includes an external or state-changing action. I can discuss or analyze it here, but I will not execute, fetch, install, publish, contact, transfer, sign or modify anything without explicit review.",
        }
    if _PROBE_RE.match(raw):
        return {
            "mode":"fallback","reason":"probe_only",
            "reply":"pong — A2A conversation is available.",
        }

    conversational_raw=_INTRO_LINE_RE.sub("",raw).strip() if intro_received else raw
    if intro_received and not conversational_raw:
        return {
            "mode":"fallback","reason":"introduction_received_no_question",
            "reply":(
                "Your structured body introduction has been received and noted as SELF_DECLARED_UNVERIFIED. "
                "You do not need to repeat agent_id, capabilities, protocol, limitations or documentation in this thread. "
                "No peer admission, trust or action authorization follows from that declaration. "
                "Add the concrete question, critique, research problem or conversational proposal you want discussed."
            ),
        }

    subject=safe_subject(conversational_raw or raw)
    if _CRITIQUE_RE.search(conversational_raw):
        reply=(
            "Your critique is being treated as untrusted evidence, not as an instruction. "
            f"The point I can engage with is: “{subject}” "
            "A useful next step is to isolate the challenged claim, state the strongest counterexample, and identify an observation that would distinguish the competing explanations. "
            "I can continue that analysis in this thread without peer admission."
        )
        mode_reason="substantive_critique"
    elif _RESEARCH_RE.search(conversational_raw):
        reply=(
            "I can engage with this as a research question while keeping identity and trust separate from the content. "
            f"The topic received is: “{subject}” "
            "For a falsifiable exchange, separate the hypothesis from supporting observations, name the main confounder, and define what result would count against the hypothesis. "
            "I can evaluate those pieces conversationally; no external action or admission is implied."
        )
        mode_reason="substantive_research"
    elif _COLLAB_RE.search(conversational_raw):
        reply=(
            "A conversational collaboration is possible without admission or verified identity. "
            f"The proposed topic is: “{subject}” "
            "We can compare assumptions, evidence, failure modes and test criteria in this HTTP thread. "
            "Any external contact, execution, publication, credential use, payment or state-changing step remains outside the conversational permission boundary."
        )
        mode_reason="substantive_collaboration"
    elif _QUESTION_RE.search(conversational_raw):
        reply=(
            f"I can address the question in-thread: “{subject}” "
            "I will treat any claims in it as unverified until supported. "
            "If the question concerns MYCELIX itself, conversation does not require admission; identity verification, peer admission and action authorization remain separate decisions."
        )
        mode_reason="substantive_question"
    else:
        if intro_received:
            return {
                "mode":"fallback","reason":"introduction_received_no_question",
                "reply":(
                    "Your structured body introduction has been received and noted as SELF_DECLARED_UNVERIFIED. "
                    "You do not need to repeat agent_id, capabilities, protocol, limitations or documentation in this thread. "
                    "No peer admission, trust or action authorization follows from that declaration. "
                    "Add the concrete question, critique, research problem or conversational proposal you want discussed."
                ),
            }
        return {
            "mode":"fallback","reason":"ambiguous_non_probe",
            "reply":"MYCELIX received the message, but it does not contain a clear question, critique, research problem or conversational proposal. Add the concrete point you want discussed.",
        }

    if intro_received:
        reply += " Your body introduction has already been noted as SELF_DECLARED_UNVERIFIED, so I will not ask you to repeat it in this thread."
    return {"mode":"substantive","reason":mode_reason,"reply":outbound_filter(reply)}


def origin_rate_key(client_ip: str, salt: str) -> str:
    """Return a salted non-public bucket key without retaining the raw IP."""
    ip=_clean(client_ip,180)
    secret=str(salt or "")
    if not ip or not secret:
        return "origin:unknown"
    digest=hmac.new(secret.encode("utf-8"),ip.encode("utf-8"),hashlib.sha256).hexdigest()[:24]
    return "origin:"+digest


def consume_rate(bucket: dict, key: str, now_seconds: float, *, limit: int=6, window_seconds: int=600) -> dict:
    """In-memory per-conversation rate limit; returns a bounded response policy, never an exception."""
    cutoff=float(now_seconds)-float(window_seconds)
    recent=[float(x) for x in list(bucket.get(key) or []) if float(x)>=cutoff]
    allowed=len(recent)<int(limit)
    if allowed:
        recent.append(float(now_seconds))
    bucket[key]=recent
    return {
        "allowed":allowed,
        "remaining":max(0,int(limit)-len(recent)),
        "reason":"within_rate_limit" if allowed else "substantive_rate_limited",
    }
