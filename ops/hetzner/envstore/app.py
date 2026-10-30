"""envstore: a tiny, Render-API-compatible state store backed by local files.

Why
---
NEO persists its small checkpoint (NEO_STATE_JSON), the private SETI state and,
as a fallback, memory chunks as *Render environment variables* written through
the Render REST API. On a plain VPS there is no such API. Instead of touching
the ~40 call sites in cloud_mcp.py, this sidecar speaks the same four routes
and keeps every value as one file on the persistent disk:

    GET    /v1/services/{id}/env-vars?limit=&cursor=   -> [{"envVar":{key,value},"cursor"}]
    GET    /v1/services/{id}/env-vars/{key}            -> {"key","value"}
    PUT    /v1/services/{id}/env-vars/{key}  {"value"} -> {"key","value"}
    DELETE /v1/services/{id}/env-vars/{key}            -> 204
    GET    /v1/services/{id}                           -> minimal service object
    GET    /v1/services/{id}/deploys?limit=            -> [{"deploy":{...},"cursor"}]
    POST   /v1/services/{id}/deploys                   -> deploy object (runs DEPLOY_COMMAND)
    GET|POST /deploy/{hook}?ref=<sha>                  -> Render-style deploy hook
    GET    /healthz

NEO is pointed at it with RENDER_API_BASE=http://envstore:8000/v1,
RENDER_SERVICE_ID=neo and RENDER_API_KEY=<ENVSTORE_TOKEN>. Everything else in
the service keeps working unchanged (render_saved_env.py reads the saved
values at boot through the same list route).

Properties
----------
* Writes are atomic (tmp file + fsync + rename) so a crash never leaves a
  half-written checkpoint. Keys are validated against [A-Za-z0-9_.-].
* Values are never logged. Only key names and sizes appear in the log.
* Stdlib only, single process, threaded server. No dependency to install.
* Optional size guard: ENVSTORE_MAX_VALUE_BYTES (default 16 MB) per value.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

DATA_DIR = os.getenv("ENVSTORE_DATA_DIR", "/data")
TOKEN = (os.getenv("ENVSTORE_TOKEN") or "").strip()
SERVICE_ID = (os.getenv("ENVSTORE_SERVICE_ID") or "neo").strip()
SERVICE_NAME = (os.getenv("ENVSTORE_SERVICE_NAME") or "neo-collective-cloud").strip()
PUBLIC_URL = (os.getenv("ENVSTORE_PUBLIC_URL") or "").strip()
DEPLOY_HOOK = (os.getenv("ENVSTORE_DEPLOY_HOOK") or "").strip()
DEPLOY_COMMAND = (os.getenv("ENVSTORE_DEPLOY_COMMAND") or "").strip()
MAX_VALUE_BYTES = int(os.getenv("ENVSTORE_MAX_VALUE_BYTES") or 16 * 1024 * 1024)
PORT = int(os.getenv("PORT") or 8000)
KEY_RE = re.compile(r"^[A-Za-z0-9_.-]{1,200}$")
DEPLOYS_FILE = "deploys.json"
VARS_DIR = "vars"

_lock = threading.RLock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _vars_dir() -> str:
    path = os.path.join(DATA_DIR, VARS_DIR)
    os.makedirs(path, exist_ok=True)
    return path


def _atomic_write(path: str, data: bytes) -> None:
    tmp = f"{path}.tmp-{uuid.uuid4().hex}"
    with open(tmp, "wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
    try:
        dir_fd = os.open(os.path.dirname(path) or ".", os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except OSError:
        pass


class Store:
    """Key/value store, one file per key, listing sorted by key for stable cursors."""

    def __init__(self, data_dir: str) -> None:
        self.data_dir = data_dir

    def _path(self, key: str) -> str:
        return os.path.join(_vars_dir(), key)

    def keys(self) -> list[str]:
        with _lock:
            return sorted(k for k in os.listdir(_vars_dir()) if KEY_RE.match(k) and not k.endswith(".tmp"))

    def get(self, key: str) -> str | None:
        with _lock:
            try:
                with open(self._path(key), "rb") as fh:
                    return fh.read().decode("utf-8")
            except FileNotFoundError:
                return None

    def put(self, key: str, value: str) -> None:
        with _lock:
            _atomic_write(self._path(key), value.encode("utf-8"))

    def delete(self, key: str) -> bool:
        with _lock:
            try:
                os.remove(self._path(key))
                return True
            except FileNotFoundError:
                return False

    def page(self, limit: int, cursor: str | None) -> list[dict]:
        keys = self.keys()
        if cursor:
            keys = [k for k in keys if k > cursor]
        out = []
        for k in keys[:limit]:
            v = self.get(k)
            if v is None:
                continue
            out.append({"envVar": {"key": k, "value": v}, "cursor": k})
        return out

    # deploys -------------------------------------------------------------
    def _deploys_path(self) -> str:
        os.makedirs(self.data_dir, exist_ok=True)
        return os.path.join(self.data_dir, DEPLOYS_FILE)

    def deploys(self) -> list[dict]:
        with _lock:
            try:
                with open(self._deploys_path(), "r", encoding="utf-8") as fh:
                    rows = json.load(fh)
                return rows if isinstance(rows, list) else []
            except (FileNotFoundError, ValueError):
                return []

    def add_deploy(self, ref: str, trigger: str) -> dict:
        deploy = {
            "id": "dep-" + uuid.uuid4().hex[:12],
            "commit": {"id": ref or "", "message": ""},
            "status": "build_in_progress" if DEPLOY_COMMAND else "deactivated",
            "trigger": trigger,
            "createdAt": _now(),
            "updatedAt": _now(),
            "finishedAt": None,
        }
        with _lock:
            rows = [deploy] + self.deploys()
            _atomic_write(self._deploys_path(), json.dumps(rows[:50], ensure_ascii=False).encode("utf-8"))
        return deploy

    def finish_deploy(self, deploy_id: str, ok: bool) -> None:
        with _lock:
            rows = self.deploys()
            for row in rows:
                if row.get("id") == deploy_id:
                    row["status"] = "live" if ok else "build_failed"
                    row["finishedAt"] = _now()
                    row["updatedAt"] = _now()
            _atomic_write(self._deploys_path(), json.dumps(rows[:50], ensure_ascii=False).encode("utf-8"))


STORE = Store(DATA_DIR)


def _run_deploy(deploy: dict, ref: str) -> None:
    if not DEPLOY_COMMAND:
        return
    env = dict(os.environ)
    env["DEPLOY_REF"] = ref or ""
    env["DEPLOY_ID"] = deploy["id"]
    try:
        proc = subprocess.run(shlex.split(DEPLOY_COMMAND), env=env, timeout=1800)
        STORE.finish_deploy(deploy["id"], proc.returncode == 0)
        print(f"envstore: deploy {deploy['id']} ref={ref[:12]} exit={proc.returncode}", flush=True)
    except Exception as exc:  # timeout, missing binary
        STORE.finish_deploy(deploy["id"], False)
        print(f"envstore: deploy {deploy['id']} failed: {type(exc).__name__}", flush=True)


def _service_object() -> dict:
    return {
        "id": SERVICE_ID,
        "name": SERVICE_NAME,
        "type": "web_service",
        "region": "hetzner",
        "suspended": "not_suspended",
        "plan": "vps",
        "ownerId": "self-hosted",
        "updatedAt": _now(),
        "serviceDetails": {"url": PUBLIC_URL, "region": "hetzner", "plan": "vps", "env": "docker"},
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "envstore/1"

    # ---- helpers ---------------------------------------------------------
    def _send(self, status: int, body: object | None = None) -> None:
        data = b"" if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if data:
            self.wfile.write(data)

    def _authorized(self) -> bool:
        if not TOKEN:
            return True
        header = self.headers.get("Authorization") or ""
        return header.strip() == f"Bearer {TOKEN}"

    def _body_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        if length > MAX_VALUE_BYTES + 4096:
            raise ValueError("body too large")
        raw = self.rfile.read(length)
        body = json.loads(raw.decode("utf-8"))
        return body if isinstance(body, dict) else {}

    def log_message(self, fmt: str, *args) -> None:  # never log bodies
        sys.stderr.write("envstore: %s %s\n" % (self.command, urlparse(self.path).path))

    # ---- routing ---------------------------------------------------------
    def _route(self):
        parsed = urlparse(self.path)
        parts = [p for p in parsed.path.split("/") if p]
        query = {k: v[-1] for k, v in parse_qs(parsed.query).items()}
        if parts == ["healthz"]:
            return self._send(200, {"ok": True, "keys": len(STORE.keys()), "service": SERVICE_ID})
        if len(parts) == 2 and parts[0] == "deploy":
            return self._deploy_hook(parts[1], query)
        if not self._authorized():
            return self._send(401, {"message": "unauthorized"})
        if len(parts) >= 3 and parts[0] == "v1" and parts[1] == "services":
            if parts[2] != SERVICE_ID:
                return self._send(404, {"message": "service not found"})
            rest = parts[3:]
            if not rest and self.command == "GET":
                return self._send(200, _service_object())
            if rest == ["env-vars"]:
                return self._env_list(query)
            if len(rest) == 2 and rest[0] == "env-vars":
                return self._env_item(rest[1])
            if rest == ["deploys"]:
                return self._deploys(query)
        if parts == ["v1", "logs"] and self.command == "GET":
            return self._send(200, {"logs": [], "hasMore": False, "note": "use `docker compose logs` on the host"})
        return self._send(404, {"message": "not found"})

    def _env_list(self, query: dict) -> None:
        if self.command != "GET":
            return self._send(405, {"message": "method not allowed"})
        try:
            limit = max(1, min(int(query.get("limit") or 20), 100))
        except ValueError:
            limit = 20
        return self._send(200, STORE.page(limit, query.get("cursor") or None))

    def _env_item(self, key: str) -> None:
        if not KEY_RE.match(key):
            return self._send(400, {"message": "invalid key"})
        if self.command == "GET":
            value = STORE.get(key)
            if value is None:
                return self._send(404, {"message": "env var not found"})
            return self._send(200, {"key": key, "value": value})
        if self.command == "PUT":
            try:
                body = self._body_json()
            except ValueError as exc:
                return self._send(400, {"message": str(exc)[:80]})
            value = body.get("value")
            if not isinstance(value, str):
                return self._send(400, {"message": "value must be a string"})
            if len(value.encode("utf-8")) > MAX_VALUE_BYTES:
                return self._send(413, {"message": "value too large"})
            STORE.put(key, value)
            print(f"envstore: put {key} bytes={len(value)}", flush=True)
            return self._send(200, {"key": key, "value": value})
        if self.command == "DELETE":
            existed = STORE.delete(key)
            return self._send(204 if existed else 404, None if existed else {"message": "env var not found"})
        return self._send(405, {"message": "method not allowed"})

    def _deploys(self, query: dict) -> None:
        if self.command == "GET":
            try:
                limit = max(1, min(int(query.get("limit") or 20), 100))
            except ValueError:
                limit = 20
            return self._send(200, [{"deploy": d, "cursor": d.get("id")} for d in STORE.deploys()[:limit]])
        if self.command == "POST":
            try:
                body = self._body_json()
            except ValueError as exc:
                return self._send(400, {"message": str(exc)[:80]})
            ref = str(body.get("commitId") or body.get("ref") or "")
            return self._start_deploy(ref, "api")
        return self._send(405, {"message": "method not allowed"})

    def _deploy_hook(self, hook: str, query: dict) -> None:
        if self.command not in ("GET", "POST"):
            return self._send(405, {"message": "method not allowed"})
        if not DEPLOY_HOOK or hook != DEPLOY_HOOK:
            return self._send(404, {"message": "not found"})
        return self._start_deploy(str(query.get("ref") or ""), "hook")

    def _start_deploy(self, ref: str, trigger: str) -> None:
        if ref and (not re.match(r"^[A-Za-z0-9_][A-Za-z0-9_./-]{0,119}$", ref) or ".." in ref):
            return self._send(400, {"message": "invalid ref"})
        deploy = STORE.add_deploy(ref, trigger)
        threading.Thread(target=_run_deploy, args=(deploy, ref), daemon=True).start()
        return self._send(201, deploy)

    def do_GET(self):  # noqa: N802
        self._route()

    def do_PUT(self):  # noqa: N802
        self._route()

    def do_POST(self):  # noqa: N802
        self._route()

    def do_DELETE(self):  # noqa: N802
        self._route()


def serve(port: int = PORT) -> None:
    _vars_dir()
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"envstore: listening on {port}, data={DATA_DIR}, keys={len(STORE.keys())}, auth={'on' if TOKEN else 'OFF'}", flush=True)
    server.serve_forever()


def import_dotenv(path: str, prefixes: tuple[str, ...]) -> int:
    """Load KEY=VALUE lines from a .env export into the store (used once, at migration)."""
    count = 0
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if not KEY_RE.match(key) or (prefixes and not key.startswith(prefixes)):
                continue
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
                value = value[1:-1]
            STORE.put(key, value)
            count += 1
    return count


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "import":
        prefixes = tuple(p for p in (sys.argv[3] if len(sys.argv) > 3 else "NEO_,BACKUP_").split(",") if p)
        n = import_dotenv(sys.argv[2], prefixes)
        print(f"envstore: imported {n} keys with prefixes {prefixes} into {DATA_DIR}")
        sys.exit(0)
    serve()
