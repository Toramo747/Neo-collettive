# SPDX-License-Identifier: BUSL-1.1
"""Bounded Alcubierre reference diagnostics; never a feasibility or fitness gate.

Alcubierre (1994), https://arxiv.org/abs/gr-qc/0009013, equations 6, 8,
10 and 19. Signature -+++, G=c=1, unit lapse, Euclidean spatial slices.
Only the Eulerian energy density is evaluated, not the full stress tensor.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

SOURCE = "https://arxiv.org/abs/gr-qc/0009013"
VERSION = "alcubierre-eulerian-v1"


@dataclass(frozen=True)
class AlcubierreReference:
    radius: float
    wall_scale: float
    beta: float

    def __post_init__(self):
        if not all(math.isfinite(v) for v in (self.radius, self.wall_scale, self.beta)):
            raise ValueError("non-finite reference parameters")
        # Bounded numerical domain includes every current arena candidate.
        if not (0.5 <= self.radius <= 3.0 and 0.08 <= self.wall_scale <= 1.25
                and abs(self.beta) <= 1.5):
            raise ValueError("parameters outside validated reference domain")

    def shape(self, r: float) -> float:
        s = 1.0 / self.wall_scale
        return (math.tanh(s * (r + self.radius)) - math.tanh(s * (r - self.radius))) / (2 * math.tanh(s * self.radius))

    def shape_derivative(self, r: float) -> float:
        def sech_squared(z):
            e = math.exp(-2 * abs(z))
            return 4 * e / (1 + e) ** 2
        s = 1.0 / self.wall_scale
        return s * (sech_squared(s * (r + self.radius)) - sech_squared(s * (r - self.radius))) / (2 * math.tanh(s * self.radius))

    def density(self, x: float, y: float, z: float) -> float:
        r = math.sqrt(x*x + y*y + z*z)
        if r == 0:
            return 0.0
        return -self.beta**2 * (y*y + z*z) / r**2 * self.shape_derivative(r)**2 / (32 * math.pi)

    def density_from_constraint(self, point: tuple, step: float) -> float:
        """Independent finite differences of shift, ADM Hamiltonian constraint.

        R^(3)=0; rho=(K^2-K_ij K^ij)/(16 pi), with K_ij from Eq.10.
        """
        gradient = []
        for axis in range(3):
            plus, minus = list(point), list(point)
            plus[axis] += step
            minus[axis] -= step
            def shift(p):
                return -self.beta * self.shape(math.sqrt(sum(v*v for v in p)))
            gradient.append((shift(plus) - shift(minus)) / (2 * step))
        k = [[0.0]*3 for _ in range(3)]
        for i in range(3):
            for j in range(3):
                k[i][j] = ((gradient[j] if i == 0 else 0.0)
                           + (gradient[i] if j == 0 else 0.0)) / 2
        trace = sum(k[i][i] for i in range(3))
        norm = sum(v*v for row in k for v in row)
        return (trace**2 - norm) / (16 * math.pi)


def simpson(function, upper: float, intervals: int) -> float:
    if intervals < 2 or intervals > 8192 or intervals % 2:
        raise ValueError("Simpson intervals must be even, between 2 and 8192")
    h = upper / intervals
    return h / 3 * (function(0) + function(upper) + math.fsum(
        (4 if i % 2 else 2) * function(i*h) for i in range(1, intervals)))


def energy_integral(metric: AlcubierreReference, intervals=1024, tail_walls=12) -> float:
    """Eulerian volume integral, NOT ADM mass or engine energy demand.

    Angular integral of sin^2(theta) is 8*pi/3, hence E=-beta^2/12
    integral r^2 f'(r)^2 dr. Integration is truncated with a tail check.
    """
    upper = metric.radius + tail_walls * metric.wall_scale
    return -metric.beta**2 / 12 * simpson(
        lambda r: r*r * metric.shape_derivative(r)**2, upper, intervals)


def relative_error(a: float, b: float) -> float:
    return abs(a-b) / max(abs(b), 1e-30)


def metric_diagnostics(metric: AlcubierreReference) -> dict:
    fine = energy_integral(metric)
    coarse = energy_integral(metric, intervals=512)
    expanded = energy_integral(metric, tail_walls=16)
    grid_error = relative_error(coarse, fine)
    tail_error = relative_error(expanded, fine)
    upper = metric.radius + 12 * metric.wall_scale
    minimum = min(metric.density(0, upper*i/1024, 0) for i in range(1025))
    return {
        "status": "REFERENCE_METRIC_ONLY",
        "metric": "alcubierre_1994_tanh_unit_lapse",
        "parameters": {"radius": metric.radius, "sigma": 1/metric.wall_scale, "beta": metric.beta},
        "units": "G=c=1; unspecified common length unit L0",
        "eulerian_energy_integral_over_L0": fine,
        "minimum_sampled_eulerian_density_times_L0_squared": minimum,
        "weak_energy_condition": "VIOLATION_FOUND" if minimum < 0 else "NOT_ESTABLISHED",
        "numerics": {
            "radial_intervals": 1024,
            "upper_radius_over_L0": upper,
            "grid_relative_difference": grid_error,
            "tail_extension_relative_difference": tail_error,
            "converged": grid_error < 1e-5 and tail_error < 1e-5,
        },
        "full_stress_tensor_evaluated": False,
        "stability_evaluated": False,
        "causal_structure_evaluated": False,
        "physical_feasibility_established": False,
    }


def reference_checks() -> dict:
    """Analytic controls plus an independent derivative/constraint route."""
    m = AlcubierreReference(1.0, 0.125, 1.0)
    points = [(0, 1, 0), (0.6, 0.8, 0), (0.3, 0.4, math.sqrt(0.75))]
    errors = [relative_error(m.density_from_constraint(p, m.wall_scale*1e-3), m.density(*p)) for p in points]
    refined_errors = [relative_error(m.density_from_constraint(p, m.wall_scale*5e-4), m.density(*p)) for p in points]
    # Separate smooth radial profile: f=exp(-r^2), E=-sqrt(pi)/(32 sqrt(2)).
    gaussian = -simpson(lambda r: 4*r**4*math.exp(-2*r*r), 8, 1024) / 12
    gaussian_exact = -math.sqrt(math.pi) / (32*math.sqrt(2))
    zero = AlcubierreReference(1.0, 0.125, 0.0)
    reference = metric_diagnostics(m)
    checks = {
        "shape_center_normalized": abs(m.shape(0)-1) < 1e-14,
        "minkowski_zero_velocity": zero.density(0, 1, 0) == 0 and energy_integral(zero) == 0,
        "negative_equatorial_density": m.density(0, 1, 0) < 0,
        "hamiltonian_matches_published_density": max(refined_errors) < 1e-5,
        "finite_difference_refinement": max(refined_errors) < max(errors),
        "gaussian_integral_matches_analytic": relative_error(gaussian, gaussian_exact) < 1e-10,
        "reference_integral_converged": reference["numerics"]["converged"],
    }
    return {"passed": all(checks.values()), "checks": checks,
            "max_density_relative_error": max(refined_errors),
            "gaussian_integral_relative_error": relative_error(gaussian, gaussian_exact)}


def evaluate_candidate(parameters: dict) -> dict:
    if parameters.get("family") != "alcubierre_like":
        return {"status": "UNSUPPORTED_GEOMETRY", "reason": "NO_EXPLICIT_METRIC_IMPLEMENTED",
                "physical_feasibility_established": False}
    try:
        metric = AlcubierreReference(float(parameters["bubble_radius"]),
                                    float(parameters["wall_thickness"]),
                                    float(parameters["effective_beta"]))
    except (KeyError, TypeError, ValueError, OverflowError):
        return {"status": "INVALID_REFERENCE_PARAMETERS", "physical_feasibility_established": False}
    result = metric_diagnostics(metric)
    result["mapping"] = {
        "wall_scale": "sigma=1/wall_thickness; modeling convention, not a measured wall width",
        "unmodeled_candidate_parameters": ["shear_control", "lapse_modulation"],
        "candidate_geometry_fully_evaluated": False,
    }
    return result


def evaluate_population(evaluated: list[dict]) -> dict:
    checks = reference_checks()
    if not checks["passed"]:
        raise RuntimeError("warp reference benchmarks failed; refusing to publish generation")
    rows = [{"candidate_id": c["candidate_id"], "family": c["family"],
             "result": evaluate_candidate(c["parameters"])} for c in evaluated]
    return {
        "version": VERSION, "source": SOURCE, "reference_checks": checks,
        "affects_fitness": False, "affects_selection": False,
        "reference_evaluated_count": sum(r["result"]["status"] == "REFERENCE_METRIC_ONLY" for r in rows),
        "unsupported_count": sum(r["result"]["status"] == "UNSUPPORTED_GEOMETRY" for r in rows),
        "invalid_count": sum(r["result"]["status"] == "INVALID_REFERENCE_PARAMETERS" for r in rows),
        "unconverged_count": sum(r["result"].get("numerics", {}).get("converged") is False for r in rows),
        "reference_case": metric_diagnostics(AlcubierreReference(1.0, 0.125, 1.0)),
        "evaluations": rows,
    }
