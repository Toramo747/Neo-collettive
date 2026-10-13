# SPDX-License-Identifier: BUSL-1.1
"""Separate evolutionary reference-profile comparison at fixed transport targets.

Uses existing wall-scale parameter only. No physical feasibility promotion.
The tanh interior/exterior constraints are research conventions, not safety proofs.
"""
from __future__ import annotations

import hashlib
import math
import random

from warp_physics import AlcubierreReference, metric_diagnostics
from warp_tensor import point_tensor, observer_witnesses, tensor_benchmarks

VERSION = "fixed-alcubierre-tensor-v1"
TARGET_BETAS = (.8, 1.1)
BASE_WALLS = (.08, .10, .125, .15, .18, .20, .22, .25)


def sample_points(metric):
    points = [(0., 0., 0.)]
    for radius in (.5, metric.radius-metric.wall_scale, metric.radius,
                   metric.radius+metric.wall_scale, 2.):
        points += [(radius, 0., 0.), (0., radius, 0.),
                   (radius/math.sqrt(2), radius/math.sqrt(2), 0.)]
    return points


def measure_profile(wall: float, beta: float) -> dict:
    metric = AlcubierreReference(1., wall, beta)
    profile_id = hashlib.sha256(f'{VERSION}:{beta:.17g}:{wall:.17g}'.encode()).hexdigest()[:16]
    result = {"profile_id": profile_id, "radius_over_L0": 1., "target_beta": beta,
              "wall_scale_over_L0": wall, "physical_feasibility_established": False,
              "interior_shape_at_half_radius": metric.shape(.5),
              "exterior_shape_at_twice_radius": metric.shape(2.)}
    reasons = []
    if metric.shape(.5) < .99:
        reasons.append("INTERIOR_SHAPE_CONSTRAINT_FAILED")
    if metric.shape(2.) > .01:
        reasons.append("EXTERIOR_SHAPE_CONSTRAINT_FAILED")
    if reasons:
        return {**result, "eligible_for_reference_selection": False, "rejection_reasons": reasons}
    energy = metric_diagnostics(metric)
    tensors = [point_tensor(metric, p) for p in sample_points(metric)]
    density_error = max(abs(t["stress_eulerian_times_L0_squared"][0][0]
                            - metric.density(*t["point_over_L0"])) for t in tensors)
    observers = [observer_witnesses(t["stress_eulerian_times_L0_squared"]) for t in tensors]
    witnesses = {}
    for name in ("null_energy_condition", "weak_energy_condition"):
        i = min(range(len(tensors)), key=lambda i: observers[i][name]["minimum_sampled_contraction"])
        witnesses[name] = {**observers[i][name], "point_over_L0": tensors[i]["point_over_L0"]}
    tidal = [max(abs(v) for row in t["tidal_eulerian_times_L0_squared"] for v in row) for t in tensors]
    interior = [tidal[i] for i, t in enumerate(tensors)
                if sum(x*x for x in t["point_over_L0"]) <= .5**2+1e-14]
    objectives = {"absolute_eulerian_energy_integral_over_L0": abs(energy["eulerian_energy_integral_over_L0"]),
                  "maximum_sampled_tidal_component_times_L0_squared": max(tidal),
                  "maximum_sampled_interior_tidal_component_times_L0_squared": max(interior)}
    if not energy["numerics"]["converged"]:
        reasons.append("ENERGY_QUADRATURE_NOT_CONVERGED")
    if density_error > 1e-9:
        reasons.append("TENSOR_DENSITY_REFERENCE_MISMATCH")
    if not all(math.isfinite(v) for v in objectives.values()):
        reasons.append("NONFINITE_OBJECTIVE")
    # Complete tensor retained at center and three wall directions; summaries use all samples.
    details = [t for t in tensors if abs(math.sqrt(sum(x*x for x in t["point_over_L0"]))-1.) < 1e-12
               or t["point_over_L0"] == [0., 0., 0.]]
    return {**result, "eligible_for_reference_selection": not reasons, "rejection_reasons": reasons,
            "objectives_to_minimize": objectives, "sampled_energy_conditions": witnesses,
            "tensor_samples": details, "tensor_spatial_sample_count": len(tensors),
            "null_observers_per_point": 26, "timelike_observers_per_point": 53,
            "numerics": {**energy["numerics"], "tensor_density_max_absolute_error": density_error},
            "full_required_stress_tensor_computed_at_samples": True,
            "all_spacetime_points_checked": False, "all_observers_checked": False,
            "matter_model_supplied": False, "stability_evaluated": False,
            "causal_structure_evaluated": False, "passenger_safety_established": False}


def pareto_front(rows: list[dict]) -> list[dict]:
    valid = [r for r in rows if r["eligible_for_reference_selection"]]
    def dominates(a, b):
        av, bv = a["objectives_to_minimize"], b["objectives_to_minimize"]
        return all(av[k] <= bv[k] for k in av) and any(av[k] < bv[k] for k in av)
    return [r for r in valid if not any(dominates(other, r) for other in valid)]


def run_reference_search(state: dict, seed: int) -> tuple[dict, dict]:
    benchmarks = tensor_benchmarks()
    if not benchmarks["passed"]:
        raise RuntimeError("full tensor reference checks failed; refusing to publish generation")
    parents = state.get("champion_wall_scales") or [.125, .20]
    if not isinstance(parents, list) or len(parents) > 4 or any(
            not isinstance(x, (float, int)) or isinstance(x, bool)
            or not math.isfinite(x) or not .08 <= x <= 1.25 for x in parents):
        raise ValueError("invalid reference-profile state")
    walls = sorted(set(BASE_WALLS+tuple(parents)))
    rng = random.Random(seed)
    for _ in range(64):
        if len(walls) >= 12:
            break
        walls = sorted(set(walls+[max(.08, min(1.25, rng.choice(parents)*rng.uniform(.85, 1.15)))]))
    walls = walls[:12]
    groups, champions = [], set()
    for beta in TARGET_BETAS:
        rows = [measure_profile(wall, beta) for wall in walls]
        reference = next(r for r in rows if r["wall_scale_over_L0"] == .125)
        front = pareto_front(rows)
        if not front or not reference["eligible_for_reference_selection"]:
            raise RuntimeError("reference search has no valid baseline or comparison")
        energy_key = "absolute_eulerian_energy_integral_over_L0"
        interior_key = "maximum_sampled_interior_tidal_component_times_L0_squared"
        lowest_energy = min(front, key=lambda r: r["objectives_to_minimize"][energy_key])
        lowest_interior_tidal = min(front, key=lambda r: r["objectives_to_minimize"][interior_key])
        champions.update((lowest_energy["wall_scale_over_L0"], lowest_interior_tidal["wall_scale_over_L0"]))
        reference_energy = reference["objectives_to_minimize"][energy_key]
        groups.append({"target_beta": beta, "radius_over_L0": 1., "profile_count": len(rows),
                       "reference_profile_id": reference["profile_id"], "reference": reference,
                       "pareto_profile_ids": [r["profile_id"] for r in front],
                       "lowest_energy_profile_id": lowest_energy["profile_id"],
                       "energy_integral_reduction_vs_reference": 1-lowest_energy["objectives_to_minimize"][energy_key]/reference_energy,
                       "selection_basis": "Pareto: energy integral, sampled wall tides, sampled interior tides",
                       "profiles": rows})
    next_state = {"schema_v": 1, "generation": int(state.get("generation", 0))+1,
                  "champion_wall_scales": sorted(champions)}
    report = {"version": VERSION, "generation": next_state["generation"], "tensor_benchmarks": benchmarks,
              "sources": ["https://arxiv.org/abs/gr-qc/0009013", "https://arxiv.org/abs/2404.03095",
                          "https://arxiv.org/abs/2602.16495"],
              "affects_heuristic_selection": False, "affects_reference_profile_selection": True,
              "comparison_constraints": {"radius_over_L0": 1., "target_betas": list(TARGET_BETAS),
                                          "interior_radius_over_L0": .5, "minimum_interior_shape": .99,
                                          "exterior_radius_over_L0": 2., "maximum_exterior_shape": .01},
              "groups": groups, "physical_feasibility_established": False,
              "limitations": ["Required stress tensor derived from geometry; no realizable source supplied",
                              "Constant speed only; no creation, acceleration, braking or dynamic stability",
                              "Finite spatial and observer sampling does not prove energy conditions or safety",
                              "Shape constraints are declared research conventions, not flatness or transport proofs",
                              "Geometric units without a chosen physical size; no joules or engineering power estimate",
                              "Alcubierre tanh profile comparison only; no new metric discovery"]}
    return next_state, report
