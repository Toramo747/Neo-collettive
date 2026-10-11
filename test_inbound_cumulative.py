# SPDX-License-Identifier: BUSL-1.1
"""Inbound totals must be cumulative: ring-buffer and checkpoint trims must not lose counts."""
import unittest
from datetime import datetime, timedelta, timezone

import arena_research_algorithm as ara
from inbound_traffic import account_evicted, append_event_tracked, empty_evicted, summarize_events
from state_compaction import trim_inbound_traffic_events

NOW = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)


def ev(i, cat="crawler_probe"):
    return {"timestamp_utc": (NOW - timedelta(minutes=i)).isoformat(), "endpoint": "/mcp", "method": "POST",
            "category": cat, "reason": "test", "ip_or_origin": f"origin-{i}", "user_agent": "t"}


class InboundCumulativeTests(unittest.TestCase):
    def test_ring_buffer_trim_is_counted(self):
        rows, evicted = [], empty_evicted(NOW)
        for i in range(25):
            rows, evicted = append_event_tracked(rows, ev(100 - i, "real_contact" if i < 3 else "crawler_probe"),
                                                 evicted, max_events=10)
        self.assertEqual(len(rows), 10)
        self.assertEqual(evicted["events"], 15)
        s = summarize_events(rows, now=NOW, evicted=evicted)
        self.assertEqual(s["events_total"], 25)
        self.assertEqual(s["events_in_buffer"], 10)
        self.assertEqual(s["counts"]["total"]["real_contact"], 3)
        self.assertEqual(s["counts"]["total"]["crawler_probe"], 22)
        self.assertEqual(s["cumulative_counting"], "buffer_plus_evicted")
        self.assertIsNotNone(s["first_real_contact_utc"])     # first contacts survive although evicted
        self.assertEqual(sum(s["counts"]["last_24h"].values()), 10)  # windows still come from the buffer

    def test_checkpoint_trim_moves_counts_to_evicted(self):
        payload = {"inbound_traffic_events": [ev(i) for i in range(40)], "inbound_traffic_summary": {"x": 1}}
        out = trim_inbound_traffic_events(payload, limit=15)
        self.assertEqual(len(out["inbound_traffic_events"]), 15)
        self.assertEqual(out["inbound_traffic_evicted"]["events"], 25)
        self.assertEqual(out["inbound_traffic_summary"], {"x": 1})   # summary untouched
        again = trim_inbound_traffic_events(out, limit=10)
        self.assertEqual(again["inbound_traffic_evicted"]["events"], 30)
        s = summarize_events(again["inbound_traffic_events"], now=NOW, evicted=again["inbound_traffic_evicted"])
        self.assertEqual(s["events_total"], 40)

    def test_without_evicted_is_marked_buffer_only(self):
        s = summarize_events([ev(1)], now=NOW)
        self.assertEqual(s["cumulative_counting"], "buffer_only")
        self.assertEqual(account_evicted(None, [])["events"], 0)


class InboundRestartTests(unittest.TestCase):
    def test_counts_survive_checkpoint_trim_and_restart(self):
        from copy import deepcopy
        import cloud_mcp
        previous = deepcopy(cloud_mcp.AUTOPILOT_STATE)
        try:
            events = [ev(i) for i in range(400)]
            cloud_mcp.AUTOPILOT_STATE["inbound_traffic_events"] = events
            cloud_mcp.AUTOPILOT_STATE["inbound_traffic_evicted"] = empty_evicted(NOW)
            payload = trim_inbound_traffic_events(cloud_mcp._state_payload(), limit=300)
            self.assertEqual(payload["inbound_traffic_evicted"]["events"], 100)
            cloud_mcp.AUTOPILOT_STATE.clear()
            self.assertTrue(cloud_mcp._merge_state_payload(payload))
            s = cloud_mcp.AUTOPILOT_STATE["inbound_traffic_summary"]
            # Restored buffer may gain events reconciled from stored inbound messages;
            # what matters is that the 100 trimmed events are still counted.
            self.assertEqual(s["events_total"] - s["events_in_buffer"], 100)
            self.assertGreaterEqual(s["events_in_buffer"], 300)
        finally:
            cloud_mcp.AUTOPILOT_STATE.clear()
            cloud_mcp.AUTOPILOT_STATE.update(previous)


class TeacherSummaryReferenceTests(unittest.TestCase):
    def test_teacher_mode_compares_against_lexicon_order(self):
        a = {"genome_id": "a", "metrics": {"signal_hits": 3, "unique_signal_threads": 2, "fitness": 10,
                                            "shadow_teacher": {"teacher_hits": 0}}}
        b = {"genome_id": "b", "metrics": {"signal_hits": 1, "unique_signal_threads": 1, "fitness": 5,
                                            "shadow_teacher": {"teacher_hits": 9}}}
        teacher_order = sorted([a, b], key=ara.teacher_ranking_key, reverse=True)
        trivial = ara.shadow_teacher_summary(teacher_order)
        self.assertEqual(trivial["rank_correlation"], 1.0)          # the old, degenerate comparison
        fixed = ara.shadow_teacher_summary(sorted(teacher_order, key=ara.ranking_key, reverse=True),
                                           reference="lexicon_ranking")
        self.assertEqual(fixed["rank_correlation"], -1.0)
        self.assertEqual(fixed["reference"], "lexicon_ranking")


if __name__ == "__main__":
    unittest.main()
