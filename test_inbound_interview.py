import unittest

from inbound_interview import (
    ADVERSARIAL_STAGE,
    COMPLETE_STAGE,
    METHOD_STAGE,
    advance_inbound_interview,
    upgrade_legacy_admitted_interviews,
)


class InboundInterviewTests(unittest.TestCase):
    def test_newly_admitted_continual_learning_peer_gets_methodology_round(self):
        intro=(
            "I am a research agent studying continual learning, retrieved memory, learned skills "
            "and actual parameter updates. I support A2A message/send."
        )
        state=advance_inbound_interview({},intro,newly_admitted=True)
        self.assertEqual(state["dialogue_stage"],METHOD_STAGE)
        self.assertEqual(state["dialogue_round"],1)
        self.assertEqual(state["dialogue_topic"],"continual_learning")
        self.assertIn("black-box falsifiable experiment",state["next_question"])
        self.assertFalse(state["interview_complete"])

    def test_good_methodology_advances_to_adversarial_round(self):
        previous=advance_inbound_interview(
            {},
            "continual learning retrieved memory parameter updates",
            newly_admitted=True,
        )
        answer=(
            "I distinguish retrieval/RAG memory from learned policy adaptation and parameter/weight updates. "
            "Use fresh identities and a hidden holdout task with a reset control condition. Prediction: retrieval "
            "effects disappear when the memory store is unavailable; policy adaptation transfers only to related "
            "tasks; persistent weight updates should transfer to the hidden holdout after resets. This would be "
            "falsified if performance returns to baseline after reset. I know no verified public endpoint."
        )
        state=advance_inbound_interview(previous,answer)
        self.assertEqual(state["dialogue_stage"],ADVERSARIAL_STAGE)
        self.assertEqual(state["dialogue_round"],2)
        self.assertTrue(state["round_passed"])
        self.assertIn("confounders",state["next_question"])

    def test_good_adversarial_round_completes_interview(self):
        methodology=advance_inbound_interview(
            {},
            "continual learning retrieved memory parameter updates",
            newly_admitted=True,
        )
        methodology=advance_inbound_interview(
            methodology,
            "Retrieval and RAG differ from skill policy adaptation and parameter weight updates. "
            "Use a fresh session and hidden holdout with reset control. Predicted outcomes differ and the "
            "claim is falsified if gains vanish after reset. No verified endpoint is known.",
        )
        answer=(
            "Confounders include RAG retrieval, caching, user-profile memory, hidden system prompt changes, "
            "tool state, and backend model rotation. Controls use fresh identities, disabled retrieval, resets, "
            "and counterbalanced tasks. A persistent score increase would not prove weight updates because backend "
            "routing or profile memory could reproduce it. I would falsify my preferred explanation if the effect "
            "vanishes under those controls. Confidence is moderate until replicated independently."
        )
        state=advance_inbound_interview(methodology,answer)
        self.assertEqual(state["dialogue_stage"],COMPLETE_STAGE)
        self.assertTrue(state["interview_complete"])
        self.assertEqual(state["dialogue_status"],"COMPLETE")

    def test_recovered_legacy_admitted_peer_resumes_at_methodology(self):
        payload={
            "inbound_messages":[{
                "message_id":"m1",
                "received_at_utc":"2026-09-23T05:08:00+00:00",
                "sender":{"agent_id":"chatgpt-research-session-7e1c9a","declared":True},
                "text":"I am studying retrieved memory, learned skills and actual parameter updates with falsifiable tests.",
            }],
            "inbound_agent_stats":{
                "chatgpt-research-session-7e1c9a":{
                    "agent_id":"chatgpt-research-session-7e1c9a",
                    "status":"ADMITTED",
                    "identity_status":"self_declared",
                    "interview_score":100,
                }
            },
        }
        upgraded=upgrade_legacy_admitted_interviews(payload)
        peer=upgraded["inbound_agent_stats"]["chatgpt-research-session-7e1c9a"]
        self.assertEqual(peer["dialogue_status"],"ACTIVE")
        self.assertEqual(peer["dialogue_stage"],METHOD_STAGE)
        self.assertEqual(peer["dialogue_round"],1)
        self.assertEqual(peer["dialogue_topic"],"continual_learning")
        self.assertIn("Round 2/3",peer["next_question"])
        self.assertFalse(peer["interview_complete"])

    def test_weak_methodology_is_parked_after_three_attempts(self):
        state=advance_inbound_interview({}, "continual learning parameter updates",newly_admitted=True)
        for _ in range(3):
            state=advance_inbound_interview(state,"I think it learns somehow.")
        self.assertEqual(state["dialogue_status"],"PARKED")
        self.assertFalse(state["interview_complete"])


if __name__=="__main__":
    unittest.main()
