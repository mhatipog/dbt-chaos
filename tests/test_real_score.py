import unittest
from dbt_chaos.real_score import summarize_real

class ScoreTests(unittest.TestCase):
    def test_exclude_baseline_and_execution_errors(self):
        entries=[
            {"strategy":"strict","elapsed_seconds":1,"dbt_calls":3,"checkpoints":[
                {"label":"baseline","mismatch":False,"silent":False,"alerts":[]},
                {"label":"late","mismatch":True,"silent":True,"alerts":[]}]},
            {"strategy":"strict","execution_error":"no runner"}
        ]
        report=summarize_real(entries)["strategies"]["strict"]
        self.assertEqual(report["fault_checkpoints"],1)
        self.assertEqual(report["silent_corruption"],1)
        self.assertEqual(report["score_0_100"],0)
        self.assertEqual(report["execution_errors"],1)
    def test_alerted_incorrect_counted_detected(self):
        result={"strategy":"cdc","checkpoints":[
            {"label":"late","mismatch":True,"silent":False,"alerts":["contract_error"]}]}
        item=summarize_real([result])["strategies"]["cdc"]
        self.assertEqual(item["detected_corruption"],1)
        self.assertEqual(item["silent_corruption"],0)
        self.assertEqual(item["score_0_100"],100)

if __name__=="__main__":unittest.main()
