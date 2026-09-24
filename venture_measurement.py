from __future__ import annotations

from typing import Any

MEASUREMENT_SCHEMA_VERSION = 1


def _number(value: Any, field: str, *, allow_zero: bool = True) -> float:
    try:
        number=float(value)
    except (TypeError,ValueError):
        raise ValueError(field+"_must_be_numeric")
    if number < 0 or (not allow_zero and number <= 0):
        raise ValueError(field+"_out_of_range")
    return round(number,4)


def start_observed_measurement(
    *,
    measurement_id: str,
    build_id: str,
    family: str,
    process_label: str,
    baseline_minutes_each: Any,
    baseline_weekly_runs: Any,
    baseline_weekly_errors: Any = 0,
    observed_at_utc: str,
) -> dict:
    measurement_id=str(measurement_id or "").strip()
    build_id=str(build_id or "").strip()
    family=str(family or "").strip()
    process_label=" ".join(str(process_label or "").split())[:500]
    if not measurement_id:
        raise ValueError("measurement_id_required")
    if not build_id:
        raise ValueError("build_id_required")
    if not family:
        raise ValueError("family_required")
    if not process_label:
        raise ValueError("process_label_required")

    minutes_each=_number(baseline_minutes_each,"baseline_minutes_each",allow_zero=False)
    weekly_runs=_number(baseline_weekly_runs,"baseline_weekly_runs",allow_zero=False)
    weekly_errors=_number(baseline_weekly_errors,"baseline_weekly_errors",allow_zero=True)
    weekly_minutes=round(minutes_each*weekly_runs,2)

    return {
        "schema_v":MEASUREMENT_SCHEMA_VERSION,
        "measurement_id":measurement_id,
        "build_id":build_id,
        "family":family,
        "process_label":process_label,
        "status":"BASELINE_RECORDED",
        "baseline":{
            "observed_at_utc":str(observed_at_utc or ""),
            "minutes_each":minutes_each,
            "weekly_runs":weekly_runs,
            "weekly_minutes":weekly_minutes,
            "weekly_errors":weekly_errors,
            "source":"human_observed",
        },
        "result":None,
        "outcome":None,
        "evidence_boundary":{
            "observed_not_synthetic":True,
            "self_reported_not_independently_verified":True,
            "does_not_prove_market_demand":True,
            "does_not_authorize_external_actions":True,
        },
    }


def complete_observed_measurement(
    session: dict,
    *,
    after_minutes_each: Any,
    after_weekly_runs: Any | None = None,
    after_weekly_errors: Any = 0,
    observed_at_utc: str,
) -> dict:
    if not isinstance(session,dict):
        raise ValueError("measurement_session_required")
    if str(session.get("status") or "")!="BASELINE_RECORDED":
        raise ValueError("measurement_not_open")

    baseline=session.get("baseline") or {}
    baseline_runs=_number(baseline.get("weekly_runs"),"baseline_weekly_runs",allow_zero=False)
    baseline_minutes=_number(baseline.get("weekly_minutes"),"baseline_weekly_minutes",allow_zero=False)
    baseline_errors=_number(baseline.get("weekly_errors") or 0,"baseline_weekly_errors",allow_zero=True)

    minutes_each=_number(after_minutes_each,"after_minutes_each",allow_zero=True)
    weekly_runs=baseline_runs if after_weekly_runs in (None,"") else _number(after_weekly_runs,"after_weekly_runs",allow_zero=False)
    weekly_errors=_number(after_weekly_errors,"after_weekly_errors",allow_zero=True)
    weekly_minutes=round(minutes_each*weekly_runs,2)

    saved_minutes=round(baseline_minutes-weekly_minutes,2)
    saved_errors=round(baseline_errors-weekly_errors,2)
    reduction_pct=round((saved_minutes/baseline_minutes)*100,2) if baseline_minutes>0 else None
    error_reduction_pct=round((saved_errors/baseline_errors)*100,2) if baseline_errors>0 else None

    if saved_minutes>0 or saved_errors>0:
        outcome="IMPROVED"
    elif saved_minutes<0 or saved_errors<0:
        outcome="REGRESSED"
    else:
        outcome="NO_CHANGE"

    updated=dict(session)
    updated["status"]="OBSERVED_RESULT"
    updated["result"]={
        "observed_at_utc":str(observed_at_utc or ""),
        "minutes_each":minutes_each,
        "weekly_runs":weekly_runs,
        "weekly_minutes":weekly_minutes,
        "weekly_errors":weekly_errors,
        "weekly_minutes_saved":saved_minutes,
        "weekly_errors_avoided":saved_errors,
        "minutes_reduction_pct":reduction_pct,
        "error_reduction_pct":error_reduction_pct,
        "source":"human_observed",
    }
    updated["outcome"]=outcome
    return updated


def measurement_summary(sessions: list[dict], *, build_id: str = "", family: str = "") -> dict:
    rows=[]
    for row in sessions or []:
        if not isinstance(row,dict):
            continue
        if build_id and str(row.get("build_id") or "")!=str(build_id):
            continue
        if family and str(row.get("family") or "")!=str(family):
            continue
        rows.append(row)

    completed=[x for x in rows if str(x.get("status") or "")=="OBSERVED_RESULT"]
    open_rows=[x for x in rows if str(x.get("status") or "")=="BASELINE_RECORDED"]
    improved=[x for x in completed if str(x.get("outcome") or "")=="IMPROVED"]
    regressed=[x for x in completed if str(x.get("outcome") or "")=="REGRESSED"]
    unchanged=[x for x in completed if str(x.get("outcome") or "")=="NO_CHANGE"]

    return {
        "sessions":len(rows),
        "open_baselines":len(open_rows),
        "completed_results":len(completed),
        "improved":len(improved),
        "regressed":len(regressed),
        "no_change":len(unchanged),
        "latest_completed":completed[-1] if completed else None,
        "latest_open":open_rows[-1] if open_rows else None,
    }
