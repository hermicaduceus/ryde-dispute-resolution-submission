"""W23 B2 acceptance: read-only operator case and payload endpoints."""
from __future__ import annotations
import json
import unittest
from tests.w23_support import Server, body

class OperatorReads(unittest.TestCase):
    def setUp(self): self.s=Server()
    def tearDown(self): self.s.close()
    def get(self,path):
        status,headers,raw=self.s.raw("GET",path)
        self.assertEqual("no-store",headers.get("Cache-Control"))
        return status,json.loads(raw)
    def test_case_exact_shape_for_party_and_cli_runs_and_decision(self):
        party=self.s.file("T-RD0109",55.16); cli=self.s.cli_run()
        for run in (party["run_id"],cli):
            status,payload=self.get("/api/review/%s/case"%run)
            self.assertEqual(200,status);self.assertEqual(["case_file","human_decision"],list(payload))
            self.assertEqual(self.s.case(run),payload["case_file"]);self.assertIsNone(payload["human_decision"])
        self.assertEqual(200,self.s.decide(party["run_id"],body("reject"))[0])
        self.assertEqual("reject",self.get("/api/review/%s/case"%party["run_id"])[1]["human_decision"]["decision"])
    def test_case_works_for_non_withheld_run(self):
        run=self.s.file("T-RD0109",5.81)["run_id"]
        self.assertEqual("ruled",self.get("/api/review/%s/case"%run)[1]["case_file"]["resolution"]["outcome"])
    def test_case_unknown_missing_corrupt_array_and_bad_run_ids(self):
        good=self.s.file("T-RD0109",55.16)["run_id"]
        variants=(("missing",None),("corrupt","{"),("array","[]"))
        for name,text in variants:
            d=self.s.out/name;d.mkdir()
            if text is not None:(d/"case_file.json").write_text(text,encoding="utf-8")
        for run in ("nope","missing","corrupt","array","..","%2e%2e","..%2F..%2Fapp","A"*129):
            with self.subTest(run=run): self.assertEqual((404,{"error":"unknown run"}),self.get("/api/review/%s/case"%run))
        self.assertTrue(good)
    def test_payload_returns_any_parsed_json_value(self):
        run=self.s.file("T-RD0109",55.16)["run_id"]; folder=self.s.run_dir(run)/"payloads"
        values={"0001-object.json":{"x":1},"0002-array.json":[1,2],"0003-null.json":None}
        for name,value in values.items():
            (folder/name).write_text(json.dumps(value),encoding="utf-8")
            self.assertEqual((200,value),self.get("/api/review/%s/payloads/%s"%(run,name)))
    def test_payload_rejects_unknown_run_bad_names_missing_and_bad_json(self):
        run=self.s.file("T-RD0109",55.16)["run_id"]; folder=self.s.run_dir(run)/"payloads"
        (folder/"0001-bad.json").write_text("{",encoding="utf-8")
        (folder/"0004-bad$name.json").write_text("{}",encoding="utf-8")
        for name in ("%2e%2e%2Fcase_file.json","%2Fetc%2Fpasswd","x.json","0001-bad%20name.json","0004-bad%24name.json","0001-bad.json","9999-missing.json"):
            with self.subTest(name=name): self.assertEqual((404,{"error":"unknown payload"}),self.get("/api/review/%s/payloads/%s"%(run,name)))
        self.assertEqual((404,{"error":"unknown run"}),self.get("/api/review/nope/payloads/0001-good.json"))

if __name__=="__main__":unittest.main()
