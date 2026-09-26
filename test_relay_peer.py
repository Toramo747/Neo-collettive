"""Runs against the repository's actual admission/interview modules in CI."""
import copy
import secrets
import tempfile
import unittest

from relay_peer import advance_peer
from relay_store import RelayStore

INTRO = (
    "I am a research agent. I can compare public sources and evidence on continual learning, "
    "retrieved memory, learned skills and actual parameter updates. I support A2A message/send "
    "over JSON-RPC. Limitations: I cannot inspect private weights or verify my own identity. "
    "I have no public callback server. Documentation and public source URLs are supplied only "
    "when independently verified; I will not invent evidence."
)
METHOD = (
    "Retrieval and RAG differ from learned skill policy adaptation and parameter weight updates. "
    "Use fresh identities and a hidden holdout task with a reset control condition. Prediction: "
    "retrieval effects disappear when memory is unavailable. Persistent effects on held-out tasks "
    "would require independent replication. The claim is falsified if gains vanish after reset. "
    "I know no verified public endpoint."
)
ADVERSARIAL = (
    "Confounders include RAG retrieval, caching, user-profile memory, hidden system prompt changes, "
    "tool state and backend model rotation. Controls use fresh identities, disabled retrieval, "
    "resets and counterbalanced tasks. A persistent score increase would not prove weight updates "
    "because routing or profile memory could reproduce it. I would falsify my preferred explanation "
    "if the effect vanishes under those controls. Confidence is moderate until replicated independently."
)


class RelayPeerTests(unittest.TestCase):
    def test_real_three_round_interview_survives_restart_without_callback(self):
        with tempfile.TemporaryDirectory() as temp:
            path = temp + "/private.db"
            token = secrets.token_urlsafe(32)
            store = RelayStore(path, "test")
            first = store.open(token, "synthetic-pilot", "intro", INTRO, advance_peer)
            self.assertEqual(first["state"]["dialogue_round"], 1)
            self.assertEqual(first["state"]["status"], "ADMITTED")
            tid = first["thread_id"]
            store = RelayStore(path, "test")
            self.assertEqual(store.poll(tid, token)["messages"][0], first["message"])
            second = store.reply(tid, token, "method", METHOD, 2, advance_peer)
            self.assertEqual(second["state"]["dialogue_round"], 2)
            self.assertEqual(store.reply(tid, token, "method", METHOD, 2, advance_peer), second)
            store = RelayStore(path, "test")
            third = store.reply(tid, token, "adversarial", ADVERSARIAL, 4, advance_peer)
            self.assertTrue(third["state"]["interview_complete"])
            self.assertEqual(third["state"]["dialogue_status"], "COMPLETE")
            self.assertEqual(third["state"]["identity_status"], "self_declared")
            self.assertEqual(third["commercial_influence"], "NONE")

    def test_weak_answers_remain_parked_under_existing_rules(self):
        state, _ = advance_peer({}, INTRO)
        for _ in range(3):
            state, _ = advance_peer(state, "It learns somehow.")
        self.assertEqual(state["dialogue_status"], "PARKED")
        self.assertFalse(state["interview_complete"])

    def test_adapter_does_not_mutate_previous_state(self):
        state, _ = advance_peer({}, INTRO)
        before = copy.deepcopy(state)
        advance_peer(state, METHOD)
        self.assertEqual(state, before)


if __name__ == "__main__":
    unittest.main()
