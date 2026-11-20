"""Replay controlled seed faults against an *unfamiliar* local dbt/DuckDB project.

This module EXECUTES the project's dbt SQL, macros and hooks. A copied
project and temporary DuckDB database avoid changing the original project,
but ARE NOT a security sandbox. Run only trusted projects on throwaway,
network-restricted workers with no ambient credentials.

In the absence of an independently supplied expected output, changed
business output is explicitly only "unverified drift", NOT corruption.
"""
from __future__ import annotations

from collections import Counter
import csv
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Any

FORMAT = "dbt_chaos_external_seed_campaign_v2"
FAULTS = ("amount_shift", "duplicate_row", "drop_row", "reorder_rows")
IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
SKIP_DIRS = {
    ".git", ".github", ".venv", "venv", "target", "logs", "dbt_packages",
    "__pycache__", "node_modules", "dist", "build", ".tox", ".mypy_cache",
}
COPY_SUFFIXES = {".sql", ".csv", ".yml", ".yaml", ".md", ".json"}
MAX_FILES, MAX_BYTES, MAX_ROWS = 500, 16_000_000, 100_000


class ExternalProjectError(ValueError):
    """Unsupported/unsafe project configuration or incomplete execution."""


def _validate_name(name: str, label: str) -> str:
    if not isinstance(name, str) or not IDENT.fullmatch(name):
        raise ExternalProjectError(f"{label} must be a simple dbt identifier")
    return name


def _load_yaml(path: Path) -> dict:
    try:
        import yaml
    except ImportError as exc:
        raise ExternalProjectError(
            "PyYAML required; install python -m pip install -e '.[dbt]'"
        ) from exc
    data = yaml.safe_load(path.read_text(encoding="utf8"))
    if not isinstance(data, dict):
        raise ExternalProjectError("dbt_project.yml must be a YAML mapping")
    return data


def _inventory(root: Path) -> dict:
    """Reject symlinks and unexpected project scope; never copy profiles/secrets."""
    root = root.resolve()
    if not root.is_dir() or not (root / "dbt_project.yml").is_file():
        raise ExternalProjectError("existing project with dbt_project.yml required")
    if (root / "dbt_project.yml").is_symlink():
        raise ExternalProjectError("symlinked project config rejected")
    config = _load_yaml(root / "dbt_project.yml")
    name = _validate_name(config.get("name"), "project name")
    profile = _validate_name(config.get("profile", name), "dbt profile")
    if (root / "packages.yml").exists() or (root / "dependencies.yml").exists():
        raise ExternalProjectError(
            "dbt package installs are not supported in this first offline adapter")
    files = []
    size = 0
    # Unlike a permissive copytree, this cannot bring .env, private profiles,
    # Python plugins, package dependencies, or symlink escapes into the runner.
    for parent, dirs, names in os.walk(root, followlinks=False):
        parent_path = Path(parent)
        for d in list(dirs):
            path = parent_path / d
            if path.is_symlink():
                raise ExternalProjectError("symlinked project directory rejected")
            if d in SKIP_DIRS or d.startswith("."):
                dirs.remove(d)
        for name_part in names:
            source = parent_path / name_part
            if source.is_symlink():
                raise ExternalProjectError("symlinked project file rejected")
            if (source.name == "profiles.yml"
                    or source.name.startswith(".")
                    or source.suffix.lower() not in COPY_SUFFIXES):
                continue
            # No archived executable binaries; SQL/macros are still executable.
            relative = source.relative_to(root)
            if len(relative.parts) > 10:
                raise ExternalProjectError("unsupported deeply nested project")
            size += source.stat().st_size
            files.append(relative)
            if len(files) > MAX_FILES or size > MAX_BYTES:
                raise ExternalProjectError("project exceeds bounded file/size limit")
    if Path("dbt_project.yml") not in files:
        raise ExternalProjectError("project config missing from allowed inventory")
    return {
        "name": name, "profile": profile, "root": root,
        "files": sorted(files), "total_bytes": size,
    }



def inspect_external_project(project_dir: Path) -> dict:
    """Side-effect-free seed inventory; never expose source row values or run dbt.

    SQL filenames are heuristics, not compiled lineage. Execution still
    requires an explicit reviewed, credential-free and isolated environment.
    """
    info = _inventory(project_dir)
    seeds = []
    for file in info["files"]:
        if file.suffix.lower() != ".csv":
            continue
        try:
            columns, rows = _read_csv(info["root"] / file)
        except (ExternalProjectError, OSError, UnicodeError) as exc:
            seeds.append({
                "seed": file.stem, "relative_path": file.as_posix(),
                "supported_for_bounded_mutation": False,
                "reason": type(exc).__name__,
            })
            continue
        keys = [
            field for field in columns
            if (field.lower() == "id" or field.lower().endswith("_id")
                or field.lower().endswith("_key"))
            and all(r[field] for r in rows)
            and len({r[field] for r in rows}) == len(rows)
        ]
        numeric = [
            field for field in columns
            if any(tag in field.lower() for tag in
                   ("amount", "price", "cost", "total", "value", "refund"))
            and any(re.fullmatch(r"[0-9]+", r[field]) and int(r[field]) > 1
                    for r in rows)
        ]
        seeds.append({
            "seed": file.stem, "relative_path": file.as_posix(),
            "row_count": len(rows), "columns": columns,
            "candidate_row_keys": keys,
            "candidate_integer_amount_columns": numeric,
            "supported_for_bounded_mutation": bool(keys and numeric),
            "warning": (
                "Candidate columns are inferred from names and input shape; "
                "neither key semantics nor business truth is inferred."
            ),
        })
    models = sorted(
        file.stem for file in info["files"]
        if file.suffix.lower() == ".sql" and "models" in file.parts
    )
    return {
        "format": "dbt_chaos_external_inspection_v1",
        "project": info["name"],
        "schema_only_no_row_values_exposed": True,
        "dbt_or_macro_code_executed": False,
        "files_in_allowed_scope": len(info["files"]),
        "model_file_names_not_compiled_dag": models,
        "seeds": seeds,
        "note": "Inspect and review target code; a matching seed is not "
                "proof that a DuckDB run will be portable.",
    }

def _seed_path(info: dict, table: str) -> Path:
    matches = [p for p in info["files"]
               if p.suffix.lower() == ".csv" and p.stem == table]
    if len(matches) != 1:
        raise ExternalProjectError(
            f"expected exactly one CSV seed named {table!r}; found {len(matches)}")
    return matches[0]


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if path.stat().st_size > 4_000_000:
        raise ExternalProjectError("single seed CSV too large for bounded run")
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        columns = reader.fieldnames
        if not columns or len(set(columns)) != len(columns):
            raise ExternalProjectError("missing or duplicate CSV column names")
        rows = list(reader)
    if len(rows) > 20_000 or not rows:
        raise ExternalProjectError("seed must contain 1..20000 source rows")
    if any(None in row or any(value is None for value in row.values())
           for row in rows):
        raise ExternalProjectError("ragged seed CSV")
    return columns, rows


def build_mutation(
    source: Path, fault: str, *, column: str, match_column: str,
    match_value: str, delta: int,
) -> tuple[bytes, dict]:
    """Deterministically mutate exactly one CSV seed without touching original."""
    if fault not in FAULTS:
        raise ExternalProjectError("unsupported seed fault")
    if type(delta) is not int or delta <= 0 or delta > 1_000_000_000:
        raise ExternalProjectError("delta must be bounded positive integer")
    columns, rows = _read_csv(source)
    if match_column not in columns or column not in columns:
        raise ExternalProjectError("target column and match column must exist")
    matched = [i for i, r in enumerate(rows)
               if r[match_column] == match_value]
    if len(matched) != 1:
        raise ExternalProjectError("row selector must match exactly one input row")
    index = matched[0]
    changed = [dict(r) for r in rows]
    before = changed[index][column]
    if fault == "amount_shift":
        if not re.fullmatch(r"[0-9]+", before):
            raise ExternalProjectError(
                "amount_shift currently supports unsigned integer cents only")
        value = int(before)
        if value <= delta:
            raise ExternalProjectError("amount_shift would make amount nonpositive")
        changed[index][column] = str(value - delta)
    elif fault == "duplicate_row":
        changed.insert(index + 1, dict(changed[index]))
    elif fault == "drop_row":
        changed.pop(index)
    elif fault == "reorder_rows":
        if len(changed) < 2:
            raise ExternalProjectError("reorder_rows needs at least two records")
        changed.reverse()  # deliberately benign multiset-preserving control
    result = io.StringIO(newline="")
    writer = csv.DictWriter(result, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    writer.writerows(changed)
    data = result.getvalue().encode("utf8")
    return data, {
        "fault": fault, "selected_row": match_column + "=" + match_value,
        "target_column": column, "old_cell": before if fault == "amount_shift" else None,
        "new_cell": changed[index][column] if fault == "amount_shift" else None,
        "input_rows_before": len(rows), "input_rows_after": len(changed),
        "mutated_csv_sha256": sha256(data).hexdigest(),
    }


def _profile_yaml(profile: str, warehouse: Path) -> str:
    # Fixed keys, simple validated profile identifier and JSON-quoted local path.
    return (
        f"{profile}:\n  target: isolated\n  outputs:\n    isolated:\n"
        f"      type: duckdb\n      path: {json.dumps(str(warehouse))}\n"
        f"      threads: 1\n"
    )


def _safe_environment(temp_home: Path) -> dict[str, str]:
    """Reduce accidental credential inheritance (NOT network containment)."""
    result = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(temp_home),
        "DBT_SEND_ANONYMOUS_USAGE_STATS": "false",
        "DO_NOT_TRACK": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    if os.name == "nt":
        for key in ("SYSTEMROOT", "WINDIR", "PATHEXT", "COMSPEC"):
            if key in os.environ:
                result[key] = os.environ[key]
    return result


def _run_dbt(
    cmd: str, project: Path, profiles: Path, home: Path,
    *, model: str, timeout: int, test_scope: str = "full",
) -> dict:
    binary = shutil.which("dbt")
    if binary is None:
        raise ExternalProjectError("dbt CLI unavailable: install -e '.[dbt]'")
    # dbt Core 1.10 accepts --project-dir/--profiles-dir on the
    # *subcommand*, not before it as top-level CLI options.
    args = [
        binary, "--no-use-colors", cmd,
        "--project-dir", str(project),
        "--profiles-dir", str(profiles),
    ]
    if cmd == "seed":
        args += ["--full-refresh"]
    if cmd in ("run", "test") and test_scope == "selected":
        args += ["--select", "+" + model]
    if cmd == "run":
        args += ["--full-refresh"]
    try:
        proc = subprocess.run(
            args, cwd=project, env=_safe_environment(home),
            capture_output=True, text=True, errors="replace",
            timeout=timeout, check=False,
        )
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "returncode": None,
                "test_statuses": {}, "tests_executed": 0}
    statuses = Counter()
    failed_tests = []
    executed_test_ids = []
    results = project / "target" / "run_results.json"
    # dbt rewrites this artifact after each command.
    if results.is_file():
        try:
            data = json.loads(results.read_text(encoding="utf8"))
            for item in data.get("results", []):
                status = str(item.get("status", "unknown")).lower()
                if cmd == "test":
                    executed_test_ids.append(str(item.get("unique_id", "")))
                statuses[status] += 1
                if (cmd == "test" and status in ("fail", "warn", "error")
                        and len(failed_tests) < 100):
                    identifier = str(item.get("unique_id", ""))
                    # Limit untrusted project metadata for public CI evidence.
                    failed_tests.append(identifier[:220])
        except (OSError, ValueError, TypeError):
            statuses["unreadable_run_results"] += 1
    result = {
        "status": "ok" if proc.returncode == 0 else "nonzero",
        "returncode": proc.returncode,
        "test_statuses": dict(sorted(statuses.items())),
        "failed_test_ids": failed_tests,
        "executed_test_ids": executed_test_ids if cmd == "test" else [],
        "tests_executed": sum(statuses.values()) if cmd == "test" else 0,
    }
    # Deliberately opt-in diagnostic for synthetic CI only. dbt stdout can
    # contain user data or credentials: NEVER include by default.
    if proc.returncode != 0 and os.environ.get("DBT_CHAOS_SYNTHETIC_DEBUG") == "1":
        result["synthetic_debug"] = (proc.stdout + "\n" + proc.stderr)[-4500:]
    return result


def _table_snapshot(database: Path, manifest: Path, model: str) -> dict:
    try:
        import duckdb
    except ImportError as exc:
        raise ExternalProjectError("DuckDB Python dependency unavailable") from exc
    data = json.loads(manifest.read_text(encoding="utf8"))
    matches = [
        node for node in data.get("nodes", {}).values()
        if node.get("resource_type") == "model" and node.get("name") == model
    ]
    if len(matches) != 1:
        raise ExternalProjectError("target dbt model absent or ambiguous in manifest")
    node = matches[0]
    if node.get("config", {}).get("materialized") == "ephemeral":
        raise ExternalProjectError("ephemeral target cannot be queried as a table")
    pieces = [node.get("database"), node.get("schema"),
              node.get("alias") or model]
    parts = [_validate_name(part, "model relation identifier") for part in pieces]
    table = ".".join('"' + part + '"' for part in parts)
    with duckdb.connect(str(database), read_only=True) as con:
        cursor = con.execute(f"select * from {table}")
        columns = [c[0] for c in cursor.description]
        if len(set(columns)) != len(columns):
            raise ExternalProjectError("ambiguous duplicate output columns")
        rows = cursor.fetchmany(MAX_ROWS + 1)
        if len(rows) > MAX_ROWS:
            raise ExternalProjectError("model output exceeds bounded comparison limit")
        # Keep SQL NULL distinct from the empty string. Conflating them
        # makes an empty-vs-missing-data regression look benign.
        result = [tuple(None if v is None else str(v) for v in row)
                  for row in rows]
    return {
        "columns": columns,
        "rows": sorted(result, key=repr),
        "row_count": len(result),
        "node_id": node.get("unique_id"),
    }


def _compare(left: dict, right: dict) -> dict:
    if left["columns"] != right["columns"]:
        return {"equal": False, "columns_match": False,
                "removed_rows": None, "added_rows": None}
    one = Counter(map(tuple, left["rows"]))
    two = Counter(map(tuple, right["rows"]))
    return {
        "equal": one == two,
        "columns_match": True,
        "removed_rows": sum((one - two).values()),
        "added_rows": sum((two - one).values()),
    }


def _trusted_expected(path: Path, columns: list[str]) -> dict:
    # Explicit caller-owned reference; never derive it from the dbt baseline.
    header, rows = _read_csv(path)
    if header != columns:
        raise ExternalProjectError(
            "independently supplied expected output must match model column order")
    return {
        "columns": header,
        "rows": sorted(tuple(row[c] for c in header) for row in rows),
        "row_count": len(rows),
        "provenance": "caller_provided_reference_not_generated_by_target",
    }




def _public_mutation(metadata: dict) -> dict:
    """Provide replay evidence without leaking row IDs or raw input amounts."""
    return {
        "fault": metadata["fault"],
        "selected_row_sha256": sha256(
            metadata["selected_row"].encode("utf8")).hexdigest(),
        "source_row_identifier_redacted": True,
        "input_cell_values_redacted": True,
        "target_column": metadata["target_column"],
        "input_rows_before": metadata["input_rows_before"],
        "input_rows_after": metadata["input_rows_after"],
        "mutated_csv_sha256": metadata["mutated_csv_sha256"],
    }


def _numeric_impact(gold: dict | None, observed: dict,
                    metric_column: str | None) -> dict | None:
    """Measure trusted numeric output delta; unit is explicitly caller-defined."""
    if metric_column is None or gold is None:
        return None
    if gold["columns"] != observed["columns"]:
        raise ExternalProjectError("numeric comparison requires aligned columns")
    if metric_column not in gold["columns"]:
        raise ExternalProjectError("metric column missing from reference output")
    index = gold["columns"].index(metric_column)

    def total(rows: list) -> Decimal:
        amount = Decimal(0)
        for row in rows:
            item = row[index]
            if item is None:
                raise ExternalProjectError(
                    "numeric metric has NULL, cannot score its financial impact")
            try:
                value = Decimal(item)
            except (InvalidOperation, TypeError, ValueError) as exc:
                raise ExternalProjectError(
                    "metric values must all be finite numeric text") from exc
            if not value.is_finite():
                raise ExternalProjectError("numeric metric contains nonfinite value")
            amount += value
        return amount

    expected, actual = total(gold["rows"]), total(observed["rows"])
    signed = actual - expected
    return {
        "metric_column": metric_column,
        "metric_unit": "as_declared_by_caller_not_inferred",
        "expected_total": str(expected),
        "actual_total": str(actual),
        "signed_error": str(signed),
        "absolute_error": str(abs(signed)),
    }

def _copy_project(info: dict, dest: Path) -> Path:
    project = dest / "project"
    for relative in info["files"]:
        target = project / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(info["root"] / relative, target)
    return project


def _trial(info: dict, *, mutation: bytes | None, source_file: Path,
           model: str, timeout: int, test_scope: str = "full") -> dict:
    with tempfile.TemporaryDirectory(prefix="dbt-chaos-external-") as temp:
        root = Path(temp)
        project = _copy_project(info, root)
        if mutation is not None:
            (project / source_file).write_bytes(mutation)
        profiles = root / "profiles"
        profiles.mkdir()
        warehouse = root / "warehouse.duckdb"
        (profiles / "profiles.yml").write_text(
            _profile_yaml(info["profile"], warehouse), encoding="utf8")
        stages = {}
        for name in ("seed", "run"):
            stage = _run_dbt(name, project, profiles, root, model=model,
                             timeout=timeout, test_scope=test_scope)
            stages[name] = stage
            if stage["status"] != "ok":
                return {"execution": "failed_before_publication",
                        "failed_stage": name, "stages": stages}
        snapshot = _table_snapshot(
            warehouse, project / "target" / "manifest.json", model)
        manifest_data = json.loads(
            (project / "target" / "manifest.json").read_text(encoding="utf8"))
        available_tests = {
            uid for uid, node in manifest_data.get("nodes", {}).items()
            if node.get("resource_type") == "test"
        }
        stages["test"] = _run_dbt(
            "test", project, profiles, root, model=model, timeout=timeout,
            test_scope=test_scope)
        test = stages["test"]
        executed = set(test.get("executed_test_ids", []))
        test["test_scope"] = test_scope
        test["manifest_test_count"] = len(available_tests)
        test["unexecuted_manifest_test_count"] = len(available_tests - executed)
        test["tests_coverage_complete"] = (
            test_scope == "full" and bool(available_tests)
            and available_tests == executed
        )
        statuses = test["test_statuses"]
        if test["status"] == "timeout":
            verdict = "test_timeout"
        elif any(k in statuses for k in ("error", "runtime error",
                                         "unreadable_run_results")):
            verdict = "test_error"
        elif any(k in statuses for k in ("fail", "warn")):
            verdict = "test_detected"
        elif statuses.get("skipped", 0) or statuses.get("skip", 0):
            verdict = "test_incomplete"
        elif test["status"] != "ok":
            verdict = "test_error"
        elif not test["tests_executed"]:
            verdict = "no_tests_executed"
        elif test_scope == "full" and not test["tests_coverage_complete"]:
            verdict = "test_incomplete"
        elif any(k not in ("pass", "success") for k in statuses):
            verdict = "test_incomplete"
        else:
            verdict = "tests_passed"
        return {"execution": "completed", "snapshot": snapshot,
                "test_verdict": verdict, "stages": stages}


def run_external_campaign(
    *, project_dir: Path, model: str, seed_table: str,
    column: str, match_column: str, match_value: str, delta: int,
    faults: tuple[str, ...], independent_expected: Path | None,
    acknowledge_code_execution: bool, timeout: int = 90,
    test_scope: str = "full", metric_column: str | None = None,
) -> dict[str, Any]:
    """Run independent fresh-DB trials; never touch the user's warehouse."""
    if not acknowledge_code_execution:
        raise ExternalProjectError(
            "explicit --acknowledge-project-code-execution required; dbt macros "
            "and hooks are arbitrary code, so use a credential-free network-restricted VM")
    for label, value in (("model", model), ("seed", seed_table),
                         ("column", column), ("match column", match_column)):
        _validate_name(value, label)
    if metric_column is not None:
        _validate_name(metric_column, "metric column")
        if independent_expected is None:
            raise ExternalProjectError(
                "numeric business impact requires a caller-provided independent reference")
    if (test_scope not in ("full", "selected") or
            type(timeout) is not int or timeout < 10 or timeout > 240
            or not faults or len(set(faults)) != len(faults)
            or any(f not in FAULTS for f in faults)):
        raise ExternalProjectError("invalid timeout or fault selection")
    info = _inventory(project_dir)
    source_file = _seed_path(info, seed_table)
    source = info["root"] / source_file
    # Validate all mutations before executing any project code.
    trials = [
        build_mutation(source, f, column=column, match_column=match_column,
                       match_value=match_value, delta=delta)
        for f in faults
    ]
    clean = _trial(info, mutation=None, source_file=source_file,
                   model=model, timeout=timeout, test_scope=test_scope)
    if clean["execution"] != "completed":
        failed = clean.get("failed_stage", "unknown")
        detail = clean.get("stages", {}).get(failed, {})
        if os.environ.get("DBT_CHAOS_SYNTHETIC_DEBUG") == "1":
            raise ExternalProjectError(
                f"synthetic baseline {failed} failed: {detail}")
        raise ExternalProjectError(
            f"clean baseline dbt {failed} did not complete "
            f"(status={detail.get('status')}, code={detail.get('returncode')})")
    if clean.get("test_verdict") not in ("tests_passed", "no_tests_executed"):
        raise ExternalProjectError(
            "clean dbt tests must be green before attributing fault detection")
    baseline = clean["snapshot"]
    gold = (_trusted_expected(independent_expected, baseline["columns"])
            if independent_expected is not None else None)
    baseline_truth = _compare(gold, baseline) if gold else None
    if gold and not baseline_truth["equal"]:
        raise ExternalProjectError(
            "clean baseline disagrees with supplied independent gold; "
            "must repair/reference-validate before mutation scoring")
    baseline_metric = _numeric_impact(gold, baseline, metric_column)
    cases = []
    for mutation, metadata in trials:
        item = _trial(info, mutation=mutation, source_file=source_file,
                      model=model, timeout=timeout, test_scope=test_scope)
        if item["execution"] != "completed":
            cases.append({
                "fault": metadata["fault"], "mutation": _public_mutation(metadata),
                "outcome": "execution_failed_not_a_dbt_test_detection",
                "failed_stage": item.get("failed_stage"),
                "stages": item["stages"],
            })
            continue
        difference = _compare(baseline, item["snapshot"])
        truth = _compare(gold, item["snapshot"]) if gold else None
        if not difference["equal"]:
            if truth is None:
                outcome = ("drift_detected_by_tests"
                           if item["test_verdict"] == "test_detected"
                           else "unverified_output_drift")
            elif truth["equal"]:
                outcome = "changed_but_truth_preserved"
            elif item["test_verdict"] == "test_detected":
                outcome = "detected_business_mismatch"
            elif item["test_verdict"] == "tests_passed":
                outcome = ("silent_business_mismatch" if test_scope == "full"
                           else "mismatch_passed_selected_tests_only")
            else:
                outcome = "business_mismatch_unverified_test_execution"
        else:
            outcome = "unchanged_business_output"
        if metadata["fault"] == "reorder_rows":
            if item["test_verdict"] == "test_detected":
                outcome = "benign_control_false_alarm"
            elif item["test_verdict"] == "tests_passed" and difference["equal"]:
                outcome = "benign_control_passed"
            else:
                outcome = "benign_control_inconclusive"
        suggestion = {
            "amount_shift": "Reconcile amount against independent provider/ledger events; nullability cannot verify plausible values",
            "drop_row": "Test completeness against an independent event count or immutable delivery sequence",
            "duplicate_row": "Enforce a stable business-key uniqueness invariant before aggregation",
            "reorder_rows": "Benign ordering control: no business value or key-set change should fail quality gates",
        }[metadata["fault"]]
        cases.append({
            "fault": metadata["fault"], "mutation": _public_mutation(metadata),
            "next_business_invariant_to_check": suggestion,
            "outcome": outcome, "difference_from_baseline": difference,
            "difference_from_independent_truth": truth,
            "numeric_business_impact": _numeric_impact(gold, item["snapshot"], metric_column),
            "test_verdict": item["test_verdict"],
            "tests_executed": item["stages"]["test"]["tests_executed"],
            "manifest_test_count": item["stages"]["test"]["manifest_test_count"],
            "unexecuted_manifest_test_count":
                item["stages"]["test"]["unexecuted_manifest_test_count"],
            "test_scope": test_scope,
            "test_statuses": item["stages"]["test"]["test_statuses"],
            "failed_test_ids": item["stages"]["test"].get("failed_test_ids", []),
            "output_rows": item["snapshot"]["row_count"],
        })
    return {
        "format": FORMAT,
        "engine": "real_dbt_core_and_duckdb",
        "project": info["name"],
        "model": model, "model_node_id": baseline["node_id"],
        "seed": seed_table, "seed_path": source_file.as_posix(),
        "original_files": len(info["files"]),
        "clean_baseline_test_verdict": clean["test_verdict"],
        "test_scope": test_scope,
        "test_scope_description": (
            "Full dbt run and test across the project" if test_scope == "full"
            else "Only the target model and its upstream dbt graph; "
                 "downstream and unrelated tests may not have been executed"
        ),
        "baseline_manifest_test_count":
            clean["stages"]["test"]["manifest_test_count"],
        "baseline_tests_executed":
            clean["stages"]["test"]["tests_executed"],
        "baseline_test_coverage_complete":
            clean["stages"]["test"]["tests_coverage_complete"],
        "baseline_rows": baseline["row_count"],
        "metric_column": metric_column,
        "baseline_numeric_business_impact": baseline_metric,
        "independent_gold_supplied": gold is not None,
        "external_gold_provenance_cryptographically_verified": False,
        "gold_provenance_assumption": (
            "caller_supplied_and_claimed_independent_not_verifiable_by_adapter"
            if gold is not None else "no_external_gold"),
        "fault_proposals_authored_by_llm": False,
        "clean_baseline_matches_independent_gold":
            baseline_truth["equal"] if baseline_truth else None,
        "causal_claim": "separate_bounded_seed_mutation_runs_not_agent_error_rates",
        "requires_explicit_project_code_execution_acknowledgement": True,
        "not_a_security_sandbox": True,
        "no_production_credentials_or_profile_copied": True,
        "cases": cases,
        "silent_business_mismatches": sum(
            c["outcome"] == "silent_business_mismatch" for c in cases),
        "benign_controls_run": sum(c["fault"] == "reorder_rows" for c in cases),
        "benign_false_alarms": sum(
            c["outcome"] == "benign_control_false_alarm" for c in cases),
        "caution": (
            "Without caller-supplied independent gold, output drift is not "
            "evidence of incorrect business data. dbt test coverage is not "
            "equivalent to correctness; SQL/macros/hooks can execute code."
        ),
    }


def write_external_report(report: dict, target: Path) -> None:
    if target.is_symlink() or target.exists():
        raise ExternalProjectError("output path must be new and not a symlink")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                      encoding="utf8")
