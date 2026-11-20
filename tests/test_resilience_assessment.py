"""End-to-end tests: actual SQLite execution, private oracle, and published pack."""
from contextlib import redirect_stdout
from copy import deepcopy
from hashlib import sha256
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from dbt_chaos.resilience_assessment import (
    FORMAT, main, render_html, render_markdown, run_assessment, write_assessment,
)


class ResilienceAssessmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = run_assessment(seed=20261119)

    def test_two_domains_with_real_sql_and_evidence_boundaries(self):
        report = self.result
        self.assertEqual(FORMAT, report["format"])
        self.assertTrue(report["controls_passed"])
        self.assertEqual(2, report["domain_count"])
        self.assertEqual(12, report["ticket_count"])
        self.assertTrue(report["not_real_dbt_or_production_adapter"])
        self.assertTrue(report["original_process_ledger_hidden_from_release_gate"])
        self.assertTrue(report["no_live_llm_called"])
        for domain in report["domains"]:
            with self.subTest(domain=domain["domain"]):
                self.assertEqual(6, domain["ticket_count"])
                self.assertFalse(domain["candidate_proposals_authored_by_llm"])
                p = domain["policies"]
                self.assertEqual(3, p["always_apply"]["wrong_case_count"])
                self.assertEqual(1, p["always_keep"]["wrong_case_count"])
                self.assertEqual(1, p["source_only_gate"]["wrong_case_count"])
                self.assertEqual(0, p["attested_upper_bound"]["wrong_case_count"])
                stages = domain["correction_lifecycle"]
                self.assertEqual(
                    ["silently_wrong", "partially_held", "correctly_published"],
                    [s["business_status"] for s in stages],
                )
                self.assertGreater(stages[0]["wrong_published_cents"], 0)
                self.assertEqual(0, stages[1]["wrong_published_cents"])
                self.assertEqual(1, stages[1]["held_reporting_groups"])
                self.assertEqual(0, stages[2]["held_reporting_groups"])
                self.assertEqual(1.0, stages[2]["correct_value_fraction"])
                self.assertTrue(all(domain["controls"].values()))

    def test_public_artifacts_are_consistent_and_no_private_ledger(self):
        with TemporaryDirectory() as tmp:
            out = Path(tmp) / "pack"
            written = write_assessment(self.result, out)
            self.assertTrue(written["controls_passed"])
            self.assertEqual(
                {"assessment.json", "assessment.md", "assessment.html", "SHA256SUMS"},
                {p.name for p in out.iterdir()},
            )
            payload = (out / "assessment.json").read_bytes()
            self.assertEqual(
                sha256(payload).hexdigest(),
                written["assessment_sha256"],
            )
            self.assertEqual(self.result, json.loads(payload))
            self.assertNotIn("process_events.jsonl", payload.decode("utf8"))
            self.assertNotIn("signing_key", payload.decode("utf8"))
            self.assertIn("two bounded transactional", (out / "assessment.md").read_text())
            self.assertIn("Content-Security-Policy", (out / "assessment.html").read_text())
            with self.assertRaisesRegex(ValueError, "new or empty"):
                write_assessment(self.result, out)

    def test_report_html_escapes_untrusted_markdown_text(self):
        altered = deepcopy(self.result)
        altered["limitations"].append('<img src=x onerror=alert(1)>')
        page = render_html(altered)
        self.assertNotIn('<img src=x', page)
        self.assertIn('&lt;img src=x', page)
        self.assertIn('selected simulated', render_markdown(self.result).lower())

    def test_cli_writes_before_nonzero_guard_exit(self):
        with TemporaryDirectory() as tmp:
            good = Path(tmp) / "good"
            output = StringIO()
            with redirect_stdout(output):
                code = main(["--out-dir", str(good), "--fail-on-unsafe"])
            self.assertEqual(0, code)
            self.assertTrue((good / "assessment.json").exists())
            unsafe = deepcopy(self.result)
            unsafe["controls_passed"] = False
            with patch("dbt_chaos.resilience_assessment.run_assessment", return_value=unsafe):
                output = StringIO()
                with redirect_stdout(output):
                    code = main(["--out-dir", str(Path(tmp) / "unsafe"), "--fail-on-unsafe"])
            self.assertEqual(2, code)
            self.assertTrue((Path(tmp) / "unsafe/assessment.json").exists())

    def test_invalid_seed_rejected(self):
        for seed in (-1, 2**32, True):
            with self.subTest(seed=seed), self.assertRaises(ValueError):
                run_assessment(seed)


if __name__ == "__main__":
    unittest.main()
