import base64
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
import receipt_cite as rc  # noqa: E402
import receipt_log as rl  # noqa: E402
from receipt_signing import sign_receipt  # noqa: E402
from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402


class ReceiptCiteTest(unittest.TestCase):
    def setUp(self):
        self.key = Ed25519PrivateKey.generate()
        self.pub = base64.b64encode(self.key.public_key().public_bytes(serialization.Encoding.Raw,
                                                                       serialization.PublicFormat.Raw)).decode()
        log = rl.empty()
        log = rl.append(log, "receipt", "a" * 64)
        self.rec = sign_receipt({"ok": True, "outcome": "verbatim", "url": "https://example.org/"}, self.key,
                                log=rl.next_position(log))
        log = rl.append(log, "receipt", rl.item_hash(self.rec))
        log = rl.append(log, "receipt", "b" * 64)
        self.d = tempfile.TemporaryDirectory()
        self.log = Path(self.d.name) / "log.jsonl"
        self.log.write_text("".join(json.dumps(e) + "\n" for e in log["entries"]))
        self.wit = Path(self.d.name) / "w.jsonl"
        head = rl.verify_chain(log["entries"])["head"]
        self.wit.write_text(json.dumps({"attestation": {"log_size": 3, "log_head": head}}) + "\n")

    def tearDown(self):
        self.d.cleanup()

    def chk(self, rec, wit=None):
        return rc.check(rec, self.pub, self.log, wit or self.wit)

    def test_good_receipt(self):
        line = "Here is my proof: RECEIPT " + json.dumps(self.rec) + " (from neo)"
        self.assertEqual(self.chk(rc.parse(line)), [])

    def test_tampered_outcome(self):
        bad = dict(self.rec, outcome="not_found")
        fails = " ".join(self.chk(bad))
        self.assertIn("signature", fails)
        self.assertIn("different receipt hash", fails)

    def test_other_key(self):
        other = base64.b64encode(Ed25519PrivateKey.generate().public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()
        self.assertTrue(rc.check(self.rec, other, self.log, self.wit))

    def test_no_witness_covers_it(self):
        w = Path(self.d.name) / "none.jsonl"
        w.write_text("")
        self.assertTrue(any("no witness" in f for f in self.chk(self.rec, w)))

    def test_parse(self):
        self.assertIsNone(rc.parse("no receipt"))
        self.assertIsNone(rc.parse("RECEIPT {broken"))


if __name__ == "__main__":
    unittest.main()
