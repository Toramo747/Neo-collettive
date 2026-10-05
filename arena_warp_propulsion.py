# SPDX-License-Identifier: BUSL-1.1
"""Isolated theoretical warp-propulsion research arena.

This is a hypothesis generator and ranking harness, not an engineering design tool.
It never claims physical feasibility and never writes to production runtime state.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from warp_physics import evaluate_population
from warp_reference_search import run_reference_search

SCHEMA_V = 1
ARENA = "warp-propulsion-research"
MODE = "THEORETICAL_SHADOW"

FAMILIES = (
    "alcubierre_like",
    "natario_like",
    "irrotational_shift",
    "positive_energy_subluminal",
)

@dataclass(frozen=True)
class Candidate:
    family: str
    wall_thickness: float
    bubble_radius: float
    effective_beta: float
    shear_control: float
    lapse_modulation: float

def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()

def _candidate_id(c: Candidate) -> str:
    blob=json.dumps(asdict(c),sort_keys=True,separators=(",",":")).encode()
    return hashlib.sha256(blob).hexdigest()[:16]

def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo,min(hi,v))

def score_candidate(c: Candidate) -> dict:
    """Dimensionless surrogate diagnostics.

    These scores are intentionally conservative heuristics. They are NOT solutions
    of Einstein's equations and MUST NOT be interpreted as evidence of feasibility.
    """
    wall=max(c.wall_thickness,1e-6)
    radius=max(c.bubble_radius,1e-6)
    beta=max(c.effective_beta,0.0)

    curvature=(beta*beta)/(wall*wall) * (1.0 + 0.35*c.lapse_modulation)
    exotic=(beta*beta)*radius*radius/max(wall,1e-6)
    shear=(beta/max(wall,1e-6))*(1.0-c.shear_control)

    family_factor={
        "alcubierre_like":1.00,
        "natario_like":0.84,
        "irrotational_shift":0.58,
        "positive_energy_subluminal":0.25 if beta < 1.0 else 1.20,
    }[c.family]
    exotic*=family_factor

    horizon_risk=_clamp((beta-0.85)/0.55,0.0,1.0)
    causal_risk=_clamp((beta-1.0)/0.50,0.0,1.0)
    stability_risk=_clamp(0.45*math.tanh(curvature/8.0)+0.35*math.tanh(shear/3.0)+0.20*horizon_risk,0.0,1.0)

    exotic_norm=math.tanh(exotic/20.0)
    curvature_norm=math.tanh(curvature/10.0)
    utility=_clamp(beta/1.5,0.0,1.0)

    penalty=(
        0.32*exotic_norm+
        0.24*curvature_norm+
        0.18*stability_risk+
        0.16*horizon_risk+
        0.10*causal_risk
    )
    fitness=_clamp(0.35*utility + 0.65*(1.0-penalty),0.0,1.0)

    hard_flags=[]
    if beta>=1.0:
        hard_flags.append("SUPERLUMINAL_CAUSALITY_UNRESOLVED")
    if causal_risk>0:
        hard_flags.append("CAUSAL_STRUCTURE_REVIEW_REQUIRED")
    if exotic_norm>0.70:
        hard_flags.append("HIGH_EXOTIC_ENERGY_SURROGATE")
    if curvature_norm>0.85:
        hard_flags.append("HIGH_CURVATURE_SURROGATE")
    if stability_risk>0.70:
        hard_flags.append("STABILITY_RISK")

    return {
        "candidate_id":_candidate_id(c),
        "family":c.family,
        "parameters":asdict(c),
        "diagnostics":{
            "exotic_energy_surrogate":round(exotic_norm,6),
            "curvature_surrogate":round(curvature_norm,6),
            "stability_risk":round(stability_risk,6),
            "horizon_risk":round(horizon_risk,6),
            "causal_risk":round(causal_risk,6),
            "effective_beta":round(beta,6),
        },
        "fitness":round(fitness,6),
        "hard_flags":hard_flags,
        "status":"THEORETICAL_ONLY",
    }

def baseline_candidates() -> list[Candidate]:
    return [
        Candidate("alcubierre_like",0.18,1.0,1.10,0.10,0.10),
        Candidate("natario_like",0.24,1.0,1.05,0.25,0.08),
        Candidate("irrotational_shift",0.35,1.0,0.95,0.55,0.06),
        Candidate("positive_energy_subluminal",0.50,1.0,0.75,0.65,0.04),
    ]

def mutate(parent: Candidate, rng: random.Random) -> Candidate:
    family=parent.family if rng.random()<0.82 else rng.choice(FAMILIES)
    return Candidate(
        family=family,
        wall_thickness=_clamp(parent.wall_thickness*rng.uniform(0.75,1.35),0.08,1.25),
        bubble_radius=_clamp(parent.bubble_radius*rng.uniform(0.85,1.20),0.50,3.00),
        effective_beta=_clamp(parent.effective_beta+rng.uniform(-0.18,0.18),0.20,1.50),
        shear_control=_clamp(parent.shear_control+rng.uniform(-0.15,0.15),0.0,1.0),
        lapse_modulation=_clamp(parent.lapse_modulation+rng.uniform(-0.05,0.05),0.0,0.40),
    )

def run_generation(state: dict, population_size: int, seed: int) -> tuple[dict,dict]:
    rng=random.Random(seed)
    previous=[Candidate(**x) for x in state.get("champions",[]) if isinstance(x,dict)]
    parents=previous or baseline_candidates()
    population=list(parents)
    while len(population)<population_size:
        population.append(mutate(rng.choice(parents),rng))

    evaluated=[score_candidate(c) for c in population]
    evaluated.sort(key=lambda x:(len(x["hard_flags"])==0,x["fitness"]),reverse=True)

    safe_pool=[x for x in evaluated if not x["hard_flags"]]
    ranked=safe_pool if safe_pool else evaluated
    champions=ranked[:4]

    generation=int(state.get("generation") or 0)+1
    reference_state,reference_report=run_reference_search(state.get("reference_search") or {},seed)
    next_state={
        "schema_v":SCHEMA_V,
        "arena":ARENA,
        "generation":generation,
        "updated_at_utc":_utc(),
        "champions":[x["parameters"] for x in champions],
        "best_fitness":champions[0]["fitness"] if champions else 0.0,
        "production_promoted":False,
        "reference_search":reference_state,
    }
    report={
        "schema_v":SCHEMA_V,
        "arena":ARENA,
        "mode":MODE,
        "generated_at_utc":_utc(),
        "generation":generation,
        "population":len(evaluated),
        "families":sorted({x["family"] for x in evaluated}),
        "best":champions[0] if champions else None,
        "top_candidates":champions,
        "hard_flagged":sum(bool(x["hard_flags"]) for x in evaluated),
        "physical_evaluation":evaluate_population(evaluated),
        "fixed_target_research":reference_report,
        "boundary":{
            "production_state_write":False,
            "production_runtime_influence":"NONE",
            "automatic_physical_claims":False,
            "automatic_engineering_promotion":False,
            "promotion":"HUMAN_SCIENTIFIC_REVIEW_ONLY",
        },
        "disclaimer":"Original fitness remains heuristic. Separate fixed-target Alcubierre profile research computes required stress tensors and sampled tides/energy-condition violations; no realizable matter source, dynamic validation or evidence of a buildable warp drive.",
    }
    return next_state,report

def main() -> int:
    p=argparse.ArgumentParser()
    p.add_argument("--data-dir",default="data/arena/warp-propulsion")
    p.add_argument("--population",type=int,default=48)
    p.add_argument("--seed",type=int,default=0)
    args=p.parse_args()

    data=Path(args.data_dir)
    data.mkdir(parents=True,exist_ok=True)
    state_path=data/"state.json"
    state={}
    if state_path.is_file():
        try:
            state=json.loads(state_path.read_text(encoding="utf-8"))
        except Exception:
            state={}

    state,report=run_generation(state,max(8,min(args.population,256)),args.seed)
    state_path.write_text(json.dumps(state,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    (data/"latest.json").write_text(json.dumps(report,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    with (data/"history.jsonl").open("a",encoding="utf-8") as fh:
        fh.write(json.dumps({
            "generation":report["generation"],
            "generated_at_utc":report["generated_at_utc"],
            "best_fitness":(report.get("best") or {}).get("fitness"),
            "best_family":(report.get("best") or {}).get("family"),
            "hard_flagged":report["hard_flagged"],
        },separators=(",",":"))+"\n")
    print(json.dumps({
        "arena":ARENA,
        "generation":report["generation"],
        "best":report.get("best"),
        "hard_flagged":report["hard_flagged"],
    },separators=(",",":")))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
