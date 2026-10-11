"""Wormhole and Van Den Broeck families: closed-form checks and literature orders."""
import math
import unittest

import warp_metrics as m
import warp_quantum as q
from warp_physics import AlcubierreReference


class WormholeTests(unittest.TestCase):
    def test_numeric_tensor_matches_closed_form(self):
        c = m.wormhole_checks()
        self.assertTrue(c["passed"], c)
        self.assertTrue(c["nec_violated_at_throat"])

    def test_one_metre_throat_needs_about_a_jupiter_mass(self):
        a = m.wormhole_assess(1.0)
        self.assertTrue(0.5 < a["negative_energy_jupiter_masses"] < 2.0)
        self.assertEqual(a["verdict"], "QI_FORBIDDEN")

    def test_qi_allows_only_planck_scale_throats(self):
        a = m.wormhole_assess(1.0)
        self.assertTrue(10 < a["qi_max_throat_planck_lengths"] < 100)
        self.assertEqual(m.wormhole_assess(0.5 * a["qi_max_throat_planck_lengths"] * q.PLANCK_LENGTH)["verdict"], "QI_COMPATIBLE")


class VanDenBroeckTests(unittest.TestCase):
    def test_reduces_to_alcubierre_when_pocket_is_flat(self):
        self.assertTrue(m.vdb_checks()["passed"])

    def test_pocket_enlarges_interior(self):
        outer = AlcubierreReference(1.0, 0.125, 0.5)
        _, B = m.vdb_metric(0.5, outer, 9.0, 0.5, 0.06)
        self.assertAlmostEqual(B(0.0) * 0.5, 5.0, places=2)

    def test_energy_grid_small_runs(self):
        outer = AlcubierreReference(1.0, 0.125, 0.5)
        e = m.vdb_energy(0.5, outer, 0.0, 0.5, 0.06, nr=60, nth=8)
        self.assertLess(e["negative"], 0)
        self.assertAlmostEqual(e["negative"], -0.0558, delta=0.01)  # plain Alcubierre at beta=0.5
