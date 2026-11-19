"""The model2data commerce dataset in examples/model2data_commerce.

The byte checks need nothing but the standard library. The dbt runs are only enabled with
the dbt extras, like test_commerce_dbt.py, and must reproduce the committed results.
"""
import csv
import hashlib
import importlib.util
import json
import sys
import unittest
from pathlib import Path

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "model2data_commerce"
MANIFEST = json.loads((EXAMPLE / "manifest.json").read_text(encoding="utf8"))
RESULTS = json.loads((EXAMPLE / "dbt_results.json").read_text(encoding="utf8"))
STABLE = ("variant", "case", "classification", "source_alerts", "output_alerts",
          "contract_difference", "mismatched_gold_keys",
          "net_synthetic_cents_difference", "absolute_synthetic_cents_difference")


def _runner():
    spec = importlib.util.spec_from_file_location(
        "model2data_commerce_runner", EXAMPLE / "run_with_dbt_chaos.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _stable(result):
    return {key: result[key] for key in STABLE if key in result}


class Model2dataDatasetTests(unittest.TestCase):
    def test_every_csv_matches_its_manifest_hash(self):
        for name, variant in MANIFEST["variants"].items():
            for file, meta in variant["files"].items():
                path = EXAMPLE / file
                with self.subTest(file=f"{name}/{file}"):
                    self.assertEqual(meta["sha256"],
                                     hashlib.sha256(path.read_bytes()).hexdigest())

    def test_columns_follow_the_commerce_contract(self):
        columns = {
            "customers": ["row_id", "customer_id", "version", "segment"],
            "orders": ["row_id", "order_id", "customer_id", "version", "order_day",
                       "gross_cents", "status", "currency"],
            "payments": ["row_id", "payment_id", "order_id", "version", "kind", "amount_cents"],
        }
        for name in MANIFEST["variants"]:
            for table, expected in columns.items():
                with (EXAMPLE / "data" / name / f"{table}.csv").open(newline="") as handle:
                    self.assertEqual(expected, next(csv.reader(handle)), f"{name}/{table}")

    def test_committed_results_cover_every_run(self):
        runs = _runner().RUNS
        self.assertEqual(len(runs), len(RESULTS))
        for (folder, _source, _sql, expected), result in zip(runs, RESULTS):
            self.assertEqual(folder, result["variant"])
            self.assertEqual(expected, result["classification"])


@unittest.skipUnless(importlib.util.find_spec("duckdb") is not None,
                     "Optional dbt/DuckDB dependencies are absent")
class Model2dataDatasetActualDbtTests(unittest.TestCase):
    def test_runs_reproduce_the_committed_results(self):
        results = _runner().run()
        self.assertEqual([_stable(r) for r in RESULTS], [_stable(r) for r in results])

    def test_controls_raise_no_source_alert(self):
        for result in RESULTS:
            if result["variant"].endswith("/control"):
                self.assertEqual([], result["source_alerts"], result["case"])


if __name__ == "__main__":
    unittest.main()
