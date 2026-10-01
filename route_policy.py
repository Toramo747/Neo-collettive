from __future__ import annotations

import base64
import hmac
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Callable

from starlette.responses import Response

PUBLIC = "PUBLIC"
PUBLIC_PROJECTION = "PUBLIC_PROJECTION"
ADMIN = "ADMIN"
OPS = "OPS"

# Exact runtime routes. Prefix families are handled by classify_path().
ROUTE_POLICY = {
    "/": PUBLIC,
    "/health": PUBLIC,
    "/livez": PUBLIC,
    "/readyz": PUBLIC,
    "/.well-known/agent-card.json": PUBLIC,
    "/.well-known/agent.json": PUBLIC,
    "/.well-known/mcp.json": PUBLIC,
    "/a2a": PUBLIC,
    "/mcp": PUBLIC,
    "/registry-health": PUBLIC,
    "/registry-health/about": PUBLIC,
    "/arena": PUBLIC,
    "/arena/neo-dialect": PUBLIC,
    "/arena/micelio": PUBLIC,
    "/arena/evoluzione": PUBLIC,
    "/neo-dialect/1.0": PUBLIC,
    "/api/discover": PUBLIC,
    "/agent": PUBLIC,
    "/radar": PUBLIC,
    "/trust": PUBLIC,
    "/agent-demand": PUBLIC,
    "/api/agent-demand": PUBLIC,
    "/council/neo-dialect/example": PUBLIC,
    "/collective": PUBLIC,
    "/api/checkpoint-status": PUBLIC,

    "/inbox": PUBLIC_PROJECTION,
    "/agent-chats": PUBLIC_PROJECTION,
    "/api/agent-chats": PUBLIC_PROJECTION,
    "/api/inbound/agents": PUBLIC_PROJECTION,
    "/api/intelligence": PUBLIC_PROJECTION,
    "/intelligence": PUBLIC_PROJECTION,

    "/api/autopilot/status": ADMIN,
    "/api/render/errors": ADMIN,
    "/api/render/diagnostics": ADMIN,
    "/system": ADMIN,
    "/api/director/run": ADMIN,
    "/api/director/results": ADMIN,
    "/results": ADMIN,
    "/api/outcomes": ADMIN,
    "/api/console": ADMIN,
    "/console": ADMIN,
    "/api/agents/diagnostics": ADMIN,
    "/council": ADMIN,
    "/api/council": ADMIN,
    "/seti/interviews": ADMIN,
    "/api/seti/interviews": ADMIN,
    "/admin/seti-interviews": ADMIN,
    "/api/admin/seti-interviews": ADMIN,
    "/api/admin/inbound": ADMIN,
    "/api/admin/agent-chats": ADMIN,
    "/api/self-improvement/proposal": ADMIN,
    "/api/collective": ADMIN,
    "/director": ADMIN,
    "/api/trust/evaluate": ADMIN,
    "/venture": ADMIN,
    "/api/venture/audit": ADMIN,
    "/api/venture/measurement": ADMIN,

    "/api/memory/status": OPS,
    "/api/builder/status": OPS,
    "/api/autonomy/status": OPS,
    "/api/runtime/snapshot-state": OPS,
    "/api/heartbeat": OPS,
    "/api/runtime/snapshot-published": OPS,
    "/api/market/run-cycles": OPS,
}

FAILED_AUTH_LIMIT = 10
FAILED_AUTH_WINDOW_SECONDS = 600.0


def classify_path(path: str) -> str:
    value = str(path or "/")
    if value.startswith("/mcp"):
        return PUBLIC
    if value.startswith("/admin/") or value.startswith("/api/admin/"):
        return ADMIN
    if value.startswith("/registry-health"):
        return PUBLIC
    if value.startswith("/arena"):
        return PUBLIC
    if value.startswith("/.well-known/"):
        return ROUTE_POLICY.get(value, ADMIN)
    return ROUTE_POLICY.get(value, ADMIN)


def admin_header_authorized(headers: dict[str, str], admin_token: str) -> bool:
    expected = str(admin_token or "")
    if not expected:
        return False
    auth = str(headers.get("authorization") or "").strip()
    if not auth:
        return False
    lower = auth.lower()
    if lower.startswith("bearer "):
        supplied = auth[7:].strip()
        return bool(supplied) and hmac.compare_digest(supplied, expected)
    if lower.startswith("basic "):
        try:
            raw = base64.b64decode(auth.split(None, 1)[1], validate=True).decode("utf-8", "strict")
            _username, supplied = raw.split(":", 1)
        except Exception:
            return False
        return bool(supplied) and hmac.compare_digest(supplied, expected)
    return False


def scope_headers(scope) -> dict[str, str]:
    return {
        key.decode("latin1").lower(): value.decode("latin1")
        for key, value in (scope.get("headers") or [])
    }


def scope_origin(scope, headers: dict[str, str]) -> str:
    forwarded = str(headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if forwarded:
        return forwarded[:160]
    real = str(headers.get("x-real-ip") or "").strip()
    if real:
        return real[:160]
    client = scope.get("client") or ("", 0)
    return str(client[0] or "unknown")[:160]


@dataclass
class RoutePolicyConfig:
    admin_token: Callable[[], str]
    hmac_secret: Callable[[], str]
    verify_hmac: Callable[[str, str, str], dict]
    projections_public: bool = False


class RoutePolicyMiddleware:
    """Central default-deny route authorization.

    PUBLIC is open. PUBLIC_PROJECTION remains admin-only until the projection
    handlers are deployed. ADMIN accepts only Basic/Bearer admin credentials.
    OPS accepts admin OR the existing per-path HMAC proof.
    """

    def __init__(self, app, config: RoutePolicyConfig):
        self.app = app
        self.config = config
        self._failed: dict[str, deque[float]] = defaultdict(deque)

    def _failed_limited(self, origin: str) -> bool:
        now = time.monotonic()
        cutoff = now - FAILED_AUTH_WINDOW_SECONDS
        bucket = self._failed[origin]
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()
        if len(bucket) >= FAILED_AUTH_LIMIT:
            return True
        bucket.append(now)
        return False

    @staticmethod
    async def _send_response(scope, receive, send, status: int, *, authenticate: bool = False):
        headers = {}
        if authenticate:
            headers["WWW-Authenticate"] = 'Basic realm="MYCELIX Admin", charset="UTF-8"'
        response = Response(content=b"", status_code=status, headers=headers)
        await response(scope, receive, send)

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            return await self.app(scope, receive, send)

        path = str(scope.get("path") or "/")
        method = str(scope.get("method") or "GET").upper()
        if path == "/api/director/run" and method != "POST":
            return await self.app(scope, receive, send)
        policy = classify_path(path)
        if policy == PUBLIC:
            return await self.app(scope, receive, send)
        if policy == PUBLIC_PROJECTION and self.config.projections_public:
            return await self.app(scope, receive, send)
        if policy == PUBLIC_PROJECTION:
            policy = ADMIN

        headers = scope_headers(scope)
        admin_token = str(self.config.admin_token() or "")
        if admin_header_authorized(headers, admin_token):
            return await self.app(scope, receive, send)

        if policy == OPS:
            proof = str(headers.get("x-mycelix-self-traffic-proof") or "")
            legacy = bool(headers.get("x-neo-heartbeat-token"))
            secret = str(self.config.hmac_secret() or "")
            verified = self.config.verify_hmac(secret, path, proof) if secret and proof and not legacy else {}
            if bool((verified or {}).get("valid")):
                return await self.app(scope, receive, send)

        # Missing admin credentials never degrade ADMIN/PROJECTION routes to public.
        if not admin_token:
            return await self._send_response(scope, receive, send, 503)

        origin = scope_origin(scope, headers)
        if self._failed_limited(origin):
            return await self._send_response(scope, receive, send, 429)

        return await self._send_response(scope, receive, send, 401, authenticate=True)
