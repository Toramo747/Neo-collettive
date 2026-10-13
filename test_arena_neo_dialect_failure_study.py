import json
import unittest

import neo_dialect as nd
from arena_neo_dialect_failure_study import (
    SCENARIOS, _fallback, dialect_observations, run_session, summarize,
)

class FakeGenerator:
    def __call__(self,prompt,schema):
        # Infer requested type from schema const.
        typ=((schema.get("properties") or {}).get("type") or {}).get("const")
        cid=None
        import re
        m=re.search(r'conversation_id="([^"]+)"',prompt)
        cid=m.group(1)
        scenario=next(x for x in SCENARIOS if f"Scenario={x}" in prompt)
        if typ=="CAPABILITIES":
            msg=nd.capabilities(cid,"Arena-3B",["structured-a2a-exchange"])
        elif typ=="PROPOSE":
            msg=nd.new_envelope("PROPOSE",cid,proposal_id="evolution-1",subject="measure",offer={"scope":"arena"},requested={"review":True})
        elif typ=="COUNTER":
            changes={"objection":"bounded objection"}
            if scenario=="confuso":
                changes={"clarification_request":"state intended outcome"}
            msg=nd.new_envelope("COUNTER",cid,proposal_id="evolution-1",counter_id="c1",changes=changes)
        elif typ=="AGREE":
            msg=nd.new_envelope("AGREE",cid,proposal_id="evolution-1",agreement_id="evolution-agreement",terms={"ok":True})
        elif typ=="RESULT":
            msg=nd.new_envelope("RESULT",cid,agreement_id="evolution-agreement",status="ok",summary={"done":True})
        else:
            raise AssertionError(typ)
        return json.dumps(msg),{"_elapsed_seconds":0.01}

class FailureStudyTests(unittest.TestCase):
    def test_four_scenarios_x_three_can_complete_to_bye(self):
        g=FakeGenerator()
        rows=[run_session(g,s,r) for s in SCENARIOS for r in range(1,4)]
        summary=summarize(rows)
        self.assertEqual(summary["sessions"],12)
        self.assertEqual(summary["complete_to_bye"],12)
        self.assertEqual(summary["model_invalid"],0)

    def test_confused_scenario_records_dialect_level_overload(self):
        row=run_session(FakeGenerator(),"confuso",1)
        kinds=[x["kind"] for x in row["dialect_observations"]]
        self.assertIn("clarification_overloaded_into_counter",kinds)

    def test_invalid_model_output_is_model_problem_and_rules_fallback(self):
        class Broken:
            def __call__(self,prompt,schema):
                return '{"truncated":',{"_elapsed_seconds":0.01}
        row=run_session(Broken(),"scettico",1)
        self.assertTrue(row["completed_to_bye"])
        self.assertGreater(row["metrics"]["model_invalid"],0)
        self.assertEqual(row["metrics"]["model_invalid"],row["metrics"]["fallbacks"])
        self.assertTrue(all(x["issue_type"]=="MODEL" for x in row["model_attempts"]))

    def test_fallbacks_are_valid_1_0(self):
        for typ in ("CAPABILITIES","PROPOSE","COUNTER","AGREE","RESULT"):
            msg=_fallback(typ,"c1","confuso","s")
            self.assertTrue(nd.validate_message(msg,expected_type=typ,expected_conversation_id="c1")["ok"])

if __name__=="__main__":
    unittest.main()
