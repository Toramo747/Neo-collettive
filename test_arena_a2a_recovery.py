import unittest
import arena_a2a_recovery as a

class A2ARecoveryArenaTests(unittest.TestCase):
    def test_boundary_isolated(self):
        self.assertFalse(a.BOUNDARY["production_state_write"])
        self.assertFalse(a.BOUNDARY["external_registry_write"])
        self.assertFalse(a.BOUNDARY["secret_persistence"])
        self.assertFalse(a.BOUNDARY["production_variant_promotion"])

    def test_early_policy_publish_survives_slow_registry(self):
        g=a.clamp({"publish_state_early":True,"registry_mode":"sequential","per_registry_timeout":20,"startup_grace_seconds":0,"registry_semantics":"policy_enabled","ordering":"global_first"})
        row=a.simulate(g,next(s for s in a.SCENARIOS if s["name"]=="all_registries_slow"))
        self.assertTrue(row["smoke_enabled"])
        self.assertTrue(row["final_enabled"])

    def test_disabled_policy_never_false_positive(self):
        for row in a.seeds():
            m=a.simulate(row["genes"],next(s for s in a.SCENARIOS if s["name"]=="policy_disabled"))
            self.assertFalse(m["smoke_enabled"])
            self.assertFalse(m["final_enabled"])

    def test_population_evolves(self):
        state={"generation":0,"population":a.seeds()}
        out=a.evolve(state)
        self.assertEqual(out["generation"],1)
        self.assertEqual(len(out["population"]),a.POPULATION_SIZE)
        self.assertFalse(out["promotion_candidate"]["production_promoted"])

if __name__=="__main__":
    unittest.main()
