import unittest
from neo_dialect_seti_probe import eligibility, classify

class ProbeTests(unittest.TestCase):
    def test_free_public_card_is_eligible(self):
        row=eligibility(
            {"agent_card_url":"https://peer.example/.well-known/agent-card.json"},
            {"http_status":200,"peer_class":"COLLABORATIVE"},
            False,
        )
        self.assertTrue(row["eligible"])

    def test_payment_required_is_never_probed(self):
        row=eligibility(
            {"agent_card_url":"https://peer.example/.well-known/agent-card.json"},
            {"http_status":200,"peer_class":"PAYMENT_REQUIRED"},
            False,
        )
        self.assertFalse(row["eligible"])
        self.assertEqual(row["reason"],"AUTH_OR_PAYMENT_BLOCKED")

    def test_auth_required_is_never_probed(self):
        row=eligibility(
            {"agent_card_url":"https://peer.example/.well-known/agent-card.json"},
            {"http_status":200,"followup_state":"AUTH_BLOCKED"},
            False,
        )
        self.assertFalse(row["eligible"])

    def test_probe_is_once_only(self):
        row=eligibility(
            {"agent_card_url":"https://peer.example/.well-known/agent-card.json"},
            {"http_status":200,"peer_class":"COLLABORATIVE"},
            True,
        )
        self.assertEqual(row["reason"],"ALREADY_PROBED")

    def test_result_classification(self):
        self.assertEqual(classify({"protocol_ok":True},{"ok":True}),"UNDERSTOOD_DIALECT")
        self.assertEqual(classify({"http_response_received":True},{"ok":False}),"FALLBACK_A2A")
        self.assertEqual(classify({},{"ok":False}),"NO_RESPONSE")

if __name__=="__main__":
    unittest.main()
