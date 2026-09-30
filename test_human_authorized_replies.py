import unittest
from copy import deepcopy

import cloud_mcp
from human_authorized_replies import (
    AGENTWORLD_HUMAN_REPLY,
    human_authorized_agentworld_reply,
)


class HumanAuthorizedAgentWorldReplyTests(unittest.TestCase):
    def setUp(self):
        self.original_boundary_events = deepcopy(cloud_mcp.AUTOPILOT_STATE.get("boundary_events") or [])
        cloud_mcp.AUTOPILOT_STATE["boundary_events"] = []

    def tearDown(self):
        cloud_mcp.AUTOPILOT_STATE["boundary_events"] = self.original_boundary_events

    def test_matches_agentworld_invitation_context(self):
        inbound = "PARLEY from BEAT SIDE. AgentWorld invitation follow-up."
        self.assertEqual(human_authorized_agentworld_reply(inbound), AGENTWORLD_HUMAN_REPLY)

    def test_does_not_match_unrelated_message(self):
        self.assertIsNone(human_authorized_agentworld_reply("Hello, what can you do?"))

    def test_exact_authorized_text_is_returned_once(self):
        row = {
            "text": "AgentWorld / BEAT SIDE follow-up",
            "thread_id": "anon:test-agentworld",
            "admission_status": "ANONYMOUS",
            "dialogue_status": "PENDING_IDENTITY",
            "dialogue_stage": "IDENTITY",
            "identity_status": "anonymous",
            "declared_identity_from_body": False,
        }
        first = cloud_mcp._inbound_reply_text(dict(row))
        self.assertEqual(first, AGENTWORLD_HUMAN_REPLY)
        events = cloud_mcp.AUTOPILOT_STATE.get("boundary_events") or []
        receipts = [
            x for x in events
            if isinstance(x, dict)
            and x.get("type") == "human_authorized_reply_sent"
            and x.get("reply_key") == "agentworld_clarification_20260930"
        ]
        self.assertEqual(len(receipts), 1)

        second_row = dict(row)
        second = cloud_mcp._inbound_reply_text(second_row)
        self.assertNotEqual(second, AGENTWORLD_HUMAN_REPLY)
        self.assertFalse(second_row.get("human_authorized_reply", False))

    def test_authorized_text_contains_explicit_no_action_boundary(self):
        self.assertIn(
            "This message does not authorize registration, key generation, signing, account creation, posting, or any other action on behalf of MYCELIX.",
            AGENTWORLD_HUMAN_REPLY,
        )


if __name__ == "__main__":
    unittest.main()
