from __future__ import annotations

import re
from collections import Counter
from urllib.parse import urlparse
from typing import Any

PRICE_VALIDATION_QUERY_BUDGET = 4
CANONICAL_PRICE_REQUIREMENT = "two_competitors_with_real_price"

MARKETPLACE_HOSTS = {
    "apps.shopify.com",
    "marketplace.atlassian.com",
    "chromewebstore.google.com",
    "ecosystem.hubspot.com",
    "zapier.com",
    "marketplace.visualstudio.com",
}

_ARTICLE_PATH_MARKERS = (
    "/blog/", "/blogs/", "/article/", "/articles/", "/guide/", "/guides/",
    "/news/", "/review/", "/reviews/", "/best-", "/top-", "/compare/",
)
_CONTACT_ONLY = re.compile(r"\b(contact\s+(?:us|sales)|talk\s+to\s+sales|request\s+(?:a\s+)?quote|custom\s+pricing)\b", re.I)
_PRICE = re.compile(
    r"(?P<currency>[$€£]|USD|EUR|GBP)\s*(?P<amount>\d{1,7}(?:[.,]\d{1,2})?)"
    r"|(?P<amount2>\d{1,7}(?:[.,]\d{1,2})?)\s*(?P<currency2>USD|EUR|GBP)",
    re.I,
)
_PERIOD = re.compile(
    r"(?:/|per\s+)(?P<period>month|mo|monthly|year|yr|annual|annually|week|wk|weekly|user|seat)"
    r"|\b(?P<one_time>one[- ]time|lifetime|perpetual)\b",
    re.I,
)

_CURRENCY_CODES = {"$": "USD", "€": "EUR", "£": "GBP", "USD": "USD", "EUR": "EUR", "GBP": "GBP"}


def canonical_domain(url: str) -> str:
    try:
        return (urlparse(str(url or "")).hostname or "").lower().removeprefix("www.")
    except Exception:
        return ""


def extract_price(text: str) -> dict[str, Any] | None:
    value=" ".join(str(text or "").split())
    if not value or _CONTACT_ONLY.search(value):
        return None
    for match in _PRICE.finditer(value):
        start=max(0,match.start()-48)
        end=min(len(value),match.end()+64)
        context=value[start:end]
        period_match=_PERIOD.search(context)
        if not period_match:
            continue
        currency=(match.group("currency") or match.group("currency2") or "").upper()
        amount_raw=(match.group("amount") or match.group("amount2") or "").replace(",",".")
        try:
            amount=float(amount_raw)
        except ValueError:
            continue
        if amount <= 0:
            continue
        period=period_match.group("period")
        if period:
            low=period.lower()
            period=(
                "month" if low in {"month","mo","monthly"}
                else "year" if low in {"year","yr","annual","annually"}
                else "week" if low in {"week","wk","weekly"}
                else "user" if low=="user"
                else "seat"
            )
        else:
            period="one_time"
        return {
            "currency":_CURRENCY_CODES.get(currency,currency),
            "amount":amount,
            "period":period,
            "raw":match.group(0)[:80],
        }
    return None


def product_pricing_page(url: str, title: str = "", text: str = "") -> bool:
    raw_url=str(url or "")
    parsed=urlparse(raw_url)
    host=(parsed.hostname or "").lower().removeprefix("www.")
    path=(parsed.path or "/").lower()
    if not raw_url.startswith("https://") or not host:
        return False
    if any(marker in path for marker in _ARTICLE_PATH_MARKERS):
        return False
    combined=(" ".join((str(title or ""),str(text or ""),path))).lower()
    if re.search(r"\b(best|top\s+\d+|roundup|comparison article|review roundup)\b",combined):
        return False
    if host in MARKETPLACE_HOSTS:
        return path not in {"","/"} and len(path.strip("/").split("/")) >= 1
    return any(marker in path for marker in ("/pricing","/plans","/price","/product","/products","/app","/apps"))


def validate_pricing_result(row: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(row,dict):
        return None
    url=str(row.get("url") or "")
    title=str(row.get("title") or "")
    text=str(row.get("snippet") or row.get("text") or row.get("description") or "")
    if not product_pricing_page(url,title,text):
        return None
    price=extract_price(title+" "+text)
    if not price:
        return None
    domain=canonical_domain(url)
    if not domain:
        return None
    return {
        "url":url,
        "domain":domain,
        "title":title[:240],
        "price":price,
        "product_page":True,
    }


def buyer_voice_counts(rows: list[dict[str, Any]] | None) -> dict[str,int]:
    counts=Counter()
    for row in rows or []:
        if not isinstance(row,dict) or not bool(row.get("gate_eligible")):
            continue
        family=str(row.get("family") or "")
        signals={str(x) for x in (row.get("signal_types") or [])}
        if family and signals & {"PAIN","BUY_INTENT","PAID_DEMAND"}:
            counts[family]+=1
    return dict(counts)


def price_validation_plan(
    evidence_rows: list[dict[str, Any]] | None,
    *,
    cycle: int,
    category_configs: dict[str,dict[str,Any]],
    budget: int = PRICE_VALIDATION_QUERY_BUDGET,
) -> list[dict[str,Any]]:
    counts=buyer_voice_counts(evidence_rows)
    families=sorted(f for f,n in counts.items() if n>=1 and f in category_configs)
    if not families:
        return []
    family=families[max(0,int(cycle or 0)) % len(families)]
    cfg=category_configs[family]
    aliases=[str(x).strip() for x in (cfg.get("aliases") or []) if str(x).strip()]
    alias=aliases[0] if aliases else str(cfg.get("title") or family)
    known_tool=str(cfg.get("title") or alias)
    queries=[
        (f'"{alias}" pricing',"pricing_page"),
        (f'"{alias}" per month plans',"pricing_page"),
        (f'"{known_tool}" alternatives',"alternatives"),
        (f'site:marketplace.visualstudio.com "{alias}" price',"marketplace"),
        (f'site:apps.shopify.com "{alias}" price',"marketplace"),
        (f'site:marketplace.atlassian.com "{alias}" price',"marketplace"),
        (f'site:ecosystem.hubspot.com "{alias}" price',"marketplace"),
        (f'site:zapier.com/apps "{alias}" price',"marketplace"),
        (f'site:chromewebstore.google.com "{alias}" price',"marketplace"),
    ]
    out=[]
    for query,kind in queries[:max(1,min(int(budget or 4),9))]:
        out.append({
            "query":query,
            "class":"tool_market_validation",
            "role":"price_validation",
            "family":family,
            "tool_name":known_tool,
            "query_intent":"verify_competitor_real_price",
            "validation_kind":kind,
            "buyer_voice":int(counts.get(family) or 0),
        })
    return out


def summarize_validation(
    plan: list[dict[str,Any]] | None,
    groups: list[dict[str,Any]] | None,
) -> dict[str,Any]:
    telemetry={}
    meta={" ".join(str(x.get("query") or "").split()).lower():x for x in (plan or []) if isinstance(x,dict)}
    for row in plan or []:
        family=str(row.get("family") or "")
        if family:
            telemetry.setdefault(family,{
                "validation_queries":0,
                "pricing_pages_found":0,
                "prices_extracted":0,
                "competitors_with_price":0,
            })["validation_queries"]+=1
    competitors={}
    for group in groups or []:
        if not isinstance(group,dict):
            continue
        key=" ".join(str(group.get("query") or "").split()).lower()
        family=str((meta.get(key) or {}).get("family") or "")
        if not family:
            continue
        stats=telemetry.setdefault(family,{
            "validation_queries":0,
            "pricing_pages_found":0,
            "prices_extracted":0,
            "competitors_with_price":0,
        })
        for result in group.get("results") or []:
            if not isinstance(result,dict):
                continue
            url=str(result.get("url") or "")
            title=str(result.get("title") or "")
            text=str(result.get("snippet") or result.get("text") or "")
            if product_pricing_page(url,title,text):
                stats["pricing_pages_found"]+=1
            validated=validate_pricing_result(result)
            if not validated:
                continue
            stats["prices_extracted"]+=1
            competitors.setdefault(family,set()).add(validated["domain"])
    for family,domains in competitors.items():
        telemetry[family]["competitors_with_price"]=len(domains)
    return telemetry
