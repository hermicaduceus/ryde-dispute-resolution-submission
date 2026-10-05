"""Frozen W16 behaviour. Run /usr/bin/python3 -B -m unittest tests.test_w16_driver_contract."""
import inspect
import json
import unittest
from app import schemas as s
from app.dispute import parse_dispute
from app.llm.mock import MockLLMClient
from tests.w16_support import DRIVER, RIDER, BANK, FORM, BLANK, record, script, _run, ORG_DIR, SYNTH_DIR

class TablesAndSlots(unittest.TestCase):
    def selector(self):
        fn = getattr(s, "intake_questions_for", None)
        self.assertTrue(callable(fn), "missing role/category intake selector")
        return fn

    def enum(self, category, role):
        self.assertIn("filed_by", inspect.signature(s.follow_up_slot_ids).parameters,
                      "enumerator must accept the filer explicitly")
        return s.follow_up_slot_ids(category, role)

    def test_exact_driver_table_and_kinds(self):
        self.assertEqual({c: tuple((k,l) for k,l,t in rows) for c,rows in DRIVER.items()},
                         getattr(s,"DRIVER_INTAKE_QUESTIONS",None))
        self.assertEqual(frozenset(k for rows in DRIVER.values() for k,l,t in rows if t=="yes_no"),
                         getattr(s,"DRIVER_YES_NO_INTAKE_KEYS",None))
        for rows in DRIVER.values():
            self.assertEqual(len(rows), len(set(k for k,l,t in rows)))

    def test_rider_exports_and_default_selector_unchanged(self):
        from app.server import QUESTIONNAIRES
        self.assertEqual({c:tuple((k,l) for k,l,t in rows) for c,rows in RIDER.items()},s.INTAKE_QUESTIONS)
        self.assertEqual({c:tuple(k for k,l,t in rows) for c,rows in RIDER.items()},QUESTIONNAIRES)
        self.assertEqual(frozenset(k for rows in RIDER.values() for k,l,t in rows if t=="yes_no"),s.YES_NO_INTAKE_KEYS)
        for c,rows in RIDER.items():
            self.assertEqual(list(BANK[c])+["form:"+k for k,l,t in rows],s.follow_up_slot_ids(c))
            for k,l,t in rows:self.assertEqual(FORM%l,s.render_follow_up_slot(c,"form:"+k))

    def test_selector_enum_render_parity_both_roles(self):
        fn=self.selector()
        for role,table in (("rider",RIDER),("driver",DRIVER)):
            for c,rows in table.items():
                with self.subTest(role=role,category=c):
                    self.assertEqual(tuple((k,l) for k,l,t in rows),fn(c,role))
                    if role=="rider":self.assertEqual(tuple((k,l) for k,l,t in rows),fn(c))
                    expected=(list(BANK[c]) if role=="rider" else [])+["form:"+k for k,l,t in rows]
                    self.assertEqual(expected,self.enum(c,role))
                    for k,l,t in rows:
                        self.assertEqual(FORM%l,s.render_follow_up_slot(c,"form:"+k,role))
                    self.assertTrue(all(s.render_follow_up_slot(c,i,role) is not None for i in expected))
                    if role=="rider":self.assertEqual(expected,s.follow_up_slot_ids(c))

    def test_malformed_selector_and_enum_are_total(self):
        fn=self.selector()
        bad=[None,True,3,[],{},""," ","unknown"]
        for c,r in [(c,r) for c in bad for r in ("rider","driver")]+[("route_deviation",r) for r in bad]+[("route_deviation"," Driver ")]:
            with self.subTest(category=c,role=r):
                try: selected,slots=fn(c,r),self.enum(c,r)
                except (TypeError,ValueError) as exc:self.fail("malformed arguments must be refused, not raised: %s"%exc)
                self.assertEqual((),selected)
                self.assertEqual([],slots)
                if r=="rider":
                    try: default_slots=s.follow_up_slot_ids(c)
                    except (TypeError,ValueError) as exc:self.fail("malformed rider default must be refused, not raised: %s"%exc)
                    self.assertEqual([],default_slots)
        for c in ("other","property_damage_mess","safety_incident"):
            self.assertEqual((),fn(c,"driver"));self.assertEqual([],self.enum(c,"driver"))

    def test_render_refuses_wrong_role_category_id_and_type(self):
        bad=[None,True,3,[],{},""," ","unknown"]
        cases=[(c,"form:safety_concern","driver") for c in bad]
        cases += [("route_deviation",i,"driver") for i in bad]
        cases += [("route_deviation","form:safety_concern",r) for r in bad+[" Driver "]]
        cases += [("route_deviation",i,"driver") for i in BANK["route_deviation"]]
        cases += [("no_show_charge",i,"driver") for i in BANK["no_show_charge"]]
        cases += [(c,"form:"+k,"driver") for c,rows in RIDER.items() for k,l,t in rows if k!="safety_concern"]
        cases += [(c,"form:"+k,"rider") for c,rows in DRIVER.items() for k,l,t in rows if k!="safety_concern"]
        cases += [("route_deviation","form:driver_waiting_place","driver"),("no_show_charge","form:rider_requested_stop","driver")]
        for c,i,r in cases:
            with self.subTest(category=c,id=i,role=r):
                try:value=s.render_follow_up_slot(c,i,r)
                except (TypeError,ValueError) as exc:self.fail("renderer raised instead of refusing: %s"%exc)
                self.assertIsNone(value)
        for role in ("driver","rider"):
            for c in DRIVER:self.assertEqual(FORM%DRIVER[c][-1][1],s.render_follow_up_slot(c,"form:safety_concern",role))

class AdvocateAndPipeline(unittest.TestCase):
    def test_driver_parser_preserves_audit_dedup_bound_and_refuses_shapes(self):
        payload={"requested_outcome":"no action","requested_amount_sgd":0,"argument":"x","claim_summary":"x"}
        def parse(slots):return s.AdvocateCase.from_payload(dict(payload,follow_up_slots=slots,follow_up_questions=["SMUGGLED?"]),party="rider",agent="rider_advocate",category="route_deviation",filed_by="driver")
        slots=["form:rider_requested_stop","form:rider_requested_stop","route_shown","form:expected_route","SMUGGLED?","unknown","form:safety_concern"]
        case=parse(slots)
        self.assertEqual(slots[:6],case.follow_up_slots)
        self.assertEqual([FORM%DRIVER["route_deviation"][2][1]],case.follow_up_questions)
        notes=" ".join(case.validation["notes"])
        for token in ("route_shown","form:expected_route","SMUGGLED","limit 6"):self.assertIn(token,notes)
        self.assertEqual([],parse(None).follow_up_questions)
        for bad in ([],):self.assertEqual([],parse(bad).follow_up_questions)
        for bad in ("x",{},[None],[True],[3],[[]],[{}],[""]):
            with self.subTest(bad=bad),self.assertRaises(s.ContractError):parse(bad)

    def test_both_advocate_prompts_offer_exact_filer_slots(self):
        for category,rows in DRIVER.items():
            llm=script();_run(record(category),llm=llm)
            requests=[q for q in llm.calls if q.agent.endswith("advocate")]
            self.assertEqual(2,len(requests))
            for request in requests:
                self.assertIn("filed_by: driver",request.user_prompt)
                block=request.user_prompt.split("FOLLOW-UP QUESTION SLOTS\n")[1].split("\n\nYOUR TASK")[0]
                self.assertEqual("\n".join("form:%s: %s"%(k,FORM%l) for k,l,t in rows),block)
                for k,l,t in rows:self.assertIn('"'+k+'"',request.user_prompt)

    def test_mock_blank_key_each_category_and_pack_then_no_reask(self):
        class Capture(MockLLMClient):
            def __init__(self):super().__init__();self.calls=[]
            def complete(self,request):self.calls.append(request);return super().complete(request)
        for pack in (ORG_DIR,SYNTH_DIR):
            for category,rows in DRIVER.items():
                for k,l,t in rows:
                    with self.subTest(pack=pack.name,category=category,key=k):
                        rec=record(category,pack,intake={k:"   "});llm=Capture();case=_run(rec,llm=llm)
                        self.assertEqual("needs_info",case["resolution"]["outcome"])
                        self.assertEqual([FORM%l],case["resolution"]["questions_for_party"])
                        self.assertEqual(["form:"+k],case["claims"]["driver"]["follow_up_slots"])
                        self.assertEqual([],case["claims"]["rider"]["follow_up_slots"])
                        self.assertEqual([k],llm.calls[1].metadata["blank_intake_questions"])
                        rec=record(category,pack,intake={k:""},replies=[{"question":FORM%l,"answer":"Reply"}])
                        second=_run(rec,llm=Capture())
                        self.assertNotEqual("needs_info",second["resolution"]["outcome"])
                        self.assertEqual([],second["claims"]["driver"]["follow_up_slots"])

    def test_fallback_driver_table_order_present_blanks_only(self):
        for c,rows in DRIVER.items():
            case=_run(record(c,intake={k:"" for k,l,t in reversed(rows)}),llm=script(driver=["wrong"]))
            self.assertEqual("needs_info",case["resolution"]["outcome"])
            self.assertEqual([BLANK%l for k,l,t in rows][:3],case["resolution"]["questions_for_party"])
            case=_run(record(c,intake={rows[0][0]:None}),llm=script(driver=["wrong"]))
            self.assertNotEqual("needs_info",case["resolution"]["outcome"])
            self.assertEqual([],case["resolution"]["questions_for_party"])

    def test_valid_slots_suppress_fallback_filer_first_dedup_cap(self):
        rows=DRIVER["route_deviation"]
        llm=script(rider=["form:"+rows[0][0],"form:"+rows[3][0]],driver=["form:"+rows[2][0],"form:"+rows[1][0],"form:"+rows[2][0]])
        case=_run(record(intake={k:"" for k,l,t in rows}),llm=llm)
        self.assertEqual("needs_info",case["resolution"]["outcome"])
        self.assertEqual([FORM%rows[i][1] for i in (2,1,0)],case["resolution"]["questions_for_party"])
        self.assertFalse(any(q.agent=="judge" for q in llm.calls))

if __name__=="__main__":unittest.main()
