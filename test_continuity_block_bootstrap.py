import unittest
from scripts.continuity_block_bootstrap import validate_runtime


class ContinuityBootstrapTests(unittest.TestCase):
    def sample(self, evidence=291, cycles=4300, reason='stale_generation_write_blocked'):
        state = {'last_checkpoint': {'reason': reason},
                 'evidence_memory_telemetry': {'evidence_out': evidence},
                 'cycles_completed': cycles}
        snapshot = {'autopilot': {'select_diagnostics': {'persistent_evidence_items': 291},
                                 'cycles_completed': 4297}}
        return state, snapshot, {'cycles_completed': 4290}

    def test_regression_above_old_incident_floor_is_blocked(self):
        out = validate_runtime(*self.sample(evidence=200))
        self.assertFalse(out['allowed'])
        self.assertEqual(out['evidence_floor'], 291)

    def test_intact_runtime_can_bootstrap(self):
        self.assertTrue(validate_runtime(*self.sample())['allowed'])

    def test_other_failure_or_regressed_cycles_are_blocked(self):
        self.assertFalse(validate_runtime(*self.sample(reason='timeout'))['allowed'])
        self.assertFalse(validate_runtime(*self.sample(cycles=4295))['allowed'])

    def test_missing_published_floor_is_blocked(self):
        state, _, floor = self.sample()
        self.assertFalse(validate_runtime(state, {}, floor)['allowed'])
        self.assertFalse(validate_runtime(state, {}, {})['allowed'])
