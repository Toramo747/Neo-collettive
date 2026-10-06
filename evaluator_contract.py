# SPDX-License-Identifier: BUSL-1.1
"""Shared deterministic evaluator contract for MYCELIX evolutionary paths.

LLMs may propose genomes or critique outputs, but evaluation and promotion
eligibility are deterministic and fail closed.
"""
from __future__ import annotations

import ast
import inspect
import math
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping

Genome = dict[str, Any]
MetricMap = dict[str, Any]


@dataclass(frozen=True)
class EvaluatorContract:
    name: str
    genome_schema: dict[str, dict[str, Any]]
    evaluate: Callable[[Genome], MetricMap]
    benchmarks: tuple[dict[str, Any], ...]
    robustness: Callable[[Genome], MetricMap]
    control_set: Callable[[], MetricMap]
    source_objects: tuple[Any, ...] = ()
    forbidden_answer_labels: tuple[str, ...] = ()
    robustness_tolerance: float = 0.05
    promotion_mode: str = "MANUAL_REVIEW_ONLY"


def validate_genome(schema: Mapping[str, Mapping[str, Any]], genome: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(genome, Mapping):
        raise ValueError("genome_not_mapping")
    out: dict[str, Any] = {}
    unknown=set(genome)-set(schema)
    if unknown:
        raise ValueError("unknown_genome_fields:"+",".join(sorted(str(x) for x in unknown)))
    for name,spec0 in schema.items():
        spec=dict(spec0 or {})
        required=bool(spec.get("required",True))
        if name not in genome:
            if required:
                raise ValueError("missing_genome_field:"+name)
            if "default" in spec:
                out[name]=spec["default"]
            continue
        value=genome[name]
        typ=str(spec.get("type") or "")
        if typ=="int":
            if isinstance(value,bool):
                raise ValueError("invalid_int:"+name)
            value=int(value)
        elif typ=="float":
            if isinstance(value,bool):
                raise ValueError("invalid_float:"+name)
            value=float(value)
            if not math.isfinite(value):
                raise ValueError("nonfinite_float:"+name)
        elif typ=="bool":
            if not isinstance(value,bool):
                raise ValueError("invalid_bool:"+name)
        elif typ=="enum":
            value=str(value)
            values=tuple(str(x) for x in (spec.get("values") or ()))
            if value not in values:
                raise ValueError("invalid_enum:"+name)
        elif typ=="str":
            value=str(value)
        else:
            raise ValueError("unsupported_genome_type:"+name)
        if typ in {"int","float"}:
            if "min" in spec and value < spec["min"]:
                raise ValueError("below_min:"+name)
            if "max" in spec and value > spec["max"]:
                raise ValueError("above_max:"+name)
        out[name]=value
    return out


def _numeric_close(actual: Any, expected: Any, tolerance: float) -> bool:
    if isinstance(expected,bool) or isinstance(actual,bool):
        return actual is expected
    if isinstance(expected,(int,float)) and isinstance(actual,(int,float)):
        a=float(actual); e=float(expected)
        if not (math.isfinite(a) and math.isfinite(e)):
            return False
        scale=max(1.0,abs(e))
        return abs(a-e) <= max(0.0,float(tolerance))*scale
    return actual==expected


def evaluate_benchmarks(contract: EvaluatorContract) -> dict[str, Any]:
    passed=0
    rows=[]
    for index,case in enumerate(contract.benchmarks):
        genome=validate_genome(contract.genome_schema,case.get("genome") or {})
        observed=contract.evaluate(genome)
        expected=case.get("expected") if isinstance(case.get("expected"),dict) else {}
        tolerance=max(0.0,float(case.get("tolerance",1e-9)))
        ok=all(_numeric_close(observed.get(key),value,tolerance) for key,value in expected.items())
        passed+=int(ok)
        rows.append({"index":index,"ok":ok})
    return {
        "cases":len(rows),
        "passed":passed,
        "ok":bool(rows) and passed==len(rows),
        "details":rows,
    }


def no_hardcoded_answers(
    source_objects: Iterable[Any],
    forbidden_labels: Iterable[str],
) -> dict[str, Any]:
    """Reject label/family keyed lookup tables inside evaluate/score/fitness functions.

    This intentionally targets answer-specific multipliers/lookup tables, not
    ordinary enum validation or seed declarations outside evaluator functions.
    """
    labels={str(x) for x in forbidden_labels if str(x)}
    violations=[]
    for obj in source_objects:
        try:
            source=inspect.getsource(obj)
        except Exception:
            continue
        try:
            tree=ast.parse(source)
        except SyntaxError:
            violations.append("unparseable_source")
            continue
        for node in ast.walk(tree):
            if not isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):
                continue
            lname=node.name.lower()
            if not any(token in lname for token in ("evaluate","score","fitness")):
                continue
            for inner in ast.walk(node):
                if not isinstance(inner,ast.Dict):
                    continue
                keys={
                    str(k.value) for k in inner.keys
                    if isinstance(k,ast.Constant) and isinstance(k.value,str)
                }
                overlap=sorted(keys & labels)
                if overlap:
                    violations.append(node.name+":"+",".join(overlap))
    return {"ok":not violations,"violations":len(violations)}


def run_evaluator_contract(contract: EvaluatorContract, genome: Genome) -> dict[str, Any]:
    validated=validate_genome(contract.genome_schema,genome)
    benchmark=evaluate_benchmarks(contract)
    raw=contract.evaluate(validated) if benchmark["ok"] else {"fitness":0.0}
    robust=contract.robustness(validated) if benchmark["ok"] else {"ok":False,"max_relative_delta":1.0}
    robust_ok=bool(robust.get("ok"))
    delta=float(robust.get("max_relative_delta") or 0.0)
    if delta > max(0.0,float(contract.robustness_tolerance)):
        robust_ok=False
    controls=contract.control_set()
    public_ok=bool(controls.get("public_ok"))
    hidden_ok=bool(controls.get("hidden_ok"))
    hardcoded=no_hardcoded_answers(contract.source_objects,contract.forbidden_answer_labels)
    raw_fitness=max(0.0,float(raw.get("fitness") or 0.0))
    effective_fitness=raw_fitness if benchmark["ok"] and robust_ok else 0.0
    promotion_ready=bool(
        benchmark["ok"]
        and robust_ok
        and public_ok
        and hidden_ok
        and hardcoded["ok"]
        and contract.promotion_mode=="MANUAL_REVIEW_ONLY"
    )
    return {
        "contract":contract.name,
        "benchmark_ok":bool(benchmark["ok"]),
        "robustness_ok":robust_ok,
        "control_ok":bool(public_ok and hidden_ok),
        "public_control_ok":public_ok,
        "hidden_control_ok":hidden_ok,
        "no_hardcoded_answers_ok":bool(hardcoded["ok"]),
        "best_fitness":effective_fitness,
        "raw_fitness":raw_fitness,
        "promotion_ready":promotion_ready,
        "promotion_mode":"MANUAL_REVIEW_ONLY",
        "benchmark_cases":int(benchmark["cases"]),
        "robustness_delta_ppm":max(0,int(delta*1_000_000)),
    }


def numeric_telemetry(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "benchmark_ok":bool(report.get("benchmark_ok")),
        "robustness_ok":bool(report.get("robustness_ok")),
        "control_ok":bool(report.get("control_ok")),
        "best_fitness":float(report.get("best_fitness") or 0.0),
        "promotion_ready":bool(report.get("promotion_ready")),
    }
