import unittest

import market_inference as mi
import tool_opportunity


def row(url, text, domain=None, date="2026-10-01T00:00:00+00:00", signals=()):
    from urllib.parse import urlparse
    return {"url": url, "domain": domain or urlparse(url).hostname, "title": "", "excerpt": text,
            "date": date, "signal_types": list(signals)}


class MarketInferenceTests(unittest.TestCase):
    def test_reference_bot_and_marketing_are_never_demand(self):
        self.assertEqual(mi.classify_row(row("https://en.wikipedia.org/wiki/X", "We need a tool for reports")), "noise")
        self.assertEqual(mi.classify_row(row("https://github.com/a/b/issues/1", "This issue lists Renovate updates; we need them")), "noise")
        self.assertEqual(mi.classify_row(row("https://x.example/p", "Sign up today. We help teams who struggle with reports", signals=["PAYMENT"])), "supply")
        self.assertEqual(mi.classify_row(row("https://news.ycombinator.com/item?id=1", "Show HN: we built a thing because I hate manual reports")), "supply")

    def test_first_person_pain_is_demand(self):
        self.assertEqual(mi.classify_row(row("https://reddit.com/r/x/1", "I spend hours every week manually reconciling CSV exports")), "demand")
        self.assertEqual(mi.classify_row(row("https://forum.example/t/2", "Is there a tool that monitors report drift?")), "demand")

    def test_shadow_gate_needs_independent_requesters_and_money_or_market(self):
        demand = [
            row("https://reddit.com/r/a/1", "I waste a day each month fixing broken dashboards", date="2026-08-20T00:00:00+00:00"),
            row("https://forum.example/t/2", "We need something to catch report drift; we would pay for it", date="2026-09-25T00:00:00+00:00"),
            row("https://github.com/org/repo/issues/9", "Our team struggles with stale reports every release"),
        ]
        seller = row("https://vendor.example/pricing", "Pricing plans per month", signals=["PAYMENT"])
        out = mi.assess(demand + [seller], thesis_specific=True, now="2026-10-12T00:00:00+00:00")
        self.assertEqual(out["independent_requesters"], 3)
        self.assertTrue(out["shadow_gate_pass"], out)
        self.assertFalse(out["affects_gate"])
        weak = mi.assess(demand[:2], thesis_specific=True, now="2026-10-12T00:00:00+00:00")
        self.assertFalse(weak["shadow_gate_pass"])
        self.assertIn("three_independent_requesters", weak["missing"])

    def test_same_repo_counts_once(self):
        rows = [row(f"https://github.com/org/repo/issues/{i}", "We need a way to replay CI failures") for i in range(5)]
        self.assertEqual(mi.assess(rows, thesis_specific=True)["independent_requesters"], 1)

    def test_shadow_is_attached_and_never_changes_gate_pass(self):
        result = tool_opportunity.analyze_tool_opportunities([], [], [], {}, "2026-10-12T00:00:00+00:00")
        self.assertIn("market_inference_shadow_pass", result["candidate_counts"])
        for opp in result["top5"]:
            self.assertFalse(opp["market_inference"]["affects_gate"])
            self.assertFalse(opp["gate_pass"])

if __name__ == "__main__":
    unittest.main()
