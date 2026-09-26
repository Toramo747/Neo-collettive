"""Isolated compatibility check of the real, unmodified production app."""
import os
import subprocess
import sys
import unittest


class RelayCoreTests(unittest.TestCase):
    def test_disabled_overlay_preserves_real_core_and_private_state(self):
        script = '''
import asyncio, copy, httpx
import cloud_mcp
from relay_app import build_app, RelayOverlay
from relay_peer import advance_peer
from test_relay_peer import INTRO, METHOD, ADVERSARIAL
before = copy.deepcopy(cloud_mcp._state_payload())
app = build_app(cloud_mcp.app, {})
assert app is cloud_mcp.app
state = {}
for text in (INTRO, METHOD, ADVERSARIAL):
    state, _ = advance_peer(state, text)
assert state["interview_complete"]
after = cloud_mcp._state_payload()
before.pop("state_saved_at_utc", None)
after.pop("state_saved_at_utc", None)
assert before == after, "relay touched public or commercial state"
assert any(getattr(r, "path", "") == "/a2a" and r.endpoint is cloud_mcp.a2a_endpoint for r in app.routes)
async def probe():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://test") as c:
        result = await c.get("/health")
        assert result.status_code == 200
        assert result.json()["version"] == cloud_mcp.VERSION
        result = await c.get("/api/autopilot/status")
        assert result.status_code == 200
        assert not result.json()["autopilot"]["enabled"]
asyncio.run(probe())
print("real core unchanged; disabled overlay is identical; private relay did not mutate state")
'''
        env = dict(os.environ, NEO_AUTOPILOT_ENABLED="false", NEO_SETI_ENABLED="false",
                   NEO_CYCLE_FLOOR_URL=" ", MYCELIX_RELAY_ENABLED="0",
                   RENDER_API_KEY="", RENDER_SERVICE_ID="", JARVIS_API_KEY="", JARVIS_URL="")
        result = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
