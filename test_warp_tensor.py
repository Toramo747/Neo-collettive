# SPDX-License-Identifier: BUSL-1.1
import math
import unittest
from unittest.mock import patch

import numpy as np
import arena_warp_propulsion as arena
from warp_physics import AlcubierreReference
import warp_tensor as tensor
import warp_reference_search as search


def numerical_metric_derivatives(metric, point, step):
    def value(p):
        return tensor.comoving_metric(metric, p)[0]
    p = np.array(point, dtype=float)
    g = value(p)
    dg, ddg = np.zeros((4, 4, 4)), np.zeros((4, 4, 4, 4))
    for i in range(3):
        ei = np.eye(3)[i]*step
        dg[i+1] = (value(p+ei)-value(p-ei))/(2*step)
        ddg[i+1, i+1] = (value(p+ei)-2*g+value(p-ei))/step**2
        for j in range(i):
            ej = np.eye(3)[j]*step
            mixed = (value(p+ei+ej)-value(p+ei-ej)-value(p-ei+ej)+value(p-ei-ej))/(4*step**2)
            ddg[i+1, j+1] = ddg[j+1, i+1] = mixed
    return g, dg, ddg


class WarpTensorTests(unittest.TestCase):
    def test_independent_exact_spacetime_benchmarks(self):
        self.assertTrue(tensor.tensor_benchmarks()["passed"])

    def test_minkowski_limit_complete_tensor(self):
        m = AlcubierreReference(1, .2, 0)
        for p in ((0, 0, 0), (0, 1, 0), (.6, .8, 0)):
            g, dg, ddg, e = tensor.comoving_metric(m, p)
            result = tensor.curvature(g, dg, ddg)
            np.testing.assert_array_equal(result["stress_covariant"], np.zeros((4, 4)))
            self.assertEqual(result["kretschmann"], 0)

    def test_tetrad_and_riemann_symmetries(self):
        m = AlcubierreReference(1, .125, 1.1)
        g, dg, ddg, e = tensor.comoving_metric(m, (.6, .8, 0))
        np.testing.assert_allclose(e.T@g@e, np.diag([-1, 1, 1, 1]), atol=1e-14)
        result = tensor.curvature(g, dg, ddg)
        r = result["riemann_covariant"]
        np.testing.assert_allclose(r, -r.swapaxes(0, 1), atol=1e-12)
        np.testing.assert_allclose(r, -r.swapaxes(2, 3), atol=1e-12)
        np.testing.assert_allclose(r, r.transpose(2, 3, 0, 1), atol=1e-12)
        np.testing.assert_allclose(r+r.transpose(0, 2, 3, 1)+r.transpose(0, 3, 1, 2), 0, atol=1e-12)
        np.testing.assert_allclose(result["stress_covariant"], result["stress_covariant"].T, atol=1e-12)

    def test_full_tensor_against_independent_finite_differences(self):
        m = AlcubierreReference(1, .2, 1.1)
        for p in ((.6, .8, 0), (0, 0, 0), (0, 1, 0)):
            with self.subTest(point=p):
                exact = tensor.curvature(*tensor.comoving_metric(m, p)[:3])["stress_covariant"]
                coarse = tensor.curvature(*numerical_metric_derivatives(m, p, .0004))["stress_covariant"]
                fine = tensor.curvature(*numerical_metric_derivatives(m, p, .0002))["stress_covariant"]
                self.assertLess(np.max(np.abs(fine-exact)), 2e-6)
                self.assertLess(np.max(np.abs(fine-exact)), np.max(np.abs(coarse-exact)))

    def test_numerical_covariant_conservation(self):
        m = AlcubierreReference(1, .2, 1.1)
        p = np.array([.6, .8, 0.])
        def raised(point):
            g, dg, ddg, _ = tensor.comoving_metric(m, point)
            r = tensor.curvature(g, dg, ddg)
            inverse = np.linalg.inv(g)
            return inverse@r["stress_covariant"]@inverse, r["christoffel"]
        t, gamma = raised(p)
        divergence = np.zeros(4)
        for i in range(3):
            delta = np.eye(3)[i]*.00002
            divergence += (raised(p+delta)[0][i+1]-raised(p-delta)[0][i+1])/.00004
        divergence += np.einsum('mml,ln->n', gamma, t)+np.einsum('nml,ml->n', gamma, t)
        np.testing.assert_allclose(divergence, 0, atol=1e-6)

    def test_full_tensor_and_tidal_length_scaling(self):
        a = tensor.point_tensor(AlcubierreReference(1, .2, 1.1), (.6, .8, 0))
        b = tensor.point_tensor(AlcubierreReference(2, .4, 1.1), (1.2, 1.6, 0))
        np.testing.assert_allclose(b["stress_eulerian_times_L0_squared"], np.array(a["stress_eulerian_times_L0_squared"])/4, atol=1e-12)
        np.testing.assert_allclose(b["tidal_eulerian_times_L0_squared"], np.array(a["tidal_eulerian_times_L0_squared"])/4, atol=1e-12)
        self.assertAlmostEqual(b["kretschmann_times_L0_fourth"], a["kretschmann_times_L0_fourth"]/16)

    def test_observer_sampling_finds_violations_without_claiming_proof(self):
        m = AlcubierreReference(1, .2, 1.1)
        t = tensor.point_tensor(m, (0, 1, 0))["stress_eulerian_times_L0_squared"]
        witnesses = tensor.observer_witnesses(t)
        for name in ('null_energy_condition', 'weak_energy_condition'):
            w = witnesses[name]
            self.assertEqual(w["status"], "VIOLATION_FOUND")
            v = w["observer_in_eulerian_frame"]
            norm = -v[0]**2+sum(x*x for x in v[1:])
            self.assertAlmostEqual(norm, 0 if name == 'null_energy_condition' else -1)
        self.assertEqual(tensor.observer_witnesses(np.zeros((4, 4)))["weak_energy_condition"]["status"], "NOT_ESTABLISHED")

    def test_reference_comparison_cannot_slow_or_shrink(self):
        state, report = search.run_reference_search({}, 42)
        self.assertEqual(report["comparison_constraints"]["target_betas"], [.8, 1.1])
        for g in report["groups"]:
            for p in g["profiles"]:
                self.assertEqual(p["target_beta"], g["target_beta"])
                self.assertEqual(p["radius_over_L0"], 1)
                self.assertFalse(p["physical_feasibility_established"])
                if p["eligible_for_reference_selection"]:
                    self.assertGreaterEqual(p["interior_shape_at_half_radius"], .99)
                    self.assertTrue(p["numerics"]["converged"])
                    self.assertEqual(p["sampled_energy_conditions"]["weak_energy_condition"]["status"], "VIOLATION_FOUND")
            self.assertGreater(g["energy_integral_reduction_vs_reference"], 0)
        next_state, next_report = search.run_reference_search(state, 43)
        self.assertEqual(next_state["generation"], 2)
        self.assertTrue(next_report["tensor_benchmarks"]["passed"])

    def test_thick_wall_cannot_erase_interior_region(self):
        p = search.measure_profile(.78, 1.1)
        self.assertFalse(p["eligible_for_reference_selection"])
        self.assertIn("INTERIOR_SHAPE_CONSTRAINT_FAILED", p["rejection_reasons"])
        self.assertNotIn("objectives_to_minimize", p)

    def test_pareto_preserves_tradeoffs_and_rejects_invalid(self):
        def row(a, b, valid=True):
            return {"eligible_for_reference_selection": valid, "objectives_to_minimize": {"energy": a, "tides": b}}
        first, second, dominated, invalid = row(1, 2), row(2, 1), row(3, 3), row(0, 0, False)
        self.assertEqual(search.pareto_front([first, second, dominated, invalid]), [first, second])

    def test_benchmark_failure_prevents_generation(self):
        with patch.object(search, "tensor_benchmarks", return_value={"passed": False}):
            with self.assertRaises(RuntimeError):
                arena.run_generation({}, 8, 42)

    def test_invalid_parent_state_is_rejected(self):
        for parents in ([math.nan], [True], [0], [2], 'invalid'):
            with self.assertRaises(ValueError):
                search.run_reference_search({"champion_wall_scales": parents}, 42)

    def test_reference_track_does_not_change_original_champions(self):
        s, r = arena.run_generation({}, 8, 42)
        with patch.object(arena, "run_reference_search", return_value=({}, {})):
            control, cr = arena.run_generation({}, 8, 42)
        self.assertEqual(s["champions"], control["champions"])
        self.assertEqual(r["top_candidates"], cr["top_candidates"])
        self.assertEqual(s["reference_search"]["generation"], 1)
        self.assertFalse(r["fixed_target_research"]["affects_heuristic_selection"])
        self.assertTrue(r["fixed_target_research"]["affects_reference_profile_selection"])
        self.assertFalse(s["production_promoted"])


if __name__ == '__main__':
    unittest.main()
