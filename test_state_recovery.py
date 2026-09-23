import unittest

from state_recovery import select_freshest_state, state_freshness


class StateRecoveryTests(unittest.TestCase):
    def test_higher_cycle_count_beats_newer_but_stale_env_timestamp(self):
        source,payload,meta=select_freshest_state([
            ("render_env",{
                "cycles_completed":139,
                "state_saved_at_utc":"2026-09-23T03:00:00+00:00",
            }),
            ("repo_snapshot",{
                "cycles_completed":141,
                "last_finished_utc":"2026-09-23T00:41:36+00:00",
            }),
        ])
        self.assertEqual(source,"repo_snapshot")
        self.assertEqual(payload["cycles_completed"],141)
        self.assertEqual(meta["selected_cycles"],141)

    def test_timestamp_breaks_tie_between_equal_cycle_counts(self):
        source,payload,_=select_freshest_state([
            ("render_env",{
                "cycles_completed":141,
                "state_saved_at_utc":"2026-09-23T00:40:00+00:00",
            }),
            ("repo_snapshot",{
                "cycles_completed":141,
                "last_finished_utc":"2026-09-23T00:41:36+00:00",
            }),
        ])
        self.assertEqual(source,"repo_snapshot")
        self.assertEqual(payload["cycles_completed"],141)

    def test_exact_tie_prefers_fuller_local_state(self):
        source,_,_=select_freshest_state([
            ("repo_snapshot",{"cycles_completed":8}),
            ("render_env",{"cycles_completed":8}),
            ("local_snapshot",{"cycles_completed":8}),
        ])
        self.assertEqual(source,"local_snapshot")

    def test_empty_candidates_return_fresh(self):
        source,payload,meta=select_freshest_state([
            ("render_env",None),
            ("repo_snapshot",{}),
        ])
        self.assertEqual(source,"fresh")
        self.assertIsNone(payload)
        self.assertEqual(meta["candidates"],0)

    def test_freshness_handles_invalid_values(self):
        self.assertEqual(state_freshness({"cycles_completed":"bad"}),(0,0.0))


if __name__=="__main__":
    unittest.main()
