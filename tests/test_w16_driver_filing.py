"""Real HTTP and actual Judge gates on isolated scripted/mock W16 filings."""
import copy
import json
import unittest
from app.dispute import parse_dispute
from app.schemas import DEMO_NOTICE_MESSAGE, UNDER_REVIEW_MESSAGE, HUMAN_REVIEW_MESSAGE
from tests.w16_support import Server, DRIVER, RIDER, FORM, filing, answers, script, judge_payload, ORG_DIR, SYNTH_DIR, _record, _run
from tests.w23_support import PARTY_VIEW_KEYS

class DriverHTTP(unittest.TestCase):
    def start(self,pack=ORG_DIR,llm=None):
        server=Server(pack_dir=pack,llm=llm or script());self.addCleanup(server.close);return server
    def post(self,server,body):
        status,view=server.json("POST","/api/disputes",body)
        self.assertEqual(200,status,view)
        self.assertEqual(PARTY_VIEW_KEYS,list(view))
        return view
    def stored(self,server,view):
        path=server.run_dir(view["run_id"])/"dispute.json"
        self.assertTrue(path.is_file(),"successful filing must persist its input")
        return json.loads(path.read_text())
    def lookup(self,server,view):
        self.assertEqual((200,view),server.json("GET","/api/disputes/"+view["dispute_id"]))

    def test_valid_driver_both_categories_packs_storage_and_all_requests(self):
        for pack in (ORG_DIR,SYNTH_DIR):
            llm=script();server=self.start(pack,llm)
            for category,trip,name in (("no_show_charge","T-NS0201","NS-0201.json"),("route_deviation","T-RD0103","RD-0103.json")):
                with self.subTest(pack=pack.name,category=category):
                    llm.calls.clear();body=filing(category,trip);view=self.post(server,body)
                    stored=self.stored(server,view);parsed=parse_dispute(stored);case=server.case(view["run_id"])
                    block=stored["ryde_extensions"] if "dispute_ticket" in stored else stored
                    self.assertEqual(body["answers"],block["intake"])
                    self.assertEqual(body["answers"],parsed.intake)
                    self.assertEqual("driver",parsed.filed_by)
                    self.assertEqual([],parsed.follow_up_answers)
                    self.assertIsNone(parsed.cancellation.get("rider_claims_driver_absent"))
                    self.assertEqual(body["answers"],case["intake"]["form_answers"])
                    self.assertEqual("driver",case["intake"]["filed_by"])
                    original=parse_dispute(_record(pack,name))
                    expected_cancellation=copy.deepcopy(original.cancellation)
                    expected_cancellation.pop("rider_claims_driver_absent",None)
                    self.assertEqual(expected_cancellation,parsed.cancellation)
                    for field in ("trip","chat_log","profiles"):
                        self.assertEqual(getattr(original,field),getattr(parsed,field),field)
                    self.assertEqual(3,len(llm.calls))
                    for request in llm.calls:
                        self.assertIn("filed_by: driver",request.user_prompt)
                        for key in body["answers"]:self.assertIn('"'+key+'"',request.user_prompt)
                    self.lookup(server,view)

    def test_cross_party_category_removed_unknown_and_non_string_refused_before_run(self):
        llm=script();server=self.start(llm=llm)
        for role,category,trip,keys in (("driver","route_deviation","T-RD0103",["expected_route","was_route_agreed","asked_driver_to_stop","driver_waiting_place"]),
                ("driver","no_show_charge","T-NS0201",["where_were_you","did_driver_contact_you","rider_requested_stop"]),
                ("rider","route_deviation","T-RD0103",["route_shown_to_driver","route_agreed_with_rider","rider_requested_stop"]),
                ("rider","no_show_charge","T-NS0201",["driver_waiting_place","driver_contacted_rider"])):
            for key in keys+["what_went_wrong","unknown"]:
                with self.subTest(role=role,key=key):
                    before=list(server.out.iterdir());calls=len(llm.calls)
                    status,payload=server.json("POST","/api/disputes",filing(category,trip,role,answers={key:"x"}))
                    self.assertEqual(400,status,payload);self.assertEqual(before,list(server.out.iterdir()));self.assertEqual(calls,len(llm.calls))
        for bad in (None,True,3,[],{}):
            before=list(server.out.iterdir());calls=len(llm.calls)
            status,payload=server.json("POST","/api/disputes",filing(answers={"safety_concern":bad}))
            self.assertEqual(400,status,payload);self.assertEqual(before,list(server.out.iterdir()));self.assertEqual(calls,len(llm.calls))

    def test_shared_safety_rider_legacy_strings_normalization_and_optional_answers(self):
        server=self.start()
        for role in ("rider","driver"):
            self.post(server,filing(role=role,answers={"safety_concern":"arbitrary legacy string"}))
            self.post(server,filing(role=role,answers={}))
            body=filing(role=role);body.pop("answers");view=self.post(server,body)
            self.assertEqual({},parse_dispute(self.stored(server,view)).intake)
        body=filing(role="driver",answers={"driver_waiting_place":"x"*10001});body["filed_by"]=" Driver "
        view=self.post(server,body);self.assertEqual("driver",parse_dispute(self.stored(server,view)).filed_by)

    def test_driver_existing_invalid_fields_and_boundaries(self):
        llm=script();server=self.start(llm=llm)
        invalid=[{"description":x} for x in (None,"","   ","x"*2001)]
        invalid += [{"filed_by":x} for x in (None,[],True,"owner")]
        invalid += [{"answers":x} for x in (None,[],True,"x")]
        invalid += [{"claim_amount_sgd":x} for x in (True,"1",-0.01,500.01,float("inf"))]
        invalid += [{"category":"other", "answers":{"safety_concern":"No"}}, {"trip_id":"T-RD0103"},
                    {"category":"route_deviation","trip_id":"T-NS0201","answers":{}}, {"trip_id":"UNKNOWN"}]
        for patch in invalid:
            with self.subTest(patch=patch):
                before=list(server.out.iterdir());calls=len(llm.calls)
                status,payload=server.json("POST","/api/disputes",dict(filing(),**patch))
                self.assertEqual(404 if patch.get("trip_id")=="UNKNOWN" else 400,status,payload)
                self.assertEqual(before,list(server.out.iterdir()));self.assertEqual(calls,len(llm.calls))
        for amount in (None,0,500):self.post(server,filing(description="x"*2000,claim_amount_sgd=amount,answers={}))

    def test_one_round_driver_identity_replies_reference_recovery_both_packs(self):
        for pack in (ORG_DIR,SYNTH_DIR):
          for category,trip,slot,gate in (("route_deviation","T-RD0103","rider_requested_stop","RD-4"),
                                         ("no_show_charge","T-NS0201","driver_contacted_rider","NS-8")):
            label=next(l for k,l,t in DRIVER[category] if k==slot);question=FORM%label
            llm=script(rider=["form:"+slot],driver=["form:"+slot],judge=judge_payload("compensation",.5,("RD-1",) if gate=="RD-4" else ("NS-2",),.95))
            server=self.start(pack,llm);first=self.post(server,filing(category,trip))
            self.assertEqual("needs_info",first["status"]);self.assertEqual([question],first["questions"])
            self.assertEqual(["rider_advocate","driver_advocate"],[q.agent for q in llm.calls]);self.lookup(server,first)
            reply={"answers":[{"question":question,"answer":"The rider asked for that stop."}]}
            status,second=server.json("POST","/api/disputes/"+first["run_id"]+"/answers",reply)
            self.assertEqual(200,status,second);self.assertEqual("under_review",second["status"])
            self.assertNotEqual(first["run_id"],second["run_id"]);self.assertEqual(first["dispute_id"],second["dispute_id"])
            self.assertEqual([],second["questions"]);self.lookup(server,second)
            stored=self.stored(server,second);parsed=parse_dispute(stored)
            block=stored["ryde_extensions"] if "dispute_ticket" in stored else stored
            self.assertEqual(reply["answers"],block["follow_up_answers"])
            self.assertEqual(reply["answers"],parsed.follow_up_answers);self.assertEqual("driver",parsed.filed_by)
            self.assertEqual(answers(category),parsed.intake)
            case=server.case(second["run_id"]);self.assertEqual(reply["answers"],case["intake"]["follow_up_answers"])
            self.assertIsInstance(case["resolution"]["withheld_candidate"],dict)
            self.assertTrue(any(gate in n for n in case["resolution"]["notes"]))
            for request in llm.calls[2:]:
                self.assertIn("filed_by: driver",request.user_prompt);self.assertIn(reply["answers"][0]["answer"],request.user_prompt)
            self.assertEqual(409,server.json("POST","/api/disputes/"+first["run_id"]+"/answers",reply)[0])

    def test_pre_feature_driver_persisted_question_remains_answerable(self):
        # A real rider stop is copied then marked as an old driver filing. New HTTP rejects its keys;
        # persisted strings remain authoritative for continuation, with no migration.
        server=self.start(llm=script(driver=["form:expected_route"]))
        first=self.post(server,filing("route_deviation","T-RD0103",role="rider"))
        self.assertEqual("needs_info",first["status"])
        def old_driver(doc):doc["dispute_ticket"]["filed_by"]="driver"
        path=server.run_dir(first["run_id"])/"dispute.json"
        historical=json.loads(path.read_text());old_driver(historical);path.write_text(json.dumps(historical))
        reply={"answers":[{"question":q,"answer":"Historical reply"} for q in first["questions"]]}
        server.set_llm(script())
        status,view=server.json("POST","/api/disputes/"+first["run_id"]+"/answers",reply)
        self.assertEqual(200,status,view);self.assertNotEqual("needs_info",view["status"])
        self.assertEqual("driver",parse_dispute(self.stored(server,view)).filed_by)
        self.lookup(server,view)

    def test_fixed_account_separation_read_only_driver_stop(self):
        server=self.start(llm=script(driver=["form:rider_requested_stop"]))
        mine=self.post(server,filing("route_deviation","T-RD0109"))
        other=self.post(server,filing("route_deviation","T-RD0103"))
        self.assertEqual("needs_info",mine["status"])
        status,drivers=server.json("GET","/api/demo/driver");self.assertEqual(200,status)
        self.assertEqual("D-2009",drivers["account"]["driver_id"])
        self.assertEqual([mine["dispute_id"]],[e["dispute_id"] for e in drivers["disputes"]])
        entry=drivers["disputes"][0];self.assertEqual("",entry["run_id"]);self.assertEqual([],entry["questions"])
        self.assertEqual("under_review",entry["status"])
        self.assertEqual([],server.json("GET","/api/demo/rider")[1]["disputes"])
        self.lookup(server,mine);self.lookup(server,other)

    def test_supported_ns0201_existing_fee_stands_no_transfer(self):
        judge=judge_payload("no action",0,("NS-2","NS-3"),.95)
        judge["cited_evidence_refs"]=["cancellation.driver_wait_minutes","cancellation.driver_distance_from_pickup_m","cancellation.cancellation_fee_sgd"]
        server=self.start(llm=script(judge=judge));view=self.post(server,filing())
        self.assertEqual("decided",view["status"]);self.assertTrue(view["message"].startswith(DEMO_NOTICE_MESSAGE))
        self.assertIn("Decision: no action.",view["message"]);self.assertNotIn("SGD",view["message"])
        case=server.case(view["run_id"]);resolution=case["resolution"]
        self.assertEqual("ruled",resolution["outcome"]);self.assertIsNone(resolution["withheld_candidate"])
        self.assertEqual(0,resolution["ruling"]["recommended_amount_sgd"])
        self.assertEqual([],resolution["ruling"]["validation"]["unknown_evidence_refs"])
        pack=case["evidence_pack"]
        self.assertEqual((5.5,18.1,6.61),tuple(pack["cancellation"][k] for k in ("driver_wait_minutes","driver_distance_from_pickup_m","cancellation_fee_sgd")))
        self.assertEqual(6.61,parse_dispute(self.stored(server,view)).cancellation["cancellation_fee_sgd"])
        self.assertEqual([],server.json("GET","/api/review/queue")[1]["cases"]);self.lookup(server,view)

    def test_small_compensation_sole_ns8_and_rd4_hold_no_party_leak(self):
        for c,trip,gate in (("no_show_charge","T-NS0201","NS-8"),("route_deviation","T-RD0103","RD-4")):
            server=self.start(llm=script(judge=judge_payload("compensation",.5,("NS-2",) if gate=="NS-8" else ("RD-1",),.95)))
            view=self.post(server,filing(c,trip));self.assertEqual("under_review",view["status"])
            self.assertEqual(UNDER_REVIEW_MESSAGE,view["message"]);self.assertEqual([],view["questions"])
            case=server.case(view["run_id"]);resolution=case["resolution"]
            self.assertEqual("withheld",resolution["outcome"]);self.assertIsNone(resolution["ruling"])
            candidate=resolution["withheld_candidate"];self.assertIsInstance(candidate,dict)
            self.assertEqual(("compensation",.5,.95),(candidate["action"],candidate["recommended_amount_sgd"],candidate["confidence"]))
            self.assertTrue(any(gate in n for n in resolution["notes"]))
            if gate=="RD-4":
                pack=case["evidence_pack"]
                self.assertEqual(6.0,pack["route"]["deviation_pct"])
                self.assertEqual((11.69,0.0,[]),tuple(pack["fare"][k] for k in ("charged_sgd","difference_sgd","unreadable_inputs")))
            status,queue=server.json("GET","/api/review/queue");self.assertEqual(200,status)
            self.assertEqual(1,len(queue["cases"]));self.assertEqual([gate],queue["cases"][0]["held_by"])
            self.assertEqual(.5,queue["cases"][0]["proposed"]["amount_sgd"])
            status,operator=server.json("GET","/api/review/"+view["run_id"]+"/case");self.assertEqual(200,status)
            self.assertIn("0.5",json.dumps(operator));self.lookup(server,view)
            for token in ("withheld_candidate","confidence","compensation",gate,"0.50","0.95","scripted ruling"):
                self.assertNotIn(token,json.dumps(view))
            from tests.w16_support import drive
            dom=drive("driver",view=view)
            self.assertEqual(UNDER_REVIEW_MESSAGE,dom["message"])
            for token in ("0.50","0.95",gate,"compensation","scripted ruling"):
                self.assertNotIn(token,dom["title"]+dom["message"])

    def test_cleaning_support_zero_calls_no_withheld_queue_or_image_workflow(self):
        llm=script();server=self.start(llm=llm)
        for trip in ("T-NS0201","T-RD0103"):
            view=self.post(server,filing("property_damage_mess",trip,claim_amount_sgd=25,answers={}))
            self.assertEqual("passed_to_support",view["status"]);self.assertEqual(HUMAN_REVIEW_MESSAGE,view["message"])
            self.assertEqual([],llm.calls);case=server.case(view["run_id"])
            self.assertEqual("property_damage_mess",case["intake"]["category_as_submitted"])
            self.assertEqual("other",case["category"])
            self.assertIsNone(case["evidence_pack"]);self.assertEqual({"rider":None,"driver":None},case["claims"])
            self.assertIsNone(case["resolution"]["ruling"]);self.assertIsNone(case["resolution"]["withheld_candidate"])
            self.assertEqual([],server.json("GET","/api/review/queue")[1]["cases"])
            self.assertEqual(409,server.decide(view["run_id"], {"decision":"reject","reviewer":"Test","reason":"No workflow"})[0]);self.lookup(server,view)

    def test_driver_legacy_rider_blank_keys_never_trigger_driver_follow_up(self):
        for category, key in (("no_show_charge", "where_were_you"),
                              ("route_deviation", "asked_driver_to_stop")):
            case=_record(ORG_DIR, "NS-0201.json" if category == "no_show_charge" else "RD-0103.json")
            case["dispute_ticket"]["filed_by"]="driver"
            case["ryde_extensions"]["intake"]={key:""}
            result=_run(case, llm=script(driver=["wrong"]))
            self.assertNotEqual("needs_info",result["resolution"]["outcome"])
            self.assertEqual([],result["resolution"].get("questions_for_party",[]))

if __name__=="__main__":unittest.main()
