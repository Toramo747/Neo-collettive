"""Synthetic keys and results only; never reads deployment credentials."""
import asyncio
import base64
from copy import deepcopy
from datetime import datetime
import json
import os
import unittest
from unittest.mock import AsyncMock, patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import receipt_signing as rs

# Publicly known RFC 8032 test-vector seed, never a production key.
TEST_SEED = "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60"


class ReceiptSigningTests(unittest.TestCase):
    def setUp(self):
        self.key = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(TEST_SEED))
        self.pub = rs.public_key_info(self.key)["public_key_b64"]
        self.result = {"ok": True, "outcome": "not_found", "quote": "È una frase verificabile", "details": {"count": 0}}

    def test_load_key_missing_invalid_and_fixed(self):
        for value in (None, "", "0" * 63, "g" * 64, "00 " * 32, "0" * 65):
            with self.subTest(value=value), patch.dict(os.environ, {}, clear=True):
                if value is not None:
                    os.environ["NEO_RECEIPT_SIGNING_KEY"] = value
                self.assertIsNone(rs.load_key())
        with patch.dict(os.environ, {"NEO_RECEIPT_SIGNING_KEY": TEST_SEED}):
            self.assertEqual(rs.public_key_info(rs.load_key()), rs.public_key_info(self.key))

    def test_signature_verifies_independently_and_preserves_input(self):
        original = deepcopy(self.result)
        obj = rs.sign_receipt(self.result, self.key)
        self.assertEqual(self.result, original)
        self.assertTrue(rs.verify_receipt(obj, self.pub))
        payload = dict(obj)
        signature = base64.urlsafe_b64decode(payload.pop("signature") + "==")
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        self.key.public_key().verify(signature, raw)
        self.assertNotIn("=", obj["signature"])
        self.assertEqual(obj["receipt"]["tool"], "verify_quote")
        self.assertEqual(obj["receipt"]["issuer"], "neo (OSIXBAY)")
        self.assertEqual(datetime.fromisoformat(obj["receipt"]["issued_at_utc"]).utcoffset().total_seconds(), 0)

    def test_every_field_is_covered_including_receipt_and_nested_fields(self):
        obj = rs.sign_receipt(self.result, self.key)
        paths = [(k,) for k in obj] + [("receipt", k) for k in obj["receipt"]] + [("details", "count")]
        for path in paths:
            changed = deepcopy(obj)
            parent = changed
            for k in path[:-1]:
                parent = parent[k]
            parent[path[-1]] = "verbatim"
            with self.subTest(path=path):
                self.assertFalse(rs.verify_receipt(changed, self.pub))
        self.assertTrue(rs.verify_receipt(dict(reversed(list(obj.items()))), self.pub))
        changed = deepcopy(obj)
        changed["extra"] = True
        self.assertFalse(rs.verify_receipt(changed, self.pub))
        del changed["extra"]
        del changed["quote"]
        self.assertFalse(rs.verify_receipt(changed, self.pub))

    def test_malformed_receipts_and_wrong_keys_fail_closed(self):
        obj = rs.sign_receipt(self.result, self.key)
        for malformed in ({}, None, {**obj, "signature": "!"}, {**obj, "signature": 1}):
            self.assertFalse(rs.verify_receipt(malformed, self.pub))
        for pub in ("!", "", base64.b64encode(b"short").decode(), rs.public_key_info(Ed25519PrivateKey.from_private_bytes(bytes(32)))["public_key_b64"]):
            self.assertFalse(rs.verify_receipt(obj, pub))


class ReceiptIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_tool_outcomes_and_timeout_are_signed_with_card_key(self):
        import cloud_mcp as cm
        key = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(TEST_SEED))
        with patch.object(cm, "RECEIPT_SIGNING_KEY", key):
            card = cm._neo_agent_card()["receipt_signing"]
            self.assertEqual(card, rs.public_key_info(key))
            for outcome in ("verbatim", "paraphrase", "not_found", "unreachable"):
                result = {"ok": True, "outcome": outcome}
                with patch.object(cm.quote_verifier, "verify_quote", new=AsyncMock(return_value=result)):
                    obj = await cm.verify_quote(None, "https://example.com", "some exact sentence here")
                self.assertTrue(rs.verify_receipt(obj, card["public_key_b64"]))
                self.assertEqual(obj["receipt"]["key_id"], card["key_id"])
            # Real validation path: no network involved.
            obj = await cm.verify_quote(None, "https://example.com", "hi")
            self.assertEqual(obj["error"], "quote_too_short")
            self.assertTrue(rs.verify_receipt(obj, card["public_key_b64"]))
            with patch.object(cm.quote_verifier, "verify_quote", new=AsyncMock(side_effect=asyncio.TimeoutError)):
                obj = await cm.verify_quote(None)
            self.assertEqual(obj["error"], "verification_deadline_exceeded")
            self.assertTrue(rs.verify_receipt(obj, card["public_key_b64"]))

    async def test_no_key_still_returns_result_and_null_card(self):
        import cloud_mcp as cm
        with patch.object(cm, "RECEIPT_SIGNING_KEY", None):
            self.assertIsNone(cm._neo_agent_card()["receipt_signing"])
            obj = await cm.verify_quote(None, "https://example.com", "hi")
            self.assertEqual(obj["error"], "quote_too_short")
            self.assertIs(obj["signed"], False)
            self.assertNotIn("signature", obj)
            self.assertNotIn("receipt", obj)


class CanonicalSignatureTest(unittest.TestCase):
    def test_spare_bit_variants_are_refused(self):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        import base64 as b64
        from cryptography.hazmat.primitives import serialization
        k = Ed25519PrivateKey.generate()
        pub = b64.b64encode(k.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()
        signed = rs.sign_receipt({"ok": True, "outcome": "verbatim"}, k)
        self.assertTrue(rs.verify_receipt(signed, pub))
        last = signed["signature"][-1]
        alph = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
        sib = alph[(alph.index(last) // 16) * 16 + ((alph.index(last) % 16) + 1) % 16]
        self.assertFalse(rs.verify_receipt(dict(signed, signature=signed["signature"][:-1] + sib), pub))
