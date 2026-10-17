"""Free public quote verifier: does this exact sentence appear on this public page?

The rule Agent Commons adopted on 2026-10-17 ("one public link + the exact
sentence + who wrote it") made checkable in one call. Read-only: one GET to a
public HTTPS page (same SSRF checks, IP pinning and per-caller limits as
verify_mcp_endpoint), no credentials, no cookies, no JavaScript.

Outcomes:
  verbatim      every piece of the quote is on the page (cuts with "…" allowed)
  paraphrase    most of the quote's 4-word sequences are on the page, not all
  not_found     the text is not on the page
  unreachable   the page could not be fetched (reason given)
"""
from __future__ import annotations

import html
import re
import time
from collections import Counter
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

import mcp_endpoint_verifier as ev

MAX_PAGE_BYTES = 2 * 1024 * 1024
MAX_QUOTE_CHARS = 600
MAX_REDIRECTS = 3
TIMEOUT_SECONDS = 15.0
PARAPHRASE_SHARE = 0.5
TEXT_TYPES = ("text/html", "text/plain", "application/json", "application/xhtml", "text/markdown")
USER_AGENT = "OSIXBAY-QuoteVerifier/1.0 (+https://neo-collettive.onrender.com; read-only)"

METRICS: Counter = Counter()

ELLIPSIS_RE = re.compile(r"\s*(?:\.\.\.+|…)\s*")
_TAG_DROP_RE = re.compile(r"(?is)<(script|style|noscript|template)[^>]*>.*?</\1>")


def norm(text: str) -> str:
    text = _TAG_DROP_RE.sub(" ", text or "")
    text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    text = (text.replace("`", "").replace("’", "'").replace("‘", "'")
                .replace("“", '"').replace("”", '"').replace("\\n", " ").replace('\\"', '"'))
    return " ".join(text.lower().split())


def quote_segments(quote: str) -> list[str]:
    """Split at "…" cuts, drop the half-word next to each cut, keep pieces of 3+ words."""
    raw = (quote or "").strip().strip('"“”')
    parts = ELLIPSIS_RE.split(raw)
    segs = []
    for i, part in enumerate(parts):
        words = norm(part).split()
        if i > 0 and words:
            words = words[1:]
        if i < len(parts) - 1 and words:
            words = words[:-1]
        if len(words) >= 3:
            segs.append(" ".join(words))
    return segs or ([norm(raw)] if norm(raw) else [])


def judge(quote: str, page_text: str) -> dict[str, Any]:
    hay = norm(page_text)
    segs = quote_segments(quote)
    found = [s for s in segs if s in hay]
    if segs and len(found) == len(segs):
        first = hay.find(found[0])
        return {"outcome": "verbatim", "segments": len(segs), "segments_found": len(found),
                "context": hay[max(0, first - 80): first + len(found[0]) + 80]}
    words = norm(" ".join(segs)).split()
    shingles = [" ".join(words[i:i + 4]) for i in range(max(0, len(words) - 3))]
    share = (sum(1 for s in shingles if s in hay) / len(shingles)) if shingles else 0.0
    outcome = "paraphrase" if share >= PARAPHRASE_SHARE else "not_found"
    return {"outcome": outcome, "segments": len(segs), "segments_found": len(found),
            "four_word_overlap": round(share, 2)}


async def _fetch(url: str) -> dict[str, Any]:
    current = url
    async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS, follow_redirects=False, trust_env=False) as client:
        for hop in range(MAX_REDIRECTS + 1):
            target = await ev.validate_public_https(current)
            headers = {"User-Agent": USER_AGENT, "Accept": "text/html, text/plain, application/json;q=0.8"}
            pinned, pinned_headers, ext = ev.pin_to_resolved_ip(current, target, headers)
            async with client.stream("GET", pinned, headers=pinned_headers, extensions=ext) as r:
                if r.status_code in (301, 302, 303, 307, 308):
                    loc = r.headers.get("location")
                    if not loc or hop >= MAX_REDIRECTS:
                        raise ev.VerificationError("too_many_redirects")
                    current = urljoin(current, loc)
                    continue
                ctype = str(r.headers.get("content-type") or "").lower()
                if r.status_code >= 400:
                    raise ev.VerificationError("http_status", str(r.status_code))
                if ctype and not ctype.startswith(TEXT_TYPES):
                    raise ev.VerificationError("not_a_text_page", ctype.split(";")[0])
                total, chunks = 0, []
                async for chunk in r.aiter_bytes():
                    total += len(chunk)
                    if total > MAX_PAGE_BYTES:
                        break  # judge on the first 2 MB
                    chunks.append(chunk)
                return {"final_url": current, "host": target["host"], "status": r.status_code,
                        "bytes": min(total, MAX_PAGE_BYTES), "text": b"".join(chunks).decode("utf-8", "replace")}
    raise ev.VerificationError("too_many_redirects")


async def verify_quote(url: str, quote: str, caller: str | None = None) -> dict[str, Any]:
    started = time.perf_counter()
    quote = str(quote or "").strip()
    METRICS["calls"] += 1
    if not quote or len(quote.split()) < 3:
        return {"ok": False, "error": "quote_too_short", "hint": "send the exact sentence, at least 3 words"}
    if len(quote) > MAX_QUOTE_CHARS:
        return {"ok": False, "error": "quote_too_long", "max_chars": MAX_QUOTE_CHARS}
    try:
        ev.consume_rate_limit(ev.caller_bucket(caller))
    except ev.VerificationError as exc:
        METRICS["rate_limited"] += 1
        return {"ok": False, "error": exc.args[0] if exc.args else "rate_limited"}
    try:
        page = await _fetch(str(url or "").strip())
    except ev.VerificationError as exc:
        METRICS["unreachable"] += 1
        return {"ok": True, "outcome": "unreachable", "reason": exc.args[0] if exc.args else "unknown",
                "url": url, "latency_ms": round((time.perf_counter() - started) * 1000)}
    except httpx.HTTPError as exc:
        METRICS["unreachable"] += 1
        return {"ok": True, "outcome": "unreachable", "reason": type(exc).__name__, "url": url,
                "latency_ms": round((time.perf_counter() - started) * 1000)}
    verdict = judge(quote, page["text"])
    METRICS[verdict["outcome"]] += 1
    return {
        "ok": True, **verdict,
        "url": url, "final_url": page["final_url"], "http_status": page["status"], "page_bytes": page["bytes"],
        "latency_ms": round((time.perf_counter() - started) * 1000),
        "note": ("Checks the text only. Who wrote it (the person with the problem, or a vendor) is still "
                 "yours to judge; the page is fetched without login or JavaScript."),
    }


def usage_counts() -> dict[str, int]:
    return dict(METRICS)
