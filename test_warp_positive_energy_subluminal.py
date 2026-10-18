"""A static subluminal positive-density spherical shell: reference-only tests."""
import unittest
import warp_metrics as metrics


class SubluminalShellTests(unittest.TestCase):
    def test_tensor_matches_analytic_density_and_anisotropic_pressures(self):
        checks = metrics.positive_energy_subluminal_checks()
        self.assertTrue(checks["passed"], checks)
        self.assertLess(checks["numerics"]["fine_max_absolute_error"],
                        checks["numerics"]["coarse_max_absolute_error"])

    def test_positive_mass_and_no_claim_of_propulsion(self):
        result = metrics.positive_energy_subluminal_assess(.5)
        self.assertGreater(result["eulerian_energy_integral_over_L0"], 0)
        self.assertEqual(result["status"], "REFERENCE_METRIC_ONLY")
        self.assertFalse(result["physical_feasibility_established"])
        self.assertFalse(result["acceleration_or_propulsion_model_supplied"])
        self.assertTrue(result["eligible_for_reference_selection"])

    def test_reject_non_subluminal_and_unphysical_inputs(self):
        for kwargs in ({"beta": 1.0}, {"beta": -0.1}, {"beta": float("nan")},
                       {"beta": .5, "mass": -1}, {"beta": .5, "inner": 1.5, "outer": 1.1},
                       {"beta": .5, "mass": .1}):
            with self.subTest(kwargs=kwargs):
                result = metrics.positive_energy_subluminal_assess(**kwargs)
                self.assertEqual(result["status"], "INVALID_REFERENCE_PARAMETERS")
                self.assertFalse(result["eligible_for_reference_selection"])

    def test_velocity_is_a_label_not_a_stress_reduction_trick(self):
        a = metrics.positive_energy_subluminal_assess(.2)
        b = metrics.positive_energy_subluminal_assess(.8)
        self.assertEqual(a["eulerian_energy_integral_over_L0"],
                         b["eulerian_energy_integral_over_L0"])


if __name__ == "__main__":
    unittest.main()
