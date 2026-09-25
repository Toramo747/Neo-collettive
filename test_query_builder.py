import unittest

from query_builder import breakout_queries, discovery_query, observed_buyer_phrases, scout_queries


class QueryBuilderTests(unittest.TestCase):
    def setUp(self):
        self.rows=[{
            "tagger_v":3,
            "quarantine_reason":None,
            "family":"manual_data_entry",
            "signal_types":["PAIN","BUY_INTENT"],
            "title":"Looking for help replacing repetitive invoice entry",
            "snippet":"Our operations team manually copies invoice fields every morning and needs help removing this repetitive workaround.",
            "seen_count":2,
        }]

    def test_observed_buyer_language_changes_discovery_query(self):
        current=discovery_query(
            "manual_data_entry",
            ["manual data entry","data entry"],
            "explore",
            self.rows,
        )
        fallback=discovery_query(
            "manual_data_entry",
            ["manual data entry","data entry"],
            "explore",
            [],
        )
        self.assertNotEqual(current,fallback)
        self.assertTrue("Looking for help" in current or "manually copies" in current)

    def test_fallback_is_deterministic_and_family_specific(self):
        explore=discovery_query("manual_data_entry",["manual data entry"],"explore",[])
        exploit=discovery_query("manual_data_entry",["manual data entry"],"exploit",[])
        self.assertTrue(explore.startswith("manual data entry "))
        self.assertIn("site:reddit.com",explore)
        self.assertIn("site:stackoverflow.com",explore)
        self.assertIn("site:news.ycombinator.com",explore)
        self.assertIn('"I need"',explore)
        self.assertTrue(exploit.startswith("manual data entry "))
        self.assertIn("contractor",exploit)
        self.assertIn("site:reddit.com",exploit)

    def test_quarantined_or_old_tagger_rows_are_not_learned(self):
        rows=[
            dict(self.rows[0],tagger_v=2),
            dict(self.rows[0],quarantine_reason="legacy_unverified_tagger_v1"),
        ]
        self.assertEqual(observed_buyer_phrases(rows,"manual_data_entry"),[])

    def test_scout_queries_use_observed_language(self):
        queries=scout_queries(self.rows,7)
        self.assertTrue(queries)
        self.assertNotIn("AI SaaS",queries)

    def test_observed_phrase_keeps_family_anchor(self):
        rows=[{
            "tagger_v":3,
            "quarantine_reason":None,
            "family":"hr_tools",
            "signal_types":["PAIN","BUY_INTENT"],
            "title":"Looking for help with a repetitive employee onboarding process",
            "snippet":"We need help because onboarding is manual and repetitive.",
            "seen_count":1,
        }]
        q=discovery_query("hr_tools",["HR workflow automation"],"explore",rows)
        self.assertTrue(q.startswith("HR workflow automation "))
        self.assertIn("Looking for help",q)

    def test_breakout_has_no_reddit_template(self):
        queries=breakout_queries("manual data entry",[],family="manual_data_entry")
        self.assertEqual(len(queries),2)
        self.assertTrue(all("site:reddit.com" in q for q in queries))
        self.assertTrue(any('"I need"' in q for q in queries))
        self.assertTrue(any("RFP" in q for q in queries))


if __name__=="__main__":
    unittest.main()
