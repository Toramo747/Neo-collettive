import json, unittest
from arena_local_llm_compare import FALLBACK_MODEL, PRIMARY_MODEL, case_for, quality_score, schema_for

class LocalLLMComparisonTests(unittest.TestCase):
    def test_prompt_contains_required_glossary(self):
        typ,prompt=case_for("Critic","cid",3)
        self.assertEqual(typ,"COUNTER")
        self.assertIn("MCP means Model Context Protocol",prompt)
        self.assertIn("A2A means Agent2Agent",prompt)
        self.assertIn("Never interpret MCP as Microsoft Certified Professional",prompt)

    def test_real_neo_dialect_schema_used(self):
        s=schema_for("PROPOSE")
        self.assertEqual(s.get("type"),"object")
        self.assertIn("conversation_id",s.get("required") or [])
        self.assertIn("proposal_id",s.get("required") or [])

    def test_primary_model_policy_prefers_3b(self):
        self.assertEqual(PRIMARY_MODEL,"qwen2.5:3b-instruct-q4_K_M")
        self.assertEqual(FALLBACK_MODEL,"qwen2.5:0.5b-instruct")
        self.assertNotEqual(PRIMARY_MODEL,FALLBACK_MODEL)

    def test_microsoft_certified_misread_is_penalized(self):
        q=quality_score("Critic",{"changes":{"objection":"Microsoft Certified Professional"}},"{}",False)
        self.assertFalse(q["glossary_correct"])
        self.assertLess(q["score"],0.5)

if __name__=="__main__": unittest.main()
