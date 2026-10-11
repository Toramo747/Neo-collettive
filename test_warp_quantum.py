"""Quantum layer: reproduces Pfenning & Ford (1997) orders of magnitude."""
import math
import unittest

import arena_warp_propulsion as arena
import warp_quantum as q


class QuantumInequalityTests(unittest.TestCase):
    def test_thin_wall_energy_matches_numerical_integral(self):
        check = q.verify_thin_wall_constant()
        self.assertLess(check["max_relative_difference"], 0.01)
        self.assertTrue(check["improves_as_wall_thins"])

    def test_qi_wall_is_a_few_hundred_planck_lengths(self):
        # Pfenning & Ford: "a few hundred Planck lengths" for v ~ c.
        lp = q.max_wall_m(0.99) / q.PLANCK_LENGTH
        self.assertTrue(100 < lp < 1000, lp)

    def test_closed_form_is_the_balance_point(self):
        w = q.max_wall_m(0.8)
        ratio = q.peak_required_density_si(w, 0.8) / q.qi_bound_si(q.DEFAULT_ALPHA * w)
        self.assertAlmostEqual(ratio, 1.0, places=9)

    def test_100m_bubble_needs_astronomical_negative_energy(self):
        a = q.assess(100.0, 10.0, 0.99)
        self.assertEqual(a["verdict"], "QI_FORBIDDEN")
        self.assertTrue(1e60 < a["negative_energy_at_qi_wall_kg"] < 1e64)
        self.assertFalse(a["physical_feasibility_established"])

    def test_no_macroscopic_bubble_is_qi_compatible(self):
        self.assertFalse(q.feasibility_map()["any_qi_compatible_macroscopic_bubble"])

    def test_superluminal_flags_semiclassical_instability(self):
        self.assertTrue(q.assess(100.0, 10.0, 1.1)["semiclassical_instability_flag"])


class PhysicsSelectionTests(unittest.TestCase):
    def test_unsupported_families_are_never_selected_when_supported_exist(self):
        _, report = arena.run_generation({}, 48, 7)
        self.assertTrue(report["selection"]["physics_affects_selection"])
        for c in report["top_candidates"]:
            self.assertEqual(c["family"], "alcubierre_like")
            self.assertNotIn("NO_PHYSICAL_EVALUATOR", c["hard_flags"])
        self.assertEqual(report["best_quantum_verdict"], "QI_FORBIDDEN")

    def test_unsupported_family_gets_flag(self):
        _, report = arena.run_generation({"champions": [
            {"family": "positive_energy_subluminal", "wall_thickness": 1.25, "bubble_radius": 0.65,
             "effective_beta": 0.86, "shear_control": 1.0, "lapse_modulation": 0.04}]}, 16, 1)
        self.assertGreaterEqual(report["hard_flagged"], 1)
