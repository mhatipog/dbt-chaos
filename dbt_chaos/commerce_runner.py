"""Real dbt/DuckDB execution for the source + transformation chaos workload.

Only shipped SQL and allowlisted fault names are executed against temporary synthetic
data. Never passes through external profiles, credentials or user-authored SQL.
"""
from __future__ import annotations
import json
from copy import deepcopy
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from time import perf_counter
from .commerce import CommerceCase, TABLES, inject_source, source_contract_alerts, assess, summarize

PROJECT=Path(__file__).resolve().parent/"commerce_sql"
COLUMNS={
 "customers":("row_id","customer_id","version","segment"),
 "orders":("row_id","order_id","customer_id","version","order_day","gross_cents","status","currency"),
 "payments":("row_id","payment_id","order_id","version","kind","amount_cents"),
}
DDL={
 "customers":"create table raw.customers(row_id integer, customer_id integer, version integer, segment varchar)",
 "orders":"create table raw.orders(row_id integer, order_id integer, customer_id integer, version integer, order_day varchar, gross_cents integer, status varchar, currency varchar)",
 "payments":"create table raw.payments(row_id integer, payment_id integer, order_id integer, version integer, kind varchar, amount_cents integer)",
}
SOURCE_TEST_IDS={
 "duplicate_customers":"source_duplicate_customers",
 "duplicate_orders":"source_duplicate_orders",
 "duplicate_payments":"source_duplicate_payments",
 "invalid_orders":"source_invalid_orders",
 "invalid_payments":"source_invalid_payments",
}

def run_case(case:CommerceCase, *, admitted_data:dict|None=None,
             process_data:dict|None=None, quality_enabled:bool=False)->dict:
    try:
        import duckdb
    except ImportError as exc:
        raise RuntimeError("Install real dbt dependencies: pip install -e '.[dbt]'") from exc
    data=inject_source(case.source_fault) if admitted_data is None else deepcopy(admitted_data)
    expected_alerts=source_contract_alerts(data)
    started=perf_counter()
    with TemporaryDirectory(prefix="dbt-chaos-commerce-") as temp:
        root=Path(temp)
        project=root/"project"
        shutil.copytree(PROJECT,project)
        database=root/"case.duckdb"
        with duckdb.connect(str(database)) as db:
            db.execute("create schema raw")
            for table in TABLES:
                db.execute(DDL[table])
                rows=[tuple(row[col] for col in COLUMNS[table]) for row in data[table]]
                if rows:
                    placeholders=",".join("?" for _ in COLUMNS[table])
                    db.executemany(f"insert into raw.{table} values ({placeholders})",rows)

        def invoke(command:str):
            env={key:os.environ[key] for key in
                 ("PATH","HOME","LANG","LC_ALL","TMPDIR","SYSTEMROOT","USERPROFILE")
                 if key in os.environ}
            env.update(CHAOS_DB=str(database), DBT_SEND_ANONYMOUS_USAGE_STATS="false",
                       DBT_PARTIAL_PARSE="false", DBT_USE_COLORS="false",
                       OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1")
            artifact=project/"target"/"run_results.json"
            artifact.unlink(missing_ok=True)
            cmd=[str(Path(sys.executable).with_name("dbt")),command,
                 "--project-dir",str(project),"--profiles-dir",str(project),
                 "--target","local","--vars",json.dumps({"logic_fault":case.logic_fault,
                                                     "enable_quality_models":quality_enabled})]
            before=perf_counter()
            try:
                proc=subprocess.run(cmd,cwd=project,env=env,text=True,
                                    capture_output=True,timeout=95,check=False)
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError(f"dbt {command} exceeded 95 seconds") from exc
            seconds=round(perf_counter()-before,3)
            if not artifact.exists():
                raise RuntimeError(f"dbt {command} failed without artifact; rc={proc.returncode}; {proc.stdout[-1500:]} {proc.stderr[-700:]}")
            statuses=[{"id":x["unique_id"],"status":x["status"]}
                      for x in json.loads(artifact.read_text(encoding="utf8")).get("results",[])]
            valid=("success",) if command=="run" else ("pass","fail")
            if not statuses or any(x["status"] not in valid for x in statuses):
                raise RuntimeError(f"dbt {command} node failure: {statuses}; {proc.stdout[-1500:]}")
            if command=="run" and proc.returncode!=0:
                raise RuntimeError(f"dbt run returned {proc.returncode}: {proc.stdout[-1500:]}")
            if command=="test" and (proc.returncode not in (0,1) or
                    bool(proc.returncode)!=any(x["status"]=="fail" for x in statuses)):
                raise RuntimeError(f"dbt test results inconsistent with exit status: {statuses}")
            return statuses,seconds

        models,model_seconds=invoke("run")
        tests,test_seconds=invoke("test")
        with duckdb.connect(str(database),read_only=True) as db:
            rows=db.execute(
                "select order_day,segment,revenue_cents from analytics.gold_daily_revenue"
                " order by order_day,segment").fetchall()
            native_payload=None
            if quality_enabled:
                published=db.execute(
                    "select order_day,segment,revenue_cents "
                    "from analytics.quality_gold_published "
                    "order by order_day,segment").fetchall()
                quarantined=db.execute(
                    "select row_id,payment_id,order_id,quarantine_reason "
                    "from analytics.quality_quarantine_payments "
                    "order by row_id").fetchall()
                held=db.execute(
                    "select order_day,segment from analytics.quality_held_groups "
                    "order by order_day,segment").fetchall()
                gate=db.execute(
                    "select publication_status,quarantine_rows,global_risks,local_risks "
                    "from analytics.quality_release_gate").fetchone()
                if gate is None:
                    raise RuntimeError("native quality gate produced no publication state")
                native_payload={
                    "release_status":gate[0],
                    "quarantined_row_count":gate[1],
                    "global_risk_count":gate[2],
                    "local_risk_count":gate[3],
                    "quarantine":[{"row_id":r[0],"payment_id":r[1],
                                   "order_id":r[2],"reason":r[3]} for r in quarantined],
                    "held_groups":[f"{day}|{seg}" for day,seg in held],
                    "released_gold":{f"{day}|{seg}":int(cents)
                                     for day,seg,cents in published},
                    "models_executed_by_dbt":True,
                    "implementation":"native_dbt_sql_opt_in",
                }

    observed={}
    for day,segment,cents in rows:
        key=(str(day),str(segment))
        if key in observed:
            raise RuntimeError("Duplicate output grain: cannot safely collapse discrepancies")
        observed[key]=int(cents)
    failed=[x["id"] for x in tests if x["status"]=="fail"]
    source_alerts=[test for test in SOURCE_TEST_IDS.values()
                   if any("."+test in node for node in failed)]
    output_alerts=[node for node in failed
                   if not any("."+test in node for test in SOURCE_TEST_IDS.values())]
    if set(source_alerts)!={SOURCE_TEST_IDS[tag] for tag in expected_alerts}:
        raise RuntimeError(f"Source test contract discrepancy: expected {expected_alerts}, got {source_alerts}")
    result=assess(case,observed,source_alerts,output_alerts,
                  admitted_data=data,process_data=process_data)
    result.update(evidence_level="executed_dbt_duckdb", dbt_calls=2,
                  model_seconds=model_seconds,test_seconds=test_seconds,
                  elapsed_seconds=round(perf_counter()-started,3),
                  model_statuses=models,test_count=len(tests),
                  source_contract_warnings=expected_alerts)
    if quality_enabled:
        result["native_quality"]=native_payload
    return result

def run_matrix(selected:list[CommerceCase],max_cases:int=30)->dict:
    if not selected or not 1<=max_cases<=100 or len(selected)>max_cases:
        raise ValueError("real dbt matrix exceeds bounded execution budget")
    results=[]
    for case in selected:
        try:
            results.append(run_case(case))
        except (ValueError,RuntimeError) as exc:
            result=assess(case,{},[],[],execution_error=str(exc)[:1500])
            result["evidence_level"]="execution_error"
            results.append(result)
    summary=summarize(results)
    summary["results"]=results
    return summary
