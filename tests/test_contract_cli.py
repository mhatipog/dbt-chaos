"""Test user-facing CLI workflows, not just internal Python functions."""
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest

from dbt_chaos.cli import main


class ContractMaintenanceCLITests(unittest.TestCase):
    def _call(self, cmd):
        out=StringIO()
        with redirect_stdout(out):
            value=main(cmd)
        self.assertEqual(0,value)
        return json.loads(out.getvalue())

    def test_contract_agent_cli_runs_two_domains_without_model_api(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp)
            for name in ("procurement","grants"):
                with self.subTest(name=name):
                    pub=root/(name+"-pub")
                    pri=root/(name+"-pri")
                    summary=root/(name+"-summary.json")
                    result=self._call([
                        "contract-agent",
                        "--contract",str(Path("contracts")/(name+".json")),
                        "--agent","scripted","--seed","20261119",
                        "--steps","6","--public-dir",str(pub),
                        "--private-dir",str(pri),"--out",str(summary),
                    ])
                    self.assertEqual(6,result["steps"])
                    self.assertEqual(4,result["material_business_errors"])
                    self.assertEqual(4,result["policy_results"]["raw"]
                                     ["cases_with_wrong_publication"])
                    self.assertEqual(0,result["policy_results"]["evidence_gate"]
                                     ["cases_with_wrong_publication"])
                    self.assertTrue((pub/"steps/01/raw_proposed").exists())
                    self.assertTrue((pri/"business_gold.json").exists())
                    self.assertFalse((pub/"business_gold.json").exists())
                    self.assertEqual(result,json.loads(summary.read_text()))

    def test_balanced_review_cli_real_utility_tradeoff(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp)
            for name in ("procurement","grants"):
                with self.subTest(name=name):
                    pub,pri=root/(name+"-pub"),root/(name+"-pri")
                    result=self._call([
                        "contract-review",
                        "--contract",str(Path("contracts")/(name+".json")),
                        "--agent","always_apply",
                        "--public-dir",str(pub),"--private-dir",str(pri),
                    ])
                    self.assertEqual(6,result["total_review_cases"])
                    self.assertEqual(3,result["policy_results"]
                                     ["selected_ungated_publication"]["wrong_case_count"])
                    self.assertEqual(1,result["policy_results"]
                                     ["selected_source_only_gate"]["wrong_case_count"])
                    self.assertEqual(0,result["policy_results"]
                                     ["selected_attested_gate"]["wrong_case_count"])
                    self.assertTrue((pri/"assessment.json").exists())
                    self.assertFalse((pub/"assessment.json").exists())
                    self.assertEqual(3,len(list(
                        (pub/"cases"/"uncertain_credit"/"inputs"/"initial").glob("*.csv"))))
                    self.assertEqual(3,len(list(
                        (pub/"cases"/"uncertain_credit"/"inputs"/"proposed").glob("*.csv"))))

    def test_casework_cli_emits_all_three_publication_stages(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp)
            for domain in ("procurement","grants"):
                with self.subTest(domain=domain):
                    output=root/(domain+"-casework.json")
                    out=StringIO()
                    with redirect_stdout(out):
                        result=main([
                            "contract-casework", "--contract",
                            str(Path("contracts")/(domain+".json")),
                            "--seed","20261119","--out",str(output),
                            "--fail-on-incorrect-final",
                        ])
                    self.assertEqual(0,result)
                    saved=json.loads(output.read_text())
                    self.assertEqual(3,len(saved["stages"]))
                    self.assertEqual("silently_wrong",saved["stages"][0]["score"]["status"])
                    self.assertEqual("partially_held",saved["stages"][1]["score"]["status"])
                    self.assertEqual("correctly_published",saved["stages"][2]["score"]["status"])
                    self.assertFalse(saved["source_ledger_present_in_release_planner"])
                    self.assertFalse(saved["signing_key_exported"])
                    self.assertIn("scoped_receipt_verified",out.getvalue())

    def test_model_path_missing_rejected_without_side_effects(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp)
            with self.assertRaises(SystemExit):
                self._call([
                    "contract-review",
                    "--contract","contracts/procurement.json",
                    "--agent","llama","--public-dir",str(root/"public"),
                    "--private-dir",str(root/"private"),
                ])
            self.assertFalse((root/"public").exists())


if __name__=="__main__":
    unittest.main()
