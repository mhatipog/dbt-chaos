import unittest
from dbt_chaos.commerce_report import render

class CommerceReportTests(unittest.TestCase):
    def test_escape_markup_and_preserve_evidence(self):
        report={"schema_version":1,"workload":"three-source-order-customer-payment",
                "outcomes":{"silent_corruption":1},
                "results":[{"source_fault":"duplicate_customer","logic_fault":"skip_customer_dedup",
                            "origin":"combined","classification":"silent_corruption",
                            "source_alerts":[],"output_alerts":[],
                            "contract_difference":{"<script>alert(1)</script>":{"expected":100,"actual":200}}}]}
        result=render(report)
        self.assertIn("silent_corruption",result)
        self.assertIn("&lt;script&gt;",result)
        self.assertNotIn("<script>",result)
        with self.assertRaises(ValueError):render({"schema_version":2,"workload":"other"})
        with self.assertRaises(ValueError):
            render({**report,"results":[{"classification":"unknown"}]})

if __name__=="__main__":unittest.main()
