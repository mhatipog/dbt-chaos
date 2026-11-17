import unittest
from dbt_chaos.report import render

class ReportTests(unittest.TestCase):
    def test_reject_unknown_evidence(self):
        with self.assertRaises(ValueError):render({"evidence_level":"fabric_live","strategies":{"a":{}}})
    def test_escape_untrusted_strings(self):
        html=render({"evidence_level":"python_model_screen","strategies":{"<script>alert(1)</script>":{
            "score_0_100":75,"correctness_pct":50,"incorrect":1,"silent_corruption":1,"fault_checkpoints":4}},
            "limits":["<b>not trusted</b>"]})
        self.assertNotIn("<script>",html)
        self.assertIn("&lt;script&gt;",html)
        self.assertIn("&lt;b&gt;",html)
        self.assertIn("75%",html)

if __name__=="__main__":unittest.main()
