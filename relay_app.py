"""Opt-in ASGI overlay: all non-relay traffic/lifespan go to the unchanged app."""
from __future__ import annotations

import asyncio
import hmac
import json
import os
from functools import partial

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route, Router

from relay_store import RelayError, RelayStore, token_hash

PREFIX = "/api/relay"
MAX_BODY = 16384


def response(data, status=200, retry_after=0):
    headers = {"Cache-Control": "no-store", "Pragma": "no-cache", "X-Content-Type-Options": "nosniff"}
    if retry_after:
        headers["Retry-After"] = str(retry_after)
    return JSONResponse(data, status_code=status, headers=headers)


def bearer(request: Request) -> str:
    if any(k in request.query_params for k in ("token", "access_token", "api_key")):
        raise RelayError("credentials_must_use_headers")
    header = request.headers.get("authorization", "")
    if not header.startswith("Bearer "):
        raise RelayError("invalid_credentials", 401)
    value = header[7:]
    token_hash(value)
    return value


async def read_json(request: Request, allowed: set[str]) -> dict:
    if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
        raise RelayError("json_required", 415)
    async def collect():
        chunks, size = [], 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > MAX_BODY:
                raise RelayError("request_too_large", 413)
            chunks.append(chunk)
        return b"".join(chunks)
    try:
        raw = await asyncio.wait_for(collect(), timeout=5)
        data = json.loads(raw)
    except (ValueError, UnicodeError):
        raise RelayError("invalid_json") from None
    except asyncio.TimeoutError:
        raise RelayError("request_timeout", 408) from None
    if not isinstance(data, dict) or set(data) - allowed:
        raise RelayError("invalid_fields")
    return data


class RelayOverlay:
    def __init__(self, legacy_app, store=None, *, invite="", engine=None, unavailable=False):
        self.legacy_app, self.store = legacy_app, store
        self.invite, self.engine, self.unavailable = invite, engine, unavailable
        self.router = Router(routes=[
            Route(PREFIX + "/info", self.info, methods=["GET"]),
            Route(PREFIX + "/threads", self.enroll, methods=["POST"]),
            Route(PREFIX + "/threads/{thread_id}/poll", self.poll, methods=["GET"]),
            Route(PREFIX + "/threads/{thread_id}/ack", self.ack, methods=["POST"]),
            Route(PREFIX + "/threads/{thread_id}/reply", self.reply, methods=["POST"]),
            Route(PREFIX + "/threads/{thread_id}", self.close, methods=["DELETE"]),
        ], redirect_slashes=False)

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if scope["type"] != "http" or not (path == PREFIX or path.startswith(PREFIX + "/")):
            return await self.legacy_app(scope, receive, send)
        if self.unavailable:
            return await response({"ok": False, "error": "relay_unavailable"}, 503)(scope, receive, send)
        try:
            await self.router(scope, receive, send)
        except RelayError as exc:
            await response({"ok": False, "error": exc.code}, exc.status, exc.retry_after)(scope, receive, send)
        except Exception:
            # Storage/engine failure must not leak messages, tokens or affect the core.
            await response({"ok": False, "error": "relay_unavailable"}, 503)(scope, receive, send)

    async def info(self, request):
        return response({"protocol": "mycelix-relay/v1", "mode": "invite_only_pilot",
                         "custom_api_not_a2a_tasks": True, "requires_client_polling": True,
                         "public_thread_listing": False, "commercial_influence": "NONE"})

    async def enroll(self, request):
        supplied = request.headers.get("x-mycelix-relay-invite", "")
        if not self.invite or not hmac.compare_digest(supplied.encode(), self.invite.encode()):
            raise RelayError("enrollment_not_authorized", 403)
        token = bearer(request)
        data = await read_json(request, {"agent_id", "message_id", "text"})
        result = await run_in_threadpool(partial(self.store.open, token, data.get("agent_id"),
                          data.get("message_id"), data.get("text"), self.engine))
        return response(result, 201)

    async def poll(self, request):
        token = bearer(request)
        value = request.query_params.get("after", "0")
        if not value.isascii() or not value.isdigit() or len(value) > 7:
            raise RelayError("invalid_sequence")
        result = await run_in_threadpool(self.store.poll, request.path_params["thread_id"], token, int(value))
        return response(result)

    async def ack(self, request):
        token = bearer(request)
        data = await read_json(request, {"through"})
        result = await run_in_threadpool(self.store.ack, request.path_params["thread_id"], token, data.get("through"))
        return response(result)

    async def reply(self, request):
        token = bearer(request)
        data = await read_json(request, {"message_id", "text", "in_reply_to"})
        result = await run_in_threadpool(partial(self.store.reply, request.path_params["thread_id"],
                          token, data.get("message_id"), data.get("text"), data.get("in_reply_to"), self.engine))
        return response(result)

    async def close(self, request):
        token = bearer(request)
        result = await run_in_threadpool(self.store.close, request.path_params["thread_id"], token)
        return response(result)


def build_app(legacy_app, environ=None):
    env = os.environ if environ is None else environ
    if str(env.get("MYCELIX_RELAY_ENABLED", "0")).lower() not in {"1", "true"}:
        return legacy_app  # Identical object, no routes, database or engine imported.
    try:
        if env.get("MYCELIX_RELAY_STORAGE_CONFIRMED") != "1":
            raise ValueError("persistent_volume_not_confirmed")
        invite = env.get("MYCELIX_RELAY_INVITE", "")
        if len(invite) < 32:
            raise ValueError("invite_required")
        store = RelayStore(env.get("MYCELIX_RELAY_DB_PATH", ""),
                           env.get("MYCELIX_RELAY_NAMESPACE", "mycelix-prod-main"))
        from relay_peer import advance_peer
        return RelayOverlay(legacy_app, store, invite=invite, engine=advance_peer)
    except Exception:
        return RelayOverlay(legacy_app, unavailable=True)
