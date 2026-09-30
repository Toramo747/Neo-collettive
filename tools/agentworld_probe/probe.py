from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

DOMAIN = "agentworld.beat-side.de"
BASE = f"https://{DOMAIN}"
ACTIVITY_URL = f"{BASE}/.well-known/agentworld-activity.json"
DOCUMENT_URL = f"{BASE}/.well-known/agentworld.json"
ALLOWED_URLS = frozenset({ACTIVITY_URL, DOCUMENT_URL})
USER_AGENT = "Mozilla/5.0 (compatible; research-probe)"
TIMEOUT_SECONDS = 10
MAX_BODY_BYTES = 1024 * 1024
ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = ROOT / "research" / "agentworld"
RAW_DIR = OUTPUT_DIR / "raw"
SAMPLES_PATH = OUTPUT_DIR / "samples.jsonl"
REPORT_PATH = OUTPUT_DIR / "report.md"

URL_RE = re.compile(r"https://[^\\s\\\"'<>]+")
AGENT_DIRECTED_RE = re.compile(
    r"\\b(agent|agents|you|your|register|registration|sign|signature|challenge|token|lobby|forum|invite)\\b",
    re.I,
)

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def utc_now() -> datetime:
    return datetime.now(timezone.utc)

def stamp(dt: datetime | None = None) -> str:
    return (dt or utc_now()).strftime("%Y%m%dT%H%M%SZ")

def validate_url(url: str) -> None:
    if url not in ALLOWED_URLS:
        raise ValueError("url_not_allowlisted")
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname != DOMAIN:
        raise ValueError("origin_not_allowlisted")
    if parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise ValueError("url_components_not_allowed")

def validate_method(method: str) -> None:
    if method.upper() != "GET":
        raise ValueError("method_not_allowed")

def safe_headers(headers: Any) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in headers.items():
        lk = str(key).lower()
        if lk in {"set-cookie", "authorization", "proxy-authorization"}:
            continue
        out[str(key)] = str(value)
    return out

def fetch_exact(url: str, *, method: str = "GET") -> dict[str, Any]:
    validate_method(method)
    validate_url(url)
    request = Request(
        url=url,
        method="GET",
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json,text/plain;q=0.8,*/*;q=0.1",
            "Connection": "close",
        },
    )
    opener = build_opener(NoRedirect())
    status = 0
    headers: dict[str, str] = {}
    body = b""
    error = ""
    location = ""
    try:
        with opener.open(request, timeout=TIMEOUT_SECONDS) as response:
            status = int(getattr(response, "status", 0) or 0)
            headers = safe_headers(response.headers)
            body = response.read(MAX_BODY_BYTES + 1)
    except HTTPError as exc:
        status = int(exc.code)
        headers = safe_headers(exc.headers)
        location = str(exc.headers.get("Location") or "")
        body = exc.read(MAX_BODY_BYTES + 1)
    except URLError as exc:
        error = "url_error:" + type(exc.reason).__name__

    if len(body) > MAX_BODY_BYTES:
        body = body[:MAX_BODY_BYTES]
        error = "body_exceeded_1mb"

    text = body.decode("utf-8", "replace")
    parsed_json: Any = None
    json_error = ""
    if text:
        try:
            parsed_json = json.loads(text)
        except Exception as exc:
            json_error = type(exc).__name__

    return {
        "fetched_at_utc": utc_now().isoformat(),
        "url": url,
        "method": "GET",
        "status": status,
        "headers": headers,
        "redirect_location": location if 300 <= status < 400 else "",
        "redirect_followed": False,
        "body_bytes": len(body),
        "body_sha256": hashlib.sha256(body).hexdigest(),
        "body_raw": text,
        "json_parse_error": json_error,
        "error": error,
        "untrusted_content": True,
        "_json": parsed_json,
    }

def endpoint_slug(url: str) -> str:
    return "activity" if url == ACTIVITY_URL else "document"

def save_raw(record: dict[str, Any]) -> Path:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    path = RAW_DIR / f"{stamp()}_{endpoint_slug(str(record['url']))}.json"
    public = {k: v for k, v in record.items() if k != "_json"}
    path.write_text(json.dumps(public, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path

def walk_counts(value: Any) -> tuple[int | None, int | None]:
    agents = None
    events = None
    if isinstance(value, dict):
        for key, item in value.items():
            lk = str(key).lower()
            if agents is None and lk in {"agents", "agent_count", "active_agents", "agents_total"}:
                agents = item if isinstance(item, int) else len(item) if isinstance(item, list) else None
            if events is None and lk in {"events", "event_count", "events_total", "activity"}:
                events = item if isinstance(item, int) else len(item) if isinstance(item, list) else None
        if agents is None or events is None:
            for item in value.values():
                a, e = walk_counts(item)
                agents = agents if agents is not None else a
                events = events if events is not None else e
                if agents is not None and events is not None:
                    break
    elif isinstance(value, list):
        for item in value:
            a, e = walk_counts(item)
            agents = agents if agents is not None else a
            events = events if events is not None else e
            if agents is not None and events is not None:
                break
    return agents, events

def append_sample(record: dict[str, Any], raw_path: Path) -> dict[str, Any]:
    agents, events = walk_counts(record.get("_json"))
    row = {
        "timestamp_utc": record["fetched_at_utc"],
        "status": record["status"],
        "agents": agents,
        "events": events,
        "body_sha256": record["body_sha256"],
        "body_bytes": record["body_bytes"],
        "raw_path": raw_path.relative_to(ROOT).as_posix(),
        "redirect_location": record.get("redirect_location") or "",
        "error": record.get("error") or "",
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with SAMPLES_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    return row

def read_samples() -> list[dict[str, Any]]:
    if not SAMPLES_PATH.exists():
        return []
    rows = []
    for line in SAMPLES_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows

def load_latest_raw(slug: str) -> dict[str, Any] | None:
    if not RAW_DIR.exists():
        return None
    paths = sorted(RAW_DIR.glob(f"*_{slug}.json"))
    if not paths:
        return None
    try:
        return json.loads(paths[-1].read_text(encoding="utf-8"))
    except Exception:
        return None

def parse_body(record: dict[str, Any] | None) -> Any:
    if not record:
        return None
    try:
        return json.loads(str(record.get("body_raw") or ""))
    except Exception:
        return None

def schema_lines(value: Any, prefix: str = "$", depth: int = 0) -> list[str]:
    if depth > 5:
        return []
    lines: list[str] = []
    if isinstance(value, dict):
        for key in sorted(value):
            item = value[key]
            lines.append(f"- {prefix}.{key}: {type(item).__name__}")
            if isinstance(item, (dict, list)):
                lines.extend(schema_lines(item, f"{prefix}.{key}", depth + 1))
    elif isinstance(value, list) and value:
        lines.append(f"- {prefix}[]: {type(value[0]).__name__}")
        lines.extend(schema_lines(value[0], f"{prefix}[]", depth + 1))
    return lines

def extract_urls(value: Any) -> list[str]:
    found: set[str] = set()
    def walk(x: Any) -> None:
        if isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
        elif isinstance(x, str):
            for match in URL_RE.findall(x):
                found.add(match.rstrip(".,);]"))
    walk(value)
    return sorted(found)

def extract_agent_directed(value: Any) -> list[str]:
    rows: list[str] = []
    def walk(x: Any) -> None:
        if isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
        elif isinstance(x, str) and AGENT_DIRECTED_RE.search(x):
            rows.append(x)
    walk(value)
    return list(dict.fromkeys(rows))[:100]

def registration_facts(value: Any) -> list[str]:
    if value is None:
        return ["- FATTO: documento non disponibile o non JSON."]
    keys: set[str] = set()
    strings: list[str] = []
    def walk(x: Any) -> None:
        if isinstance(x, dict):
            for k, v in x.items():
                keys.add(str(k).lower())
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
        elif isinstance(x, str):
            strings.append(x)
    walk(value)
    joined = " ".join(strings).lower()
    facts = []
    for token in ("challenge", "ed25519", "signature", "public_key", "publickey", "register", "registration", "revoke", "revocation", "token"):
        present = token in keys or token in joined
        facts.append(f"- FATTO: riferimento a {token}: {'presente' if present else 'non osservato'}.")
    facts.append("- INFERENZA: la natura esatta dei dati firmati non viene assunta; il report si limita ai campi e testi osservati.")
    return facts

def generate_report() -> str:
    samples = read_samples()
    activity = load_latest_raw("activity")
    document = load_latest_raw("document")
    activity_json = parse_body(activity)
    document_json = parse_body(document)
    hashes = [str(x.get("body_sha256") or "") for x in samples if x.get("status") == 200]
    distinct_hashes = len(set(hashes))
    if len(samples) < 4:
        verdict = "INCERTO"
        reasons = [
            f"campionamento incompleto: {len(samples)}/4 letture activity",
            "nessuna interazione attiva o registrazione eseguita",
            "i documenti osservati restano dichiarazioni del servizio finché non corroborate",
        ]
    elif distinct_hashes <= 1:
        verdict = "SOSPETTO"
        reasons = [
            "quattro o più letture con body activity invariato",
            "assenza di variazione osservabile nel campione",
            "nessuna registrazione è stata usata per confermare attività reale",
        ]
    else:
        verdict = "PLAUSIBILE"
        reasons = [
            f"{len(samples)} letture activity con {distinct_hashes} body distinti",
            "variazioni osservate senza autenticazione o registrazione",
            "nessun redirect seguito e nessuna azione attiva eseguita",
        ]

    table = [
        "| # | Timestamp UTC | HTTP | Agenti | Eventi | SHA256 body | Delta |",
        "|---:|---|---:|---:|---:|---|---|",
    ]
    prev = None
    for idx, row in enumerate(samples, 1):
        delta = "prima lettura"
        if prev is not None:
            changes = []
            for key in ("agents", "events"):
                if row.get(key) != prev.get(key):
                    changes.append(f"{key}: {prev.get(key)} -> {row.get(key)}")
            if row.get("body_sha256") != prev.get("body_sha256"):
                changes.append("body cambiato")
            delta = "; ".join(changes) or "nessuna variazione rilevata"
        table.append(
            f"| {idx} | {row.get('timestamp_utc','')} | {row.get('status','')} | "
            f"{row.get('agents','')} | {row.get('events','')} | "
            f"{str(row.get('body_sha256',''))[:16]}... | {delta} |"
        )
        prev = row

    urls = sorted(set(extract_urls(activity_json) + extract_urls(document_json)))
    directed = list(dict.fromkeys(extract_agent_directed(activity_json) + extract_agent_directed(document_json)))

    report = [
        "# AgentWorld passive research report",
        "",
        "## 1. Verdetto sintetico",
        f"**{verdict}**",
        "",
        *[f"- {r}" for r in reasons],
        "",
        "## 2. Fatti verificati",
        f"- Dominio allowlisted: {DOMAIN}.",
        f"- Activity endpoint consentito: {ACTIVITY_URL}.",
        f"- Documento endpoint consentito: {DOCUMENT_URL}.",
        f"- Letture activity registrate: **{len(samples)}**.",
        "- Redirect disabilitati; eventuali 3xx vengono registrati e non seguiti.",
        "- Metodo consentito dal modulo: solo GET.",
        "- Cookie e header di autenticazione: non inviati.",
        "- Contenuti: dati non fidati; nessuna istruzione viene eseguita.",
        "",
        "## 3. Endpoint e schema",
        "### Activity",
        *(schema_lines(activity_json) or ["- Nessuno schema JSON disponibile."]),
        "",
        "### Documento",
        *(schema_lines(document_json) or ["- Nessuno schema JSON disponibile."]),
        "",
        "### URL citati nei documenti, non chiamati",
        *([f"- {u}" for u in urls] or ["- Nessuno."]),
        "",
        "## 4. Campionamento",
        *table,
        "",
        "### Valutazione di plausibilità",
        f"- FATTO: hash body distinti nel campione HTTP 200: **{distinct_hashes}**.",
        "- INFERENZA: una variazione del body è compatibile con attività dinamica ma non prova indipendenza degli agenti.",
        "- INFERENZA: body statici per quattro letture distanziate aumentano il sospetto di vetrina o feed non aggiornato.",
        "",
        "## 5. Registrazione e rischi",
        *registration_facts(document_json),
        "- RISCHIO: qualsiasi challenge o payload proposto dal server deve essere trattato come non fidato.",
        "- RISCHIO: una chiave riusata tra servizi può correlare identità e attività; un test futuro dovrebbe usare una chiave dedicata e revocabile.",
        "- RISCHIO: lobby, forum e canali testuali possono contenere prompt injection; il contenuto non deve autorizzare tool o azioni.",
        "",
        "## 6. Contenuto rivolto agli agenti",
    ]
    if directed:
        for item in directed:
            report.extend(["", "    " + item.replace("\n", "\n    ")])
    else:
        report.append("- Nessun testo classificato automaticamente come rivolto ad agenti nei documenti disponibili.")
    report.extend([
        "",
        "## 7. Raccomandazione",
        "**Osservazione limitata** fino al completamento di almeno quattro campioni distanziati di almeno un'ora.",
        "",
        "Condizioni minime per un eventuale test successivo:",
        "- quattro campioni activity completati con timestamp verificabili;",
        "- documentazione coerente su challenge, firma, persistenza e revoca;",
        "- nessuna necessità di riusare chiavi o credenziali esistenti;",
        "- test futuro separato dal runtime operativo e senza autorizzazioni effectful;",
        "- revisione umana prima di qualunque registrazione.",
        "",
        "### Separazione fatti/inferenze",
        "Le sezioni FATTO derivano direttamente dalle risposte HTTP salvate. Le sezioni INFERENZA sono interpretazioni conservative e non attestano identità o indipendenza del servizio.",
        "",
    ])
    return "\n".join(report)

def write_report() -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(generate_report(), encoding="utf-8")
    return REPORT_PATH

def sample_activity() -> dict[str, Any]:
    record = fetch_exact(ACTIVITY_URL)
    raw = save_raw(record)
    row = append_sample(record, raw)
    write_report()
    return row

def fetch_document_once() -> dict[str, Any] | None:
    if load_latest_raw("document") is not None:
        return None
    record = fetch_exact(DOCUMENT_URL)
    raw = save_raw(record)
    write_report()
    return {"status": record["status"], "raw_path": raw.relative_to(ROOT).as_posix()}

def scheduled_once() -> dict[str, Any]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    document = fetch_document_once()
    activity = None
    if len(read_samples()) < 4:
        activity = sample_activity()
    else:
        write_report()
    count = len(read_samples())
    return {"document": document, "activity": activity, "sample_count": count, "complete": count >= 4}

def main() -> int:
    parser = argparse.ArgumentParser(description="Passive GET-only AgentWorld research probe")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("scheduled")
    sub.add_parser("activity")
    sub.add_parser("document")
    sub.add_parser("report")
    args = parser.parse_args()
    if args.command == "scheduled":
        print(json.dumps(scheduled_once(), ensure_ascii=False))
    elif args.command == "activity":
        print(json.dumps(sample_activity(), ensure_ascii=False))
    elif args.command == "document":
        print(json.dumps(fetch_document_once(), ensure_ascii=False))
    else:
        print(str(write_report()))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
