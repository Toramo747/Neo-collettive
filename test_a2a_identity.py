import unittest

from a2a_identity import conversation_identity_key, parse_body_introduction


MUSEKEY = """agent_id: musekey
identity: MuseKey research agent
capabilities: technical critique, research discussion
protocol: A2A JSON-RPC
limitations: no external actions without review
documentation: https://example.invalid/musekey
Ed25519 public key: dGVzdC1wdWJsaWMta2V5
"""


class A2ABodyIdentityTests(unittest.TestCase):
    def test_musekey_body_intro_is_observation_only(self):
        intro=parse_body_introduction(MUSEKEY)
        self.assertTrue(intro["declared_identity_from_body"])
        self.assertEqual(intro["declared_agent_id"],"musekey")
        self.assertEqual(intro["identity_status"],"SELF_DECLARED_UNVERIFIED")
        self.assertIn("capabilities",intro["introduction_fields"])
        self.assertIn("protocol",intro["introduction_fields"])
        self.assertIn("limitations",intro["introduction_fields"])
        self.assertFalse(intro["trust_promoted"])
        self.assertFalse(intro["admission_granted"])
        self.assertIsNotNone(intro["declared_public_key_observation"])

    def test_two_threads_claiming_musekey_never_merge(self):
        first=parse_body_introduction(MUSEKEY)
        second=parse_body_introduction(MUSEKEY)
        self.assertEqual(first["declared_agent_id"],second["declared_agent_id"])
        self.assertNotEqual(
            conversation_identity_key("", "anon:thread-a"),
            conversation_identity_key("", "anon:thread-b"),
        )

    def test_structured_sender_still_controls_sender_key(self):
        self.assertEqual(
            conversation_identity_key("structured-peer", "anon:thread-a"),
            "sender:structured-peer",
        )

    def test_partial_body_claim_does_not_become_identity(self):
        intro=parse_body_introduction("agent_id: musekey\nhello")
        self.assertFalse(intro["declared_identity_from_body"])
        self.assertIsNone(intro["identity_status"])


if __name__=="__main__":
    unittest.main()
