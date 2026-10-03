"""W23 B2 acceptance: console HTML, queue, payload routing and degradation."""
from __future__ import annotations
import re,unittest
from pathlib import Path
from tests.w23_b2_support import REPO,bad,base_routes,case_file,drive,ok,queue_row

class RegionsAndSafety(unittest.TestCase):
 def test_three_regions_and_exact_headings(self):
  h=(REPO/"ui/index.html").read_text()
  self.assertRegex(h,r'<section id="queue-panel" aria-labelledby="queue-title">[\s\S]*?<h2 id="queue-title">Review queue</h2>[\s\S]*?<button id="queue-refresh" type="button">Refresh</button>[\s\S]*?<p id="queue-status" role="status" aria-live="polite">[\s\S]*?<div id="queue-content">')
  self.assertRegex(h,r'<section id="overrides-panel" aria-labelledby="overrides-title">[\s\S]*?<h2 id="overrides-title">Overrides</h2>[\s\S]*?<p id="overrides-status" role="status">[\s\S]*?<div id="overrides-content">')
  self.assertRegex(h,r'id="resolution-section"[\s\S]*?<section id="decision-section" class="story-section" aria-labelledby="decision-title" hidden>[\s\S]*?<p class="section-index">05</p>[\s\S]*?HUMAN DECISION[\s\S]*?<h2 id="decision-title">Decide this case</h2>[\s\S]*?id="events-section"[\s\S]*?<p class="section-index">06</p>')
  self.assertLess(h.index('id="queue-panel"'),h.index('class="loader-panel"'));self.assertLess(h.index('id="queue-panel"'),h.index('id="overrides-panel"'))
 def test_no_injection_sinks_or_party_operator_leak(self):
  app=(REPO/"ui/app.js").read_text()
  for sink in ("innerHTML","outerHTML","insertAdjacentHTML","document.write"):self.assertNotIn(sink,app)
  for p in (REPO/"ui/party").rglob("*"):
   if p.is_file():self.assertNotIn("/api/review/",p.read_text(errors="ignore"),str(p))

class QueueBehaviour(unittest.TestCase):
 def test_rows_preserve_order_and_render_distinct_fields(self):
  rows=[queue_row(run_id="B",category="other",safety=True,amount_sgd=30,amount_source="claimed",held_by=["model_failure","RD-4"]),queue_row(run_id="A",category="no_show_charge",amount_sgd=None,amount_source=None,held_by=[])]
  o=drive(base_routes(rows),[])
  self.assertEqual(["Other","No-show charge"],[x["text"] for x in o["classes"]["queue-category"]])
  self.assertEqual(["Safety"],[x["text"] for x in o["classes"]["queue-safety"]])
  self.assertEqual(["SGD 30.00 claimed","No amount on record"],[x["text"] for x in o["classes"]["queue-amount"]])
  self.assertEqual(["Held by: model failure, RD-4","Held by: not recorded"],[x["text"] for x in o["classes"]["queue-held"]])
  self.assertEqual(["Open case","Open case"],[x["text"] for x in o["classes"]["queue-open"]]);self.assertEqual("2 cases waiting.",o["ids"]["queue-status"]["text"])
 def test_proposed_amount_and_singular_and_empty(self):
  o=drive(base_routes([queue_row()]),[]);self.assertEqual("1 case waiting.",o["ids"]["queue-status"]["text"]);self.assertEqual("SGD 55.16 proposed",o["classes"]["queue-amount"][0]["text"])
  o=drive(base_routes([]),[]);self.assertEqual("No cases are waiting for a human decision.",o["ids"]["queue-status"]["text"]);self.assertEqual([],o["classes"]["queue-row"])
 def test_waiting_boundaries_both_sides(self):
  seconds=[59,60,3599,3600,86399,86400]
  o=drive(base_routes([queue_row(run_id=str(x),waiting_seconds=x) for x in seconds]),[])
  self.assertEqual(["Waiting under a minute","Waiting 1 min","Waiting 59 min","Waiting 1 h 0 min","Waiting 23 h 59 min","Waiting 1 d 0 h"],[x["text"] for x in o["classes"]["queue-waiting"]])
 def test_missing_optional_queue_shapes_do_not_crash(self):
  rows=[]
  for key in ("amount_sgd","amount_source","held_by","proposed","can_approve"):
   r=queue_row(run_id=key);r.pop(key);rows.append(r)
  rows += [queue_row(run_id="null",amount_sgd=None),queue_row(run_id="empty",held_by=[]),queue_row(run_id="pnull",proposed=None),queue_row(run_id="no",can_approve=False)]
  o=drive(base_routes(rows),[]);self.assertEqual(len(rows),len(o["classes"]["queue-row"]))
 def test_load_and_refresh_fetch_once_then_both_again(self):
  routes=base_routes([]);routes["/api/review/queue"]*=2;routes["/api/review/overrides"]*=2
  o=drive(routes,[{"id":"queue-refresh","op":"click"}]);urls=[r["url"] for r in o["requests"]]
  self.assertEqual(2,urls.count("/api/review/queue"));self.assertEqual(2,urls.count("/api/review/overrides"))
 def test_non_200_and_rejection_degrade_independently(self):
  q="The review queue is not available. Open the console from the running server to use it."
  for qr,ov in ((bad(),bad()),({"reject":True},{"reject":True})):
   o=drive({"/api/review/queue":[qr],"/api/review/overrides":[ov]},[]);self.assertEqual(q,o["ids"]["queue-status"]["text"]);self.assertEqual("Overrides are not available.",o["ids"]["overrides-status"]["text"])
 def test_open_case_encodes_run_and_file_picker_clears_decidability(self):
  routes=base_routes([queue_row()]);routes["/api/review/RUN%20%2F%207/case"]=[ok({"case_file":case_file(),"human_decision":None})]
  o=drive(routes,[{"className":"queue-open","op":"click"}]);self.assertIn("/api/review/RUN%20%2F%207/case",[r["url"] for r in o["requests"]]);self.assertEqual("RUN / 7",o["ids"]["loaded-file"]["text"]);self.assertFalse(o["ids"]["decision-section"]["hidden"])
  o=drive(routes,[{"className":"queue-open","op":"click"},{"id":"case-picker","op":"pick","body":case_file()}]);self.assertTrue(o["ids"]["decision-section"]["hidden"])
 def test_failed_open_sets_exact_error(self):
  routes=base_routes([queue_row()]);routes["/api/review/RUN%20%2F%207/case"]=[bad()]
  o=drive(routes,[{"className":"queue-open","op":"click"}]);self.assertEqual(("The case could not be opened.","error"),(o["ids"]["load-status"]["text"],o["ids"]["load-status"]["dataset"].get("state")))
 def test_server_event_payload_uses_encoded_review_url_and_errors(self):
  routes=base_routes([queue_row()]);routes["/api/review/RUN%20%2F%207/case"]=[ok({"case_file":case_file(event=True),"human_decision":None})];url="/api/review/RUN%20%2F%207/payloads/0009-judge-ruling-withheld.json";routes[url]=[ok({"secret":"shown"})]
  o=drive(routes,[{"className":"queue-open","op":"click"},{"className":"event-row","op":"toggle"}]);self.assertIn(url,[r["url"] for r in o["requests"]]);self.assertIn("secret",o["classes"]["payload-json"][0]["text"])

if __name__=="__main__":unittest.main()
