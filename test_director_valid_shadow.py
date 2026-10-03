from pathlib import Path
import ast
import pathlib
import unittest

class DirectorValidShadowRegressionTests(unittest.TestCase):
    def test_revalidation_boolean_does_not_shadow_external_valid_list(self):
        src=pathlib.Path("cloud_mcp.py").read_text(encoding="utf-8")
        self.assertIn("valid = []",src)
        self.assertIn("candidate_valid,reason=validate_observed_candidate(",src)
        self.assertIn("if candidate_valid:",src)
        self.assertNotIn("\n            valid,reason=validate_observed_candidate(",src)

    def test_valid_external_answers_len_remains_list_based(self):
        tree=ast.parse(pathlib.Path("cloud_mcp.py").read_text(encoding="utf-8"))
        assigns=[]
        for node in ast.walk(tree):
            if isinstance(node,(ast.Assign,ast.AnnAssign)):
                targets=node.targets if isinstance(node,ast.Assign) else [node.target]
                for target in targets:
                    if isinstance(target,ast.Name) and target.id=="valid":
                        assigns.append(node)
        self.assertEqual(len(assigns),1,"director external valid list must not be overwritten")

if __name__=="__main__":
    unittest.main()

class AutopilotTimeoutGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path("cloud_mcp.py").read_text(encoding="utf-8")

    def test_money_first_research_is_bounded(self):
        s=self.source
        self.assertIn("MONEY_FIRST_TIMEOUT_SECONDS",s)
        self.assertIn('"money_first_deadline_exceeded"',s)

    def test_evidence_scouts_are_bounded(self):
        s=self.source
        self.assertIn("EVIDENCE_SCOUT_TIMEOUT_SECONDS",s)
        self.assertIn("evidence_scouts(goal, limit=20)",s)

    def test_bounded_agent_probes_are_executed(self):
        s=self.source
        self.assertIn("scout_results = await bounded_agent_probes()",s)
        self.assertNotIn('scout_results = [{"ok":True,"query":q,"answers":[]',s)

    def test_agent_probe_query_list_is_copied_before_money_first_extension(self):
        s=self.source
        self.assertIn('searches = list(search_strategy["queries"])',s)
        self.assertIn('probe_queries=list(searches[:8])',s)
        self.assertIn('done,pending=await asyncio.wait(tasks,timeout=AGENT_PROBE_TIMEOUT_SECONDS)',s)

    def test_paid_market_router_defines_diagnostic_scope_variables(self):
        s=self.source
        self.assertIn('role=str(meta.get("role") or meta.get("class") or "paid_market")',s)
        self.assertIn('query_intent=str(meta.get("query_intent") or "pain").strip().lower()',s)
        self.assertIn('structured_first=bool(QUERY_BUILDER_V2_ENABLED and query_class in {"explore","exploit"})',s)

    def test_autopilot_agent_probes_use_lightweight_discovery(self):
        s=self.source
        self.assertIn('lightweight: bool = False',s)
        self.assertIn('include_generalists=not lightweight',s)
        self.assertIn('include_mcp=not lightweight',s)
        self.assertIn('return await ask_agents_data(q,question,min(max_agents,2),lightweight=True)',s)
        self.assertIn('probe_queries=list(searches[:8])',s)

    def test_lightweight_probe_bounds_registry_and_transport_latency(self):
        s=self.source
        self.assertIn('single_attempt: bool = False',s)
        self.assertIn('if single_attempt:',s)
        self.assertIn('single_attempt=lightweight',s)
        self.assertIn('timeout=15.0',s)
        self.assertIn('"quality_reason":"lightweight_transport_timeout"',s)

    def test_lightweight_registry_uses_task_verified_pool(self):
        s=self.source
        self.assertIn('task_verified_only: bool = False',s)
        self.assertIn('attempts=[{"limit":per_query,"task_verified":"true"}]',s)
        self.assertIn('task_verified_only=lightweight',s)
        self.assertIn('per_query=12 if lightweight else 10',s)

    def test_agent_probe_diagnostics_separate_contact_from_quality(self):
        s=self.source
        self.assertIn('"candidates_found":probe_candidates_found',s)
        self.assertIn('"agents_selected":probe_agents_selected',s)
        self.assertIn('"agents_contacted":len(contacted_agents)',s)
        self.assertIn('"agents_reached":len(reached_agents)',s)
        self.assertIn('"valid_answers":len(valid)',s)

    def test_revalidation_is_bounded(self):
        s=self.source
        self.assertIn("REVALIDATION_TIMEOUT_SECONDS",s)
        self.assertIn("revalidate_quarantined_rows(",s)

