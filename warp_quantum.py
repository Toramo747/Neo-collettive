# SPDX-License-Identifier: BUSL-1.1
"""Quantum constraints on the Alcubierre reference metric (semiclassical layer).

General relativity alone says *what* stress-energy a warp bubble needs. Quantum
field theory says how much negative energy is allowed, where, and for how long.
This module applies the Ford–Roman quantum inequality (QI) to the Alcubierre
tanh profile used by warp_physics, reproducing the Pfenning & Ford (1997)
argument (gr-qc/9702026):

* QI for a massless scalar field, Lorentzian sampling time tau0, flat-space
  approximation (requires c*tau0 << local curvature scale, here the wall w):
      <rho> >= -3 hbar c / (32 pi^2 (c tau0)^4)
* Peak Eulerian density of the tanh profile (warp_physics.density, equator):
      rho = - c^4/G * beta^2 * f'(R)^2 / (32 pi),  f'(R) -> 1/(2w) for thin walls
* Requiring the bubble's need not to exceed the QI bound with c*tau0 = alpha*w
  gives a maximum wall thickness:
      w_max = L_P * 2*sqrt(3/pi) / (alpha^2 * beta)
* Total Eulerian energy for thin walls (exact limit of warp_physics
  energy_integral for the tanh profile):  E = -beta^2 R^2 / (36 w)  [G=c=1]

Every number here is an order-of-magnitude reference reproduction, not a design
input. Semiclassical instability (Finazzi, Liberati, Barcelo 2009,
arXiv:0904.0141) is reported as a literature flag for superluminal speeds;
it is not computed.
"""
from __future__ import annotations

import math

from warp_physics import AlcubierreReference, energy_integral

HBAR = 1.054571817e-34      # J s
C = 299_792_458.0           # m / s
G = 6.67430e-11             # m^3 / (kg s^2)
PLANCK_LENGTH = math.sqrt(HBAR * G / C**3)   # ~1.616e-35 m
KG_PER_GEOMETRIC_METER = C**2 / G            # mass of 1 m in G=c=1 units
SUN_MASS_KG = 1.98847e30
OBSERVABLE_UNIVERSE_ORDINARY_MASS_KG = 1.5e53  # order of magnitude
THIN_WALL_ENERGY_CONSTANT = 1.0 / 36.0         # E = -k beta^2 R^2 / w
DEFAULT_ALPHA = 0.1                            # c*tau0 = alpha * w (sampling well inside the wall)
SOURCES = {
    "quantum_inequality": "https://arxiv.org/abs/gr-qc/9702026",
    "semiclassical_instability": "https://arxiv.org/abs/0904.0141",
    "metric": "https://arxiv.org/abs/gr-qc/0009013",
}


def qi_bound_si(sampling_length_m: float) -> float:
    """Magnitude of the Ford–Roman bound, J/m^3, for c*tau0 = sampling_length_m."""
    return 3 * HBAR * C / (32 * math.pi**2 * sampling_length_m**4)


def peak_required_density_si(wall_m: float, beta: float) -> float:
    """Magnitude of the peak Eulerian density the thin-wall bubble needs, J/m^3."""
    fprime = 1.0 / (2.0 * wall_m)
    return C**4 / G * beta**2 * fprime**2 / (32 * math.pi)


def max_wall_m(beta: float, alpha: float = DEFAULT_ALPHA) -> float:
    """Thickest wall compatible with the QI (closed form of the two functions above)."""
    if beta <= 0:
        return math.inf
    return PLANCK_LENGTH * 2 * math.sqrt(3 / math.pi) / (alpha**2 * beta)


def thin_wall_energy_kg(radius_m: float, wall_m: float, beta: float) -> float:
    """Magnitude of the Eulerian negative energy, expressed as a mass (kg)."""
    return THIN_WALL_ENERGY_CONSTANT * beta**2 * radius_m**2 / wall_m * KG_PER_GEOMETRIC_METER


def verify_thin_wall_constant() -> dict:
    """Check E = -beta^2 R^2/(36 w) against warp_physics' numerical integral."""
    rows = []
    for w in (0.08, 0.1, 0.125):
        m = AlcubierreReference(1.0, w, 1.0)
        numeric = energy_integral(m, intervals=4096)
        analytic = -THIN_WALL_ENERGY_CONSTANT * 1.0 / w
        rows.append({"wall_over_R": w, "numeric": numeric, "thin_wall": analytic,
                     "relative_difference": abs(numeric - analytic) / abs(analytic)})
    # Corrections are O(w/R): the agreement must improve as walls get thinner.
    diffs = [r["relative_difference"] for r in rows]
    return {"rows": rows, "improves_as_wall_thins": diffs[0] < diffs[-1], "max_relative_difference": max(diffs)}


def assess(radius_m: float, wall_m: float, beta: float, alpha: float = DEFAULT_ALPHA) -> dict:
    """Quantum verdict for one bubble with physical size."""
    need = peak_required_density_si(wall_m, beta)
    allowed = qi_bound_si(alpha * wall_m)
    w_max = max_wall_m(beta, alpha)
    e_at_wmax = thin_wall_energy_kg(radius_m, w_max, beta) if math.isfinite(w_max) else 0.0
    return {
        "radius_m": radius_m, "wall_m": wall_m, "beta": beta, "alpha": alpha,
        "required_over_qi_bound": need / allowed,
        "verdict": "QI_FORBIDDEN" if need > allowed else "QI_COMPATIBLE",
        "qi_max_wall_m": w_max,
        "qi_max_wall_planck_lengths": w_max / PLANCK_LENGTH,
        "negative_energy_at_qi_wall_kg": e_at_wmax,
        "negative_energy_at_qi_wall_sun_masses": e_at_wmax / SUN_MASS_KG,
        "negative_energy_at_qi_wall_vs_universe_ordinary_mass": e_at_wmax / OBSERVABLE_UNIVERSE_ORDINARY_MASS_KG,
        "semiclassical_instability_flag": beta >= 1.0,
        "physical_feasibility_established": False,
    }


def feasibility_map(radii_m=(1.0, 100.0, 1000.0), betas=(0.1, 0.5, 0.8, 0.99, 1.1),
                    wall_fraction: float = 0.1, alpha: float = DEFAULT_ALPHA) -> dict:
    rows = [assess(r, wall_fraction * r, b, alpha) for r in radii_m for b in betas]
    return {
        "version": "ford-roman-qi-alcubierre-v1",
        "sources": SOURCES,
        "wall_fraction_of_radius": wall_fraction,
        "rows": rows,
        "any_qi_compatible_macroscopic_bubble": any(x["verdict"] == "QI_COMPATIBLE" for x in rows),
        "thin_wall_check": verify_thin_wall_constant(),
        "limitations": [
            "Massless scalar field QI in the flat-space limit; other fields and curved-space corrections differ by O(1) factors",
            "Peak Eulerian density only; other observers see different densities",
            "Order-of-magnitude reproduction of Pfenning & Ford (1997), not a new result",
            "Semiclassical instability (superluminal) cited, not computed",
        ],
        "affects_selection": False,
        "physical_feasibility_established": False,
    }
