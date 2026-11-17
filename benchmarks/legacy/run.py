"""Execute real dbt commands against scratch DuckDB databases only."""
import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

from scenarios import BASE, SCENARIOS, diff, oracle

ROOT = Path(__file__).resolve().parent

def run_case(case, scratch: Path) -> dict:
    import duckdb
    start = time.monotonic()
    project = scratch / "project"
    shutil.copytree(ROOT / "project", project)
    database = scratch / "lab.duckdb"
    events = []
    def append(batch):
        with duckdb.connect(str(database)) as db:
            db.execute("create schema if not exists raw")
            db.execute("create table if not exists raw.events(order_id integer, amount_cents integer, updated_at integer, arrival_seq integer)")
            db.executemany("insert into raw.events values (?, ?, ?, ?)", [(*e, len(events)+i) for i,e in enumerate(batch)])
        events.extend(batch)
    def dbt(command, target="candidate", extra=()):
        env = {k:v for k,v in os.environ.items() if k in ("PATH","HOME","LANG","LC_ALL","TMPDIR","SYSTEMROOT","USERPROFILE")}
        env.update(CHAOS_DB=str(database), DBT_SEND_ANONYMOUS_USAGE_STATS="false", DBT_USE_COLORS="false", DBT_PARTIAL_PARSE="false", OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1")
        artifact = project / "target" / "run_results.json"
        artifact.unlink(missing_ok=True)
        args = [str(Path(sys.executable).with_name("dbt")), command, "--project-dir", str(project), "--profiles-dir", str(project), "--target", target, "--vars", json.dumps({"watermark": case.watermark}), *extra]
        p = subprocess.run(args, cwd=project, env=env, capture_output=True, text=True, timeout=90)
        if not artifact.exists():
            raise RuntimeError(f"dbt {command} emitted no current artifact (rc={p.returncode}): {p.stdout[-4000:]} {p.stderr[-2000:]}")
        results = json.loads(artifact.read_text())["results"]
        statuses = [{"id":r["unique_id"],"status":r["status"]} for r in results]
        if not statuses:
            raise RuntimeError(f"dbt {command} executed no nodes")
        allowed = {"pass","fail"} if command == "test" else {"success"}
        if p.returncode not in (0,1) or any(r["status"] not in allowed for r in statuses):
            raise RuntimeError(f"dbt {command} infrastructure/model error: {statuses} {p.stdout[-4000:]}")
        if command != "test" and p.returncode:
            raise RuntimeError(f"dbt model failed: {p.stdout[-4000:]}")
        if command == "test" and (len(statuses) != 4 or bool(p.returncode) != any(r["status"]=="fail" for r in statuses)):
            raise RuntimeError(f"unexpected test artifact: {statuses}")
        return statuses
    def read(schema):
        with duckdb.connect(str(database), read_only=True) as db:
            return db.execute(f"select order_id, amount_cents, updated_at from {schema}.orders order by order_id, amount_cents, updated_at").fetchall()
    append(BASE)
    dbt("run")
    if read("candidate") != oracle(events):
        raise RuntimeError("initial baseline does not match independent oracle")
    steps = []
    for batch in case.batches:
        append(batch)
        dbt("run")
        expected = oracle(events)
        # Test every checkpoint, so transient corruption cannot be hidden by later recovery.
        tests = dbt("test")
        dbt("run", "reference", ("--full-refresh",))
        reference, observed = read("reference"), read("candidate")
        if reference != expected:
            raise RuntimeError("full refresh disagrees with independent reference")
        delta = diff(expected, observed)
        failed = any(t["status"] == "fail" for t in tests)
        mismatch = bool(delta["missing"] or delta["unexpected"])
        classification = "test_detected" if failed else ("silent_corruption" if mismatch else "clean")
        steps.append({"classification":classification,"tests":tests,"difference":delta,"oracle_mismatch":mismatch})
    outcomes = {s["classification"] for s in steps}
    # Detection and silent failures are independently retained per checkpoint.
    classification = "silent_corruption" if "silent_corruption" in outcomes else ("test_detected" if "test_detected" in outcomes else "clean")
    return {"scenario":case.name,"watermark":case.watermark,"expected":case.expected,"classification":classification,"steps":steps,"seconds":round(time.monotonic()-start,3)}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("results.json"))
    parser.add_argument("--scenario", action="append", choices=[s.name for s in SCENARIOS])
    args = parser.parse_args()
    results = []
    for case in SCENARIOS:
        if args.scenario and case.name not in args.scenario:
            continue
        try:
            with tempfile.TemporaryDirectory(prefix="dbt-chaos-") as tmp:
                result = run_case(case, Path(tmp))
        except (Exception,) as exc:
            result = {"scenario":case.name,"expected":case.expected,"classification":"execution_error","error":str(exc)}
        results.append(result)
        print(json.dumps(result), flush=True)
    report = {"schema_version":1,"versions":{k:importlib.metadata.version(k) for k in ("dbt-core","dbt-duckdb","duckdb")},"scenarios":results}
    args.output.write_text(json.dumps(report,indent=2)+"\n")
    return int(any(r["classification"] != r["expected"] for r in results))

if __name__ == "__main__":
    raise SystemExit(main())
