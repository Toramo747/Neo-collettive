import asyncio
import unittest
from pathlib import Path
import arena_production_recovery as arena

class ProductionRecoveryTests(unittest.TestCase):
    def test_real_cycle_fault_injection_selects_bounds_without_gate_changes(self):
        source=Path('cloud_mcp.py').read_text()
        cycle=arena.cycle_source(source)
        ranked=asyncio.run(arena.evaluate(cycle))
        winner=ranked[0]
        baseline=next(row for row in ranked if not row['genes'])
        self.assertEqual(winner['passed'],5)
        self.assertGreater(winner['passed'],baseline['passed'])
        for result in winner['scenarios']:
            self.assertTrue(result['lock_released'])
            self.assertTrue(result['running_cleared'])
            self.assertTrue(result['terminal_recorded'])
            if result['fault']!='healthy':self.assertTrue(result['error_recorded'])
        patched=arena.mutate(cycle,winner['genes'])
        self.assertIn('timeout=AUTOPILOT_CYCLE_TIMEOUT_SECONDS',patched)
        self.assertIn('quality_gate=bool(quality.get("quality_gate"))',patched)
        self.assertNotIn('api_heartbeat',patched)

    def test_mutation_is_confined_to_selected_awaits(self):
        source=arena.cycle_source(Path('cloud_mcp.py').read_text())
        changed=arena.mutate(source,('seti',))
        self.assertEqual(changed.count('timeout=min(AUTOPILOT_CYCLE_TIMEOUT_SECONDS,120.0)'),1)
        self.assertIn('await _checkpoint_state_to_render()',changed)
        self.assertIn('await _checkpoint_seti_private_to_render()',changed)

if __name__=='__main__':unittest.main()
