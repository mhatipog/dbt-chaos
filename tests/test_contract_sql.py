"""Contract-generated SQL must execute and distinguish visible vs hidden errors."""
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import sqlite3
import csv
import unittest

from dbt_chaos.process_contract import (
    ROLES, columns_for, export_contract_challenge,
    run_sqlite_reference, validate_contract,
)
from dbt_chaos.contract_sql import build_sql_pack, evaluate_public_quality


class ContractSQLTests(unittest.TestCase):
    contracts = (Path("contracts/procurement.json"), Path("contracts/grants.json"))

    def sample(self, path, fault, seed=20261119):
        folder=TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        root=Path(folder.name)
        public=root/"public"; secret=root/"private"
        export_contract_challenge(
            contract_path=path,seed=seed,fault=fault,
            public_dir=public,private_dir=secret)
        return public,secret

    def test_portable_sql_is_generated_and_integrity_protected(self):
        for path in self.contracts:
            with self.subTest(path=path):
                pub,secret=self.sample(path,"rewrite_credit")
                manifest=json.loads((pub/"manifest.json").read_text())
                self.assertEqual(
                    {"sql/reference_query.sql","sql/quality_checks.sql"},
                    set(manifest["support_files"]))
                actual=build_sql_pack(json.loads((pub/"contract.json").read_text()))
                for file, contents in actual.items():
                    self.assertEqual(contents,(pub/"sql"/file).read_text())
                    self.assertNotIn("DROP TABLE",contents.upper())
                self.assertIn("ROW_NUMBER()",actual["reference_query.sql"])
                self.assertIn("orphan_movement",actual["quality_checks.sql"])
                self.assertIn("benign_delivery_retry",actual["quality_checks.sql"])

    def test_observable_probes_reveal_orphans_without_rejecting_plausible_facts(self):
        for path in self.contracts:
            for fault in ("rewrite_credit","reclassify_party","drop_document",
                          "duplicate_delivery"):
                with self.subTest(contract=path,fault=fault):
                    pub,_=self.sample(path,fault)
                    result=evaluate_public_quality(pub)
                    clean=result["results"]["clean"]
                    bad=result["results"]["chaos"]
                    self.assertEqual(0,clean["block_count"])
                    self.assertEqual("observable_delivered_csv_only",
                                     result["evidence_tier"])
                    self.assertFalse(result["native_warehouse_tests_installed"])
                    if fault=="drop_document":
                        self.assertGreater(bad["block_count"],0)
                        self.assertIn(
                            "orphan_movement",
                            {x["check_name"] for x in bad["issues"]})
                    else:
                        self.assertEqual(0,bad["block_count"])
                    if fault=="duplicate_delivery":
                        self.assertGreater(
                            bad["informational_count"],
                            clean["informational_count"])

    def test_sql_pack_reference_matches_independent_source_oracle(self):
        for contract_path in self.contracts:
            pub,_=self.sample(contract_path,"reclassify_party")
            c=validate_contract(json.loads((pub/"contract.json").read_text()))
            sql=(pub/"sql/reference_query.sql").read_text()
            for scenario in ("clean","chaos"):
                with self.subTest(contract=contract_path,scenario=scenario):
                    source={}
                    with sqlite3.connect(":memory:") as db:
                        for role in ROLES:
                            r=c["roles"][role]
                            table=r["table"]
                            cols=columns_for(c,role)
                            ints={"row_id","version",r["id"]}
                            if role=="document":
                                ints|={r["party_fk"],r["gross"]}
                            if role=="movement":
                                ints|={r["document_fk"],r["amount"]}
                            db.execute("CREATE TABLE "+table+"("+
                                ",".join(col+" "+("INTEGER" if col in ints else "TEXT")
                                         for col in cols)+")")
                            with (pub/"inputs"/scenario/(table+".csv")).open(
                                    newline="",encoding="utf8") as stream:
                                rows=[
                                    {name:int(row[name]) if name in ints else row[name]
                                     for name in cols}
                                    for row in csv.DictReader(stream)]
                            source[table]=rows
                            if rows:
                                db.executemany("INSERT INTO "+table+" VALUES ("+
                                    ",".join("?" for _ in cols)+")",[
                                    tuple(row[x] for x in cols) for row in rows])
                        actual={(str(day),str(group)):int(cents)
                                for day,group,cents in db.execute(sql).fetchall()}
                    expected=run_sqlite_reference(c,source)
                    self.assertEqual(expected,actual)

    def test_generated_sql_support_cannot_be_tampered_without_score_failure(self):
        from dbt_chaos.process_contract import (
            run_reference_from_public,score_contract_challenge)
        pub,secret=self.sample(self.contracts[0],"rewrite_credit")
        out=pub.parent/"output"
        run_reference_from_public(pub,out)
        f=pub/"sql/reference_query.sql"
        f.write_bytes(f.read_bytes()+b"\n-- hostile mutation\n")
        with self.assertRaisesRegex(ValueError,"SQL support changed"):
            score_contract_challenge(
                public_dir=pub,answer_key=secret/"answer_key.json",
                published_dir=out)


if __name__=="__main__":
    unittest.main()
