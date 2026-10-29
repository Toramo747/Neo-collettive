# SPDX-License-Identifier: BUSL-1.1
"""mcp-ledger (29/10): digests, Merkle proofs, per-server state, volatility, well-known opt-out, offline read."""
import asyncio
import gzip
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import tools.mcp_ledger as L


class TestCanonical(unittest.TestCase):
    def test_url_canonical_and_key_stable(self):
        a = L.canonical_url("HTTPS://Example.COM:443/mcp#frag")
        b = L.canonical_url("https://example.com/mcp")
        self.assertEqual(a, b)
        self.assertEqual(L.server_key(a), L.server_key(b))
        self.assertEqual(len(L.server_key(a)), 32)
        self.assertNotEqual(L.server_key("https://example.com/mcp"), L.server_key("https://example.com/mcp?x=1"))
        self.assertEqual(L.canonical_url("https://example.com:8443/mcp"), "https://example.com:8443/mcp")

    def test_key_formula_is_public(self):
        url = "https://example.com/mcp"
        expect = hashlib.sha256(b"neo-mcp-ledger-v1\x00" + url.encode()).hexdigest()[:32]
        self.assertEqual(L.server_key(url), expect)

    def test_contract_sorted_and_digest_ignores_order_and_extra_fields(self):
        t1 = [{"name": "b", "description": "B", "inputSchema": {"type": "object"}, "extra": 1},
              {"name": "a", "description": "A", "inputSchema": {"type": "object"}}]
        t2 = list(reversed(t1))
        c1, c2 = L.contract_of(t1), L.contract_of(t2)
        self.assertEqual([t["name"] for t in c1], ["a", "b"])
        self.assertEqual(L.contract_digest(c1), L.contract_digest(c2))
        c3 = L.contract_of([dict(t1[0], description="B changed"), t1[1]])
        self.assertNotEqual(L.contract_digest(c1), L.contract_digest(c3))
        self.assertEqual(L.contract_of([{"description": "no name"}, "junk"]), [])


class TestMerkle(unittest.TestCase):
    def rows(self, n):
        return sorted([[hashlib.sha256(str(i).encode()).hexdigest()[:32], "d" * 64, "ok", i] for i in range(n)], key=lambda r: r[0])

    def test_root_and_paths_verify(self):
        for n in (1, 2, 3, 5, 8, 13):
            rows = self.rows(n)
            root = L.merkle_root(rows)
            for i in range(n):
                path = L.merkle_path(rows, i)
                self.assertTrue(L.verify_path(rows[i], path, root), (n, i))
                bad = list(rows[i])
                bad[2] = "no_tools"
                self.assertFalse(L.verify_path(bad, path, root))

    def test_root_changes_with_any_row(self):
        rows = self.rows(6)
        root = L.merkle_root(rows)
        rows[3][1] = "e" * 64
        self.assertNotEqual(root, L.merkle_root(rows))

    def test_empty(self):
        self.assertEqual(L.merkle_root([]), hashlib.sha256(b"").hexdigest())


class TestState(unittest.TestCase):
    def test_changes_gaps_and_volatility(self):
        st = {}
        L.update_state(st, "k", "2026-10-29", "ok", "a" * 64)
        self.assertEqual(st["k"]["first_seen"], "2026-10-29")
        L.update_state(st, "k", "2026-10-30", "unreachable", None)   # a gap is not a change
        L.update_state(st, "k", "2026-10-31", "ok", "a" * 64)
        self.assertEqual(st["k"]["changes"], [])
        self.assertEqual(st["k"]["gaps"], 1)
        for i, d in enumerate(("b", "c", "d")):
            L.update_state(st, "k", f"2026-11-0{i+1}", "ok", d * 64)
        self.assertEqual(len(st["k"]["changes"]), 3)
        self.assertTrue(L.is_volatile(st["k"], "2026-11-03"))
        self.assertFalse(L.is_volatile(st["k"], "2026-11-20"))
        self.assertEqual([h[1][0] for h in st["k"]["history"]], ["a", "b", "c", "d"])


class _Resp:
    def __init__(self, status, body):
        self.status, self.body = status, body


class TestReadOffline(unittest.TestCase):
    """read_contract against a fake _bounded_request: initialize, initialized, tools/list with two pages."""

    def _fake(self, calls):
        async def fake(client, method, url, *, json_body=None, headers=None, user_agent=None, request_pacer=None, request_counts=None):
            calls.append(json_body["method"])
            if json_body["method"] == "initialize":
                return {"status": 200, "headers": {"content-type": "application/json", "mcp-session-id": "s1"},
                        "body": json.dumps({"result": {"protocolVersion": "2025-11-25"}})}
            if json_body["method"] == "notifications/initialized":
                return {"status": 202, "headers": {"content-type": "application/json"}, "body": ""}
            if json_body["method"] == "tools/list":
                self.assertEqual(headers.get("Mcp-Session-Id"), "s1")
                if not json_body["params"].get("cursor"):
                    return {"status": 200, "headers": {"content-type": "text/event-stream"},
                            "body": "event: message\ndata: " + json.dumps({"result": {"tools": [{"name": "z", "inputSchema": {}}], "nextCursor": "p2"}}) + "\n"}
                return {"status": 200, "headers": {"content-type": "application/json"},
                        "body": json.dumps({"result": {"tools": [{"name": "a", "description": "A", "inputSchema": {}}]}})}
            raise AssertionError(json_body)
        return fake

    def test_pages_followed_and_contract_sorted(self):
        calls = []
        import mcp_endpoint_verifier as ev
        with mock.patch.object(ev, "_bounded_request", self._fake(calls)):
            r = asyncio.run(L.read_contract("https://example.com/mcp", client=None, pacer=None))
        self.assertEqual(r["outcome"], "ok")
        self.assertEqual(r["pages"], 2)
        self.assertEqual([t["name"] for t in L.contract_of(r["tools"])], ["a", "z"])
        self.assertEqual(calls, ["initialize", "notifications/initialized", "tools/list", "tools/list"])

    def test_refused_and_unreachable(self):
        import mcp_endpoint_verifier as ev

        async def refused(*a, **k):
            return {"status": 401, "headers": {"content-type": "application/json"}, "body": ""}

        async def down(*a, **k):
            raise ev.VerificationError("transport_error", "ConnectTimeout")

        with mock.patch.object(ev, "_bounded_request", refused):
            self.assertEqual(asyncio.run(L.read_contract("https://x.example/mcp", None, None))["outcome"], "refused")
        with mock.patch.object(ev, "_bounded_request", down):
            self.assertEqual(asyncio.run(L.read_contract("https://x.example/mcp", None, None))["outcome"], "timeout")


class TestProve(unittest.TestCase):
    def test_prove_from_day_file(self):
        with tempfile.TemporaryDirectory() as d:
            rows = sorted([["k1" * 16, "a" * 64, "ok", 3], ["k2" * 16, "", "unreachable", 0]], key=lambda r: r[0])
            root = L.merkle_root(rows)
            days = Path(d) / "days"
            days.mkdir()
            with gzip.open(days / "2026-10-29.json.gz", "wt") as f:
                json.dump({"rows": rows, "root": root}, f)
            import io, contextlib
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = L.prove("2026-10-29", "k2" * 16, d)
            out = json.loads(buf.getvalue())
            self.assertEqual(rc, 0)
            self.assertTrue(out["verified"])
            self.assertEqual(out["row"][2], "unreachable")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(L.prove("2026-10-29", "zz" * 16, d), 1)


if __name__ == "__main__":
    unittest.main()


class TestRunReadOffline(unittest.TestCase):
    """Whole daily read with the registry and the handshake faked: files, root, summary, private archive, idempotence."""

    def test_end_to_end(self):
        import registry_health as rh
        servers = [{"name": f"io.example/s{i}", "access_class": "remote", "remotes": [{"url": f"https://s{i}.example.com/mcp"}]} for i in range(4)]
        servers[3]["remotes"][0]["url"] = "https://s2.example.com/other"  # same host as s2: one well-known check per host

        async def fake_registry(client):
            return {"servers": servers + [{"name": "pkg", "access_class": "package_only", "remotes": []}]}

        async def fake_read(url, client, pacer):
            if "s0" in url:
                return {"outcome": "ok", "tools": [{"name": "t", "inputSchema": {}}], "latency_ms": 10, "pages": 1}
            if "s1" in url:
                return {"outcome": "unreachable", "tools": None}
            return {"outcome": "ok", "tools": [{"name": "u", "description": url, "inputSchema": {}}], "latency_ms": 20, "pages": 1}

        async def no_opt_out(host, client):
            return host == "s1.example.com"

        with tempfile.TemporaryDirectory() as d, mock.patch.object(rh, "fetch_complete_registry", fake_registry), \
             mock.patch.object(rh, "read_opt_out", lambda: set()), mock.patch.object(L, "read_contract", fake_read), \
             mock.patch.object(L, "well_known_opt_out", no_opt_out):
            pub, priv = str(Path(d) / "pub"), str(Path(d) / "priv")
            rc = L.main(["read", "--state", pub, "--private", priv, "--concurrency", "4"])
            self.assertEqual(rc, 0)
            roots = list((Path(pub) / "days").glob("*.root.json"))
            self.assertEqual(len(roots), 1)
            s = json.loads(roots[0].read_text())
            self.assertEqual(s["rows"], 4)
            self.assertEqual(s["outcomes"], {"ok": 3, "opted_out": 1})
            self.assertEqual(s["distinct_contracts_new_in_archive"], 3)
            self.assertFalse(s["names_published"])
            day = json.loads(gzip.open(roots[0].with_name(roots[0].name.replace(".root.json", ".json.gz")), "rt").read())
            self.assertEqual(day["root"], L.merkle_root(day["rows"]))
            dumped = (Path(pub) / "days" / roots[0].name).read_text() + json.dumps(day)
            self.assertNotIn("example.com", dumped)  # no URL, no name in the public repo
            self.assertEqual(len(list((Path(priv) / "mcp-ledger" / "contracts").rglob("*.json.gz"))), 3)
            # second run the same day: nothing happens
            rc2 = L.main(["read", "--state", pub, "--private", priv])
            self.assertEqual(rc2, 0)
            self.assertEqual(len(list((Path(pub) / "days").glob("*.root.json"))), 1)


class TestPurge(unittest.TestCase):
    def test_opted_out_texts_removed_unless_shared(self):
        with tempfile.TemporaryDirectory() as d:
            priv = Path(d)
            for dg in ("a" * 64, "b" * 64):
                f = priv / L.PRIVATE_SUBDIR / dg[:2] / f"{dg}.json.gz"
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_bytes(b"x")
            state = {"gone": {"last": "a" * 64, "history": [["2026-10-29", "a" * 64], ["2026-10-30", "b" * 64]]},
                     "stays": {"last": "b" * 64, "history": [["2026-10-29", "b" * 64]]}}
            n = L.purge_opted_out(state, ["gone"], priv)
            self.assertEqual(n, 1)
            self.assertFalse((priv / L.PRIVATE_SUBDIR / "aa" / ("a" * 64 + ".json.gz")).exists())
            self.assertTrue((priv / L.PRIVATE_SUBDIR / "bb" / ("b" * 64 + ".json.gz")).exists())
            self.assertTrue(state["gone"]["opted_out"])
            self.assertEqual(L.purge_opted_out(state, [], priv), 0)
