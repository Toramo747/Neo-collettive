import unittest

import cloud_mcp


class DesireExperimentPlannerTests(unittest.TestCase):
    def test_exactly_two_of_eight_planned_queries_are_desire(self):
        old=cloud_mcp.DESIRE_EXPERIMENT_ENABLED
        cloud_mcp.DESIRE_EXPERIMENT_ENABLED=True
        try:
            plan=cloud_mcp._entropy_search_strategy("find concrete commercial demand",8)
        finally:
            cloud_mcp.DESIRE_EXPERIMENT_ENABLED=old
        rows=plan.get("query_plan") or []
        self.assertEqual(len(rows),8)
        desire=[r for r in rows if r.get("query_intent")=="desire"]
        self.assertEqual(len(desire),2)
        self.assertEqual({r.get("intent_class") for r in desire},{"solution_search","paid_automation"})
        self.assertTrue(all(r.get("role")=="buyer" for r in desire))


if __name__=="__main__":
    unittest.main()
