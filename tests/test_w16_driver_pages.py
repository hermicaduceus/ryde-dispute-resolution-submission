"""Driven shared JavaScript and HTTP-served W16 pages. Not a real browser claim."""
import json
import re
import unittest
from tests.w16_support import ROOT, DRIVER, RIDER, RIDER_CATEGORIES, RIDER_CATEGORY_IDS, DRIVER_CATEGORIES, DRIVER_CATEGORY_IDS, DESCRIPTION_ERROR, AMOUNT_ERROR, INVALID_PAGE, drive, Server
from tests.w23_support import html_text

class DrivenPages(unittest.TestCase):
    def test_all_role_category_cards_keep_labels_and_post_ids(self):
        for role, labels, ids in ((None, RIDER_CATEGORIES, RIDER_CATEGORY_IDS),
                                  ("rider", RIDER_CATEGORIES, RIDER_CATEGORY_IDS),
                                  ("driver", DRIVER_CATEGORIES, DRIVER_CATEGORY_IDS)):
            with self.subTest(role=role):
                out = drive(role, category=0, pending=True)
                self.assertEqual(labels, out["categories"])
                for index, expected_id in enumerate(ids):
                    with self.subTest(category=index, expected_id=expected_id):
                        selected = drive(role, category=index, pending=True)
                        posts = [call for call in selected["calls"] if call["method"] == "POST"]
                        self.assertEqual(1, len(posts))
                        self.assertEqual(expected_id, posts[0]["body"]["category"])

    def test_each_role_category_exact_rendered_rows_and_accessible_controls(self):
        for role,table in ((None,RIDER),("rider",RIDER),("driver",DRIVER)):
            for i,(category,rows) in enumerate(table.items()):
                with self.subTest(role=role,category=category):
                    out=drive(role,category=i,pending=True)
                    self.assertEqual(list(rows),[(r["key"],r["label"],r["kind"]) for r in out["initial"]])
                    self.assertEqual([False,False,True],out["visible"])
                    for row in out["initial"]:
                        if row["kind"]=="yes_no":
                            self.assertEqual("group",row["role"]);self.assertEqual("label-"+row["key"],row["labelledBy"])
                            self.assertEqual(row["labelledBy"],row["labelId"]);self.assertEqual(["false","false"],row["pressed"])
                            self.assertEqual("Tell us more: "+row["label"],row["elaboration"])
                        else:self.assertEqual("answer-"+row["key"],row["for"])
                    posted=[c for c in out["calls"] if c["method"]=="POST"]
                    self.assertEqual(1,len(posted));self.assertEqual(role or "rider",posted[0]["body"]["filed_by"])
                    self.assertEqual({k:"" for k,l,t in rows},posted[0]["body"]["answers"])
                    self.assertIsNone(posted[0]["body"]["claim_amount_sgd"])
                    self.assertTrue(out["submitDisabled"])
                    if role=="driver":self.assertEqual(DRIVER_CATEGORIES,out["categories"])

    def test_driver_choice_serialization_switch_and_same_choice(self):
        for steps,expected in (([["click","rider_requested_stop","Yes"],["type","rider_requested_stop"," At the shop "]],"Yes - At the shop"),
            ([["click","rider_requested_stop","Yes"],["type","rider_requested_stop","Old"],["click","rider_requested_stop","No"]],"No"),
            ([["click","rider_requested_stop","Yes"],["type","rider_requested_stop","Old"],["click","rider_requested_stop","Yes"]],"Yes - Old")):
            out=drive("driver",steps=steps+[["open","route_shown_to_driver","route text"]],pending=True)
            posts=[c for c in out["calls"] if c["method"]=="POST"];self.assertEqual(1,len(posts))
            self.assertEqual({"route_shown_to_driver":"route text","route_agreed_with_rider":"","rider_requested_stop":expected,"safety_concern":""},posts[0]["body"]["answers"])

    def test_category_switch_resets_trip_and_serializes_only_new_keys(self):
        out=drive("driver",steps=[["open","route_shown_to_driver","old route"]],switchCategory=1,pending=True)
        self.assertEqual({"tripDisabled":True,"tripCount":0},out["reset"])
        self.assertEqual(list(DRIVER["no_show_charge"]),[(r["key"],r["label"],r["kind"]) for r in out["finalRows"]])
        posts=[c for c in out["calls"] if c["method"]=="POST"];self.assertEqual(1,len(posts))
        self.assertEqual("no_show_charge",posts[0]["body"]["category"])
        self.assertEqual({"driver_waiting_place":"","driver_contacted_rider":"","safety_concern":""},posts[0]["body"]["answers"])
        self.assertEqual("driver",posts[0]["body"]["filed_by"])

    def test_invalid_explicit_marker_disables_all_requests(self):
        for role in (""," Driver ","owner","DRIVER","null","constructor","__proto__",
                     "toString","hasOwnProperty","valueOf","isPrototypeOf"):
            with self.subTest(role=role):
                out=drive(role)
                self.assertEqual([],out["calls"])
                self.assertEqual(INVALID_PAGE,out["error"])
                self.assertTrue(out["errorVisible"])
        self.assertTrue(drive(None,pending=True)["calls"])
        self.assertTrue(drive("driver",pending=True)["calls"])

    def test_driver_required_description_and_amount_limits(self):
        for opts in ({"description":" "},{"amount":"-1"},{"amount":"500.01"}):
            out=drive("driver",**opts)
            self.assertEqual([], [c for c in out["calls"] if c["method"]=="POST"])
            self.assertTrue(out["detailsError"])
        out=drive("driver",amount="500",pending=True)
        self.assertEqual(500,out["calls"][-1]["body"]["claim_amount_sgd"])

    def test_outcome_safe_text_status_headings_and_exact_reply_post(self):
        for status,heading in (("decided","We have made a decision"),("under_review","Your case is still under review"),("passed_to_support","Your report has been passed to our support team"),("needs_info","We need a little more information")):
            out=drive("driver",view={"run_id":"current-run","dispute_id":"PF-REF","status":status,"message":"<img src=x onerror=evil()>","questions":[]})
            self.assertEqual(heading,out["title"]);self.assertEqual("PF-REF",out["reference"])
            self.assertEqual("<img src=x onerror=evil()>",out["message"])
        out=drive("driver",reply=True)
        self.assertEqual(["I have nothing more to add",""],out["ownBox"]);self.assertEqual(1,out["missingReplyPosts"])
        self.assertTrue(out["replyDisabled"])
        posts=[c for c in out["calls"] if c["method"]=="POST"];self.assertEqual(2,len(posts))
        self.assertEqual("/api/disputes/run-first/answers",posts[1]["url"])
        self.assertEqual({"answers":[{"question":"First question?","answer":"I have nothing more to add"},{"question":"Second question?","answer":"Reply 1"}]},posts[1]["body"])
        self.assertEqual("Your case is still under review",out["title"])

class ServedPagesAndDocs(unittest.TestCase):
    def setUp(self):self.server=Server();self.addCleanup(self.server.close)
    def get(self,path,mime="text/html"):
        status,headers,raw=self.server.raw("GET",path)
        self.assertEqual(200,status,"missing served page/resource: "+path)
        self.assertIn(mime,headers.get("Content-Type",""));return raw.decode()

    def test_new_page_shared_resources_exact_copy_and_links(self):
        html=self.get("/party/driver-filing.html");text=html_text(html)
        copy=["Ryde - file a driver trip dispute","RYDE / DRIVER HELP","File a driver trip dispute",
              "Tell us what happened on a trip from your side as the driver. Three quick steps.",
              "Demo filing: choose a sample trip and file from that trip's driver's perspective. This is not a signed-in account.",
              "The driver demo account shows only trips for driver D-2009, including T-RD0109. A filing on another sample trip will not appear there.",
              "An amount you enter is a request, not a payment."]
        for value in copy:self.assertIn(value,text)
        hint="Save your reference number. Use it on the status page to answer questions or check the outcome. Driver filings are not listed in the rider demo list."
        self.assertEqual(1,text.count(hint));self.assertEqual(2,text.count("Look up your reference number"))
        for href,label in (("./status.html#reference-input","Look up your reference number"),("./index.html","Go to rider help"),("./driver.html","View the driver demo account")):
            self.assertRegex(html,r'<a\s+href="'+re.escape(href)+r'">'+re.escape(label)+r'</a>')
        self.assertRegex(html,r'<section\b[^>]*id="form-steps"[^>]*data-filed-by="driver"')
        self.assertEqual(1,html.count('data-filed-by="driver"'))
        self.assertIn('<script src="./party.js" defer></script>',html);self.assertIn('href="./party.css"',html)
        self.assertLess(html.index('id="description"'),html.index('id="question-list"'))
        self.assertNotRegex(html,r'type="file"|<img|upload|photograph')
        self.get("/party/party.js","javascript");self.get("/party/party.css","text/css")

    def test_driver_shell_contains_every_party_script_id(self):
        html=self.get("/party/driver-filing.html")
        script=self.get("/party/party.js","javascript")
        html_ids=set(re.findall(r'\bid="([^"]+)"',html))
        script_ids=set(re.findall(r'document\.getElementById\("([^"]+)"\)',script))
        self.assertTrue(script_ids)
        self.assertTrue(script_ids.issubset(html_ids),
                        "driver shell is missing party.js ids: %s" % sorted(script_ids-html_ids))

    def test_navigation_account_boundary_form_free_and_status_anchor(self):
        rider=self.get("/party/index.html");driver=self.get("/party/driver.html");status=self.get("/party/status.html")
        self.assertIn('<a href="./driver-filing.html">Filing as a driver?</a>',rider)
        self.assertIn('<a href="./driver-filing.html">File a driver trip dispute</a>',driver)
        text=html_text(driver)
        self.assertIn("This page is read-only. To file a driver dispute, use the driver filing page.",text)
        self.assertIn("This demo account is for driver D-2009. The filing page lets you choose other sample trips; those filings will not appear here.",text)
        self.assertNotRegex(driver,r'<(?:form|textarea|input)\b|data-filed-by')
        self.assertIn('<script src="./driver.js" defer></script>',driver)
        self.assertNotIn("party.js",driver);self.assertIn('id="reference-input"',status)

    def test_role_error_and_amount_validation_copy_is_exact(self):
        for role in (None, "rider", "driver"):
            with self.subTest(role=role):
                missing=drive(role,description=" ")
                self.assertEqual(DESCRIPTION_ERROR,missing["detailsError"])
                bad=drive(role,amount="500.01")
                self.assertEqual(AMOUNT_ERROR,bad["detailsError"])

    def test_docs_both_roles_diagram_parity_identity_and_support_limits(self):
        readme=(ROOT/"README.md").read_text();arch=(ROOT/"docs/architecture.md").read_text();prompts=(ROOT/"docs/prompts.md").read_text()
        blocks=[re.findall(r'```mermaid\n(.*?)```',text,re.S) for text in (readme,arch)]
        self.assertTrue(blocks[0]);self.assertEqual(blocks[0],blocks[1])
        self.assertRegex(blocks[0][0],r'(?i)rider.*driver|driver.*rider')
        for text in (readme,arch):self.assertIn("driver-filing.html",text)
        for token in ("D-2009","reference","driver","form slots","cleaning","queue"):
            self.assertIn(token,arch)
        self.assertNotRegex(arch.lower(),r'driver[^\n]*(?:form not built|filing form.*not built)|driver-side intake form is not built')
        self.assertRegex(prompts,r'(?is)category.{0,80}filer|filer.{0,80}category')
        self.assertIn("driver form",prompts);self.assertRegex(prompts,r'(?i)not (?:corroborated )?evidence')

if __name__=="__main__":unittest.main()
