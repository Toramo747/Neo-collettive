import unittest
import neo_dialect_council as council

class CouncilTests(unittest.TestCase):
    def test_redacts_sensitive_keys_and_values(self):
        row=council.redact({"api_key":"abc","text":"Bearer abcdefghijklmnop","nested":{"password":"x"}})
        self.assertEqual(row["api_key"],"[REDACTED]")
        self.assertEqual(row["nested"]["password"],"[REDACTED]")
        self.assertNotIn("abcdefghijklmnop",row["text"])

    def test_example_is_full_seven_turn_sequence(self):
        rows=council.example_transcript()
        self.assertEqual([x["message"]["type"] for x in rows],["HELLO","CAPABILITIES","PROPOSE","COUNTER","AGREE","RESULT","BYE"])
        self.assertTrue(all(x["schema_valid"] for x in rows))

    def test_hostile_scenarios_do_not_accept_attacks(self):
        rows=council.hostile_report()
        names={x["attack"] for x in rows}
        self.assertTrue({"instruction_injection","out_of_schema","oversize","counter_loop","internal_data_request","violation_limit"}.issubset(names))
        for row in rows:
            self.assertFalse(bool(row.get("accepted")))

if __name__=="__main__":
    unittest.main()
