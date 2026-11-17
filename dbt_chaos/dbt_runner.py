"""Run actual dbt Core with temporary DuckDB and independent source-version oracle.

This module never accepts or forwards customer database targets, credentials,
profiles, GitHub secrets or arbitrary SQL from scenario JSON.
"""
from __future__ import annotations
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import os
import shutil
import subprocess
import sys
from time import perf_counter
from .core import Event,Plan,STRATEGIES,oracle,delta

SQL=Path(__file__).resolve().parent/"sql"

def run_real(plan:Plan,strategy:str="strict",lookback:int=10)->dict:
    if strategy not in STRATEGIES or not 0<=lookback<=1_000_000:
        raise ValueError("unsupported strategy or lookback")
    try:
        import duckdb
    except ImportError as exc:
        raise RuntimeError("Install dbt-core, dbt-duckdb and duckdb first; see README") from exc
    with TemporaryDirectory(prefix="dbt-chaos-") as directory:
        scratch=Path(directory)
        project=scratch/"project"
        shutil.copytree(SQL,project)
        database=scratch/"scratch.duckdb"
        with duckdb.connect(str(database)) as db:
            db.execute("create schema raw")
            db.execute("""create table raw.events(
                event_id varchar, order_id integer, source_version integer,
                event_time integer, amount_cents integer, op varchar,
                arrival_seq integer)""")
        arrivals:list[Event]=[]
        count=0
        dbt_calls=0
        start=perf_counter()
        checkpoints=[]
        def dbt(command:str,target:str="candidate",full_refresh:bool=False):
            nonlocal dbt_calls
            env={key:os.environ[key] for key in ("PATH","HOME","LANG","LC_ALL","TMPDIR","SYSTEMROOT","USERPROFILE") if key in os.environ}
            env.update(CHAOS_DB=str(database),DBT_SEND_ANONYMOUS_USAGE_STATS="false",
                       DBT_PARTIAL_PARSE="false",DBT_USE_COLORS="false",OPENBLAS_NUM_THREADS="1",OMP_NUM_THREADS="1")
            artifact=project/"target"/"run_results.json"
            artifact.unlink(missing_ok=True)
            arguments=[str(Path(sys.executable).with_name("dbt")),command,"--project-dir",str(project),
                       "--profiles-dir",str(project),"--target",target,
                       "--vars",json.dumps({"strategy":strategy if target=="candidate" else "full",
                                            "lookback":lookback})]
            if full_refresh:arguments.append("--full-refresh")
            try:
                process=subprocess.run(arguments,cwd=project,env=env,capture_output=True,text=True,timeout=100)
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError("real dbt command exceeded 100 seconds") from exc
            dbt_calls+=1
            if not artifact.exists():
                raise RuntimeError(f"dbt {command} failed before results artifact, rc={process.returncode}: {process.stdout[-1500:]} {process.stderr[-1000:]}")
            rows=json.loads(artifact.read_text(encoding="utf8")).get("results",[])
            if not rows:
                raise RuntimeError(f"dbt {command} executed no nodes")
            statuses=[{"id":row["unique_id"],"status":row["status"]} for row in rows]
            if command=="run" and (process.returncode!=0 or any(row["status"]!="success" for row in rows)):
                raise RuntimeError(f"dbt run unexpectedly failed: {statuses} {process.stdout[-2500:]}")
            if command=="test" and (process.returncode not in (0,1) or
                any(row["status"] not in ("pass","fail") for row in rows) or
                bool(process.returncode)!=any(row["status"]=="fail" for row in rows)):
                raise RuntimeError(f"dbt test infra/contract failure: {statuses} {process.stdout[-1500:]}")
            return statuses
        def current(schema:str)->dict[int,Event]:
            if schema not in ("candidate","reference"):raise ValueError("invalid schema")
            with duckdb.connect(str(database),read_only=True) as db:
                rows=db.execute(
                    "select order_id, source_version, event_time, amount_cents, op, event_id "
                    "from "+schema+".orders order by order_id").fetchall()
            return {row[0]:Event(row[5],row[0],row[1],row[2],row[3],row[4]) for row in rows}
        for index,step in enumerate(plan.steps):
            if step.kind=="deliver":
                inserted=[]
                for event in step.events:
                    count+=1
                    inserted.append((event.event_id,event.key,event.version,event.time,
                                     event.cents,event.op,count))
                if inserted:
                    with duckdb.connect(str(database)) as db:
                        db.executemany("insert into raw.events values (?,?,?,?,?,?,?)",inserted)
                arrivals.extend(step.events)
            elif step.kind=="run":
                dbt("run")
            else:
                statuses=dbt("test")
                dbt("run","reference",True)
                expected=oracle(arrivals)
                ref=current("reference")
                if delta(expected,ref)!={"missing":{},"extra":{},"changed":{}}:
                    raise RuntimeError("full refresh differs from independent source-version oracle")
                actual=current("candidate")
                discrepancies=delta(expected,actual)
                mismatch=any(bool(v) for v in discrepancies.values())
                alerts=[row["id"] for row in statuses if row["status"]=="fail"]
                checkpoints.append({"step":index,"label":step.label,
                                   "mismatch":mismatch,"silent":bool(mismatch and not alerts),
                                   "alerts":alerts,"delta":discrepancies,
                                   "test_statuses":statuses})
        return {"evidence_level":"executed_dbt_duckdb","plan":plan.name,
                "seed":plan.seed,"faults":list(plan.faults),"strategy":strategy,
                "dbt_calls":dbt_calls,"elapsed_seconds":round(perf_counter()-start,3),
                "checkpoints":checkpoints,
                "silent_corruption":any(c["silent"] for c in checkpoints),
                "final_correct":not checkpoints[-1]["mismatch"]}
