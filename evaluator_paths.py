# SPDX-License-Identifier: BUSL-1.1
"""Contract declarations for the three MYCELIX evaluator paths."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from evaluator_contract import EvaluatorContract
import arena_research_algorithm as research
import arena_warp_propulsion as warp
import challenge_track as challenge
from hidden_control_gate import evaluate_hidden_control
from hidden_challenge_control_gate import evaluate_hidden_challenge_control


_RESEARCH_FIXTURE=[
    {
        "topic":"manual data entry",
        "query":"manual data entry problem",
        "hits":[{
            "comment_text":"astronomy telescope calibration discussion unrelated to office workflows",
            "story_id":"fixture-1",
        }],
    },
]


def _research_evaluate(genome: dict[str,Any]) -> dict[str,Any]:
    return research.score_hits(genome,_RESEARCH_FIXTURE)


def _research_robustness(genome: dict[str,Any]) -> dict[str,Any]:
    base=_research_evaluate(genome)
    perturbed=research.score_hits(genome,list(reversed(_RESEARCH_FIXTURE)))
    a=float(base.get("fitness") or 0.0)
    b=float(perturbed.get("fitness") or 0.0)
    delta=abs(a-b)/max(1.0,abs(a))
    return {"ok":delta<=0.05,"max_relative_delta":delta}


def _research_controls() -> dict[str,Any]:
    data=json.loads(Path("data/arena/research-algorithm/control_cases.json").read_text(encoding="utf-8"))
    public=research.evaluate_control_cases(data.get("cases") or [])
    hidden=evaluate_hidden_control()
    return {
        "public_ok":bool(public.get("cases")) and public.get("correct")==public.get("cases"),
        "hidden_ok":bool(hidden.get("cases")) and bool(hidden.get("ok")),
    }


RESEARCH_CONTRACT=EvaluatorContract(
    name="commercial-research-arena",
    genome_schema={
        "query_mode":{"type":"enum","values":research.QUERY_MODES},
        "query_count":{"type":"int","min":2,"max":research.MAX_QUERIES_PER_GENOME},
        "recency_days":{"type":"int","min":7,"max":45},
        "min_relevance_tokens":{"type":"int","min":1,"max":3},
        "suffix_family":{"type":"enum","values":research.SUFFIX_FAMILIES},
        "topic_shape":{"type":"enum","values":research.TOPIC_SHAPE_MODES},
        "query_frame":{"type":"enum","values":research.QUERY_FRAMES},
        "term_order":{"type":"enum","values":research.TERM_ORDERS},
        "source_scope":{"type":"enum","values":research.SOURCE_SCOPES},
    },
    evaluate=_research_evaluate,
    benchmarks=(
        {
            "genome":research.clamp_genome({}),
            "expected":{"fitness":0.0,"signal_hits":0,"relevant_hits":0},
            "tolerance":0.0,
        },
    ),
    robustness=_research_robustness,
    control_set=_research_controls,
    source_objects=(research.score_hits,),
    forbidden_answer_labels=tuple(research.QUERY_MODES),
    robustness_tolerance=0.05,
)


_CHALLENGE_NOW=2_000_000_000.0
_CHALLENGE_ROWS=[
    {
        "track":"challenge","challenge_key":"fixture","requester_key":"r1","domain":"a.example",
        "created_at_epoch":_CHALLENGE_NOW-90*86400,"workaround":True,"feasibility":"feasible",
        "reward":False,"resolved":False,"fingerprint":"f1",
    },
    {
        "track":"challenge","challenge_key":"fixture","requester_key":"r2","domain":"b.example",
        "created_at_epoch":_CHALLENGE_NOW-80*86400,"workaround":True,"feasibility":"feasible",
        "reward":False,"resolved":False,"fingerprint":"f2",
    },
    {
        "track":"challenge","challenge_key":"fixture","requester_key":"r3","domain":"a.example",
        "created_at_epoch":_CHALLENGE_NOW-70*86400,"workaround":False,"feasibility":"feasible",
        "reward":False,"resolved":False,"fingerprint":"f3",
    },
]


def _challenge_evaluate(genome: dict[str,Any]) -> dict[str,Any]:
    cfg={
        "min_requesters":genome["min_requesters"],
        "min_domains":genome["min_domains"],
        "min_age_days":genome["min_age_days"],
        "require_workaround":genome["require_workaround"],
        "hard_blocks":genome["hard_blocks"],
        "manual_confirmation_required":True,
        "mode":"shadow",
    }
    rows=challenge.evaluate_challenges(_CHALLENGE_ROWS,config=cfg,now_epoch=_CHALLENGE_NOW)
    top=rows[0] if rows else {}
    return {"fitness":float(top.get("score") or 0.0),"ready":bool(top.get("gate_pass"))}


def _challenge_robustness(genome: dict[str,Any]) -> dict[str,Any]:
    base=_challenge_evaluate(genome)
    original=list(_CHALLENGE_ROWS)
    duplicate=dict(_CHALLENGE_ROWS[0],fingerprint="f1-dup")
    rows=list(reversed(original))+[duplicate]
    cfg={
        "min_requesters":genome["min_requesters"],"min_domains":genome["min_domains"],
        "min_age_days":genome["min_age_days"],"require_workaround":genome["require_workaround"],
        "hard_blocks":genome["hard_blocks"],
    }
    top=(challenge.evaluate_challenges(rows,config=cfg,now_epoch=_CHALLENGE_NOW) or [{}])[0]
    other=float(top.get("score") or 0.0)
    base_f=float(base.get("fitness") or 0.0)
    delta=abs(base_f-other)/max(1.0,abs(base_f))
    return {"ok":delta<=0.05,"max_relative_delta":delta}


def _challenge_controls() -> dict[str,Any]:
    data=json.loads(Path("data/challenge/control_cases.json").read_text(encoding="utf-8"))
    public=challenge.evaluate_public_control_cases(data.get("cases") or [])
    hidden=evaluate_hidden_challenge_control()
    return {
        "public_ok":bool(public.get("cases")) and public.get("correct")==public.get("cases"),
        "hidden_ok":bool(hidden.get("cases")) and bool(hidden.get("ok")),
    }


CHALLENGE_CONTRACT=EvaluatorContract(
    name="challenge-track",
    genome_schema={
        "min_requesters":{"type":"int","min":1,"max":20},
        "min_domains":{"type":"int","min":1,"max":10},
        "min_age_days":{"type":"int","min":1,"max":3650},
        "require_workaround":{"type":"bool"},
        "hard_blocks":{"type":"bool"},
    },
    evaluate=_challenge_evaluate,
    benchmarks=(
        {
            "genome":{"min_requesters":3,"min_domains":2,"min_age_days":60,"require_workaround":True,"hard_blocks":True},
            "expected":{"fitness":100.0,"ready":True},
            "tolerance":0.0,
        },
    ),
    robustness=_challenge_robustness,
    control_set=_challenge_controls,
    source_objects=(challenge.evaluate_challenges,),
    forbidden_answer_labels=("true_challenge","solved","trivial","infeasible"),
    robustness_tolerance=0.05,
)


def _warp_evaluate(genome: dict[str,Any]) -> dict[str,Any]:
    candidate=warp.Candidate(
        family=genome["family"],
        wall_thickness=genome["wall_thickness"],
        bubble_radius=genome["bubble_radius"],
        effective_beta=genome["effective_beta"],
        shear_control=genome["shear_control"],
        lapse_modulation=genome["lapse_modulation"],
    )
    score=warp.score_candidate(candidate)
    return {"fitness":float(score.get("fitness") or 0.0),"theoretical_only":score.get("status")=="THEORETICAL_ONLY"}


def _warp_robustness(genome: dict[str,Any]) -> dict[str,Any]:
    # Phase 2 replaces this placeholder with double-resolution tensor evaluation.
    return {"ok":False,"max_relative_delta":1.0}


def _warp_controls() -> dict[str,Any]:
    # No hidden physics holdout is wired yet; fail closed until Phase 2.
    return {"public_ok":True,"hidden_ok":False}


WARP_CONTRACT=EvaluatorContract(
    name="warp-propulsion",
    genome_schema={
        "family":{"type":"enum","values":warp.FAMILIES},
        "wall_thickness":{"type":"float","min":0.08,"max":1.25},
        "bubble_radius":{"type":"float","min":0.5,"max":3.0},
        "effective_beta":{"type":"float","min":0.2,"max":1.5},
        "shear_control":{"type":"float","min":0.0,"max":1.0},
        "lapse_modulation":{"type":"float","min":0.0,"max":0.4},
    },
    evaluate=_warp_evaluate,
    benchmarks=(
        {
            "genome":{
                "family":"positive_energy_subluminal","wall_thickness":0.5,"bubble_radius":1.0,
                "effective_beta":0.75,"shear_control":0.65,"lapse_modulation":0.04,
            },
            "expected":{"theoretical_only":True},
            "tolerance":0.0,
        },
    ),
    robustness=_warp_robustness,
    control_set=_warp_controls,
    source_objects=(warp.score_candidate,),
    forbidden_answer_labels=tuple(warp.FAMILIES),
    robustness_tolerance=0.05,
)


CONTRACTS={
    "commercial":RESEARCH_CONTRACT,
    "challenge":CHALLENGE_CONTRACT,
    "warp":WARP_CONTRACT,
}
