"""Actual dbt integration tests. Only run in the explicitly dependency-installed real workflow."""
import unittest
import importlib.util
from dbt_chaos.core import DOMAINS
from dbt_chaos.faults import generate
from dbt_chaos.dbt_runner import run_real

@unittest.skipUnless(importlib.util.find_spec('duckdb') is not None, 'optional dbt/DuckDB dependencies not installed')
class RealDbtTests(unittest.TestCase):
    def test_late_arrival_strict_silent(self):
        p=generate(count=2)[1]
        result=run_real(p,"strict")
        self.assertEqual("executed_dbt_duckdb",result["evidence_level"])
        self.assertTrue(result["silent_corruption"])
        self.assertFalse(result["final_correct"])
    def test_late_arrival_full_correct(self):
        p=generate(count=2)[1]
        result=run_real(p,"full")
        self.assertTrue(result["final_correct"])
        self.assertFalse(result["silent_corruption"])
    def test_late_arrival_offset_correct(self):
        p=generate(count=2)[1]
        result=run_real(p,"offset")
        self.assertTrue(result["final_correct"])
        self.assertFalse(result["silent_corruption"])
    def test_negative_amount_detected(self):
        p=generate(count=len(DOMAINS))[list(DOMAINS).index("negative_amount")]
        result=run_real(p,"strict")
        self.assertFalse(result["silent_corruption"])
        self.assertTrue(result["checkpoints"][-1]["alerts"])

if __name__=="__main__":unittest.main()
