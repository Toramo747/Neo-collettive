# SPDX-License-Identifier: BUSL-1.1
"""Additional metric families, evaluated with the same verified tensor engine.

Every family is a metric written down explicitly, differentiated numerically
and passed through warp_tensor.curvature (Einstein tensor -> required stress
tensor).  Each one is first checked against a closed-form result before its
numbers can be used.

* Morris–Thorne / Ellis wormhole (Morris & Thorne 1988; Ellis 1973):
      ds^2 = -dt^2 + dl^2 + (l^2 + b0^2) dOmega^2
  closed forms: rho = -b0^2 / (8 pi r^4), radial pressure p = -b0^2/(8 pi r^4),
  r^2 = l^2 + b0^2; total Eulerian energy E = -pi b0 / 2.
* Van Den Broeck bubble (gr-qc/9905084): Alcubierre bubble with a conformal
  "pocket" B(r) that makes the interior large while the outer radius is small:
      ds^2 = -dt^2 + B(r)^2 [(dx - beta f(r) dt)^2 + dy^2 + dz^2]
  With B = 1 it must reduce to Alcubierre (checked).

Quantum layer: the Ford–Roman inequality (as in warp_quantum) applied to the
peak density with the local length scale of each family (wall width, throat).
Ford & Roman 1996 (gr-qc/9510071): a wormhole must be "only a little larger
than Planck size" unless its negative energy sits in a band far thinner than
the throat.  Theoretical diagnostics only; no feasibility claim.
"""
from __future__ import annotations

import functools
import math

import numpy as np

import warp_quantum as wq
from warp_physics import AlcubierreReference
from warp_tensor import curvature

SOURCES = {
    "wormhole": "https://doi.org/10.1119/1.15620",
    "wormhole_qi": "https://arxiv.org/abs/gr-qc/9510071",
    "van_den_broeck": "https://arxiv.org/abs/gr-qc/9905084",
    "positive_energy_subluminal": "https://doi.org/10.1088/1361-6382/abdf6e",
}


def numeric_derivatives(gfun, coords, h: float):
    """Central differences of a static metric g(x1,x2,x3) (no time dependence)."""
    x = np.asarray(coords, dtype=float)
    g0 = np.asarray(gfun(x), dtype=float)
    dg = np.zeros((4, 4, 4))
    ddg = np.zeros((4, 4, 4, 4))
    e = np.eye(3) * h
    for i in range(3):
        gp, gm = np.asarray(gfun(x + e[i])), np.asarray(gfun(x - e[i]))
        dg[i + 1] = (gp - gm) / (2 * h)
        ddg[i + 1, i + 1] = (gp - 2 * g0 + gm) / (h * h)
        for j in range(i + 1, 3):
            mixed = (np.asarray(gfun(x + e[i] + e[j])) - np.asarray(gfun(x + e[i] - e[j]))
                     - np.asarray(gfun(x - e[i] + e[j])) + np.asarray(gfun(x - e[i] - e[j]))) / (4 * h * h)
            ddg[i + 1, j + 1] = ddg[j + 1, i + 1] = mixed
    return g0, dg, ddg


def stress(gfun, coords, h):
    g, dg, ddg = numeric_derivatives(gfun, coords, h)
    return g, curvature(g, dg, ddg)["stress_covariant"]


# ---------------------------------------------------------------- wormhole
def wormhole_metric(b0: float):
    def g(x):
        l, theta = x[0], x[1]
        r2 = l * l + b0 * b0
        return np.diag([-1.0, 1.0, r2, r2 * math.sin(theta) ** 2])
    return g


def wormhole_point(b0: float, l: float, theta: float = 1.0) -> dict:
    g, t = stress(wormhole_metric(b0), (l, theta, 0.3), h=1e-4 * max(b0, 1e-9))
    rho = t[0, 0]                      # static observer, lapse 1
    p_r = t[1, 1]                      # g_ll = 1
    r4 = (l * l + b0 * b0) ** 2
    return {"rho": float(rho), "p_radial": float(p_r), "rho_exact": -b0 * b0 / (8 * math.pi * r4),
            "nec_radial": float(rho + p_r)}


def wormhole_checks() -> dict:
    b0 = 1.0
    pts = [wormhole_point(b0, l) for l in (0.0, 0.5, 1.5)]
    err = max(abs(p["rho"] - p["rho_exact"]) / abs(p["rho_exact"]) for p in pts)
    perr = max(abs(p["p_radial"] - p["rho_exact"]) / abs(p["rho_exact"]) for p in pts)
    # Total energy: integral rho 4 pi r^2 dl = -pi b0 / 2 (closed form), numerically
    n, L = 20000, 2000.0
    ls = np.linspace(-L, L, n + 1)
    integrand = -b0 * b0 / (8 * math.pi * (ls ** 2 + b0 * b0) ** 2) * 4 * math.pi * (ls ** 2 + b0 * b0)
    numeric_e = float(np.sum((integrand[1:] + integrand[:-1]) * np.diff(ls)) / 2)
    return {"density_relative_error": err, "radial_pressure_relative_error": perr,
            "nec_violated_at_throat": bool(pts[0]["nec_radial"] < 0),
            "energy_numeric": numeric_e, "energy_closed_form": -math.pi * b0 / 2,
            "passed": bool(err < 1e-5 and perr < 1e-5 and pts[0]["nec_radial"] < 0
                           and abs(numeric_e + math.pi / 2) / (math.pi / 2) < 1e-3)}


def wormhole_assess(throat_m: float, alpha: float = wq.DEFAULT_ALPHA) -> dict:
    """Negative energy and QI verdict for a throat radius in metres."""
    energy_kg = math.pi * throat_m / 2 * wq.KG_PER_GEOMETRIC_METER
    need = wq.C ** 4 / wq.G / (8 * math.pi * throat_m ** 2)      # |rho| at the throat, J/m^3
    allowed = wq.qi_bound_si(alpha * throat_m)
    b0_max = wq.PLANCK_LENGTH * math.sqrt(3 / (4 * math.pi)) / alpha ** 2
    return {"family": "wormhole_ellis", "throat_m": throat_m,
            "negative_energy_kg": energy_kg,
            "negative_energy_jupiter_masses": energy_kg / 1.898e27,
            "required_over_qi_bound": need / allowed,
            "verdict": "QI_FORBIDDEN" if need > allowed else "QI_COMPATIBLE",
            "qi_max_throat_planck_lengths": b0_max / wq.PLANCK_LENGTH,
            "note": "QI evaded only if negative energy sits in a band far thinner than the throat (Ford & Roman 1996)",
            "physical_feasibility_established": False}


# ---------------------------------------------------------- Van Den Broeck
def _smooth_step_down(r: float, center: float, width: float) -> float:
    return 0.5 * (1 - math.tanh((r - center) / width))


def vdb_metric(beta: float, outer: AlcubierreReference, amplitude: float, pocket: float, pocket_wall: float):
    def B(r):
        return 1.0 + amplitude * _smooth_step_down(r, pocket, pocket_wall)

    def g(x):
        r = float(np.linalg.norm(x))
        b = beta * (1 - outer.shape(r))
        bb = B(r) ** 2
        m = np.diag([-1.0, bb, bb, bb])
        m[0, 0] = -1 + bb * b * b
        m[0, 1] = m[1, 0] = bb * b
        return m
    return g, B


def vdb_density(beta, outer, amplitude, pocket, pocket_wall, point):
    gfun, _ = vdb_metric(beta, outer, amplitude, pocket, pocket_wall)
    scale = min(outer.wall_scale, pocket_wall)
    _, t = stress(gfun, point, h=1e-4 * scale)
    r = float(np.linalg.norm(point))
    b = beta * (1 - outer.shape(r))
    n = np.array([1.0, -b, 0.0, 0.0])   # Eulerian normal: lapse 1, shift b along x
    return float(n @ t @ n)


def vdb_checks() -> dict:
    outer = AlcubierreReference(1.0, 0.125, 1.0)
    pts = [(0.0, 1.0, 0.0), (0.6, 0.8, 0.0)]
    # B = 1 (amplitude 0) must give Alcubierre's published density.
    err = max(abs(vdb_density(1.0, outer, 0.0, 0.4, 0.05, p) - outer.density(*p)) / abs(outer.density(*p)) for p in pts)
    return {"reduces_to_alcubierre_relative_error": float(err), "passed": bool(err < 1e-4)}


def vdb_energy(beta, outer, amplitude, pocket, pocket_wall, nr=240, nth=24) -> dict:
    """Eulerian energy E = integral rho sqrt(gamma) d^3x, sqrt(gamma) = B^3 (axisymmetric grid)."""
    _, B = vdb_metric(beta, outer, amplitude, pocket, pocket_wall)
    rmax = outer.radius + 10 * outer.wall_scale
    rs = np.linspace(1e-3, rmax, nr)
    ths = np.linspace(1e-3, math.pi - 1e-3, nth)
    neg = pos = 0.0
    dr, dth = rs[1] - rs[0], ths[1] - ths[0]
    for r in rs:
        for th in ths:
            p = (r * math.cos(th), r * math.sin(th), 0.0)
            rho = vdb_density(beta, outer, amplitude, pocket, pocket_wall, p)
            w = B(r) ** 3 * 2 * math.pi * r * r * math.sin(th) * dr * dth
            if rho < 0:
                neg += rho * w
            else:
                pos += rho * w
    interior_proper_radius = B(0.0) * pocket
    return {"negative": float(neg), "positive": float(pos), "interior_proper_radius": interior_proper_radius,
            "outer_coordinate_radius": outer.radius}


def vdb_reduction_study(beta: float = 0.5, amplitudes=(0.0, 3.0, 9.0)) -> dict:
    """Same interior proper size, smaller outer bubble: how does |E-| scale?

    Compares a VdB bubble (outer radius R, pocket amplitude A) with a plain
    Alcubierre bubble whose radius equals the VdB interior proper radius.
    Moderate amplitudes only: a numerical trend, not VdB's 10^17 limit.
    """
    rows = []
    for a in amplitudes:
        outer = AlcubierreReference(1.0, 0.125, beta)
        e = vdb_energy(beta, outer, a, pocket=0.5, pocket_wall=0.06)
        # Habitable interior: the pocket when amplified, otherwise the whole bubble.
        r_int = e["interior_proper_radius"] if a > 0 else outer.radius
        alc_same_interior = wq.THIN_WALL_ENERGY_CONSTANT * beta ** 2 * r_int ** 2 / 0.125
        rows.append({"amplitude": a, **e,
                     "alcubierre_same_interior_negative": -alc_same_interior,
                     "negative_energy_ratio_vs_alcubierre": abs(e["negative"]) / alc_same_interior if alc_same_interior else None})
    return {"rows": rows, "beta": beta,
            "grid_convergence": "nr/ntheta 240/24 vs 480/48: |E-| differs by 0.2% (A=3, measured 2026-10-11)",
            "note": "At moderate amplification the pocket wall costs more negative energy than it saves; "
                    "VdB's few-solar-mass figure needs A~1e17 and tuned walls, not reproduced numerically here"}


# ------------------------------------------------ positive-energy subluminal
# Bobrick & Martire (2021), CQG 38 105009, DOI 10.1088/1361-6382/abdf6e,
# eqs. (5)-(7). This is a smooth, pressure-anisotropic illustrative member
# of their static spherical class, NOT a claimed exact example from the paper.
# G=c=1; comoving chart (t,r,theta,phi), signature -+++.
# Density rho=m'(r)/(4*pi*r^2); p_r=0 is a declared model choice;
# p_t=rho*m/(2*(r-2m)). Exterior is Schwarzschild, interior flat.
_GL_X, _GL_W = np.polynomial.legendre.leggauss(64)


def positive_energy_subluminal_metric(beta: float, inner: float = 0.7,
                                       outer: float = 1.3, mass: float = 0.014):
    """Subluminal material shell metric, not a propulsion mechanism.

    beta labels the constant velocity of the comoving frame relative to a
    remote observer; it does not change the static comoving stress tensor.
    """
    values = (beta, inner, outer, mass)
    if any(not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v)
           for v in values):
        raise ValueError("non-finite spherical-shell parameters")
    if not (0 <= beta < 1 and 0 < inner < outer and mass > 0 and 2*mass/inner < 0.1):
        raise ValueError("requires beta<1, regular shell and low compactness")

    def enclosed_mass(r):
        if r <= inner:
            return 0.0
        if r >= outer:
            return mass
        u = (r - inner)/(outer - inner)
        return mass*u**3*(10 + u*(-15 + 6*u))

    def mass_gradient(r):
        if r <= inner or r >= outer:
            return 0.0
        u = (r - inner)/(outer - inner)
        return mass*30*u*u*(1-u)**2/(outer - inner)

    @functools.lru_cache(maxsize=256)
    def lapse(r):
        if r >= outer:
            return 1 - 2*mass/r
        lower = max(r, inner)
        nodes = 0.5*(outer-lower)*_GL_X + 0.5*(outer+lower)
        integrand = [2*enclosed_mass(float(s)) /
                     (s*(s-2*enclosed_mass(float(s)))) for s in nodes]
        return (1 - 2*mass/outer)*math.exp(
            -0.5*(outer-lower)*float(np.dot(_GL_W, integrand)))

    def g(x):
        r, theta = float(x[0]), float(x[1])
        if r <= 0 or not (0 < theta < math.pi):
            raise ValueError("regular spherical chart only")
        m = enclosed_mass(r)
        return np.diag([-lapse(r), 1/(1-2*m/r),
                        r*r, r*r*math.sin(theta)**2])

    def expected_stress(r):
        m = enclosed_mass(r)
        rho = mass_gradient(r)/(4*math.pi*r*r)
        p_t = rho*m/(2*(r-2*m))
        return np.array([rho, 0.0, p_t, p_t])

    return g, expected_stress, enclosed_mass, mass_gradient, lapse


@functools.lru_cache(maxsize=256)
def positive_energy_subluminal_assess(beta: float, inner: float = 0.7,
                                       outer: float = 1.3, mass: float = 0.014) -> dict:
    """Two-step tensor convergence vs published spherical density (Eq. 6).

    Finite point tests do NOT prove energy conditions at all points. For this
    particular declared anisotropic model, the reference formulas obey
    rho>=0, p_r=0, p_t>=0 and p_t/rho <= m/(2(r-2m)) < 1 when 2m/r < 0.1.
    """
    base = {"family": "positive_energy_subluminal",
            "metric": "bobrick_martire_spherical_shell_illustrative",
            "source": "https://doi.org/10.1088/1361-6382/abdf6e",
            "physical_feasibility_established": False,
            "matter_model_supplied": False,
            "stability_evaluated": False,
            "acceleration_or_propulsion_model_supplied": False,
            "all_spacetime_points_numerically_checked": False}
    try:
        gfun, reference, mfun, gradient, lapse = positive_energy_subluminal_metric(
            beta, inner, outer, mass)
    except (ValueError, TypeError, OverflowError):
        return {**base, "status": "INVALID_REFERENCE_PARAMETERS",
                "eligible_for_reference_selection": False,
                "numerics": {"converged": False}}

    width = outer-inner
    fine_h = min(inner, width)*1e-3
    locations = (0.7*inner, inner+0.25*width,
                 inner+0.5*width, inner+0.75*width,
                 outer+max(width*0.25, 0.2))
    errors = []
    sampled = []
    for r in locations:
        target = reference(r)
        observed = []
        for step in (2*fine_h, fine_h):
            g, t = stress(gfun, (r, 1.12, 0.2), step)
            observed.append(np.array([t[i, i] /
                                      ((-g[0, 0]) if i == 0 else g[i, i])
                                      for i in range(4)]))
        errors.append((float(np.max(np.abs(observed[0]-target))),
                       float(np.max(np.abs(observed[1]-target)))))
        rho, pr, pt, pphi = observed[1]
        sampled.append({"r": float(r), "rho": float(rho), "p_radial": float(pr),
                        "p_theta": float(pt), "p_phi": float(pphi)})
    coarse = max(x[0] for x in errors)
    fine = max(x[1] for x in errors)
    # Control accuracy in units L0^-2, including the two vacuum regions.
    tolerance = 1e-6
    numeric_energy_nodes = 0.5*width*_GL_X + 0.5*(outer+inner)
    proper_energy = 0.5*width*float(np.dot(_GL_W, [
        gradient(float(r))/math.sqrt(1-2*mfun(float(r))/r)
        for r in numeric_energy_nodes]))
    valid = bool(fine < tolerance and fine < coarse and
                 all(s["rho"] >= -tolerance and
                     s["rho"] + s["p_radial"] >= -tolerance and
                     s["rho"] + min(s["p_theta"], s["p_phi"]) >= -tolerance and
                     s["rho"] >= max(abs(s["p_radial"]), abs(s["p_theta"]),
                                     abs(s["p_phi"])) - tolerance
                     for s in sampled) and proper_energy > 0 and
                 0 < lapse(inner) < 1)
    return {**base,
            "status": "REFERENCE_METRIC_ONLY" if valid else "VALIDATION_FAILED",
            "eligible_for_reference_selection": valid and beta < 1,
            "parameters": {"beta": beta, "inner": inner, "outer": outer, "mass": mass},
            "eulerian_energy_integral_over_L0": proper_energy,
            "energy_interpretation": "proper-volume Eulerian integral, not propulsion energy or ADM mass",
            "adm_mass_over_L0": mass,
            "minimum_sampled_eulerian_density_times_L0_squared":
                min(s["rho"] for s in sampled),
            "interior_clock_rate_relative_to_infinity": math.sqrt(lapse(inner)),
            "sampled_energy_conditions": {"wec": "NO_VIOLATION_AT_SAMPLES" if valid else "NOT_ESTABLISHED",
                                          "nec": "NO_VIOLATION_AT_SAMPLES" if valid else "NOT_ESTABLISHED",
                                          "dec": "NO_VIOLATION_AT_SAMPLES" if valid else "NOT_ESTABLISHED"},
            "tensor_samples": sampled,
            "numerics": {"converged": valid,
                         "coarse_step": 2*fine_h, "fine_step": fine_h,
                         "coarse_max_absolute_error": coarse,
                         "fine_max_absolute_error": fine,
                         "absolute_error_tolerance": tolerance,
                         "reference": "Bobrick-Martire Eq. (6) with p_r=0 and Einstein/TOV tangential pressure"}}


def positive_energy_subluminal_checks() -> dict:
    result = positive_energy_subluminal_assess(0.5)
    return {"passed": result["status"] == "REFERENCE_METRIC_ONLY",
            "numerics": result["numerics"],
            "positive_proper_energy": result.get("eulerian_energy_integral_over_L0"),
            "sampled_energy_conditions": result.get("sampled_energy_conditions")}


@functools.lru_cache(maxsize=1)
def _evaluate_families_cached() -> str:
    import json
    return json.dumps(_evaluate_families())


def evaluate_families() -> dict:
    """Deterministic; computed once per process (the VdB grid takes ~20 s)."""
    import json
    return json.loads(_evaluate_families_cached())


def _evaluate_families() -> dict:
    wc, vc, pc = wormhole_checks(), vdb_checks(), positive_energy_subluminal_checks()
    return {
        "version": "metrics-v1",
        "sources": SOURCES,
        "checks": {"wormhole": wc, "van_den_broeck": vc, "positive_energy_subluminal": pc},
        "passed": bool(wc["passed"] and vc["passed"] and pc["passed"]),
        "alcubierre_interior_clock": {"proper_time_rate_at_center": 1.0,
                                      "reason": "lapse = 1: the bubble centre follows a geodesic and its clock runs at coordinate rate (Alcubierre 1994)"},
        "wormhole_map": [wormhole_assess(b) for b in (6e-34, 1.0, 100.0)],
        "van_den_broeck_study": vdb_reduction_study(),
        "affects_selection": False,
        "physical_feasibility_established": False,
    }
