"""Offline tests for the maestro census (no network)."""
import importlib.util
import unittest
from pathlib import Path

_spec = importlib.util.spec_from_file_location("census", Path(__file__).parent / "tools" / "maestro_label_census.py")
census = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(census)


class CensusTests(unittest.TestCase):
    def test_all_families_two_terms(self):
        fams = census.family_terms()
        self.assertEqual(len(fams), 25)
        self.assertTrue(all(1 <= len(t) <= 2 for t in fams.values()))

    def test_verdict_rule(self):
        mk = lambda n, v: {"families": {f"f{i}": {"proof_total": v} for i in range(n)}}
        self.assertTrue(census.verdict(mk(25, 45))["viable"])     # 1125 total, 25 strong
        self.assertFalse(census.verdict(mk(25, 39))["viable"])    # 975 total
        r = mk(25, 0)
        for i in range(14):
            r["families"][f"f{i}"]["proof_total"] = 100            # 1400 total, only 14 strong
        self.assertFalse(census.verdict(r)["viable"])


if __name__ == "__main__":
    unittest.main()
