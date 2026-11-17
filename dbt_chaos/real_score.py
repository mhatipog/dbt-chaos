"""Aggregate real dbt/DuckDB evidence, with explicit execution and coverage accounting."""
from __future__ import annotations
from datetime import datetime, timezone
from collections import defaultdict
from time import monotonic
import os
from .core import DOMAINS
from .impact import impact

def summarize_real(observations):
    by_model=defaultdict(list)
    for item in observations:
        by_model[item["strategy"]].append(item)
    models={}
    for strategy,items in sorted(by_model.items()):
        valid=[i for i in items if "execution_error" not in i]
        points=[p for i in valid for p in i["checkpoints"] if p["label"]!="baseline"]
        num=len(points)
        silent=sum(int(p["silent"]) for p in points)
        incorrect=sum(int(p["mismatch"]) for p in points)
        detected=sum(int(p["mismatch"] and bool(p["alerts"])) for p in points)
        quality_alerts=sum(int(not p["mismatch"] and bool(p["alerts"])) for p in points)
        by_domain=defaultdict(lambda:[0,0])
        for p in points:
            name=p["label"]
            if name in DOMAINS:
                domain=DOMAINS[name]
                by_domain[domain][0]+=1
                by_domain[domain][1]+=int(p["silent"])
        models[strategy]={
            "planned_runs":len(items),"executed_runs":len(valid),
            "execution_errors":len(items)-len(valid),"fault_checkpoints":num,
            "incorrect":incorrect,
            "correctness_pct":round(100*(num-incorrect)/num,2) if num else None,
            "affected_key_checkpoints":sum(impact(p["delta"])["affected_keys"] for p in points),
            "absolute_synthetic_cents_exposure":sum(impact(p["delta"])["absolute_cents_exposure"] for p in points),
            "silent_corruption":silent,
            "detected_corruption":detected,"quality_alerts":quality_alerts,
            "score_0_100":round(100*(num-silent)/num,2) if num else None,
            "total_elapsed_seconds":round(sum(i.get("elapsed_seconds",0) for i in valid),3),
            "dbt_invocations":sum(i.get("dbt_calls",0) for i in valid),
            "domain_breakdown":{k:{"checkpoints":v[0],"silent":v[1]} for k,v in sorted(by_domain.items())}
        }
    return {
        "schema_version":1,"evidence_level":"executed_dbt_duckdb",
        "generated_utc":datetime.now(timezone.utc).isoformat(),
        "git_sha":os.getenv("GITHUB_SHA"),
        "score_definition":"100 x (1 - silent evaluated fault checkpoints / all evaluated fault checkpoints)",
        "limits":[
            "Synthetic controlled cases cannot estimate real incident frequency or platform availability.",
            "A full-refresh comparator is additionally checked against a separate source-version oracle.",
            "The score is specific to the included scenarios, dbt version and workload.",
            "Failures to execute are never counted as successful or resilient cases.",
            "Not all listed fault categories or backend adapters are implemented."
        ],
        "strategies":models,"observations":observations
    }

def run_campaign(plans,strategies,max_executions=12,time_budget_seconds=900):
    from .dbt_runner import run_real
    if not 1<=len(plans)*len(strategies)<=max_executions or not 1<=max_executions<=60:
        raise ValueError("actual dbt run count exceeds the explicit bounded budget")
    if not 60<=time_budget_seconds<=1200:
        raise ValueError("actual dbt budget must be 60-1200 seconds")
    observations=[]
    start=monotonic()
    for plan in plans:
        for strategy in strategies:
            if monotonic()-start>time_budget_seconds-20:
                observations.append({"plan":plan.name,"strategy":strategy,"execution_error":"time budget exhausted before start"})
                continue
            try:
                result=run_real(plan,strategy)
                observations.append(result)
            except Exception as exc:
                observations.append({"plan":plan.name,"strategy":strategy,"execution_error":str(exc)[:1000]})
    report=summarize_real(observations)
    report["elapsed_campaign_seconds"]=round(monotonic()-start,3)
    return report
