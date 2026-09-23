"""Session six fix round: acceptance target for the ten confirmed review findings.

Written BEFORE the fixes, so it is RED until the CodeBuddy build lane ships them. Each
test names the finding it pins (R1..R10, see docs/session-six-fix-brief.md). Every
finding was reproduced firsthand before it was written down here.

the operator ruled option A for R1 on 2026-09-23: the party-facing decision message is BUILT IN
CODE from structured ruling fields (action, amount, the plain titles of the policy rules
cited). The Judge's explanation stays in the case file for the operator console and is
never relayed to a party.
"""

from __future__ import annotations

import copy
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path

from app.llm.mock import MockLLMClient
from app.policy import load_policy
from tests.support import ScriptedLLM
from tests.test_party_surface import (
    FORBIDDEN_PARTY_WORDS,
    ORG_DIR,
    PARTY_VIEW_KEYS,
    POLICY,
    REPO,
    SYNTH_DIR,
    _asking_advocate,
    _blank_org,
    _filing,
    _record,
    _run,
    _Server,
)

RULE_ID = re.compile(r"\b[A-Z]{2,5}-\d{1,3}\b")

#: A Judge explanation written to leak everything it can. None of it may reach a party.
LEAKY_EXPLANATION = (
    "EXPLANATION-SENTINEL. The Judge's confidence is 0.91; both advocates agreed; the AI "
    "model checked ESC-4 and nothing was withheld or escalated."
)


def _leaky_judge(action="refund", amount=4.87, rules=("RD-1", "ESC-5", "ESC-6")):
    return {
        "action": action,
        "recommended_amount_sgd": amount,
        "confidence": 0.91,
        "explanation": LEAKY_EXPLANATION,
        "cited_rule_ids": list(rules),
        "cited_evidence_refs": [],
    }


def _scripted(judge=None, rider_questions=(), driver_questions=()):
    return ScriptedLLM(
        {
            "rider_advocate": _asking_advocate(list(rider_questions)),
            "driver_advocate": _asking_advocate(list(driver_questions)),
            "judge": judge if judge is not None else _leaky_judge(),
        }
    )


def _assert_party_clean(test, text, what):
    test.assertIsNone(FORBIDDEN_PARTY_WORDS.search(text), "%s leaks: %r" % (what, text))
    test.assertIsNone(RULE_ID.search(text), "%s carries a rule id: %r" % (what, text))
    test.assertNotIn("EXPLANATION-SENTINEL", text, "%s relays the Judge's explanation" % what)
    test.assertNotIn("0.91", text, "%s carries the confidence" % what)


# ------------------------------------------------------------------ R1 message


class R1DecisionMessageIsBuiltInCode(unittest.TestCase):
    """The decision a party reads is composed from structured fields, never relayed."""

    def test_policy_exposes_plain_rule_titles(self):
        policy = load_policy(POLICY)
        self.assertEqual("When a deviation is material", policy.rule_title("RD-1"))
        self.assertEqual("The wait must be real", policy.rule_title("NS-2"))
        for rule_id in policy.rule_ids():
            title = policy.rule_title(rule_id)
            self.assertTrue(title.strip(), rule_id)
            self.assertNotIn("[", title, "provenance tag must be stripped: %r" % title)
            self.assertNotIn(rule_id, title)

    def test_message_carries_action_amount_and_titles_but_not_the_explanation(self):
        from app.schemas import JudgeRuling, party_message_for_ruling

        policy = load_policy(POLICY)
        ruling = JudgeRuling.from_payload(_leaky_judge())
        message = party_message_for_ruling(ruling, policy)
        self.assertIn("refund", message)
        self.assertIn("4.87", message)
        self.assertIn("When a deviation is material", message)
        _assert_party_clean(self, message, "decision message")

    def test_message_without_a_policy_still_does_not_relay_the_explanation(self):
        from app.schemas import JudgeRuling, party_message_for_ruling

        message = party_message_for_ruling(JudgeRuling.from_payload(_leaky_judge()))
        self.assertIn("4.87", message)
        _assert_party_clean(self, message, "decision message (no policy)")

    def test_no_action_message_has_no_amount_and_is_clean(self):
        from app.schemas import JudgeRuling, party_message_for_ruling

        ruling = JudgeRuling.from_payload(_leaky_judge(action="no action", amount=0.0, rules=("NS-2",)))
        message = party_message_for_ruling(ruling, load_policy(POLICY))
        self.assertIn("no action", message)
        self.assertNotIn("SGD", message)
        self.assertIn("The wait must be real", message)
        _assert_party_clean(self, message, "no-action message")

    def test_pipeline_ruled_message_is_clean_with_a_leaky_judge(self):
        case = _run(_record(ORG_DIR, "RD-0101.json"), llm=_scripted())
        resolution = case["resolution"]
        self.assertEqual("ruled", resolution["outcome"])
        _assert_party_clean(self, resolution["party_message"], "pipeline party_message")
        # The operator console still gets the Judge's full reasoning.
        self.assertIn("EXPLANATION-SENTINEL", resolution["ruling"]["explanation"])

    def test_every_mock_ruled_case_in_both_packs_is_clean(self):
        checked = 0
        for pack in (ORG_DIR, SYNTH_DIR):
            for path in sorted((pack / "disputes").glob("*.json")):
                case = _run(json.loads(path.read_text(encoding="utf-8")))
                if case["resolution"]["outcome"] != "ruled":
                    continue
                checked += 1
                with self.subTest(pack=pack.name, case=path.name):
                    _assert_party_clean(self, case["resolution"]["party_message"], path.name)
        self.assertGreater(checked, 10, "expected most corpus cases to rule")

    def test_server_decided_view_is_clean_with_a_leaky_judge(self):
        server = _Server()
        try:
            server.httpd.ryde_state.llm = _scripted()
            _, trips = server.json("GET", "/api/trips?category=route_deviation")
            status, raw = server.request("POST", "/api/disputes", _filing(trips["trips"][0]["trip_id"], claim=4.87))
            self.assertEqual(200, status, raw)
            view = json.loads(raw)
            self.assertEqual("decided", view["status"], view)
            _assert_party_clean(self, raw.decode("utf-8"), "decided party view")
        finally:
            server.close()

    def test_party_view_fails_closed_on_a_leaky_planted_message(self):
        # Updated in fix round two (S1): a needs-info file's message is never
        # relayed at any more — the view shows the canonical constant and keeps
        # safe questions, so a leaky message there is no longer grounds to fail
        # the whole view closed. The decided message still fails closed, and a
        # needs-info run's QUESTIONS keep their check (leaky question -> closed).
        from app.server import party_view
        from app.schemas import NEEDS_INFO_MESSAGE, UNDER_REVIEW_MESSAGE

        case = {
            "run_id": "r", "dispute_id": "d",
            "resolution": {"outcome": "ruled",
                           "party_message": "Decision: refund. The Judge was confident."},
        }
        view = party_view(case)
        self.assertEqual("under_review", view["status"])
        self.assertEqual(UNDER_REVIEW_MESSAGE, view["message"])
        self.assertEqual([], view["questions"])

        case = {
            "run_id": "r", "dispute_id": "d",
            "resolution": {"outcome": "needs_info",
                           "party_message": "Decision: refund. The Judge was confident.",
                           "questions_for_party": ["Where were you?"]},
        }
        view = party_view(case)
        self.assertEqual("needs_info", view["status"])
        self.assertEqual(NEEDS_INFO_MESSAGE, view["message"])
        self.assertEqual(["Where were you?"], view["questions"])

        case = {
            "run_id": "r", "dispute_id": "d",
            "resolution": {"outcome": "needs_info",
                           "party_message": "We will look into it.",
                           "questions_for_party": ["Why did the Judge escalate?"]},
        }
        view = party_view(case)
        self.assertEqual("under_review", view["status"])
        self.assertEqual(UNDER_REVIEW_MESSAGE, view["message"])
        self.assertEqual([], view["questions"])


# ---------------------------------------------------------------- R2 questions


class R2QuestionsPassAGateInCode(unittest.TestCase):
    """A question that would leak is replaced in code, before it is stored or sent."""

    LEAKY = [
        "What is your confidence the Judge should escalate this?",
        "Our AI model needs to know: which route did the app show?",
        "Under RD-1, how long was the detour?",
    ]

    def test_leaky_questions_never_reach_the_case_file(self):
        record = _blank_org(_record(ORG_DIR, "RD-0101.json"), "expected_route")
        case = _run(record, llm=_scripted(rider_questions=self.LEAKY))
        resolution = case["resolution"]
        self.assertEqual("needs_info", resolution["outcome"])
        questions = resolution["questions_for_party"]
        self.assertTrue(1 <= len(questions) <= 3, questions)
        self.assertEqual(len(questions), len(set(questions)), "replacements must not duplicate")
        for question in questions:
            _assert_party_clean(self, question, "question")
            self.assertTrue(question.strip())

    def test_a_replacement_names_the_blank_form_field_in_plain_words(self):
        record = _blank_org(_record(ORG_DIR, "RD-0101.json"), "expected_route")
        case = _run(record, llm=_scripted(rider_questions=self.LEAKY[:1]))
        questions = case["resolution"]["questions_for_party"]
        self.assertTrue(
            any("What route did the app show you" in q for q in questions),
            "the template question must quote the blank field's form label: %r" % questions,
        )

    def test_clean_questions_pass_through_unchanged(self):
        clean = "Which pickup point did you walk to?"
        case = _run(_record(ORG_DIR, "NS-0201.json"), llm=_scripted(rider_questions=[clean]))
        self.assertEqual([clean], case["resolution"]["questions_for_party"])

    def test_the_intake_labels_have_one_owner(self):
        """The Python labels that templates quote must match what the party page shows."""
        from app.schemas import INTAKE_QUESTIONS

        source = (REPO / "ui" / "party" / "party.js").read_text(encoding="utf-8")
        js = dict(re.findall(r'key:\s*"([a-z_]+)",\s*label:\s*"([^"]+)"', source))
        self.assertTrue(js, "could not read party.js questionnaire labels")
        for category, items in INTAKE_QUESTIONS.items():
            for key, label in items:
                with self.subTest(category=category, key=key):
                    self.assertEqual(js.get(key), label)
        from app.server import QUESTIONNAIRES

        self.assertEqual(
            {c: tuple(k for k, _ in items) for c, items in INTAKE_QUESTIONS.items()},
            dict(QUESTIONNAIRES),
        )


# ------------------------------------------------ R3 + R5 category/trip mismatch


class R3CategoryMustMatchTheTrip(unittest.TestCase):
    """A locked category filed against another category's trip is refused, not crashed."""

    def setUp(self):
        self.server = _Server()

    def tearDown(self):
        self.server.close()

    def _trip(self, category):
        _, body = self.server.json("GET", "/api/trips?category=%s" % category)
        return body["trips"][0]["trip_id"]

    def _dirs(self):
        return sorted(p.name for p in self.server.out.iterdir() if p.is_dir())

    def test_no_show_filing_on_a_route_trip_is_a_400_and_files_nothing(self):
        before = self._dirs()
        filing = _filing(self._trip("route_deviation"), category="no_show_charge", answers={})
        status, body = self.server.json("POST", "/api/disputes", filing)
        self.assertEqual(400, status, body)
        self.assertIn("trip", body["error"].lower())
        self.assertEqual(before, self._dirs(), "a refused filing must not leave a run directory")

    def test_route_filing_on_a_no_show_trip_is_a_400(self):
        filing = _filing(self._trip("no_show_charge"), category="route_deviation", answers={})
        status, body = self.server.json("POST", "/api/disputes", filing)
        self.assertEqual(400, status, body)

    def test_out_of_scope_categories_still_accept_any_trip(self):
        for trip_category in ("route_deviation", "no_show_charge"):
            with self.subTest(trip=trip_category):
                filing = _filing(self._trip(trip_category), category="other", claim=None, answers={})
                status, view = self.server.json("POST", "/api/disputes", filing)
                self.assertEqual((200, "passed_to_support"), (status, view["status"]), view)


# ----------------------------------------------------------- R4 + R7 answering


class _SlowMock(MockLLMClient):
    def complete(self, request):
        time.sleep(0.4)
        return super().complete(request)


class R4AnswerOnceUnderConcurrency(unittest.TestCase):
    def test_two_concurrent_answers_one_wins_one_409(self):
        server = _Server()
        try:
            server.httpd.ryde_state.llm = _SlowMock()
            answers = _filing("x")["answers"]
            answers["expected_route"] = ""
            _, trips = server.json("GET", "/api/trips?category=route_deviation")
            _, first = server.json("POST", "/api/disputes", _filing(trips["trips"][0]["trip_id"], answers=answers))
            self.assertEqual("needs_info", first["status"], first)
            reply = {"answers": [{"question": q, "answer": "The expressway."} for q in first["questions"]]}
            results = []

            def answer():
                results.append(server.json("POST", "/api/disputes/%s/answers" % first["run_id"], reply)[0])

            threads = [threading.Thread(target=answer) for _ in range(4)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(30)
            self.assertEqual([200, 409, 409, 409], sorted(results))
            run_dirs = [p for p in server.out.iterdir() if p.is_dir()]
            self.assertEqual(2, len(run_dirs), "exactly the asking run and one round-two run")
        finally:
            server.close()


class R7FailedAnswerLeavesNoLitter(unittest.TestCase):
    def test_a_crashing_round_two_leaves_no_run_dir_and_stays_answerable(self):
        server = _Server()
        try:
            run_dir = server.out / "planted-run-0001"
            run_dir.mkdir()
            (run_dir / "case_file.json").write_text(json.dumps({
                "run_id": "planted-run-0001", "dispute_id": "PF-PLANT",
                "resolution": {"outcome": "needs_info", "party_message": "x",
                               "questions_for_party": ["Where were you?"]},
            }), encoding="utf-8")
            (run_dir / "dispute.json").write_text(json.dumps({"dispute_ticket": {"filed_by": 7}}), encoding="utf-8")
            reply = {"answers": [{"question": "Where were you?", "answer": "At the lobby."}]}
            for attempt in (1, 2):
                with self.subTest(attempt=attempt):
                    status, body = server.json("POST", "/api/disputes/planted-run-0001/answers", reply)
                    self.assertEqual(500, status, body)
                    self.assertEqual(["planted-run-0001"], sorted(p.name for p in server.out.iterdir()),
                                     "a crashed run must not leave a half-written directory")
        finally:
            server.close()


# -------------------------------------------------------- R6 console array guard


class R6ConsoleFollowUpAnswersShapeGuard(unittest.TestCase):
    """Arrays, empty objects and non-string fields are skipped, not rendered as rows."""

    HARNESS = r'''
const fs = require("fs"); const vm = require("vm");
class N { constructor(t){ this.tagName=t; this.children=[]; this.className=""; this.dataset={};
  this.hidden=false; this.files=[]; this.listeners={}; let own="";
  Object.defineProperty(this,"textContent",{get:()=>own+this.children.map(c=>c.textContent).join(""),
    set:(v)=>{own=v==null?"":String(v); this.children=[];}});
  this.classList={add:(...n)=>{this.className+=" "+n.join(" ");}}; }
  appendChild(c){this.children.push(c); return c;} removeChild(c){this.children=this.children.filter(x=>x!==c); return c;}
  get firstChild(){return this.children[0]||null;}
  addEventListener(n,h){(this.listeners[n]=this.listeners[n]||[]).push(h);}
  dispatch(n){(this.listeners[n]||[]).forEach(h=>h({target:this}));} }
(async()=>{ const roots={}; const doc={getElementById:(id)=>roots[id]||(roots[id]=new N("div")),createElement:(t)=>new N(t)};
  vm.runInNewContext(fs.readFileSync(process.env.UI,"utf8"),{document:doc});
  const cf=JSON.parse(fs.readFileSync(process.env.CF,"utf8"));
  roots["case-picker"].files=[{name:"case_file.json",text:()=>Promise.resolve(JSON.stringify(cf))}];
  roots["case-picker"].dispatch("change"); await new Promise(r=>setTimeout(r,0));
  process.stdout.write(JSON.stringify({g:roots["grievance-content"].textContent}));
})().catch(e=>{process.stderr.write(String(e.stack||e)); process.exit(1);});
'''

    def _grievance(self, follow_ups):
        node = shutil.which("node")
        if not node:
            self.fail("Node is required for the UI behavioural pin")
        case = _run(_record(SYNTH_DIR, "RD-0101.json"))
        case["intake"]["follow_up_answers"] = follow_ups
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "case_file.json"
            path.write_text(json.dumps(case), encoding="utf-8")
            env = dict(os.environ, UI=str(REPO / "ui" / "app.js"), CF=str(path))
            result = subprocess.run([node, "-e", self.HARNESS], env=env, capture_output=True, text=True, timeout=20)
        self.assertEqual(0, result.returncode, result.stderr)
        return json.loads(result.stdout)["g"]

    def test_the_whole_family_of_wrong_shapes_is_skipped(self):
        good = {"question": "Q-SENTINEL?", "answer": "A-SENTINEL"}
        baseline = self._grievance([good])
        self.assertIn("Q-SENTINEL?", baseline)
        for bad in ([["q", "a"]], [[]], [{}], [{"question": 5, "answer": "a"}],
                    [{"question": "q"}], [None], ["x"], [7]):
            with self.subTest(bad=bad):
                self.assertEqual(baseline, self._grievance(bad + [good]))


# ------------------------------------------------------------ R8 trip charges


class R8TripChargeIsLabelled(unittest.TestCase):
    def setUp(self):
        self.server = _Server()

    def tearDown(self):
        self.server.close()

    def test_every_trip_says_what_its_amount_is(self):
        allowed = {"trip_id", "label", "kind", "kind_label", "pickup", "dropoff", "date",
                   "fare_sgd", "charge_label"}
        for category, expected in (("route_deviation", {"fare"}),
                                   ("no_show_charge", {"cancellation fee", "waiting fee"})):
            _, body = self.server.json("GET", "/api/trips?category=%s" % category)
            for trip in body["trips"]:
                with self.subTest(trip=trip["trip_id"]):
                    self.assertTrue(set(trip) <= allowed, set(trip) - allowed)
                    if trip["fare_sgd"] is None:
                        self.assertIsNone(trip["charge_label"])
                    else:
                        self.assertIn(trip["charge_label"], expected)

    def test_trip_kind_has_a_plain_label(self):
        _, body = self.server.json("GET", "/api/trips?category=other")
        for trip in body["trips"]:
            with self.subTest(trip=trip["trip_id"]):
                self.assertTrue(trip["kind_label"].strip())
                self.assertNotIn("_", trip["kind_label"])

    def test_an_unknown_charge_is_null_not_zero(self):
        from app.server import _trip_summary

        record = _record(ORG_DIR, "NS-0201.json")
        trip = record["trip_data"]
        trip.pop("fare", None)
        trip["cancellation_fee"] = None
        trip.pop("waiting_fee", None)
        summary = _trip_summary(record)
        self.assertIsNone(summary["fare_sgd"])
        self.assertIsNone(summary["charge_label"])


# --------------------------------------------------- R10 mock question wording


class R10MockQuestionSpeaksPlainly(unittest.TestCase):
    def test_mock_question_quotes_the_form_label_not_the_key(self):
        case = _run(_blank_org(_record(ORG_DIR, "RD-0101.json"), "expected_route"))
        questions = case["resolution"]["questions_for_party"]
        self.assertTrue(questions)
        for question in questions:
            self.assertNotIn("expected_route", question)
            self.assertNotRegex(question, r"\b[a-z]+_[a-z_]+\b", "no snake_case field names")
        self.assertTrue(any("What route did the app show you" in q for q in questions), questions)


if __name__ == "__main__":
    unittest.main()
