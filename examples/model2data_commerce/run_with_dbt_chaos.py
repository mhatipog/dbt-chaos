"""Run dbt-chaos's real commerce runner on these CSVs instead of its built-in data.

    pip install -e '.[dbt]'                       # from the repository root
    python examples/model2data_commerce/run_with_dbt_chaos.py
    python examples/model2data_commerce/run_with_dbt_chaos.py --out results.json

Only dbt-chaos's `baseline()` and `inject_source()` are replaced, and only while the runs
last: its dbt SQL, source and gold tests, reference calculation and classification all run
unchanged. The source-fault label passed to dbt-chaos only names the case; the data comes
from the variant folder.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from unittest import mock

from dbt_chaos import commerce, commerce_runner
from dbt_chaos.commerce import CommerceCase

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
TABLES = ("customers", "orders", "payments")
INTS = {"row_id", "customer_id", "order_id", "payment_id", "version", "gross_cents", "amount_cents"}

# (variant folder, dbt-chaos source-fault label, dbt-chaos SQL fault, expected classification)
RUNS = [
    ("baseline", "none", "none", "correct"),
    ("baseline", "none", "skip_customer_dedup", "correct"),
    ("missing_dimension/fault", "orphan_customer", "none", "contained"),
    ("missing_dimension/control", "none", "none", "correct"),
    ("duplicate_join_key/fault", "duplicate_customer", "none", "contained"),
    ("duplicate_join_key/fault", "duplicate_customer", "skip_customer_dedup", "silent_corruption"),
    ("duplicate_join_key/control", "none", "none", "correct"),
    ("duplicate_join_key/control", "none", "skip_customer_dedup", "silent_corruption"),
]


def load(folder: Path) -> dict[str, list[dict]]:
    tables = {}
    for table in TABLES:
        with (folder / f"{table}.csv").open(newline="", encoding="utf8") as handle:
            tables[table] = [
                {k: int(v) if k in INTS else v for k, v in row.items()}
                for row in csv.DictReader(handle)
            ]
    return tables


def run(data: Path = DATA, echo: bool = False) -> list[dict]:
    """Every case of RUNS through the real runner, in order; one result dict per case."""
    baseline = load(data / "baseline")
    results = []
    # The baseline is the "original business snapshot" dbt-chaos compares every run to.
    with mock.patch.object(commerce, "baseline", lambda: baseline):
        for folder, source_label, sql_fault, _expected in RUNS:
            variant = load(data / folder)

            def inject(_fault: str, variant: dict = variant) -> dict:
                return variant

            with mock.patch.object(commerce, "inject_source", inject), mock.patch.object(
                commerce_runner, "inject_source", inject
            ):
                result = commerce_runner.run_case(
                    CommerceCase(source_fault=source_label, logic_fault=sql_fault)
                )
            result["variant"] = folder
            results.append(result)
            if echo:
                print(
                    f"{folder:28} sql={sql_fault:20} {result['classification']:18} "
                    f"source_alerts={result['source_alerts']} "
                    f"mismatched_gold_rows={result['mismatched_gold_keys']}",
                    flush=True,
                )
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("data", type=Path, nargs="?", default=DATA, help="the data/ folder")
    parser.add_argument("--out", type=Path, help="write every run's full result as JSON")
    args = parser.parse_args()
    results = run(args.data, echo=True)
    if args.out:
        args.out.write_text(json.dumps(results, indent=1, default=str) + "\n", encoding="utf8")


if __name__ == "__main__":
    main()
