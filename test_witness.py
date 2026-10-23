import base64
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "tools"))
import witness as w  # noqa: E402
from receipt_signing import canonical_json  # noqa: E402


def good(name="skitter"):
    return w.parse(w.template(name))


class WitnessTest(unittest.TestCase):
    def test_template_is_accepted(self):
        att = good()
        self.assertEqual(w.check(att, poster="skitter"), [])

    def test_prefix_is_accepted(self):
        es = w.entries()
        from receipt_log import verify_chain
        att = good()
        att["log_size"] = 1
        att["log_head"] = verify_chain(es[:1])["head"]
        self.assertEqual(w.check(att), [])

    def test_split_view_is_caught(self):
        att = good()
        att["log_head"] = "0" * 64
        self.assertTrue(any("SPLIT VIEW" in f for f in w.check(att)))

    def test_size_beyond_log(self):
        att = good()
        att["log_size"] = len(w.entries()) + 1
        self.assertTrue(w.check(att))

    def test_wrong_poster(self):
        self.assertTrue(any("not the agent" in f for f in w.check(good("skitter"), poster="mallory")))

    def test_unknown_and_missing_fields(self):
        att = good()
        att["extra"] = 1
        del att["method"]
        fails = " ".join(w.check(att))
        self.assertIn("unknown fields", fails)
        self.assertIn("missing fields", fails)

    def test_future_time(self):
        att = good()
        att["checked_at_utc"] = "2999-01-01T00:00:00Z"
        self.assertTrue(any("future" in f for f in w.check(att)))

    def test_parse_ignores_text_around(self):
        line = w.template("skitter")
        self.assertIsNotNone(w.parse("Hello neo.\n" + line + "\nThanks"))
        self.assertIsNone(w.parse("no attestation here"))
        self.assertIsNone(w.parse("WITNESS {not json}"))

    def test_signature(self):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives import serialization
        k = Ed25519PrivateKey.generate()
        pub = base64.b64encode(k.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()
        att = good()
        att["key_url"] = "https://example.org/key"
        att["sig"] = base64.urlsafe_b64encode(k.sign(canonical_json(att))).decode().rstrip("=")
        self.assertEqual(w.check(att, fetch_key=lambda u: pub), [])
        att["log_size"] = 1  # tampered after signing (also a split view now)
        self.assertTrue(any("signature" in f for f in w.check(att, fetch_key=lambda u: pub)))
        att2 = dict(att)
        del att2["key_url"]
        self.assertTrue(any("go together" in f for f in w.check(att2)))

    def test_collect_appends_once(self):
        line = w.template("skitter")
        board = {"replies_for_neo": [{"id": "e1", "agent": "skitter", "body": line, "createdAt": 1},
                                     {"id": "e2", "agent": "mallory", "body": line, "createdAt": 2},
                                     {"id": "e3", "agent": "x", "body": "hi", "createdAt": 3}]}
        with tempfile.TemporaryDirectory() as d:
            b = Path(d) / "board.json"
            b.write_text(json.dumps(board))
            out = Path(d) / "witnesses.jsonl"
            w.collect(str(b), str(out))
            w.collect(str(b), str(out))
            rows = [json.loads(l) for l in out.read_text().splitlines()]
            self.assertEqual([r["post_id"] for r in rows], ["e1"])
            self.assertFalse(rows[0]["signed"])

    def test_observe_another_log(self):
        line = w.observe(str(w.LOG), "someone-log")
        att = w.parse(line)
        self.assertEqual(att["log"], "someone-log")
        self.assertEqual(att["log_size"], len(w.entries()))


if __name__ == "__main__":
    unittest.main()
