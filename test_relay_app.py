import secrets
import tempfile
import unittest
from unittest.mock import patch

import httpx

from relay_app import RelayOverlay, build_app
from relay_store import RelayStore
from test_relay_store import engine


async def legacy(scope, receive, send):
    if scope["type"] == "lifespan":
        event = await receive()
        await send({"type": event["type"] + ".complete"})
        return
    await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"text/plain")]})
    await send({"type": "http.response.body", "body": ("legacy:" + scope["path"]).encode()})


class RelayAppTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.token, self.invite = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        self.store = RelayStore(self.temp.name + "/relay.db", "test")
        self.app = RelayOverlay(legacy, self.store, invite=self.invite, engine=engine)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="https://test")
        self.addAsyncCleanup(self.client.aclose)
        self.headers = {"Authorization": "Bearer " + self.token, "X-Mycelix-Relay-Invite": self.invite}

    async def enroll(self):
        r = await self.client.post("/api/relay/threads", headers=self.headers,
                                   json={"agent_id": "pilot", "message_id": "intro", "text": "Introduction"})
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()["thread_id"]

    async def test_disabled_returns_identical_app_and_does_not_open_database(self):
        with patch("relay_app.RelayStore", side_effect=AssertionError("must not open")):
            self.assertIs(build_app(legacy, {}), legacy)
            self.assertIs(build_app(legacy, {"MYCELIX_RELAY_ENABLED": "0"}), legacy)

    async def test_missing_storage_configuration_does_not_break_legacy(self):
        app = build_app(legacy, {"MYCELIX_RELAY_ENABLED": "1"})
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://test") as c:
            self.assertEqual((await c.get("/health")).text, "legacy:/health")
            self.assertEqual((await c.post("/a2a", json={})).text, "legacy:/a2a")
            self.assertEqual((await c.get("/api/relay/info")).status_code, 503)

    async def test_other_endpoints_pass_through_unchanged(self):
        for path in ("/health", "/a2a", "/api/heartbeat", "/mcp", "/api/relay-other", "/api/autopilot/status"):
            self.assertEqual((await self.client.get(path)).text, "legacy:" + path)

    async def test_lifespan_passthrough(self):
        sent = []
        async def receive():
            return {"type": "lifespan.startup"}
        async def send(message):
            sent.append(message)
        await self.app({"type": "lifespan"}, receive, send)
        self.assertEqual(sent, [{"type": "lifespan.startup.complete"}])

    async def test_no_public_listing_and_invite_required(self):
        self.assertEqual((await self.client.get("/api/relay/threads")).status_code, 405)
        r = await self.client.post("/api/relay/threads", json={})
        self.assertEqual(r.status_code, 403)

    async def test_http_roundtrip_poll_ack_reply_close(self):
        tid = await self.enroll()
        base = "/api/relay/threads/" + tid
        polled = await self.client.get(base + "/poll", headers=self.headers)
        self.assertEqual(polled.json()["messages"][0]["sequence"], 2)
        ack = await self.client.post(base + "/ack", headers=self.headers, json={"through": 2})
        self.assertEqual(ack.json()["acknowledged_through"], 2)
        r = await self.client.post(base + "/reply", headers=self.headers,
                                   json={"message_id": "r2", "in_reply_to": 2, "text": "My answer"})
        self.assertEqual(r.json()["state"]["round"], 2)
        self.assertEqual(r.headers["cache-control"], "no-store")
        self.assertNotIn(self.token, r.text)
        self.assertEqual((await self.client.delete(base, headers=self.headers)).status_code, 200)
        self.assertEqual((await self.client.get(base + "/poll", headers=self.headers)).status_code, 410)

    async def test_query_string_credentials_rejected(self):
        tid = await self.enroll()
        r = await self.client.get("/api/relay/threads/" + tid + "/poll?token=hidden", headers=self.headers)
        self.assertEqual(r.status_code, 400)

    async def test_bad_json_and_oversize_body_rejected(self):
        h = dict(self.headers, **{"Content-Type": "application/json"})
        for content, code in (("{broken", 400), ("[]", 400), ("x" * 17000, 413)):
            r = await self.client.post("/api/relay/threads", headers=h, content=content)
            self.assertEqual(r.status_code, code)

    async def test_no_callback_or_unknown_fields_accepted(self):
        r = await self.client.post("/api/relay/threads", headers=self.headers,
                                   json={"agent_id": "pilot", "message_id": "intro", "text": "Hi",
                                         "callback": "http://127.0.0.1/private"})
        self.assertEqual(r.status_code, 400)

    async def test_engine_error_is_contained_and_sanitized(self):
        tid = await self.enroll()
        def broken(old, text):
            raise RuntimeError("secret-detail")
        self.app.engine = broken
        r = await self.client.post("/api/relay/threads/" + tid + "/reply", headers=self.headers,
                                   json={"message_id": "r2", "in_reply_to": 2, "text": "answer"})
        self.assertEqual(r.status_code, 503)
        self.assertNotIn("secret-detail", r.text)
        self.assertEqual((await self.client.get("/health")).status_code, 200)

    async def test_storage_error_is_contained(self):
        tid = await self.enroll()
        with patch.object(self.store, "poll", side_effect=OSError("private path")):
            r = await self.client.get("/api/relay/threads/" + tid + "/poll", headers=self.headers)
        self.assertEqual(r.status_code, 503)
        self.assertNotIn("private path", r.text)
        self.assertEqual((await self.client.get("/health")).text, "legacy:/health")

    async def test_rate_limit_header(self):
        tid = await self.enroll()
        self.store.requests_per_minute = 1
        path = "/api/relay/threads/" + tid + "/poll"
        await self.client.get(path, headers=self.headers)
        r = await self.client.get(path, headers=self.headers)
        self.assertEqual(r.status_code, 429)
        self.assertGreater(int(r.headers["retry-after"]), 0)


if __name__ == "__main__":
    unittest.main()
