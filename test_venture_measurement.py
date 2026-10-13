import unittest

from venture_measurement import (
    complete_observed_measurement,
    measurement_summary,
    start_observed_measurement,
)


class VentureMeasurementTests(unittest.TestCase):
    def baseline(self):
        return start_observed_measurement(
            measurement_id="vm-1",
            build_id="build-1",
            family="manual_data_entry",
            process_label="Copy invoice rows from CSV into ERP",
            baseline_minutes_each=30,
            baseline_weekly_runs=5,
            baseline_weekly_errors=4,
            observed_at_utc="2026-09-24T06:00:00+00:00",
        )

    def test_baseline_is_observed_but_not_an_outcome(self):
        row=self.baseline()
        self.assertEqual(row["status"],"BASELINE_RECORDED")
        self.assertEqual(row["baseline"]["weekly_minutes"],150)
        self.assertIsNone(row["outcome"])
        self.assertTrue(row["evidence_boundary"]["does_not_prove_market_demand"])

    def test_completion_computes_real_before_after_delta(self):
        row=complete_observed_measurement(
            self.baseline(),
            after_minutes_each=12,
            after_weekly_runs=5,
            after_weekly_errors=1,
            observed_at_utc="2026-09-25T06:00:00+00:00",
        )
        self.assertEqual(row["status"],"OBSERVED_RESULT")
        self.assertEqual(row["outcome"],"IMPROVED")
        self.assertEqual(row["result"]["weekly_minutes_saved"],90)
        self.assertEqual(row["result"]["minutes_reduction_pct"],60)
        self.assertEqual(row["result"]["weekly_errors_avoided"],3)

    def test_regression_is_not_relabelled_as_improvement(self):
        row=complete_observed_measurement(
            self.baseline(),
            after_minutes_each=35,
            after_weekly_runs=5,
            after_weekly_errors=5,
            observed_at_utc="2026-09-25T06:00:00+00:00",
        )
        self.assertEqual(row["outcome"],"REGRESSED")
        self.assertLess(row["result"]["weekly_minutes_saved"],0)

    def test_summary_is_scoped_to_build(self):
        baseline=self.baseline()
        completed=complete_observed_measurement(
            baseline,
            after_minutes_each=20,
            after_weekly_runs=5,
            after_weekly_errors=2,
            observed_at_utc="2026-09-25T06:00:00+00:00",
        )
        other=dict(baseline,measurement_id="vm-2",build_id="build-2")
        summary=measurement_summary([completed,other],build_id="build-1",family="manual_data_entry")
        self.assertEqual(summary["sessions"],1)
        self.assertEqual(summary["completed_results"],1)
        self.assertEqual(summary["improved"],1)

    def test_invalid_zero_baseline_is_rejected(self):
        with self.assertRaises(ValueError):
            start_observed_measurement(
                measurement_id="vm-1",
                build_id="build-1",
                family="manual_data_entry",
                process_label="Process",
                baseline_minutes_each=0,
                baseline_weekly_runs=5,
                baseline_weekly_errors=0,
                observed_at_utc="2026-09-24T06:00:00+00:00",
            )


if __name__=="__main__":
    unittest.main()
