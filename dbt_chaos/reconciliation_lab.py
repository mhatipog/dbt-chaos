"""One-command reproducible multi-source reconciliation assessment.

Generate FULL synthetic operational, provider, GL and settlement CSV feeds,
evaluate a real native dbt pipeline, and keep the independent process gold
sealed from the platform under test.

This module does not run an LLM. The original 20261119 Qwen refund edit is
replayed as a frozen, previously observed typed operation; all additional
corruption controls are deterministic scripted counterfactuals.
"""
from __future__ import annotations

import argparse
import csv
from hashlib import sha256
import io
import json
from pathlib import Path, PurePosixPath

from .commerce import CommerceCase, oracle
from .commerce_runner import COLUMNS, RECONCILIATION_COLUMNS, run_case
from .reconciliation import make_scenarios, reconcile, score_against_process
from .relay_platform_replay import score_publication

FORMAT = "dbt_chaos_multisource_evidence_v1"


def _as_csv(headers: tuple[str, ...], records: list[dict]) -> bytes:
    stream = io.StringIO(newline="")
    out = csv.DictWriter(stream, fieldnames=headers, lineterminator="\n")
    out.writeheader()
    out.writerows(records)
    return stream.getvalue().encode("utf-8")


def _gold_map(data: dict[tuple[str, str], int]) -> dict[str, int]:
    return {f"{day}|{segment}": cents
            for (day, segment), cents in sorted(data.items())}


def _separate(public: Path, private: Path):
    a, b = public.resolve(), private.resolve()
    if a == b or a in b.parents or b in a.parents:
        raise ValueError("Public inputs and private oracle must be in disjoint folders")
    if any(p.exists() and (not p.is_dir() or any(p.iterdir()))
           for p in (public, private)):
        raise ValueError("Output folders must be new or empty")


def export_scenario(case_name: str, *, public_dir: Path, private_dir: Path,
                    seed: int = 20261119) -> dict:
    _separate(public_dir, private_dir)
    dataset = make_scenarios(seed)
    if case_name not in dataset["cases"]:
        raise ValueError("unknown reconciliation scenario: " + case_name)
    case = dataset["cases"][case_name]
    public_dir.mkdir(parents=True, exist_ok=True)
    private_dir.mkdir(parents=True, exist_ok=True)
    manifest_files = {}
    for name, headers in {**COLUMNS, **RECONCILIATION_COLUMNS}.items():
        records = case["source"][name] if name in COLUMNS else case["evidence"][name]
        relative = f"inputs/{name}.csv"
        content = _as_csv(headers, records)
        file = public_dir / relative
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(content)
        manifest_files[relative] = {
            "sha256": sha256(content).hexdigest(),
            "rows": len(records),
            "bytes": len(content),
        }
    digest = sha256(json.dumps({
        "scenario": case_name, "seed": seed,
        "files": manifest_files,
    }, sort_keys=True).encode()).hexdigest()[:20]
    meta = {
        "format": FORMAT, "challenge_id": digest,
        "scenario": case_name, "seed": seed,
        "evidence_lag_days": case["as_of_lag_days"],
        "model_decisions_frozen_not_regenerated": True,
        "correlated_provenance": {
            "operational_payments": "merchant_application",
            "accounting_journal": "merchant_application",
            "provider_transactions": "independent_psp",
            "bank_batches": "independent_bank",
        },
        "raw_source_files": manifest_files,
        "gold_schema": ["order_day", "segment", "revenue_cents"],
        "business_oracle_included": False,
        "instructions": (
            "Load only inputs/ into isolated test platform. Do not expose "
            "private answer key. Run source checks and reconciliation "
            "against available evidence at evidence_lag_days, then publish "
            "reporting groups not quarantined or held. No silent zero fill."
        ),
    }
    raw = (json.dumps(meta, indent=2, sort_keys=True)+"\n").encode()
    (public_dir / "manifest.json").write_bytes(raw)
    notes = f"""# dbt-chaos independent evidence challenge: {case_name}

**Synthetic-only data. Do not run on production.** Replayed evidence
corruption, NOT new model inference.

The six CSV inputs represent operational customers/orders/payments, an
independent PSP transaction feed, an accounting journal derived from the
merchant operational event flow, and independent bank-like daily net
settlement buckets. The accounting journal and operational payments
are correlated evidence, not two independent confirmations.

The bank-style contract deliberately uses order-day buckets, no fees, no
FX and no real payout calendar. This is a **reconciliation benchmark
simplification**, not a genuine bank statement.

**As-of evidence lag:** {case["as_of_lag_days"]} days.
Only provider/journal/bank rows whose `available_after_days` is at most
this lag are visible. Late records are pending until their configured
SLA, not automatically invalid.

Business output contract: completed EUR orders, latest version of
customers/orders/payments, capture less refund cents grouped by
order_day and latest customer segment.

Export the ACTUALLY PUBLISHED groups in a file `published.csv` with:
`order_day,segment,revenue_cents`.

Optionally include `held.csv` (`order_day,segment`) listing reporting
groups deliberately withheld. Empty published output is represented by
a CSV with a header only.

To score your result, only the PRIVATE evaluator may access the answer key:
`dbt-chaos score-reconciliation --public-dir /challenge --answer-key
/private/answer_key.json --published /result/published.csv
--held /result/held.csv --out result.json`.

This tool never runs the external platform or accesses its credentials.
"""
    (public_dir / "README.md").write_text(notes)
    from .full_datasets import absolute_group_error
    true_gold = oracle(dataset["truth"])
    admitted_gold = oracle(case["source"])
    # Store exactly the process truth and enough metadata to reproduce the
    # benchmark independently, in the private evaluator only.
    key = {
        "format": FORMAT, "challenge_id": digest,
        "manifest_sha256": sha256(raw).hexdigest(),
        "scenario": case_name, "seed": seed,
        "expected_business_gold": _gold_map(true_gold),
        "expected_from_admitted_source": _gold_map(admitted_gold),
        "original_business_event_log": dataset["events"],
        "provenance": case["provenance"],
        "reference_detectability": reconcile(
            case["source"], case["evidence"],
            as_of_lag_days=case["as_of_lag_days"]),
    }
    (private_dir / "answer_key.json").write_text(
        json.dumps(key, indent=2, sort_keys=True)+"\n")
    return {
        "challenge_id": digest, "scenario": case_name,
        "seed": seed, "evidence_lag_days":case["as_of_lag_days"],
        "public_dir": str(public_dir),
        "private_dir": str(private_dir),
        "source_business_discrepancy_cents": absolute_group_error(
            true_gold, admitted_gold),
        "file_count": len(manifest_files),
        "sealed_answer_key": True,
    }


def _parse_gold(path: Path, *, kind: str) -> dict[tuple[str, str], int]:
    if not path.is_file():
        raise FileNotFoundError(f"{kind} file missing: {path}")
    results = {}
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        expected = ["order_day", "segment", "revenue_cents"] if kind == "published" else [
            "order_day", "segment"]
        if reader.fieldnames != expected:
            raise ValueError(f"{kind} CSV columns should be {expected}")
        for row in reader:
            key = (row["order_day"], row["segment"])
            if key in results:
                raise ValueError(f"duplicate {kind} grain: {key}")
            if kind == "published":
                value = int(row["revenue_cents"])
                results[key] = value
            else:
                results[key] = True
    return results


def score_scenario(*, public_dir: Path, answer_key: Path,
                   published: Path, held: Path | None = None) -> dict:
    metadata_bytes = (public_dir / "manifest.json").read_bytes()
    manifest = json.loads(metadata_bytes)
    key = json.loads(answer_key.read_text())
    if manifest.get("format") != FORMAT or key.get("format") != FORMAT:
        raise ValueError("incompatible evidence challenge format")
    if manifest["challenge_id"] != key["challenge_id"]:
        raise ValueError("public challenge and private oracle do not match")
    if sha256(metadata_bytes).hexdigest() != key["manifest_sha256"]:
        raise ValueError("public challenge manifest was modified")
    for relative, spec in manifest["raw_source_files"].items():
        parts = PurePosixPath(relative)
        if parts.is_absolute() or ".." in parts.parts or not relative.startswith("inputs/"):
            raise ValueError("untrusted challenge file path")
        blob = (public_dir / relative).read_bytes()
        if sha256(blob).hexdigest() != spec["sha256"] or len(blob) != spec["bytes"]:
            raise ValueError(f"source evidence changed: {relative}")
        if blob.count(b"\n") - 1 != spec["rows"]:
            raise ValueError(f"source evidence rows changed: {relative}")
    expected = {tuple(k.split("|", 1)):v
                for k, v in key["expected_business_gold"].items()}
    admitted = {tuple(k.split("|", 1)):v
                for k, v in key["expected_from_admitted_source"].items()}
    actual = _parse_gold(published, kind="published")
    held_keys = set(_parse_gold(held, kind="held")) if held else set()
    if held_keys - (set(expected) | set(actual)):
        raise ValueError("held group not in original business or published data")
    evaluated = score_publication(expected, actual, held_keys)
    relative_error = sum(
        abs(actual.get(k, 0) - admitted.get(k, 0))
        for k in (set(actual)|set(admitted))-held_keys
    )
    observable = key["reference_detectability"]
    source_l1 = sum(abs(expected.get(k,0)-admitted.get(k,0))
                    for k in set(expected)|set(admitted))
    detectability = (
        "no_business_error" if source_l1==0 else
        "observable_inconsistency" if observable["findings"] else
        "not_yet_observable" if observable["status"]=="pending_evidence" else
        "unobservable_with_provided_evidence"
    )
    platform_missed_detectable_error = (
        detectability == "observable_inconsistency"
        and bool(evaluated["false_published_groups"] or
                 evaluated["silent_missing_groups"])
    )
    return {
        "format": FORMAT, "challenge_id":manifest["challenge_id"],
        "detectability_given_available_evidence": detectability,
        "platform_published_error_despite_observable_dispute":
            platform_missed_detectable_error,
        "evidence_has_authenticated_independent_roots": False,
        "source_vs_business_error_cents":source_l1,
        "scenario": manifest["scenario"],
        "native_external_platform_run": False,
        "actual_external_platform_output_scored": True,
        "business_score": evaluated,
        "relative_to_admitted_source_l1_cents":relative_error,
        "observable_reference_disputes":len(observable["findings"]),
        "observable_reference_status":observable["status"],
        "observable_reference_held_groups":observable["held_groups"],
        "oracle_hidden_from_platform":True,
        "warnings":[
            "Reference detectability is a synthetic comparator, not proof "
            "that the external platform actually executed those checks.",
            "A correct number does not establish an evidence-backed repair.",
            "A missing published row without a held-group declaration is an error.",
        ],
    }


def run_native_demo(scenario: str = "qwen_refund_source_only") -> dict:
    data = make_scenarios()
    if scenario not in data["cases"]:
        raise ValueError("unknown reconciliation case: " + scenario)
    item = data["cases"][scenario]
    observable = reconcile(item["source"], item["evidence"],
                           as_of_lag_days=item["as_of_lag_days"])
    reference_score = score_against_process(
        item["source"], observable, data["truth"])
    report = run_case(
        CommerceCase(), admitted_data=item["source"],
        process_data=data["truth"], reconciliation_enabled=True,
        reconciliation_evidence=item["evidence"],
        reconciliation_as_of_lag_days=item["as_of_lag_days"],
    )
    native = report["native_reconciliation"]
    truth = oracle(data["truth"])
    original = {tuple(k.split("|", 1)):v for k,v in report["observed"].items()}
    raw_score = score_publication(truth, original, set())
    released = {tuple(k.split("|", 1)):v for k,v in native["released_gold"].items()}
    held = {tuple(k.split("|", 1)) for k in native["held_groups"]}
    if native["release_status"] == "withheld_all":
        held |= set(truth)
    published_score = score_publication(truth, released, held)
    return {
        "experiment":"native_multisource_reconciliation_v1",
        "case":scenario, "case_provenance":item["provenance"],
        "seed":data["seed"], "as_of_lag_days":item["as_of_lag_days"],
        "real_native_dbt_executed":native["models_executed_by_dbt"],
        "raw_dbt_source_alerts":report["source_alerts"],
        "raw_dbt_output_alerts":report["output_alerts"],
        "baseline_publication":raw_score,
        "observable_reconciliation":observable,
        "reference_reconciliation_score":reference_score,
        "native_dbt_reconciliation":native,
        "native_published_business_score":published_score,
        "limitations":[
            "No real payment provider or bank statements: evidence is synthetic.",
            "Bank batches use synthetic order-day periods without fees/FX.",
            "The provider and bank independence roots are assumptions, not signed credentials.",
            "The reconciler withholds wrong or uncertain groups; it does not infer a repair.",
            "The process ledger is used only for grading, never for native dbt decisions.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description="Multi-source financial truth reconciliation")
    sub = parser.add_subparsers(dest="command",required=True)
    demo = sub.add_parser("demo")
    demo.add_argument("--scenario",default="qwen_refund_source_only")
    demo.add_argument("--out",type=Path,required=True)
    exp = sub.add_parser("export")
    exp.add_argument("--scenario",default="qwen_refund_source_only")
    exp.add_argument("--public-dir",type=Path,required=True)
    exp.add_argument("--private-dir",type=Path,required=True)
    score = sub.add_parser("score")
    score.add_argument("--public-dir",type=Path,required=True)
    score.add_argument("--answer-key",type=Path,required=True)
    score.add_argument("--published",type=Path,required=True)
    score.add_argument("--held",type=Path)
    score.add_argument("--out",type=Path,required=True)
    args = parser.parse_args()
    if args.command=="demo":
        outcome=run_native_demo(args.scenario)
        args.out.parent.mkdir(parents=True,exist_ok=True)
        args.out.write_text(json.dumps(outcome,indent=2,sort_keys=True)+"\n")
        print(json.dumps({
            "scenario":outcome["case"],
            "baseline":outcome["baseline_publication"]["status"],
            "native":outcome["native_published_business_score"]["status"],
            "native_disputes":outcome["native_dbt_reconciliation"]["dispute_count"],
            "native_held_groups":outcome["native_dbt_reconciliation"]["held_group_count"],
        },indent=2))
    elif args.command=="export":
        print(json.dumps(export_scenario(
            args.scenario,public_dir=args.public_dir,
            private_dir=args.private_dir),indent=2))
    else:
        outcome=score_scenario(
            public_dir=args.public_dir,answer_key=args.answer_key,
            published=args.published,held=args.held)
        args.out.parent.mkdir(parents=True,exist_ok=True)
        args.out.write_text(json.dumps(outcome,indent=2,sort_keys=True)+"\n")
        print(json.dumps(outcome,indent=2))


if __name__=="__main__":
    main()
