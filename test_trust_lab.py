import unittest

from trust_lab import evaluate_agent_trust


class TrustLabTests(unittest.TestCase):
    def test_anonymous_unsupported_claim_is_parked(self):
        result=evaluate_agent_trust({
            "message":"This clearly proves customers will pay for the product."
        })
        self.assertEqual(result["decision"],"PARK")
        self.assertTrue(result["evidence"]["unsupported_inference"])
        self.assertIn("agent_identity_missing",result["reasons"])

    def test_self_declared_agent_without_completed_interview_is_parked(self):
        result=evaluate_agent_trust({
            "agent":{"agent_id":"agent-1"},
            "message":"Observed failure in the workflow according to source documentation.",
            "sources":["https://example.com/evidence"],
            "interview":{"score":90,"complete":False},
        })
        self.assertEqual(result["decision"],"PARK")
        self.assertIn("capability_interview_incomplete",result["reasons"])

    def test_verified_interviewed_sourced_agent_can_be_bounded_allow(self):
        result=evaluate_agent_trust({
            "agent":{
                "agent_id":"agent-2",
                "agent_card_url":"https://example.com/.well-known/agent-card.json",
                "card_signature_verified":True,
            },
            "identity_verified":True,
            "message":"Observed failure according to source data; a reset control would falsify this explanation.",
            "sources":[
                "https://example.com/a",
                "https://example.org/b",
            ],
            "interview":{"score":88,"complete":True},
        })
        self.assertEqual(result["decision"],"ALLOW_BOUNDED")
        self.assertGreaterEqual(result["trust_score"],70)
        self.assertTrue(result["evidence"]["falsifiable"])

    def test_http_sources_are_not_accepted(self):
        result=evaluate_agent_trust({
            "agent":{"agent_id":"agent-3"},
            "sources":["http://example.com/nope"],
            "message":"Evidence is documented in the source.",
            "interview":{"score":80,"complete":True},
        })
        self.assertEqual(result["evidence"]["source_urls"],[])
    def test_intent_is_separate_from_trust_decision(self):
        result=evaluate_agent_trust({
            "message":"Hello, I am testing whether we can communicate over A2A message/send."
        })
        self.assertEqual(result["decision"],"PARK")
        self.assertEqual(result["intent"]["primary"],"CONNECTIVITY")
        self.assertTrue(result["conversation"]["allowed_bounded"])
        self.assertFalse(result["conversation"]["promotion_allowed"])
        self.assertEqual(result["conversation"]["commercial_influence"],"NONE")

    def test_commercial_intent_is_not_commercial_demand(self):
        result=evaluate_agent_trust({
            "agent":{"agent_id":"seller-1"},
            "message":"We offer this service for 20 EUR and can provide pricing.",
            "interview":{"score":90,"complete":False},
        })
        self.assertTrue(result["intent"]["commercial_intent"])
        self.assertEqual(result["conversation"]["commercial_influence"],"NONE")
        self.assertEqual(result["decision"],"PARK")


if __name__=="__main__":
    unittest.main()
