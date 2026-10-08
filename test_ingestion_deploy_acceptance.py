from pathlib import Path
import unittest
from scripts.verify_ingestion_deploy import accept, project


class IngestionAcceptanceTests(unittest.TestCase):
    def sample(self, cycle=1):
        return {'cycle': cycle, 'ingestion_drought': {'rows': [{'raw_results': 150}],
                'measurement_reliable': True, 'unjoined_total': 0}, 'evidence_out': 141, 'stored_bytes': 53367}

    def test_three_consecutive_cycles_pass(self):
        previous = None
        for cycle in (2927, 2928, 2929):
            sample = self.sample(cycle)
            accept(sample, previous)
            previous = sample

    def test_any_acceptance_failure_rejects_without_repair(self):
        for field, value in (('evidence_out', 140), ('stored_bytes', 75000), ('stored_bytes', 0)):
            sample = self.sample()
            sample[field] = value
            with self.assertRaises(ValueError): accept(sample)
        for field, value in (('rows', []), ('measurement_reliable', False), ('unjoined_total', 1)):
            sample = self.sample()
            sample['ingestion_drought'][field] = value
            with self.assertRaises(ValueError): accept(sample)
        with self.assertRaises(ValueError): accept(self.sample(3), self.sample(1))

    def test_unfinished_cycle_is_not_counted(self):
        self.assertIsNone(project({'autopilot': {'running': True}}))
        self.assertIsNone(project({'autopilot': {'running': False}}))

    def test_workflow_failure_keeps_existing_rollback_enabled(self):
        import yaml
        data = yaml.safe_load(Path('.github/workflows/neo-render-deploy.yml').read_text())
        steps = next(iter(data['jobs'].values()))['steps']
        check = next(x for x in steps if x.get('name') == 'Verify three consecutive ingestion observation cycles')
        self.assertNotIn('continue-on-error', check)
        self.assertIn('verify_ingestion_deploy.py', check['run'])
        rollback = next(x for x in steps if x.get('name') == 'Restore previous Render production commit')
        self.assertIn('failure()', rollback['if'])
        self.assertLess(steps.index(check), steps.index(rollback))
