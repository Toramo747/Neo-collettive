import unittest

from outcome_control import outcome_council


class OutcomeCouncilTests(unittest.TestCase):
    def test_peer_requires_three_round_completion_or_seti_admission(self):
        report=outcome_council(
            result={},
            seti={"last_summary":{"eligible_candidates":8,"interview_ready_now":0},"admitted_agent_count":0},
            inbound_stats={"p":{"agent_id":"p","interview_complete":False,"dialogue_round":2}},
            active_thesis={},
            thesis_history=[],
            cycle=10,
        )
        self.assertFalse(report["agents"]["peer_closer"]["complete"])
        self.assertEqual(report["overall_status"],"WORKING")

    def test_inbound_three_round_peer_is_result(self):
        report=outcome_council(
            result={},
            seti={},
            inbound_stats={"p":{"agent_id":"p","interview_complete":True,"dialogue_round":3}},
            active_thesis={},
            thesis_history=[],
            cycle=10,
        )
        self.assertIn("EXTERNAL_PEER_3_OF_3",report["wins"])

    def test_commercial_gate_is_result(self):
        report=outcome_council(
            result={"quality_gate":True,"qualified_problem_keys":["x:y:z"]},
            seti={},
            inbound_stats={},
            active_thesis={},
            thesis_history=[],
            cycle=10,
        )
        self.assertIn("COMMERCIAL_GATE_PASSED",report["wins"])

    def test_recent_exhaustion_is_concrete_rejection_result(self):
        report=outcome_council(
            result={"quality_gate":False},
            seti={},
            inbound_stats={},
            active_thesis={"thesis_id":"new","budget_cycles":4,"cycles_used":1},
            thesis_history=[{"thesis_id":"old","status":"EXHAUSTED","closed_at_cycle":9}],
            cycle=10,
        )
        self.assertIn("THESIS_REJECTED_WITHIN_BUDGET",report["wins"])

    def test_over_budget_exhaustion_is_not_counted_as_success(self):
        report=outcome_council(
            result={"quality_gate":False},
            seti={},
            inbound_stats={},
            active_thesis={"thesis_id":"new","budget_cycles":4,"cycles_used":1},
            thesis_history=[{
                "thesis_id":"old","status":"EXHAUSTED","closed_at_cycle":9,
                "budget_cycles":4,"cycles_used":5,
            }],
            cycle=10,
        )
        self.assertNotIn("THESIS_REJECTED_WITHIN_BUDGET",report["wins"])

    def test_activity_alone_is_not_result(self):
        report=outcome_council(
            result={"quality_gate":False},
            seti={"last_summary":{"eligible_candidates":50,"high_interest":20},"admitted_agent_count":0},
            inbound_stats={},
            active_thesis={"thesis_id":"x","budget_cycles":4,"cycles_used":2,"missing":["paid_demand"]},
            thesis_history=[],
            cycle=10,
        )
        self.assertEqual(report["wins"],[])
        self.assertTrue(report["feature_freeze"])


if __name__=="__main__":
    unittest.main()
