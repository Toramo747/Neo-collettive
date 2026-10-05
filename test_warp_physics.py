# SPDX-License-Identifier: BUSL-1.1
import math
import unittest
from unittest.mock import patch

import arena_warp_propulsion as arena
import warp_physics as physics


class WarpPhysicsTests(unittest.TestCase):
    def test_published_reference_checks(self):
        checks = physics.reference_checks()
        self.assertTrue(checks["passed"], checks)

    def test_velocity_and_length_scaling(self):
        m = physics.AlcubierreReference(1, .2, .5)
        faster = physics.AlcubierreReference(1, .2, 1)
        larger = physics.AlcubierreReference(2, .4, .5)
        self.assertAlmostEqual(physics.energy_integral(faster), 4*physics.energy_integral(m), places=12)
        self.assertAlmostEqual(physics.energy_integral(larger), 2*physics.energy_integral(m), places=12)
        self.assertAlmostEqual(larger.density(0, 2, 0), m.density(0, 1, 0)/4, places=12)

    def test_axis_center_and_equator(self):
        m = physics.AlcubierreReference(1, .125, .8)
        self.assertEqual(m.density(0, 0, 0), 0)
        self.assertEqual(m.density(1, 0, 0), 0)
        self.assertLess(m.density(0, 1, 0), 0)
        expected = -.8**2 * m.shape_derivative(1)**2 / (32*math.pi)
        self.assertAlmostEqual(m.density(0, 1, 0), expected)

    def test_energy_integral_against_density_volume_quadrature(self):
        m = physics.AlcubierreReference(1, .2, .8)
        def radial_shell(r):
            # Integrate actual density over polar cosine mu, with azimuth 2*pi.
            angular = physics.simpson(
                lambda u: m.density(r*(u-1), r*math.sqrt(max(0, 1-(u-1)**2)), 0), 2, 32)
            return 2*math.pi*r*r*angular
        volume = physics.simpson(radial_shell, m.radius+12*m.wall_scale, 512)
        self.assertAlmostEqual(volume, physics.energy_integral(m), places=10)

    def test_zero_velocity_does_not_claim_energy_conditions_proven(self):
        result = physics.metric_diagnostics(physics.AlcubierreReference(1, .2, 0))
        self.assertEqual(result["weak_energy_condition"], "NOT_ESTABLISHED")
        self.assertFalse(result["physical_feasibility_established"])

    def test_supported_domain_corners_converge(self):
        for radius in (.5, 3):
            for wall in (.08, 1.25):
                with self.subTest(radius=radius, wall=wall):
                    result = physics.metric_diagnostics(physics.AlcubierreReference(radius, wall, 1.5))
                    self.assertTrue(result["numerics"]["converged"], result)
                    self.assertLess(result["eulerian_energy_integral_over_L0"], 0)

    def test_unknown_geometries_are_not_positive_energy_proofs(self):
        for family in arena.FAMILIES:
            c = arena.Candidate(family, .2, 1, .8, .5, .1)
            result = physics.evaluate_candidate(vars(c))
            self.assertFalse(result["physical_feasibility_established"])
            if family != "alcubierre_like":
                self.assertEqual(result["status"], "UNSUPPORTED_GEOMETRY")
                self.assertNotIn("eulerian_energy_integral_over_L0", result)
            else:
                self.assertEqual(result["mapping"]["unmodeled_candidate_parameters"], ["shear_control", "lapse_modulation"])

    def test_invalid_parameters_fail_closed(self):
        for value in (math.nan, math.inf, -.2, 0, 100, None):
            result = physics.evaluate_candidate({"family": "alcubierre_like", "bubble_radius": 1,
                                                 "wall_thickness": value, "effective_beta": .8})
            self.assertEqual(result["status"], "INVALID_REFERENCE_PARAMETERS")

    def test_scientific_report_does_not_change_evolution(self):
        state, report = arena.run_generation({}, 48, 42)
        with patch.object(arena, "evaluate_population", return_value={}):
            control_state, control_report = arena.run_generation({}, 48, 42)
        self.assertEqual(state["champions"], control_state["champions"])
        self.assertEqual(report["top_candidates"], control_report["top_candidates"])
        p = report["physical_evaluation"]
        self.assertEqual(p["reference_evaluated_count"]+p["unsupported_count"]+p["invalid_count"], 48)
        self.assertTrue(p["reference_checks"]["passed"])
        self.assertFalse(p["affects_fitness"])
        self.assertFalse(p["affects_selection"])
        self.assertFalse(state["production_promoted"])

    def test_failed_reference_checks_abort_generation(self):
        with patch.object(physics, "reference_checks", return_value={"passed": False}):
            with self.assertRaises(RuntimeError):
                arena.run_generation({}, 8, 42)


if __name__ == "__main__":
    unittest.main()
