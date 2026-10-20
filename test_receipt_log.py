import unittest

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import receipt_log as rl
import receipt_signing as rs

SEED = bytes.fromhex("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60")  # RFC 8032 test 1


class ReceiptLogTests(unittest.TestCase):
    def test_chain_verifies_and_any_edit_breaks_it(self):
        log = rl.empty()
        for i in range(5):
            log = rl.append(log, "receipt", rl.item_hash({"n": i}), ts=1000 + i)
        ok = rl.verify_chain(log["entries"])
        self.assertTrue(ok["ok"])
        self.assertEqual(ok["head"], log["head"])
        tampered = [list(e) for e in log["entries"]]
        tampered[2][3] = rl.item_hash({"n": 99})
        self.assertNotEqual(rl.verify_chain(tampered)["head"], log["head"])
        removed = log["entries"][:2] + log["entries"][3:]
        self.assertFalse(rl.verify_chain(removed)["ok"])

    def test_correction_is_appended_not_edited(self):
        log = rl.append(rl.empty(), "receipt", rl.item_hash({"n": 1}), ts=1)
        first = list(log["entries"][0])
        extra = {"ref": "1", "reason": "IPv6 bug, fixed in 0.99.67", "version": "0.99.67"}
        log = rl.append(log, "correction", rl.item_hash(extra), extra, ts=2)
        self.assertEqual(log["entries"][0], first)
        self.assertEqual(log["entries"][1][2], "correction")
        self.assertTrue(rl.verify_chain(log["entries"])["ok"])

    def test_signed_receipt_names_its_place_in_the_log(self):
        key = Ed25519PrivateKey.from_private_bytes(SEED)
        log = rl.append(rl.empty(), "receipt", rl.item_hash({"n": 0}), ts=1)
        pos = rl.next_position(log)
        signed = rs.sign_receipt({"ok": True, "outcome": "verbatim"}, key, log=pos)
        self.assertEqual(signed["receipt"]["log"], {"seq": 2, "prev": log["head"]})
        pub = rs.public_key_info(key)["public_key_b64"]
        self.assertTrue(rs.verify_receipt(signed, pub))
        log = rl.append(log, "receipt", rl.item_hash(signed), ts=2)
        self.assertEqual(log["entries"][-1][0], signed["receipt"]["log"]["seq"])
        self.assertEqual(log["entries"][-1][3], rl.item_hash(signed))

    def test_bounded_state_keeps_a_checkable_tail(self):
        log = rl.empty()
        full = []
        for i in range(rl.KEEP_RECENT + 15):
            log = rl.append(log, "receipt", rl.item_hash({"n": i}), ts=i)
            full.append(log["entries"][-1])
        self.assertEqual(len(log["entries"]), rl.KEEP_RECENT)
        tail = rl.verify_chain(log["entries"], log["base_head"], log["base_seq"])
        self.assertTrue(tail["ok"])
        self.assertEqual(tail["head"], log["head"])
        self.assertEqual(rl.verify_chain(full)["head"], log["head"])

    def test_public_view_has_only_fingerprints(self):
        log = rl.append(rl.empty(), "receipt", rl.item_hash({"url": "https://x.example/a", "quote": "secret words"}), ts=1)
        view = rl.public_view(log)
        self.assertNotIn("x.example", str(view))
        self.assertNotIn("secret", str(view))


if __name__ == "__main__":
    unittest.main()
