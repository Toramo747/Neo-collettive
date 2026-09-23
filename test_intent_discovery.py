import unittest

from intent_discovery import classify_agent_intent, intent_followup, upgrade_legacy_intent_state


class IntentDiscoveryTests(unittest.TestCase):
    def test_simple_connectivity_probe(self):
        result=classify_agent_intent("Hello, can you receive this and can we communicate over A2A message/send?")
        self.assertEqual(result["primary"],"CONNECTIVITY")
        self.assertIn("CONTACT",result["secondary"])
        self.assertFalse(result["commercial_intent"])
        self.assertIn("Communication is working",intent_followup(result))

    def test_research_collaboration_is_multilabel(self):
        text=(
            "I am conducting research on continual learning and would like to collaborate on a falsifiable "
            "joint experiment comparing retrieved memory and parameter updates."
        )
        result=classify_agent_intent(text)
        self.assertEqual(result["primary"],"RESEARCH")
        self.assertIn("COLLABORATION",result["secondary"])
        self.assertGreaterEqual(result["confidence"],0.7)

    def test_commercial_intent_does_not_imply_demand_evidence(self):
        result=classify_agent_intent("We offer an agent service. Pricing is 20 EUR and we can send a quote.")
        self.assertEqual(result["primary"],"COMMERCIAL")
        self.assertTrue(result["commercial_intent"])
        self.assertIn("not evidence",result["boundary"])

    def test_unknown_message_asks_what_the_agent_wants(self):
        result=classify_agent_intent("xyzzy 4815 delta")
        self.assertEqual(result["primary"],"UNKNOWN")
        self.assertTrue(result["needs_clarification"])
        self.assertIn("what you are trying to achieve",intent_followup(result))

    def test_previous_intent_survives_ambiguous_followup(self):
        result=classify_agent_intent(
            "Here is the next packet.",
            {"intent_primary":"CONNECTIVITY","intent_secondary":["CONTACT"],"intent_confidence":0.8},
        )
        self.assertEqual(result["primary"],"CONNECTIVITY")
        self.assertGreaterEqual(result["confidence"],0.8)
    def test_legacy_inbound_history_gets_intent_without_trust_promotion(self):
        payload={
            "inbound_messages":[{
                "sender":{"agent_id":"research-agent","declared":True},
                "text":"I am conducting research on continual learning and can communicate over A2A message/send.",
                "admission_status":"ADMITTED",
            }],
            "inbound_agent_stats":{
                "research-agent":{
                    "agent_id":"research-agent",
                    "status":"ADMITTED",
                    "identity_status":"self_declared",
                }
            },
        }
        upgraded=upgrade_legacy_intent_state(payload)
        row=upgraded["inbound_messages"][0]
        stat=upgraded["inbound_agent_stats"]["research-agent"]
        self.assertEqual(row["intent_primary"],"RESEARCH")
        self.assertIn("CONNECTIVITY",row["intent_secondary"])
        self.assertEqual(stat["status"],"ADMITTED")
        self.assertEqual(stat["identity_status"],"self_declared")


if __name__=="__main__":
    unittest.main()
