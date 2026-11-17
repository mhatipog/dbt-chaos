import unittest
from dbt_chaos.real_score import summarize_real,merge_reports

class ScoreTests(unittest.TestCase):
    def test_exclude_baseline_and_execution_errors(self):
        entries=[
            {"strategy":"strict","elapsed_seconds":1,"dbt_calls":3,"checkpoints":[
                {"label":"baseline","mismatch":False,"silent":False,"alerts":[],"delta":{"missing":{},"extra":{},"changed":{}}},
                {"label":"late","mismatch":True,"silent":True,"alerts":[],"delta":{"missing":{"3":[1,100]},"extra":{},"changed":{}}}]},
            {"strategy":"strict","execution_error":"no runner"}
        ]
        report=summarize_real(entries)["strategies"]["strict"]
        self.assertEqual(report["fault_checkpoints"],1)
        self.assertEqual(report["silent_corruption"],1)
        self.assertEqual(report["score_0_100"],0)
        self.assertEqual(report["execution_errors"],1)
        self.assertEqual(report["final_correct_cases"],0)
        self.assertEqual(report["recovered_cases"],0)
    def test_merge_strict_provenance(self):
        def shard(name):
            return {"evidence_level":"executed_dbt_duckdb","schema_version":1,
                    "git_sha":"a"*40,"observations":[
                        {"plan":name,"strategy":"strict","checkpoints":[
                            {"label":"late","mismatch":True,"silent":True,"alerts":[],
                             "delta":{"missing":{"3":[1,100]},"extra":{},"changed":{}}}]}]}
        joined=merge_reports([shard("one"),shard("two")])
        self.assertEqual(joined["shards_merged"],2)
        self.assertEqual(joined["strategies"]["strict"]["silent_corruption"],2)
        with self.assertRaises(ValueError):
            merge_reports([shard("one"),shard("one")])
        with self.assertRaises(ValueError):
            merge_reports([shard("one"),{"evidence_level":"python_model_screen","schema_version":1,"observations":[]}])
    def test_alerted_incorrect_counted_detected(self):
        result={"strategy":"cdc","checkpoints":[
            {"label":"late","mismatch":True,"silent":False,"alerts":["contract_error"],"delta":{"missing":{"3":[1,100]},"extra":{},"changed":{}}}]}
        item=summarize_real([result])["strategies"]["cdc"]
        self.assertEqual(item["detected_corruption"],1)
        self.assertEqual(item["silent_corruption"],0)
        self.assertEqual(item["score_0_100"],100)

if __name__=="__main__":unittest.main()
