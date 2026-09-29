import base64
import unittest
from datetime import datetime, timedelta, timezone

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from a2a_handshake import challenge_message, create_handshake_challenge, verify_handshake_response


class A2AHandshakeTests(unittest.TestCase):
    def setUp(self):
        self.private=Ed25519PrivateKey.generate()
        self.public=self.private.public_key().public_bytes(
            encoding=serialization.Encoding.OpenSSH,
            format=serialization.PublicFormat.OpenSSH,
        ).decode("ascii")
        self.now=datetime(2026,9,29,12,0,tzinfo=timezone.utc)
        self.store,self.challenge=create_handshake_challenge(
            {},thread_id="thread-1",public_key=self.public,now=self.now,nonce="nonce-123",
        )

    def _sig(self,message: str) -> str:
        return base64.b64encode(self.private.sign(message.encode("utf-8"))).decode("ascii")

    def test_valid_signature_verifies_key_possession_only(self):
        sig=self._sig(challenge_message("thread-1","nonce-123"))
        store,result=verify_handshake_response(
            self.store,thread_id="thread-1",nonce="nonce-123",signature_b64=sig,now=self.now,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"],"KEY_POSSESSION_VERIFIED")
        self.assertFalse(result["admission_changed"])
        self.assertFalse(result["authorization_changed"])
        self.assertTrue(store["thread-1"]["used"])

    def test_signature_for_different_nonce_is_rejected(self):
        sig=self._sig(challenge_message("thread-1","other-nonce"))
        _,result=verify_handshake_response(
            self.store,thread_id="thread-1",nonce="nonce-123",signature_b64=sig,now=self.now,
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"],"invalid_signature_or_domain")

    def test_expired_nonce_is_rejected(self):
        sig=self._sig(challenge_message("thread-1","nonce-123"))
        _,result=verify_handshake_response(
            self.store,thread_id="thread-1",nonce="nonce-123",signature_b64=sig,
            now=self.now+timedelta(seconds=301),
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"],"nonce_expired")

    def test_reused_nonce_is_rejected(self):
        sig=self._sig(challenge_message("thread-1","nonce-123"))
        used,first=verify_handshake_response(
            self.store,thread_id="thread-1",nonce="nonce-123",signature_b64=sig,now=self.now,
        )
        self.assertTrue(first["ok"])
        _,second=verify_handshake_response(
            used,thread_id="thread-1",nonce="nonce-123",signature_b64=sig,now=self.now,
        )
        self.assertFalse(second["ok"])
        self.assertEqual(second["reason"],"nonce_reused")

    def test_signature_without_domain_prefix_is_rejected(self):
        sig=self._sig("nonce-123")
        _,result=verify_handshake_response(
            self.store,thread_id="thread-1",nonce="nonce-123",signature_b64=sig,now=self.now,
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"],"invalid_signature_or_domain")

    def test_malformed_key_is_rejected_before_challenge(self):
        with self.assertRaisesRegex(ValueError,"malformed_public_key"):
            create_handshake_challenge({},thread_id="t",public_key="ssh-ed25519 not-base64",now=self.now)


if __name__=="__main__":
    unittest.main()
