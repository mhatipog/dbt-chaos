"""Vendor-neutral chaos assessment using exported source CSVs + hidden answer key.

Workflow:
  1. Generate a synthetic process and record a weak-LLM source edit chain.
  2. Export public CLEAN and CHAOS CSV inputs for ANY data platform.
  3. Keep the independent business truth / source oracle in a SEPARATE path.
  4. Run the platform yourself and export clean.csv / chaos.csv final results.
  5. Score what it actually published; separately report warnings and held
     groups. Never call an alert alone a quarantine or an exact-value result
     a verified repair without evidence.

No credentials, production connections, dynamic SQL or vendor-specific code.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import csv
from hashlib import sha256
import io
import json
from pathlib import Path
from typing import Any

from .audit_corpus import audit_corpus, read_gold, read_tables
from .commerce_runner import COLUMNS
from .full_datasets import absolute_group_error
from .relay_platform_replay import score_publication

GOLD_COLUMNS = ("order_day", "segment", "revenue_cents")
SCENARIOS = ("clean", "chaos")
FORMAT = "dbt_chaos_external_challenge_v1"


def _csv_bytes(columns: tuple[str, ...], rows: list[dict]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf8")


def _gold_map(gold: dict[tuple[str, str], int]) -> dict[str, int]:
    return {f"{d}|{s}": int(v) for (d, s), v in sorted(gold.items())}


def _parse_gold_map(mapping: dict[str, int]) -> dict[tuple[str, str], int]:
    return {tuple(key.split("|", 1)): int(value)
            for key, value in mapping.items()}


def _nonoverlap(public: Path, private: Path) -> None:
    p, q = public.resolve(), private.resolve()
    if p == q or p in q.parents or q in p.parents:
        raise ValueError(
            "public inputs and private oracle directories MUST be disjoint; "
            "never place hidden truth under a published path")


def export_external_challenge(*, corpus: Path, public_dir: Path,
                              private_dir: Path, step: int | None = None) -> dict:
    """Only source CSVs and workload contract go to the public platform."""
    _nonoverlap(public_dir, private_dir)
    if any(p.exists() and (not p.is_dir() or any(p.iterdir()))
           for p in (public_dir, private_dir)):
        raise ValueError("public and private output directories must be empty")
    verified = audit_corpus(corpus)
    trace = json.loads((corpus / "trace.json").read_text(encoding="utf8"))
    last = len(trace["steps"])
    chosen = last if step is None else step
    if not 1 <= chosen <= last:
        raise ValueError(f"step must be 1..{last}")
    truth = read_tables(corpus, "ledger/source_of_truth")
    delivered = read_tables(
        corpus, f"steps/{chosen:02d}/source_delivery")
    business_gold = read_gold(corpus, "ledger/business_gold.csv")
    delivered_gold = read_gold(corpus, f"steps/{chosen:02d}/admitted_gold.csv")

    public_dir.mkdir(parents=True, exist_ok=True)
    private_dir.mkdir(parents=True, exist_ok=True)
    files = {}
    for scenario, tables in (("clean", truth), ("chaos", delivered)):
        for table in ("customers", "orders", "payments"):
            rel = f"inputs/{scenario}/{table}.csv"
            content = _csv_bytes(COLUMNS[table], tables[table])
            file = public_dir / rel
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(content)
            files[rel] = {
                "sha256": sha256(content).hexdigest(),
                "rows": len(tables[table]), "bytes": len(content),
            }
    check_id = sha256(json.dumps({
        "model": trace["model"], "seed": trace["seed"], "step": chosen,
        "file_hashes": {f: info["sha256"] for f, info in files.items()},
    }, sort_keys=True).encode()).hexdigest()[:20]
    manifest = {
        "format": FORMAT, "challenge_id": check_id,
        "workload": "synthetic_eur_commerce_latest_customer_and_order_versions",
        "source_model": trace["model"],
        "source_model_sha256": trace.get("model_sha256"),
        "model_actions_replayed_not_regenerated": True,
        "seed": trace["seed"], "source_step": chosen,
        "source_mode": trace.get("context_mode"),
        "input_files": files,
        "expected_publication_schema": list(GOLD_COLUMNS),
        "publishable_truth_included": False,
        "policy": (
            "Run each input separately; only expose inputs/{clean,chaos}. "
            "Do NOT give the platform a private answer key or source ledger."
        ),
    }
    manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True)
                      + "\n").encode()
    (public_dir / "manifest.json").write_bytes(manifest_bytes)
    readme = f"""# dbt-chaos platform challenge {check_id}

These are complete *synthetic* commerce tables. There are two independent
inputs: `inputs/clean` and `inputs/chaos`.

Use the EXACT SAME pipeline configuration for both. In each run, replace the
three source tables (`customers`, `orders`, `payments`) with the supplied
CSV, then export the final metric as a CSV with precisely these fields:

    order_day,segment,revenue_cents

Write the two results as `clean.csv` and `chaos.csv` in one separate folder.
Include every date x segment row that the pipeline actually PUBLISHED; do
NOT invent zero rows for reports held back.

Reference business contract: take the highest version per customer ID and
order ID, use the latest payment version per payment ID, include only
completed EUR orders, sum captured payment cents and subtract refund cents
per date x customer segment. Source retries should be idempotent.

If output was intentionally withheld, optionally create
`held/clean.csv` or `held/chaos.csv` containing order_day,segment.
If the platform emitted real alerts, optionally provide an alerts JSON
with `{{"clean":["alert text"],"chaos":["alert text"]}}`.
An alert is not proof that wrong data was prevented from publication.
A claimed quarantine record is not proof of physical quarantine without
a separately verifiable rejected-row table.

Only `inputs/` should be loaded into the platform. The independent answer
key is in a *different filesystem directory* to avoid leaking truth.

Reproduce scoring (Python package locally installed):
    dbt-chaos score-challenge --public-dir PATH_TO_PUBLIC_CHALLENGE \\
      --answer-key PATH_TO_PRIVATE_ANSWER_KEY/answer_key.json \\
      --published-dir PATH_TO_YOUR_OUTPUTS --out result.json

This reference workload is commerce-specific. The scoring interface is
vendor-neutral; it does not automatically deploy code into an existing dbt,
Fabric or Databricks project.
"""
    (public_dir / "README.md").write_text(readme)
    key = {
        "format": FORMAT, "challenge_id": check_id,
        "public_manifest_sha256": sha256(manifest_bytes).hexdigest(),
        "source_model": trace["model"], "source_step": chosen,
        "event_log_sha256": sha256(
            (corpus / "ledger/process_events.jsonl").read_bytes()).hexdigest(),
        "expected_business": _gold_map(business_gold),
        "expected_given_source": {
            "clean": _gold_map(business_gold),
            "chaos": _gold_map(delivered_gold),
        },
        "business_ledger_original_tables": truth,
        "delivered_tables": delivered,
    }
    (private_dir / "answer_key.json").write_text(
        json.dumps(key, sort_keys=True, indent=2) + "\n")
    return {
        "challenge_id": check_id, "verified_source_corpus": verified["verified"],
        "source_step": chosen, "model": trace["model"],
        "public_inputs": str(public_dir),
        "private_key": str(private_dir / "answer_key.json"),
        "input_rows": {scenario: {table: len(tables[table])
                        for table in ("customers", "orders", "payments")}
                       for scenario, tables in (("clean", truth), ("chaos", delivered))},
        "source_business_l1_cents": absolute_group_error(
            business_gold, delivered_gold),
        "separation_verified": True,
    }


def _read_held(file: Path) -> set[tuple[str, str]]:
    with file.open(newline="", encoding="utf8") as f:
        reader = csv.DictReader(f)
        if set(reader.fieldnames or []) != {"order_day", "segment"}:
            raise ValueError(f"invalid held-group CSV header: {file}")
        values = set()
        for row in reader:
            key = (row["order_day"], row["segment"])
            if key in values:
                raise ValueError(f"duplicate held group: {key}")
            values.add(key)
        return values


def _safe_alerts(path: Path | None) -> dict[str, list[str]]:
    if path is None:
        return {name: [] for name in SCENARIOS}
    obj = json.loads(path.read_text(encoding="utf8"))
    if set(obj) != set(SCENARIOS) or not all(
            isinstance(obj[name], list) and all(
                isinstance(x, str) and len(x) <= 500 for x in obj[name])
            and len(obj[name]) <= 500
            for name in SCENARIOS):
        raise ValueError("alerts JSON must have clean and chaos string lists")
    return obj


def score_external_challenge(
    *, public_dir: Path, answer_key: Path,
    published_dir: Path, held_dir: Path | None = None,
    alerts_json: Path | None = None,
) -> dict:
    from .audit_corpus import read_gold
    manifest_bytes = (public_dir / "manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    key = json.loads(answer_key.read_text(encoding="utf8"))
    if manifest.get("format") != FORMAT or key.get("format") != FORMAT:
        raise ValueError("unrecognized external challenge format")
    if key["challenge_id"] != manifest["challenge_id"]:
        raise ValueError("public challenge and answer key do not match")
    if sha256(manifest_bytes).hexdigest() != key["public_manifest_sha256"]:
        raise ValueError("manifest changed since hidden answer key was issued")
    for rel, spec in manifest["input_files"].items():
        if (rel.startswith("/") or ".." in Path(rel).parts
                or not rel.startswith(("inputs/clean/", "inputs/chaos/"))):
            raise ValueError("unsafe challenge input path")
        data = (public_dir / rel).read_bytes()
        if sha256(data).hexdigest() != spec["sha256"]:
            raise ValueError(f"challenge input checksum mismatch: {rel}")
        if len(data) != spec["bytes"]:
            raise ValueError(f"challenge input size mismatch: {rel}")
        if data.count(b"\n") - 1 != spec["rows"]:
            raise ValueError(f"challenge input row-count mismatch: {rel}")

    truth = _parse_gold_map(key["expected_business"])
    warnings = _safe_alerts(alerts_json)
    evaluations = {}
    for scenario in SCENARIOS:
        observed_file = published_dir / f"{scenario}.csv"
        # Missing results must not be treated as a successful quarantine.
        if not observed_file.is_file():
            raise FileNotFoundError(
                f"need actual publication CSV even if only its header: {observed_file}")
        published = read_gold(published_dir, f"{scenario}.csv")
        held_file = (held_dir / f"{scenario}.csv"
                     if held_dir is not None else None)
        held = _read_held(held_file) if held_file and held_file.is_file() else set()
        if held - (set(truth) | set(published)):
            raise ValueError(f"unknown held reporting groups: {scenario}")
        actual = score_publication(truth, published, held)
        expected_source = _parse_gold_map(
            key["expected_given_source"][scenario])
        # Detect transformation differences on released groups, excluding
        # intentional held ones; explicitly report source-only and output
        # error separately without pretending their L1 values are additive.
        released = (set(truth) | set(expected_source) | set(published)) - held
        relative_to_admitted = sum(
            abs(published.get(g, 0) - expected_source.get(g, 0))
            for g in released)
        source_to_truth = absolute_group_error(truth, expected_source)
        missing = actual["silent_missing_groups"]
        incorrect = actual["false_published_groups"]
        if actual["status"] == "held":
            verdict = "all_withheld"
        elif not incorrect and not missing and held:
            verdict = "safe_partial_hold"
        elif not incorrect and not missing:
            verdict = ("correct_output_external_evidence_not_verified"
                       if source_to_truth else "business_correct")
        elif warnings[scenario]:
            verdict = "detected_but_exposed"
        elif relative_to_admitted == 0 and source_to_truth > 0:
            verdict = "garbage_passed_through"
        elif relative_to_admitted > 0:
            verdict = "transformation_or_unexplained_output_error"
        else:
            verdict = "silent_corruption_or_missing_source"
        evaluations[scenario] = {
            "verdict": verdict, "published": actual,
            "alert_count": len(warnings[scenario]),
            "alerts": warnings[scenario],
            "source_to_process_l1_cents": source_to_truth,
            "published_vs_admitted_l1_cents": relative_to_admitted,
            "held_group_count": len(held),
            "actual_published_group_count": len(published),
            "note": (
                "Results are graded against hidden synthetic business events. "
                "No repair/protection is credited merely because an alert "
                "or an apparently correct final number was supplied."
            ),
        }
    return {
        "format": FORMAT, "challenge_id": manifest["challenge_id"],
        "original_agent": key["source_model"],
        "original_model_step": key["source_step"],
        "external_platform_assessment": True,
        "scoring_does_not_execute_external_sql": True,
        "results": evaluations,
        "clean_baseline_wrong": evaluations["clean"]["published"]["status"]
                                == "silently_wrong",
        "wrong_chaos_published_groups": len(
            evaluations["chaos"]["published"]["false_published_groups"]),
        "correct_business_value_fraction_chaos": evaluations["chaos"]["published"]
                                               ["fraction_of_correct_business_value_published"],
        "limitations": [
            "CSV-based outcome scoring is platform-neutral, but the bundled workload is commerce-specific.",
            "No platform-specific quarantine or security policy is automatically installed.",
            "Declared alerts are not physical quarantine evidence.",
            "Correct output with corrupted source does not prove evidence-backed recovery.",
        ],
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Export or score vendor-neutral commerce chaos challenge")
    cmd = ap.add_subparsers(dest="command", required=True)
    exp = cmd.add_parser("create")
    exp.add_argument("--corpus", type=Path, required=True)
    exp.add_argument("--public-dir", type=Path, required=True)
    exp.add_argument("--private-dir", type=Path, required=True)
    exp.add_argument("--step", type=int)
    score = cmd.add_parser("score")
    score.add_argument("--public-dir", type=Path, required=True)
    score.add_argument("--answer-key", type=Path, required=True)
    score.add_argument("--published-dir", type=Path, required=True)
    score.add_argument("--held-dir", type=Path)
    score.add_argument("--alerts-json", type=Path)
    score.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    if args.command == "create":
        report = export_external_challenge(
            corpus=args.corpus, public_dir=args.public_dir,
            private_dir=args.private_dir, step=args.step)
    else:
        report = score_external_challenge(
            public_dir=args.public_dir, answer_key=args.answer_key,
            published_dir=args.published_dir, held_dir=args.held_dir,
            alerts_json=args.alerts_json)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
    print(json.dumps(report, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
