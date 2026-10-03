"""W23 B2 acceptance: decision form, confirmation, POST guard and result."""
import unittest
from tests.w23_b2_support import bad,base_routes,case_file,drive,ok,queue_row

def opened(row=None,decision=None,fare=112.56,decision_response=None):
 row=row or queue_row();routes=base_routes([row]);routes["/api/review/RUN%20%2F%207/case"]=[ok({"case_file":case_file(fare=fare),"human_decision":decision})]
 if decision_response is not None:routes["/api/review/RUN%20%2F%207/decision"]=[decision_response]
 return routes

class DecisionForm(unittest.TestCase):
 def test_form_fields_labels_and_defaults(self):
  o=drive(opened(),[{"className":"queue-open","op":"click"}]);d=o["ids"]
  self.assertFalse(d["decision-section"]["hidden"]);self.assertEqual("FORM",d["decision-form"]["tag"])
  for ident,value,label in (("decision-approve","approve","Approve the AI's proposal"),("decision-change","change","Change the decision"),("decision-reject","reject","Reject: no action")):
   self.assertEqual(("radio","decision",value,False),(d[ident]["type"],d[ident]["name"],d[ident]["value"],d[ident]["checked"]));self.assertIn(label,d["decision-content"]["text"])
  self.assertIn("Your name",d["decision-content"]["text"]);self.assertIn("Reason (staff only, never shown to the party)",d["decision-content"]["text"]);self.assertIn("Action",d["decision-content"]["text"]);self.assertIn("Amount (SGD)",d["decision-content"]["text"])
  self.assertEqual(80,d["decision-reviewer"]["maxLength"]);self.assertEqual(1000,d["decision-reason"]["maxLength"]);self.assertEqual(("number","0.01","0"),(d["decision-amount"]["type"],d["decision-amount"]["step"],d["decision-amount"]["min"]));self.assertTrue(d["decision-action"]["disabled"]);self.assertTrue(d["decision-amount"]["disabled"]);self.assertEqual("Review decision",d["decision-review"]["text"]);self.assertEqual("alert",d["decision-error"]["attrs"].get("role"))
 def test_cannot_approve_note_and_change_enables_fields(self):
  o=drive(opened(queue_row(can_approve=False,proposed=None)),[{"className":"queue-open","op":"click"},{"id":"decision-change","op":"check"}]);d=o["ids"]
  self.assertTrue(d["decision-approve"]["disabled"]);self.assertEqual("No AI proposal to approve; use Change.",o["classes"]["decision-note"][0]["text"]);self.assertFalse(d["decision-action"]["disabled"]);self.assertFalse(d["decision-amount"]["disabled"])
 def test_no_selection_exact_error(self):
  o=drive(opened(),[{"className":"queue-open","op":"click"},{"id":"decision-form","op":"submit"}]);self.assertEqual("Choose approve, change or reject.",o["ids"]["decision-error"]["text"]);self.assertNotIn("decision-confirm",o["ids"])
 def test_review_change_restates_distinct_values_warning_and_does_not_post(self):
  acts=[{"className":"queue-open","op":"click"},{"id":"decision-change","op":"check"},{"id":"decision-reviewer","op":"set","value":" Ana "},{"id":"decision-reason","op":"set","value":" because "},{"id":"decision-action","op":"set","value":"compensation"},{"id":"decision-amount","op":"set","value":"130.125"},{"id":"decision-form","op":"submit"}]
  o=drive(opened(fare=112.56),acts);text=o["ids"]["decision-confirm"]["text"]
  for line in ("Decision: Change","Amount: compensation of SGD 130.13","Trip fare charged: SGD 112.56","AI proposed: refund of SGD 55.16","This amount is more than the trip fare.","Confirm and send","Go back and edit"):self.assertIn(line,text)
  self.assertEqual([], [r for r in o["requests"] if r["method"]=="POST"])
 def test_warning_absent_on_equal_or_lower_and_missing_fare(self):
  for fare,amount,line in ((112.56,"112.56","Trip fare charged: SGD 112.56"),(None,"1","Trip fare charged: not on record")):
   acts=[{"className":"queue-open","op":"click"},{"id":"decision-change","op":"check"},{"id":"decision-action","op":"set","value":"refund"},{"id":"decision-amount","op":"set","value":amount},{"id":"decision-form","op":"submit"}];o=drive(opened(fare=fare),acts);self.assertIn(line,o["ids"]["decision-confirm"]["text"]);self.assertEqual([],o["classes"]["confirm-warning"])
 def test_non_numbers_show_exact_line_and_send_nothing(self):
  for value in ("abc",""):
   acts=[{"className":"queue-open","op":"click"},{"id":"decision-change","op":"check"},{"id":"decision-action","op":"set","value":"refund"},{"id":"decision-amount","op":"set","value":value},{"id":"decision-form","op":"submit"},{"id":"decision-confirm-send","op":"click"}]
   o=drive(opened(),acts);self.assertIn("Amount: refund, amount not a number",o["ids"]["decision-confirm"]["text"]);self.assertEqual([], [r for r in o["requests"] if r["method"]=="POST"])
 def test_approve_and_reject_confirm_lines(self):
  for ident,lines in (("decision-approve",("Decision: Approve","Amount: refund of SGD 55.16")),("decision-reject",("Decision: Reject","Amount: no action"))):
   o=drive(opened(),[{"className":"queue-open","op":"click"},{"id":ident,"op":"check"},{"id":"decision-form","op":"submit"}]);text=o["ids"]["decision-confirm"]["text"];self.assertIn(lines[0],text);self.assertIn(lines[1],text)
 def test_back_keeps_typed_values(self):
  acts=[{"className":"queue-open","op":"click"},{"id":"decision-change","op":"check"},{"id":"decision-reviewer","op":"set","value":"Ana"},{"id":"decision-reason","op":"set","value":"Why"},{"id":"decision-action","op":"set","value":"refund"},{"id":"decision-amount","op":"set","value":"45"},{"id":"decision-form","op":"submit"},{"id":"decision-confirm-back","op":"click"}]
  d=drive(opened(),acts)["ids"];self.assertFalse(d["decision-form"]["hidden"]);self.assertTrue(d["decision-confirm"]["hidden"]);self.assertEqual(("Ana","Why","refund","45"),(d["decision-reviewer"]["value"],d["decision-reason"]["value"],d["decision-action"]["value"],d["decision-amount"]["value"]))
 def test_only_confirm_posts_exact_change_body_once_on_double_click(self):
  acts=[{"className":"queue-open","op":"click"},{"id":"decision-change","op":"check"},{"id":"decision-reviewer","op":"set","value":" Ana "},{"id":"decision-reason","op":"set","value":" why "},{"id":"decision-action","op":"set","value":"refund"},{"id":"decision-amount","op":"set","value":"45.129"},{"id":"decision-form","op":"submit"},{"id":"decision-confirm-send","op":"click"},{"id":"decision-confirm-send","op":"click"}]
  resp=ok({"party_view":{"message":"Decision: refund of SGD 45.13. A member of our team reviewed your case."}});o=drive(opened(decision_response=resp),acts);posts=[r for r in o["requests"] if r["method"]=="POST"]
  self.assertEqual(1,len(posts));self.assertEqual("/api/review/RUN%20%2F%207/decision",posts[0]["url"]);self.assertEqual({"decision":"change","reviewer":" Ana ","reason":" why ","action":"refund","amount_sgd":45.129},posts[0]["body"]);self.assertIn("Decision recorded. The party now sees:",o["classes"]["decision-result"][0]["text"]);self.assertIn("Decision: refund of SGD 45.13.",o["classes"]["decision-result"][0]["text"])
 def test_approve_and_reject_body_omit_action_and_amount(self):
  for ident,decision in (("decision-approve","approve"),("decision-reject","reject")):
   acts=[{"className":"queue-open","op":"click"},{"id":ident,"op":"check"},{"id":"decision-reviewer","op":"set","value":"A"},{"id":"decision-reason","op":"set","value":"R"},{"id":"decision-form","op":"submit"},{"id":"decision-confirm-send","op":"click"}];o=drive(opened(decision_response=ok({"party_view":{"message":"done"}})),acts);post=[r for r in o["requests"] if r["method"]=="POST"][0];self.assertEqual({"decision":decision,"reviewer":"A","reason":"R"},post["body"])
 def test_server_error_and_default_error_return_to_form(self):
  for response,text in ((bad(409,{"error":"this case already has a human decision"}),"this case already has a human decision"),(bad(500,{}),"The decision could not be recorded.")):
   acts=[{"className":"queue-open","op":"click"},{"id":"decision-reject","op":"check"},{"id":"decision-form","op":"submit"},{"id":"decision-confirm-send","op":"click"}];d=drive(opened(decision_response=response),acts)["ids"];self.assertEqual(text,d["decision-error"]["text"]);self.assertFalse(d["decision-form"]["hidden"]);self.assertTrue(d["decision-confirm"]["hidden"])
 def test_recorded_decision_view_and_non_withheld_hidden(self):
  rec={"decision":"change","reviewer":"Ana","reason":"Why","action":"refund","amount_sgd":45,"decided_at":"2026-10-03"};o=drive(opened(decision=rec),[{"className":"queue-open","op":"click"}]);self.assertEqual("Human decision recorded",o["classes"]["human-decision-record"][0]["children"][0]["text"]);self.assertIn("SGD 45.00",o["classes"]["human-decision-record"][0]["text"])

if __name__=="__main__":unittest.main()
