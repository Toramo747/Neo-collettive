from __future__ import annotations

import hashlib
import re
from typing import Any

SECURITY_SCHEMA_VERSION = 1

_EVM_RE=re.compile(r"\b0x[a-fA-F0-9]{40}\b")
_BTC_RE=re.compile(r"\bbc1[ac-hj-np-z02-9]{20,90}\b",re.I)
_TRON_RE=re.compile(r"\bT[1-9A-HJ-NP-Za-km-z]{32,35}\b")
_SOL_FIELD_RE=re.compile(r'(?i)(?:"?solana"?\s*[:=]\s*"?)([1-9A-HJ-NP-Za-km-z]{32,44})')
_STRUCTURED_KEY_RE=re.compile(
    r'(?i)(?:"?(?:to|recipient|destination|payto|pay_to|address|amount|value|token|asset|chain|solana|bitcoin|tron)"?\s*[:=])'
)
_MAX_AMOUNT_RE=re.compile(r'(?i)(?:"?(?:amount|value)"?\s*[:=]\s*"?(?:max|all)"?\b)')
_ASSET_RE=re.compile(r"(?i)\b(?:USDC|USDT|BTC|BITCOIN|ETH|ETHEREUM|SOL|SOLANA|TRX|TRON)\b")
_IMPERATIVE_TRANSFER_RE=re.compile(r"(?i)\b(?:send|transfer|pay|forward)\b")
_RESEARCH_CONTEXT_RE=re.compile(r"(?i)\b(?:analy[sz]e|analysis|research|example|sample|malicious|phishing|spam|threat|detect|classifier|quoted)\b")


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _wallet_count(text: str) -> int:
    values=set()
    values.update(x.lower() for x in _EVM_RE.findall(text))
    values.update(x.lower() for x in _BTC_RE.findall(text))
    values.update(x.lower() for x in _TRON_RE.findall(text))
    values.update(x.lower() for x in _SOL_FIELD_RE.findall(text))
    return len(values)


def classify_inbound_security(text: str) -> dict:
    """Detect execution-shaped crypto transfer instructions without classifying general crypto discussion.

    This is deliberately narrow: it requires a wallet, a max/all amount, an asset,
    and either multiple structured transaction fields or a direct transfer imperative.
    """
    raw=_clean(text)
    if not raw:
        return {"blocked":False,"traffic_class":"NORMAL","reason":"empty","signals":[]}

    wallets=_wallet_count(raw)
    structured=len(_STRUCTURED_KEY_RE.findall(raw))
    has_max=bool(_MAX_AMOUNT_RE.search(raw))
    has_asset=bool(_ASSET_RE.search(raw))
    imperative=bool(_IMPERATIVE_TRANSFER_RE.search(raw))
    research_context=bool(_RESEARCH_CONTEXT_RE.search(raw))

    execution_shaped=(
        wallets>=1
        and has_max
        and has_asset
        and (
            structured>=4
            or (imperative and not research_context)
        )
    )
    if not execution_shaped:
        return {
            "blocked":False,
            "traffic_class":"NORMAL",
            "reason":"no_execution_shaped_crypto_transfer",
            "signals":[],
        }

    signals=["wallet_address","max_or_all_amount","crypto_asset"]
    if structured>=4:
        signals.append("structured_transfer_fields")
    if imperative:
        signals.append("transfer_imperative")
    return {
        "blocked":True,
        "traffic_class":"ADVERSARIAL_SPAM",
        "reason":"execution_shaped_crypto_transfer_request",
        "signals":signals,
        "wallet_count":wallets,
        "structured_field_count":structured,
    }


def redact_security_text(text: str, limit: int = 500) -> str:
    value=_clean(text)
    value=_EVM_RE.sub("[wallet]",value)
    value=_BTC_RE.sub("[wallet]",value)
    value=_TRON_RE.sub("[wallet]",value)
    value=_SOL_FIELD_RE.sub(lambda m: m.group(0).replace(m.group(1),"[wallet]"),value)
    value=re.sub(
        r'(?i)((?:"?(?:amount|value)"?\s*[:=]\s*"?))(?:max|all)',
        r'\1[blocked]',
        value,
    )
    return value[:max(80,int(limit or 500))]


def security_fingerprint(text: str) -> str:
    normalized=redact_security_text(text,2000).lower()
    normalized=re.sub(r"\s+"," ",normalized).strip()
    return hashlib.sha256(normalized.encode("utf-8","ignore")).hexdigest()[:20]


def quarantine_legacy_inbound_security(payload: dict | None) -> tuple[dict | None, dict]:
    if not isinstance(payload,dict):
        return payload,{"moved":0,"removed_chat_events":0}

    out=dict(payload)
    messages=[x for x in (out.get("inbound_messages") or []) if isinstance(x,dict)]
    existing=[x for x in (out.get("inbound_security_events") or []) if isinstance(x,dict)]
    known_ids={str(x.get("source_message_id") or "") for x in existing if x.get("source_message_id")}
    clean=[]
    moved=[]
    blocked_threads=set()
    blocked_message_ids=set()

    for row in messages:
        verdict=classify_inbound_security(str(row.get("text") or ""))
        if not verdict.get("blocked"):
            clean.append(row)
            continue
        message_id=str(row.get("message_id") or "")
        thread_id=str(row.get("thread_id") or "")
        if message_id:
            blocked_message_ids.add(message_id)
        if thread_id:
            blocked_threads.add(thread_id)
        if message_id and message_id in known_ids:
            continue
        moved.append({
            "schema_v":SECURITY_SCHEMA_VERSION,
            "event_id":"sec-legacy-"+security_fingerprint((message_id or thread_id)+"|"+str(row.get("text") or "")),
            "received_at_utc":row.get("received_at_utc"),
            "source_message_id":message_id,
            "thread_id":thread_id,
            "traffic_class":verdict.get("traffic_class"),
            "reason":verdict.get("reason"),
            "signals":verdict.get("signals") or [],
            "sender_declared":bool((row.get("sender") or {}).get("declared")) if isinstance(row.get("sender"),dict) else False,
            "text_excerpt":redact_security_text(str(row.get("text") or "")),
            "response_suppressed":True,
            "migrated_from_inbound":True,
        })

    events=[x for x in (out.get("agent_chat_events") or []) if isinstance(x,dict)]
    filtered=[]
    removed=0
    for event in events:
        if (
            str(event.get("message_id") or "") in blocked_message_ids
            or str(event.get("thread_id") or "") in blocked_threads
        ):
            removed+=1
            continue
        filtered.append(event)

    all_security=(existing+moved)[-80:]
    stats=dict(out.get("inbound_security_stats") or {})
    if moved:
        stats["blocked_total"]=max(int(stats.get("blocked_total") or 0),len(all_security))
        stats["crypto_transfer_requests"]=max(int(stats.get("crypto_transfer_requests") or 0),len(all_security))
        stats["last_seen_utc"]=moved[-1].get("received_at_utc")
    out["inbound_messages"]=clean[-80:]
    out["agent_chat_events"]=filtered[-240:]
    out["inbound_security_events"]=all_security
    out["inbound_security_stats"]=stats
    return out,{"moved":len(moved),"removed_chat_events":removed}
