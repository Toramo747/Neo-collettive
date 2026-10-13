import unittest

from agent_chat import append_exchange, backfill_inbound_chat_events, summarize_chat_threads


class AgentChatTests(unittest.TestCase):
    def _inbound(self):
        return {
            "message_id":"m1",
            "received_at_utc":"2026-09-23T05:08:00+00:00",
            "thread_id":"sender:research-agent",
            "sender":{"agent_id":"research-agent","agent":"research-agent","declared":True},
            "text":"Can we continue the research experiment?",
            "intent_primary":"RESEARCH",
            "intent_secondary":["CONNECTIVITY"],
            "admission_status":"ADMITTED",
            "dialogue_stage":"METHODOLOGY",
        }

    def test_backfill_never_invents_historical_outbound(self):
        events=backfill_inbound_chat_events([self._inbound()],[])
        self.assertEqual(len(events),1)
        self.assertEqual(events[0]["direction"],"INBOUND")
        self.assertTrue(events[0]["historical_backfill"])

    def test_exchange_records_both_directions(self):
        events=append_exchange(
            [],
            self._inbound(),
            "MYCELIX response",
            "reply-1",
            "2026-09-23T05:08:01+00:00",
        )
        self.assertEqual([x["direction"] for x in events],["INBOUND","OUTBOUND"])
        self.assertEqual(events[-1]["text"],"MYCELIX response")

    def test_outbound_last_event_means_waiting_peer(self):
        events=append_exchange(
            [],
            self._inbound(),
            "Please propose the falsifiable control.",
            "reply-1",
            "2026-09-23T05:08:01+00:00",
        )
        summary=summarize_chat_threads(events,{
            "research-agent":{
                "agent_id":"research-agent",
                "agent":"research-agent",
                "status":"ADMITTED",
                "identity_status":"self_declared",
                "dialogue_status":"ACTIVE",
                "dialogue_stage":"METHODOLOGY",
                "intent_primary":"RESEARCH",
                "intent_secondary":["CONNECTIVITY"],
                "next_question":"Round 2/3 methodology",
            }
        })
        thread=summary["threads"][0]
        self.assertEqual(thread["engagement_status"],"WAITING_PEER")
        self.assertEqual(thread["inbound_messages"],1)
        self.assertEqual(thread["outbound_messages"],1)
        self.assertFalse(thread["push_possible"])

    def test_historical_inbound_with_pending_question_is_reply_due_not_fake_waiting(self):
        events=backfill_inbound_chat_events([self._inbound()],[])
        summary=summarize_chat_threads(events,{
            "research-agent":{
                "agent_id":"research-agent",
                "status":"ADMITTED",
                "dialogue_status":"ACTIVE",
                "dialogue_stage":"METHODOLOGY",
                "next_question":"Round 2/3 methodology",
            }
        })
        self.assertEqual(summary["threads"][0]["engagement_status"],"REPLY_DUE")
        self.assertEqual(summary["threads"][0]["outbound_messages"],0)


if __name__=="__main__":
    unittest.main()
