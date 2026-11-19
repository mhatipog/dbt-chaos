"""Executable contract v1: cross-domain event truth, source/SQL and publication."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import csv
import json
import unittest

from dbt_chaos.process_contract import (
    FAULTS, FORMAT, apply_scripted_fault,
    columns_for, delivered_source_oracle, event_business_oracle,
    export_contract_challenge, project_source, run_reference_from_public,
    run_sqlite_reference, score_contract_challenge, simulate_process,
    validate_contract, load_contract,
)

CONTRACTS = (
    Path("contracts/procurement.json"), Path("contracts/grants.json")
)


class ContractTests(unittest.TestCase):
    def test_built_in_contracts_match_repository_examples(self):
        for name in ("procurement", "grants"):
            with self.subTest(name=name):
                packaged = load_contract(name)
                from_path = load_contract(Path("contracts") / f"{name}.json")
                self.assertEqual(packaged, from_path)
                self.assertEqual(3, len(packaged["roles"]))
        with self.assertRaisesRegex(ValueError, "existing bounded JSON"):
            load_contract("../malicious-contract")
        with self.assertRaisesRegex(ValueError, "existing bounded JSON"):
            load_contract("unknown_domain")

    def test_contract_validation_rejects_untrusted_dsl_and_ambiguous_columns(self):
        contract = json.loads(CONTRACTS[0].read_text())
        self.assertEqual(contract, validate_contract(contract))
        invalid = deepcopy(contract)
        invalid["arbitrary_code"] = "__import__('os')"
        with self.assertRaisesRegex(ValueError, "exactly"):
            validate_contract(invalid)
        invalid = deepcopy(contract)
        invalid["roles"]["party"]["table"] = "suppliers;DROP TABLE X"
        with self.assertRaisesRegex(ValueError, "unsafe"):
            validate_contract(invalid)
        invalid = deepcopy(contract)
        invalid["roles"]["movement"]["table"] = "invoices"
        with self.assertRaisesRegex(ValueError, "distinct"):
            validate_contract(invalid)
        invalid = deepcopy(contract)
        invalid["roles"]["party"]["dimension"] = "version"
        with self.assertRaisesRegex(ValueError, "duplicate"):
            validate_contract(invalid)
        invalid = deepcopy(contract)
        invalid["semantics"]["signs"] = {"payout": 1, "refund": 0}
        with self.assertRaisesRegex(ValueError, "signs"):
            validate_contract(invalid)
        invalid = deepcopy(contract)
        invalid["generation"]["documents"] = 10_000_000
        with self.assertRaisesRegex(ValueError, "generation.documents"):
            validate_contract(invalid)

    def test_two_real_business_domains_share_engine_not_hardcoded_columns(self):
        for path in CONTRACTS:
            with self.subTest(contract=path):
                spec = validate_contract(json.loads(path.read_text()))
                a = simulate_process(spec, 20261119)
                b = simulate_process(spec, 20261119)
                self.assertEqual(a, b)
                self.assertNotEqual(a, simulate_process(spec, 20261120))
                self.assertEqual(list(range(1, len(a)+1)),
                                 [e["event_id"] for e in a])
                self.assertTrue(any(e["type"] == "movement_redelivered" for e in a))
                self.assertTrue(any(e["type"] == "document_state" for e in a))
                self.assertTrue(any(e["type"] == "party_reclassified" for e in a))
                sources = project_source(spec, a)
                self.assertEqual(3, len(sources))
                for role in ("party", "document", "movement"):
                    table = spec["roles"][role]["table"]
                    self.assertGreater(len(sources[table]), 10)
                    self.assertEqual(set(columns_for(spec, role)),
                                     set(sources[table][0]))
                from_ledger = event_business_oracle(spec, a)
                from_source = delivered_source_oracle(spec, sources)
                from_sql = run_sqlite_reference(spec, sources)
                self.assertEqual(from_ledger, from_source)
                self.assertEqual(from_ledger, from_sql)
                self.assertGreater(len(from_ledger), 20)

    def test_all_faults_do_not_change_hidden_business_process(self):
        for path in CONTRACTS:
            spec=json.loads(path.read_text())
            events=simulate_process(spec, 20261119)
            clean=project_source(spec, events)
            business=event_business_oracle(spec, events)
            baseline=json.dumps(clean, sort_keys=True)
            for fault in FAULTS:
                with self.subTest(contract=path, fault=fault):
                    changed, descriptor=apply_scripted_fault(
                        spec, clean, events, fault)
                    self.assertEqual("scripted_good_faith_operator_calibration_not_llm",
                                     descriptor["actor"])
                    self.assertEqual(baseline, json.dumps(clean, sort_keys=True))
                    self.assertEqual(business, event_business_oracle(spec, events))
                    source=delivered_source_oracle(spec, changed)
                    sql=run_sqlite_reference(spec, changed)
                    self.assertEqual(source, sql)
                    metric=sum(abs(business.get(k,0)-source.get(k,0))
                               for k in business.keys() | source.keys())
                    if fault in ("none", "duplicate_delivery"):
                        self.assertEqual(0, metric)
                    else:
                        self.assertGreater(metric, 0)
                    if fault == "rewrite_credit":
                        self.assertEqual(2000, metric)
                    if fault == "reclassify_party":
                        self.assertEqual(sum(business.values()), sum(source.values()))
                    self.assertEqual(metric,
                                     descriptor.get("business_source_l1_cents", 0))

    def test_distinct_contract_domains_have_different_files_and_semantics(self):
        c = [json.loads(p.read_text()) for p in CONTRACTS]
        tables = [
            {c[i]["roles"][role]["table"] for role in ("party", "document", "movement")}
            for i in range(2)
        ]
        self.assertFalse(tables[0] & tables[1])
        self.assertNotEqual(c[0]["semantics"]["signs"], c[1]["semantics"]["signs"])
        self.assertNotEqual(c[0]["semantics"]["included_status"],
                            c[1]["semantics"]["included_status"])

    def test_public_challenge_isolated_and_sql_actual_output_scored(self):
        with TemporaryDirectory() as t:
            root = Path(t)
            pub, pri, out = [root / x for x in ("public", "private", "sqlite_output")]
            summary=export_contract_challenge(
                contract_path=CONTRACTS[0], seed=20261119,
                fault="rewrite_credit", public_dir=pub, private_dir=pri)
            self.assertTrue(summary["oracle_separated"])
            self.assertFalse(summary["model_generated_fault"])
            self.assertEqual(2000, summary["business_source_l1_cents"])
            self.assertTrue((pub/"contract.json").exists())
            self.assertTrue((pub/"inputs/chaos/settlements.csv").exists())
            self.assertFalse((pub/"answer_key.json").exists())
            self.assertFalse((pub/"process_events.jsonl").exists())
            self.assertTrue((pri/"process_events.jsonl").exists())
            spec = json.loads((pub/"contract.json").read_text())
            self.assertEqual(FORMAT, spec["format"])
            run=run_reference_from_public(pub, out)
            self.assertEqual("sqlite3_reference",run["adapter"])
            result=score_contract_challenge(
                public_dir=pub, answer_key=pri/"answer_key.json",
                published_dir=out)
            self.assertEqual("business_correct",
                             result["results"]["clean"]["verdict"])
            self.assertEqual("garbage_passed_through",
                             result["results"]["chaos"]["verdict"])
            self.assertEqual(2000, result["results"]["chaos"]
                             ["source_to_business_l1_cents"])
            self.assertEqual(0, result["results"]["chaos"]
                             ["published_vs_delivered_source_l1_cents"])
            self.assertTrue(result["scored_against_independent_business_events"])
            self.assertGreater(len(result["results"]["chaos"]["published"]
                                   ["false_published_groups"]),0)

    def test_party_reclassification_has_zero_net_but_nonzero_group_error(self):
        with TemporaryDirectory() as t:
            root=Path(t)
            pub,pri,out=[root/x for x in ("p","s","o")]
            report=export_contract_challenge(
                contract_path=CONTRACTS[1],seed=20261119,
                fault="reclassify_party",public_dir=pub,private_dir=pri)
            self.assertGreater(report["business_source_l1_cents"],0)
            run_reference_from_public(pub,out)
            result=score_contract_challenge(
                public_dir=pub,answer_key=pri/"answer_key.json",published_dir=out)
            self.assertEqual("garbage_passed_through",
                             result["results"]["chaos"]["verdict"])
            k=json.loads((pri/"answer_key.json").read_text())
            self.assertEqual(sum(k["expected_business"].values()),
                             sum(k["expected_given_source"]["chaos"].values()))
            self.assertGreater(len(result["results"]["chaos"]["published"]
                                   ["false_published_groups"]),0)

    def test_benign_duplicate_delivery_does_not_break_reference_reporting(self):
        with TemporaryDirectory() as t:
            root=Path(t)
            pub,pri,out=[root/x for x in ("p","s","o")]
            report=export_contract_challenge(
                contract_path=CONTRACTS[1],seed=20261119,
                fault="duplicate_delivery",public_dir=pub,private_dir=pri)
            self.assertEqual(0,report["business_source_l1_cents"])
            run_reference_from_public(pub,out)
            result=score_contract_challenge(
                public_dir=pub,answer_key=pri/"answer_key.json",published_dir=out)
            self.assertEqual("business_correct",
                             result["results"]["chaos"]["verdict"])
            self.assertEqual(1.0,result["results"]["chaos"]["published"]
                             ["fraction_of_correct_business_value_published"])

    def test_tampering_and_secret_leakage_prevented(self):
        with TemporaryDirectory() as t:
            root=Path(t)
            pub,pri,out=[root/x for x in ("p","s","o")]
            with self.assertRaisesRegex(ValueError, "disjoint"):
                export_contract_challenge(
                    contract_path=CONTRACTS[0],seed=1,fault="none",
                    public_dir=pub,private_dir=pub/"secret")
            export_contract_challenge(contract_path=CONTRACTS[0],seed=1,
                                     fault="drop_document",public_dir=pub,
                                     private_dir=pri)
            run_reference_from_public(pub,out)
            manifest=pub/"manifest.json"
            original=manifest.read_bytes()
            manifest.write_bytes(original+b"\n")
            with self.assertRaisesRegex(ValueError, "mismatch"):
                score_contract_challenge(
                    public_dir=pub,answer_key=pri/"answer_key.json",
                    published_dir=out)
            manifest.write_bytes(original)
            file=pub/"inputs/chaos/settlements.csv"
            file.write_bytes(file.read_bytes()+b"bad\n")
            with self.assertRaisesRegex(ValueError, "input changed"):
                score_contract_challenge(
                    public_dir=pub,answer_key=pri/"answer_key.json",
                    published_dir=out)

    def test_withheld_revenue_not_misreported_as_safe_transformation(self):
        with TemporaryDirectory() as t:
            root=Path(t)
            pub,pri,out,hold=[root/x for x in ("p","s","o","h")]
            export_contract_challenge(
                contract_path=CONTRACTS[1],seed=1,fault="drop_document",
                public_dir=pub,private_dir=pri)
            run_reference_from_public(pub,out)
            original=out/"chaos.csv"
            original.write_text("period,group,amount_cents\n")
            held_key=json.loads((pri/"answer_key.json").read_text())
            hold.mkdir()
            with (hold/"chaos.csv").open("w",newline="") as f:
                w=csv.writer(f)
                w.writerow(["period","group"])
                for pair in held_key["expected_business"]:
                    w.writerow(pair.split("|",1))
            result=score_contract_challenge(
                public_dir=pub,answer_key=pri/"answer_key.json",
                published_dir=out,held_dir=hold)
            self.assertEqual("all_withheld", result["results"]["chaos"]["verdict"])
            self.assertEqual(0.0, result["results"]["chaos"]["published"]
                             ["fraction_of_correct_business_value_published"])

    def test_export_rejects_overwrite_and_private_inside_public(self):
        with TemporaryDirectory() as t:
            root=Path(t)
            pub,pri=[root/x for x in ("p","s")]
            export_contract_challenge(contract_path=CONTRACTS[1],seed=1,
                                     fault="none",public_dir=pub,private_dir=pri)
            with self.assertRaisesRegex(ValueError, "empty"):
                export_contract_challenge(
                    contract_path=CONTRACTS[1],seed=1,fault="none",
                    public_dir=pub,private_dir=pri)


if __name__ == "__main__":
    unittest.main()
