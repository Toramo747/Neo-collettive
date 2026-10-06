from __future__ import annotations

import re
from collections import Counter
from urllib.parse import parse_qs, urlparse
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


def marketplace_identity(url: str, vendor: str | None = None) -> str:
    vendor_key=str(vendor or "").strip().lower()
    if vendor_key:
        return "vendor:"+vendor_key
    parsed=urlparse(str(url or ""))
    host=(parsed.hostname or "").lower().removeprefix("www.")
    if not host:
        return ""
    if host not in MARKETPLACE_HOSTS:
        return "domain:"+host
    parts=[p for p in (parsed.path or "").split("/") if p]
    app_path=""
    if host=="apps.shopify.com" and parts:
        app_path="/"+parts[0]
    elif host=="marketplace.atlassian.com" and len(parts)>=2 and parts[0]=="apps":
        app_path="/apps/"+parts[1]
    elif host=="chromewebstore.google.com" and parts:
        app_path="/"+"/".join(parts[:3])
    elif host=="ecosystem.hubspot.com" and parts:
        app_path="/"+"/".join(parts[:4])
    elif host=="zapier.com" and len(parts)>=2 and parts[0]=="apps":
        app_path="/apps/"+parts[1]
    elif host=="marketplace.visualstudio.com":
        item=(parse_qs(parsed.query).get("itemName") or [""])[0].strip().lower()
        if item:
            app_path="/items/"+item
        elif parts:
            app_path="/"+"/".join(parts[:2])
    elif parts:
        app_path="/"+parts[0]
    return "marketplace:"+host+app_path if app_path else "domain:"+host


def validate_pricing_result(row: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(row,dict):
        return None
    url=str(row.get("url") or "")
    title=str(row.get("title") or "")
    snippet=str(row.get("snippet") or row.get("text") or row.get("description") or "")
    page_text=str(row.get("page_text") or "")
    text=(snippet+" "+page_text).strip()
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
        "seller_key":marketplace_identity(url,row.get("vendor")),
        "strict_price_verified":True,
        "price_source":"page" if page_text and extract_price(title+" "+snippet) is None else "snippet",
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


def _known_pricing_domains(
    evidence_rows: list[dict[str, Any]] | None,
    family: str,
    limit: int = 3,
) -> list[str]:
    out=[]
    for row in evidence_rows or []:
        if not isinstance(row,dict) or str(row.get("family") or "") != family:
            continue
        url=str(row.get("url") or "")
        domain=canonical_domain(url)
        if not domain or domain in out:
            continue
        signals={str(x) for x in (row.get("signal_types") or [])}
        if bool(row.get("real_price")) or bool(row.get("strict_price_verified")) or "COMPETITION" in signals:
            out.append(domain)
        if len(out)>=max(1,int(limit)):
            break
    return out


def compact_price_evidence(
    plan: list[dict[str,Any]] | None,
    groups: list[dict[str,Any]] | None,
    *,
    max_rows: int = 80,
) -> list[dict[str,Any]]:
    meta={" ".join(str(x.get("query") or "").split()).lower():x for x in (plan or []) if isinstance(x,dict)}
    rows=[]
    seen=set()
    for group in groups or []:
        if not isinstance(group,dict):
            continue
        key=" ".join(str(group.get("query") or "").split()).lower()
        family=str((meta.get(key) or {}).get("family") or "")
        if not family:
            continue
        qstat={
            "query_index":query_index,
            "results_received":0,
            "discarded_article":0,
            "discarded_non_product":0,
            "accepted":0,
        }
        for result in group.get("results") or []:
            if not isinstance(result,dict):
                continue
            validated=validate_pricing_result(result)
            if not validated:
                continue
            identity=(family,validated["seller_key"],validated["url"],validated["price"]["amount"],validated["price"]["period"])
            if identity in seen:
                continue
            seen.add(identity)
            page_text=str(result.get("page_text") or "")
            snippet=str(result.get("snippet") or result.get("text") or "")
            source_text=page_text if validated["price_source"]=="page" else snippet
            price_raw=str(validated["price"].get("raw") or "")
            pos=source_text.lower().find(price_raw.lower()) if price_raw else -1
            context=(source_text[max(0,pos-48):pos+len(price_raw)+64] if pos>=0 else source_text[:120])
            rows.append({
                "track":"price_validation",
                "family":family,
                "url":validated["url"],
                "domain":validated["domain"],
                "seller_key":validated["seller_key"],
                "price_currency":validated["price"]["currency"],
                "price_amount":validated["price"]["amount"],
                "price_period":validated["price"]["period"],
                "price_context":" ".join(context.split())[:160],
                "strict_price_verified":True,
                "price_source":validated["price_source"],
            })
            if len(rows)>=max(1,int(max_rows)):
                return rows
    return rows


def persisted_price_groups(rows: list[dict[str,Any]] | None) -> list[dict[str,Any]]:
    groups=[]
    by_family={}
    for row in rows or []:
        if not isinstance(row,dict) or not bool(row.get("strict_price_verified")):
            continue
        family=str(row.get("family") or "")
        url=str(row.get("url") or "")
        if not family or not url:
            continue
        by_family.setdefault(family,[]).append({
            "url":url,
            "title":str(row.get("domain") or "")[:120],
            "snippet":"",
            "page_text":str(row.get("price_context") or "")[:160],
            "page_fetched":True,
            "source":"persisted-price-validation",
            "vendor":None,
        })
    for family,items in by_family.items():
        groups.append({
            "query":"persisted-price-evidence:"+family,
            "results":items,
            "_persisted_price_family":family,
        })
    return groups


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
        (f'"{alias}" software pricing',"pricing_page"),
        (f'"{alias}" per month plans',"pricing_page"),
        (f'"{known_tool}" pricing',"pricing_page"),
        (f'"{known_tool}" alternatives',"alternatives"),
        (f'site:marketplace.visualstudio.com "{alias}" price',"marketplace"),
        (f'site:apps.shopify.com "{alias}" price',"marketplace"),
        (f'site:marketplace.atlassian.com "{alias}" price',"marketplace"),
        (f'site:ecosystem.hubspot.com "{alias}" price',"marketplace"),
        (f'site:zapier.com/apps "{alias}" price',"marketplace"),
        (f'site:chromewebstore.google.com "{alias}" price',"marketplace"),
    ]
    for domain in _known_pricing_domains(evidence_rows,family):
        queries.append((f'site:{domain} pricing', "known_competitor_pricing"))
        queries.append((f'site:{domain} /pricing', "known_competitor_pricing"))
    take=max(1,min(int(budget or 4),len(queries)))
    start=(max(0,int(cycle or 0))*take) % len(queries)
    selected=[queries[(start+i)%len(queries)] for i in range(take)]
    out=[]
    for query,kind in selected:
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
                "strict_prices":0,
                "competitors_with_price":0,
                "pages_fetched":0,
                "prices_from_snippet":0,
                "prices_from_page":0,
            })["validation_queries"]+=1
    competitors={}
    query_stats=[]
    for query_index,group in enumerate(groups or []):
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
            "strict_prices":0,
            "competitors_with_price":0,
            "pages_fetched":0,
            "prices_from_snippet":0,
            "prices_from_page":0,
        })
        for result in group.get("results") or []:
            if not isinstance(result,dict):
                continue
            qstat["results_received"]+=1
            url=str(result.get("url") or "")
            title=str(result.get("title") or "")
            snippet=str(result.get("snippet") or result.get("text") or "")
            page_text=str(result.get("page_text") or "")
            path=(urlparse(url).path or "").lower()
            combined=(title+" "+snippet+" "+page_text).lower()
            is_article=any(marker in path for marker in _ARTICLE_PATH_MARKERS) or bool(
                re.search(r"\b(best|top\s+\d+|roundup|comparison article|review roundup)\b",combined)
            )
            is_product=product_pricing_page(url,title,snippet+" "+page_text)
            if is_product:
                stats["pricing_pages_found"]+=1
            elif is_article:
                qstat["discarded_article"]+=1
            else:
                qstat["discarded_non_product"]+=1
            if bool(result.get("page_fetched")):
                stats["pages_fetched"]+=1
            validated=validate_pricing_result(result)
            if not validated:
                continue
            qstat["accepted"]+=1
            stats["prices_extracted"]+=1
            stats["strict_prices"]+=1
            if validated["price_source"]=="page":
                stats["prices_from_page"]+=1
            else:
                stats["prices_from_snippet"]+=1
            competitors.setdefault(family,set()).add(validated["seller_key"])
        query_stats.append(qstat)
    for family,identities in competitors.items():
        telemetry[family]["competitors_with_price"]=len({x for x in identities if x})
    if query_stats:
        telemetry["_query_telemetry"]=query_stats
    return telemetry
