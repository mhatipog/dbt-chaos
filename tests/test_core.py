import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from dbt_chaos.core import Event,Plan,Step,STRATEGIES,DOMAINS,PLANNED,oracle,live,screen,read_plan
from dbt_chaos.faults import generate,coverage
from dbt_chaos.score import evaluate
from dbt_chaos.shrink import reduce_plan

class CoreTests(unittest.TestCase):
    def test_catalog_complete_and_honest(self):
        self.assertGreaterEqual(len(DOMAINS),19)
        self.assertGreaterEqual(len(PLANNED),10)
        self.assertNotIn("transaction_crash",DOMAINS)
    def test_round_trip_determinism(self):
        a=generate(seed=31,count=100)
        b=generate(seed=31,count=100)
        self.assertEqual([p.dumps() for p in a],[p.dumps() for p in b])
        for plan in a:
            self.assertEqual(plan,Plan.from_dict(json.loads(plan.dumps())))
    def test_idempotent_cdc_oracle(self):
        a=Event("a",1,1,10,100)
        delete=Event("del",1,2,1,None,"delete")
        self.assertEqual({},live(oracle([a,a,delete])))
        with self.assertRaises(ValueError):
            oracle([a,Event("a",1,1,10,200)])
    def test_invalid_plan_fails_closed(self):
        with self.assertRaises(ValueError):Event("a",1,0,20,100)
        with self.assertRaises(ValueError):Plan.from_dict({"other":1})
        with self.assertRaises(ValueError):Plan("x",0,("future",),(Step("deliver"),Step("run"),Step("check")))
    def test_late_arrival_silent_strict(self):
        plan=generate(count=2)[1]
        self.assertTrue(screen(plan,"strict")["silent_corruption"])
        self.assertFalse(screen(plan,"full")["silent_corruption"])
        self.assertFalse(screen(plan,"offset")["silent_corruption"])
    def test_all_models_execute(self):
        for plan in generate(seed=7,count=100):
            for strategy in STRATEGIES:
                r=screen(plan,strategy)
                self.assertGreater(len(r["checkpoints"]),0)
                self.assertTrue(r["final_correct"] or any(p["mismatch"] for p in r["checkpoints"]))
    def test_full_reference_no_silent_corruption(self):
        for plan in generate(seed=19,count=160):
            r=screen(plan,"full")
            self.assertTrue(r["final_correct"],plan.name)
            self.assertFalse(r["silent_corruption"],plan.name)
    def test_detection_controls(self):
        plans=generate(count=len(DOMAINS))
        for name in ("negative_amount","null_amount"):
            plan=plans[list(DOMAINS).index(name)]
            result=screen(plan,"full")
            self.assertTrue(result["checkpoints"][-1]["alerts"])
            self.assertFalse(result["checkpoints"][-1]["mismatch"])
    def test_reducer(self):
        plan=generate(count=2)[1]
        outcome=reduce_plan(plan,"strict")
        self.assertTrue(outcome["changed"])
        self.assertTrue(screen(outcome["plan"],"strict")["silent_corruption"])
        self.assertLess(len(outcome["plan"].dumps()),len(plan.dumps()))
    def test_score_measured_denominator(self):
        score=evaluate(generate(seed=11,count=100))
        self.assertEqual("python_model_screen",score["evidence_level"])
        self.assertEqual(0,score["strategies"]["full"]["silent_corruption"])
        self.assertLess(score["strategies"]["strict"]["score_0_100"],100)
        self.assertEqual(100,score["strategies"]["full"]["score_0_100"])
    def test_pairwise_generation_coverage(self):
        plans=generate(seed=112,count=210,max_faults=2)
        result=coverage(plans)
        self.assertEqual(20,result["executed_operator_kinds"])
        self.assertEqual(190,result["possible_unordered_pairs"])
        self.assertEqual(190,result["realized_distinct_pairs"])
        self.assertEqual(1.0,result["pair_coverage_fraction"])
    def test_read_plan(self):
        plan=generate(count=1)[0]
        with tempfile.TemporaryDirectory() as tmp:
            f=Path(tmp)/"replay.json"
            f.write_text(plan.dumps())
            self.assertEqual(plan,read_plan(f))

if __name__=="__main__":unittest.main()
