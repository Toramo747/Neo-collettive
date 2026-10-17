import copy
import json
import unittest

from demand_pressure import demand_pressure_index

NOW = 1_800_000_000.0


def observation(number, weeks_ago=0, **kwargs):
    item = {
        "request_id": f"{number:064x}",
        "created_at_epoch": NOW - (weeks_ago * 7 + 2) * 86400,
        "source_screened": True,
        "demand_signal_tag": "PAIN",
        "vendor_offer": False,
        "self_traffic": False,
        "agent_origin": False,
        "actor_hmac": f"{number:064x}",
        "independent_requester_verified": True,
        "origin_domain": "community.example",
        "explicit_solution_request": True,
    }
    item.update(kwargs)
    return item


class DemandPressureTests(unittest.TestCase):
    def calculate(self, rows, **kwargs):
        return demand_pressure_index(rows, now_epoch=NOW, **kwargs)

    def test_repeated_crawls_are_not_requests(self):
        x = observation(1)
        score = self.calculate([x, copy.deepcopy(x), copy.deepcopy(x)])
        self.assertEqual(score["unique_request_threads"], 1)
        self.assertEqual(score["weekly_request_threads_newest_first"], [1, 0, 0, 0])
        self.assertEqual(score["verified_requester_tokens"], 1)
        self.assertEqual(score["explicit_solution_threads"], 1)
        self.assertEqual(score["evidence_status"], "TOO_FEW_THREADS")

    def test_independent_actor_never_inferred_from_anonymous(self):
        rows = [observation(i, actor_hmac="", independent_requester_verified=False) for i in range(1, 11)]
        score = self.calculate(rows)
        self.assertEqual(score["verified_requester_tokens"], 0)
        self.assertEqual(score["unverified_request_threads"], 10)
        self.assertEqual(score["evidence_status"], "IDENTITY_NOT_VERIFIED")

    def test_conflicting_duplicate_loses_actor_and_domain_credit(self):
        a = observation(3)
        b = observation(3, actor_hmac=f"{4:064x}", origin_domain="other.example",
                        explicit_solution_request=False)
        result = self.calculate([a, b])
        self.assertEqual(result["unique_request_threads"], 1)
        self.assertEqual(result["verified_requester_tokens"], 0)
        self.assertEqual(result["origin_domains"], 0)
        self.assertEqual(result["explicit_solution_threads"], 0)

    def test_invalid_vendor_and_agent_and_unproven_rows_cannot_inflate_index(self):
        clean = observation(1)
        excluded = [
            observation(2, vendor_offer=True),
            observation(3, agent_origin=True),
            observation(4, self_traffic=True),
            observation(5, source_screened=False),
            observation(6, demand_signal_tag=""),
            observation(7, request_id="raw-user-name"),
            observation(8, created_at_epoch=None),
            observation(9, created_at_epoch=NOW + 100),
            observation(10, created_at_epoch=NOW - 35 * 86400),
        ]
        value = self.calculate([clean] + excluded)
        self.assertEqual(value["unique_request_threads"], 1)
        self.assertEqual(value["source_rows_excluded"], 9)

    def test_growth_is_not_claimed_without_comparable_exposure(self):
        rows = [observation(i) for i in range(1, 10)]
        result = self.calculate(rows)
        self.assertEqual(result["growth_status"], "EXPOSURE_MISSING")
        self.assertIsNone(result["growth_percent"])
        self.assertEqual(result["components"]["growth"], 0)

    def test_measured_growth_uses_rates_not_absolute_thread_counts(self):
        rows = [
            *[observation(i) for i in range(1, 9)],
            *[observation(i, weeks_ago=1) for i in range(9, 13)],
        ]
        up = self.calculate(rows, exposure_current=80, exposure_previous=80, sampling_comparable=True)
        flat = self.calculate(rows, exposure_current=160, exposure_previous=80, sampling_comparable=True)
        self.assertEqual(up["growth_percent"], 100.0)
        self.assertEqual(flat["growth_percent"], 0.0)
        self.assertGreater(up["ipd_score"], flat["ipd_score"])

    def test_growth_emerging_is_not_infinite_percent(self):
        result = self.calculate([observation(i) for i in range(1, 4)],
                                exposure_current=30, exposure_previous=30, sampling_comparable=True)
        self.assertEqual(result["growth_status"], "EMERGING")
        self.assertIsNone(result["growth_percent"])

    def test_recurrence_measures_distinct_weeks(self):
        rows = [observation(i, weeks_ago=i-1) for i in range(1, 5)]
        result = self.calculate(rows)
        self.assertEqual(result["components"]["recurrence"], 100)
        self.assertEqual(result["weekly_request_threads_newest_first"], [1, 1, 1, 1])

    def test_result_is_numeric_aggregate_and_no_identity_or_source_text(self):
        x = observation(20, title="secret email foo@bar.example", url="https://private.example/data")
        result = self.calculate([x])
        serialized = json.dumps(result)
        self.assertNotIn("secret", serialized)
        self.assertNotIn("private.example", serialized)
        self.assertNotIn(x["actor_hmac"], serialized)
        self.assertNotIn(x["request_id"], serialized)
        self.assertNotIn("community.example", serialized)
        self.assertNotIn("foo@bar.example", serialized)
        self.assertEqual(result["commercial_gate_influence"], "NONE")
        self.assertFalse(result["automatic_promotion"])
        self.assertTrue(0 <= result["ipd_score"] <= 100)

    def test_untrusted_time_and_exposure_fail_closed(self):
        for value in (0, float("nan"), float("inf"), None, "tomorrow"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                demand_pressure_index([], now_epoch=value)
        score = self.calculate([observation(1)], exposure_current=True,
                               exposure_previous=10, sampling_comparable=True)
        self.assertEqual(score["growth_status"], "EXPOSURE_MISSING")

    def test_input_is_unmodified_and_output_deterministic(self):
        rows = [observation(1), observation(2, weeks_ago=1)]
        before = copy.deepcopy(rows)
        x = self.calculate(rows, exposure_current=100, exposure_previous=100, sampling_comparable=True)
        y = self.calculate(list(reversed(rows)), exposure_current=100,
                           exposure_previous=100, sampling_comparable=True)
        self.assertEqual(x, y)
        self.assertEqual(rows, before)


if __name__ == "__main__":
    unittest.main()
