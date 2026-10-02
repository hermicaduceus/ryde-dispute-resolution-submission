"""Session twelve acceptance target: the step-three form gets a UX rebuild.

RED until the CodeBuddy build lane ships docs/session-twelve-brief.md.

Operator rulings (the operator, 2026-09-27, planning discussed in-session):
  1. WHAT_WENT_WRONG IS GONE. It duplicated "What happened?" (required) and the
     category card the rider already clicked on step 1. The one owner of the
     question table is INTAKE_QUESTIONS in app/schemas.py; removing the key there
     propagates to the server questionnaire and the form-slot bank automatically.
     The pack records' filled `what_went_wrong` answers stay as harmless
     pass-through — the corpus is NOT regenerated, so the 35 corpus runs must not
     drift (pinned below).
  2. YES/NO QUESTIONS GET BUTTONS. was_route_agreed, asked_driver_to_stop,
     safety_concern, did_driver_contact_you render as Yes/No buttons, not textareas.
     The submitted answer string is exactly "Yes" or "No".
  3. ELABORATE-ON-CHOICE. Once either button is chosen, a "Tell us more" textarea
     appears under that question (both categories, every yes/no question; safety
     "yes" is not special-cased in the code). An elaboration is submitted as
     "Yes - <text>" / "No - <text>"; blank elaboration submits the bare choice.
  4. REQUIRED FIRST. "What happened?" is the first field on the step-3 page,
     above the category questions; amount stays last.

What these tests pin, and why this shape:
  * The Python contracts (INTAKE_QUESTIONS, server validation, form-slot bank)
    via direct import — these are the load-bearing halves.
  * The party.js side via scoped source pins (the handler/structure body, not
    whole-file greps — the session-nine false-green lesson).
  * Corpus no-drift across all 35 runs.
  * The old-contract tests that WILL go red and must be re-baselined, not deleted.
"""
from __future__ import annotations

import json
import re
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PARTY_JS = REPO / "ui" / "party" / "party.js"

YES_NO_KEYS = {"was_route_agreed", "asked_driver_to_stop",
               "safety_concern", "did_driver_contact_you"}


def _js() -> str:
    source = PARTY_JS.read_text(encoding="utf-8")
    assert source, "could not read ui/party/party.js"
    return source


def _strip_comments(source: str) -> str:
    """Drop // and /* */ comments: a comment must never satisfy a pin."""
    source = re.sub(r"/\*[\s\S]*?\*/", "", source)
    return re.sub(r"//[^\n]*", "", source)


def _function_body(source: str, name: str) -> str:
    """The body of `function <name>(...) { ... }`, with comments stripped.

    Scoping a pin to one function body is the point: a token that appears somewhere
    else in the file (or in a comment) must not be able to satisfy it.
    """
    code = _strip_comments(source)
    match = re.search(r"function\s+%s\s*\(" % re.escape(name), code)
    if match is None:
        raise AssertionError("ui/party/party.js has no function %s" % name)
    start = code.index("{", match.end())
    depth = 0
    for index in range(start, len(code)):
        if code[index] == "{":
            depth += 1
        elif code[index] == "}":
            depth -= 1
            if depth == 0:
                return code[start:index + 1]
    raise AssertionError("unbalanced braces in function %s" % name)


def _kinds(js: str) -> list:
    """(key, kind) pairs from the page questionnaire, duplicates kept."""
    return [(key, kind) for key, kind in re.findall(
        r'key:\s*"([a-z_]+)"\s*,\s*label:\s*"[^"]+"\s*,\s*kind:\s*"(yes_no|open)"', js)]


# ------------------------------------------------------------- Python contract


class IntakeTableDropsWhatWentWrong(unittest.TestCase):
    """The one owner of the question table no longer carries the duplicate."""

    def test_intake_questions_have_no_what_went_wrong(self):
        from app.schemas import INTAKE_QUESTIONS

        for category, items in INTAKE_QUESTIONS.items():
            keys = [key for key, _ in items]
            self.assertNotIn("what_went_wrong", keys,
                             f"{category} still asks what_went_wrong")

    def test_form_slot_bank_no_longer_offers_what_went_wrong(self):
        from app.schemas import follow_up_slot_ids

        for category in ("route_deviation", "no_show_charge"):
            slots = follow_up_slot_ids(category)
            self.assertNotIn("form:what_went_wrong", slots,
                             f"{category} form slots still offer what_went_wrong")
            # the other form slots survive
            self.assertIn("form:safety_concern", slots)


class ServerQuestionnaireFollows(unittest.TestCase):
    """The server accepts what the form sends, and refuses what the form no longer sends."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

        from app.server import make_server
        from app.llm.mock import MockLLMClient

        out = Path(self.tmp.name)
        self.httpd = make_server(port=0, out_dir=out, llm=MockLLMClient())
        self.base = "http://127.0.0.1:%d" % self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.tmp.cleanup()

    def _trips(self, category):
        with urllib.request.urlopen(
            self.base + "/api/trips?category=" + category, timeout=30
        ) as resp:
            return json.load(resp)["trips"][0]["trip_id"]

    def _post(self, answers):
        trip = self._trips("route_deviation")
        data = json.dumps({
            "category": "route_deviation", "filed_by": "rider",
            "trip_id": trip, "description": "Long way round.",
            "claim_amount_sgd": 5.81, "answers": answers,
        }).encode()
        req = urllib.request.Request(self.base + "/api/disputes", data=data,
                                     method="POST")
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.status, json.load(resp)
        except urllib.error.HTTPError as err:
            return err.code, json.loads(err.read())

    def test_filing_with_what_went_wrong_is_refused(self):
        status, body = self._post({"what_went_wrong": "He went a long way round.",
                                   "safety_concern": "No"})
        self.assertEqual(400, status, body)

    def test_filing_with_yes_no_button_answers_is_accepted(self):
        status, body = self._post({
            "expected_route": "The app showed the expressway.",
            "was_route_agreed": "Yes",
            "asked_driver_to_stop": "No - stopped at a shop for two minutes",
            "safety_concern": "No",
        })
        self.assertEqual(200, status, body)
        self.assertIn("status", body)


class CorpusNoDrift(unittest.TestCase):
    """Removing a question from the form must not change any corpus outcome.

    Runs all 35 labelled records (17 ryde-synth + 18 organiser-style) through the
    real pipeline on the mock client and pins outcome/action/amount to the frozen
    baseline. The mock is a deterministic stand-in, not a solver, so this pins the
    run it actually produces today — it is a drift guard, not a label check (the
    label checks live in tests/test_corpus.py). The record pack keeps its filled
    what_went_wrong answers: intake is pass-through.
    """

    #: pack/file -> (outcome, action, amount_sgd). Frozen 2026-09-27, head 6562715+.
    #: Re-pinned 2026-10-01 (W22): RD-0106 is withheld by the RD-5 gate (the mock refunds
    #: the claimed 0.66; the records prove 3.40). No other case moved.
    #: Re-pinned 2026-10-02 (W28): RD-0103, RD-0105 and RD-0107 are withheld by the RD-4
    #: gate on both packs (each mock refund is more than the records prove). No other case
    #: moved.
    BASELINE = {
        "ryde-synth-v1/NS-0201.json": ("ruled", "refund", 6.61),
        "ryde-synth-v1/NS-0202.json": ("ruled", "refund", 6.61),
        "ryde-synth-v1/NS-0203.json": ("ruled", "refund", 6.61),
        "ryde-synth-v1/NS-0204.json": ("ruled", "refund", 6.61),
        "ryde-synth-v1/NS-0205.json": ("ruled", "refund", 6.61),
        "ryde-synth-v1/NS-0206.json": ("ruled", "refund", 6.61),
        "ryde-synth-v1/NS-0207.json": ("ruled", "refund", 5.0),
        "ryde-synth-v1/OS-0301.json": ("human_review", None, None),
        "ryde-synth-v1/RD-0101.json": ("ruled", "refund", 5.81),
        "ryde-synth-v1/RD-0102.json": ("ruled", "refund", 5.86),
        "ryde-synth-v1/RD-0103.json": ("withheld", None, None),
        "ryde-synth-v1/RD-0104.json": ("ruled", "refund", 7.7),
        "ryde-synth-v1/RD-0105.json": ("withheld", None, None),
        "ryde-synth-v1/RD-0106.json": ("withheld", None, None),
        "ryde-synth-v1/RD-0107.json": ("withheld", None, None),
        "ryde-synth-v1/RD-0108.json": ("withheld", None, None),
        "ryde-synth-v1/RD-0109.json": ("withheld", None, None),
        "organiser-style-v1/DISP-002.json": ("ruled", "no action", 0.0),
        "organiser-style-v1/NS-0201.json": ("ruled", "refund", 6.61),
        "organiser-style-v1/NS-0202.json": ("ruled", "refund", 6.61),
        "organiser-style-v1/NS-0203.json": ("ruled", "refund", 6.61),
        "organiser-style-v1/NS-0204.json": ("ruled", "refund", 6.61),
        "organiser-style-v1/NS-0205.json": ("ruled", "refund", 6.61),
        "organiser-style-v1/NS-0206.json": ("ruled", "refund", 6.61),
        "organiser-style-v1/NS-0207.json": ("ruled", "refund", 5.0),
        "organiser-style-v1/OS-0301.json": ("human_review", None, None),
        "organiser-style-v1/RD-0101.json": ("ruled", "refund", 5.81),
        "organiser-style-v1/RD-0102.json": ("ruled", "refund", 5.86),
        "organiser-style-v1/RD-0103.json": ("withheld", None, None),
        "organiser-style-v1/RD-0104.json": ("ruled", "refund", 7.7),
        "organiser-style-v1/RD-0105.json": ("withheld", None, None),
        "organiser-style-v1/RD-0106.json": ("withheld", None, None),
        "organiser-style-v1/RD-0107.json": ("withheld", None, None),
        "organiser-style-v1/RD-0108.json": ("withheld", None, None),
        "organiser-style-v1/RD-0109.json": ("withheld", None, None),
    }

    def test_all_35_runs_keep_outcome_action_and_amount(self):
        from app.dispute import load_dispute
        from app.events import EventLog
        from app.llm.mock import MockLLMClient
        from app.pipeline import run_dispute
        from app.policy import load_policy

        policy = load_policy(REPO / "docs" / "policy.md")
        ran = 0
        for pack in ("ryde-synth-v1", "organiser-style-v1"):
            pack_dir = REPO / "data" / "packs" / pack
            for record_path in sorted((pack_dir / "disputes").glob("*.json")):
                key = f"{pack}/{record_path.name}"
                with tempfile.TemporaryDirectory() as run_dir:
                    resolution = run_dispute(
                        dispute=load_dispute(record_path),
                        llm=MockLLMClient(),
                        policy=policy,
                        events=EventLog(Path(run_dir), "no-drift"),
                        confidence_threshold=0.65,
                        autonomous_cap_sgd=50.0,
                    ).to_dict()["resolution"]
                ruling = resolution.get("ruling") or {}
                got = (resolution["outcome"], ruling.get("action"),
                       ruling.get("recommended_amount_sgd"))
                with self.subTest(case=key):
                    self.assertIn(key, self.BASELINE, "record not in the frozen baseline")
                    self.assertEqual(self.BASELINE[key], got)
                ran += 1
        self.assertEqual(35, ran, "the corpus must stay 35 labelled records")
        self.assertEqual(35, len(self.BASELINE))


# ------------------------------------------------------------- party.js side


class YesNoButtonsInSource(unittest.TestCase):
    """The four yes/no questions render as buttons; open questions stay textareas.

    The identifiers pinned here are the contract written in
    docs/session-twelve-brief.md: buildQuestions dispatches on `kind`, a
    buildChoiceQuestion builder emits two choice buttons plus one elaborate box,
    and the submitted value joins choice and elaboration with " - ".
    """

    def test_questionnaire_tags_every_question_with_a_kind(self):
        js = _js()
        kinds = _kinds(js)
        self.assertTrue(kinds, "no kind-tagged questionnaire entries found")
        by_key = {}
        for key, kind in kinds:
            if key in by_key:
                self.assertEqual(by_key[key], kind,
                                 f"{key} is tagged inconsistently across categories")
            by_key[key] = kind
        for key in YES_NO_KEYS:
            self.assertEqual("yes_no", by_key.get(key),
                             f'{key} must be tagged kind: "yes_no"')
        for key in ("expected_route", "where_were_you"):
            self.assertEqual("open", by_key.get(key),
                             f'{key} must be tagged kind: "open"')

    def test_the_page_kind_tags_match_the_python_owner(self):
        """One owner: app.schemas.YES_NO_INTAKE_KEYS. The page must agree key for key."""
        from app.schemas import INTAKE_QUESTIONS, YES_NO_INTAKE_KEYS

        expected = {}
        for category, items in INTAKE_QUESTIONS.items():
            for key, _label in items:
                expected[key] = "yes_no" if key in YES_NO_INTAKE_KEYS else "open"
        self.assertEqual(expected, dict(_kinds(_js())),
                         "party.js kind tags drifted from app/schemas.py")

    def test_build_questions_dispatches_on_kind(self):
        """The dispatch has to be inside buildQuestions, wired to the right builders."""
        body = _function_body(_js(), "buildQuestions")
        self.assertRegex(body, r'kind\s*===\s*"yes_no"',
                         "buildQuestions must test for the yes/no kind")
        self.assertRegex(body, r'kind\s*===\s*"open"',
                         "buildQuestions must test for the open kind")
        yes_no_branch = body.split('"open"')[0]
        self.assertIn("buildChoiceQuestion(question)", yes_no_branch,
                      "the yes/no branch must build the question it was given")
        self.assertIn("textarea", body.split('"open"')[1],
                      "the open branch must still build a textarea")

    def test_choice_builder_builds_the_two_buttons_and_the_elaborate_box(self):
        body = _function_body(_js(), "buildChoiceQuestion")
        self.assertRegex(body, r'\[\s*"Yes"\s*,\s*"No"\s*\]',
                         "the builder must build exactly a Yes and a No control")
        self.assertRegex(body, r'element\(\s*"button"',
                         "choice controls must be real buttons, not styled textareas")
        self.assertRegex(body, r'data-choice',
                         "each choice button must carry data-choice")
        self.assertRegex(body, r'data-elaborate-for',
                         "the elaborate box must be tied to its question key")
        self.assertRegex(body, r'show\(\s*elaborate\s*\)',
                         "a choice must reveal the elaborate box")
        self.assertRegex(body, r'setAttribute\(\s*"aria-pressed"\s*,\s*"true"\s*\)',
                         'pressing a choice must set aria-pressed="true"')
        self.assertRegex(body, r'setAttribute\(\s*"aria-pressed"\s*,\s*"false"\s*\)',
                         'the released sibling must go back to aria-pressed="false"')

    def test_submitted_answer_joins_the_choice_with_the_elaboration(self):
        """Scoped to the submit path, not the whole file."""
        js = _strip_comments(_js())
        submit = js.split('getElementById("details-form")')[1]
        submit = submit[:submit.index("function renderOutcome")]
        self.assertIn("QUESTIONNAIRES[state.category]", submit,
                      "the submit path must walk the questionnaire")
        self.assertRegex(submit, r'answers\[question\.key\]\s*=\s*choice',
                         "the yes/no answer must come from the chosen button")
        self.assertRegex(submit, r'choice\s*\+\s*" - "\s*\+\s*elaboration',
                         'a filled box must submit as choice + " - " + elaboration')
        self.assertRegex(submit, r'=\s*choice[\s\S]{0,160}:\s*""',
                         "an unanswered choice question must submit a blank answer")
        self.assertRegex(submit, r'answers\[question\.key\]\s*=\s*input\s*\?[\s\S]{0,40}'
                                 r'input\.value',
                         "an open question must submit what the party typed")

    def test_required_field_is_first_on_the_page(self):
        html = (REPO / "ui" / "party" / "index.html").read_text(encoding="utf-8")
        desc_pos = html.find('id="description"')
        qlist_pos = html.find('id="question-list"')
        self.assertNotEqual(-1, desc_pos, "description field missing")
        self.assertNotEqual(-1, qlist_pos, "question-list missing")
        self.assertLess(desc_pos, qlist_pos,
                        "the required description must render before the category questions")
        # nothing may re-insert the questions above it: the description block must be
        # the first field inside the form
        form_start = html.find('id="details-form"')
        self.assertNotEqual(-1, form_start, "details form missing")
        first_field = html.find('class="field"', form_start)
        self.assertLess(first_field, qlist_pos,
                        "the first field block must be the required description")


class ChoiceGroupAccessibility(unittest.TestCase):
    """A yes/no field must be a labelled group of pressed buttons, not loose buttons.

    The choices container is a `div`, so a `<label for>` cannot point at it: the
    question text has to reach assistive tech through role="group" plus
    aria-labelledby, and the chosen answer has to be a pressed state, not only a class.
    Pinned inside the builder body, with comments stripped, so the explanatory comment
    in the source cannot satisfy any of it.
    """

    def test_choices_container_is_a_labelled_group(self):
        body = _function_body(_js(), "buildChoiceQuestion")
        self.assertRegex(body, r'(?:\.role\s*=\s*"group"|'
                                r'setAttribute\(\s*"role"\s*,\s*"group"\s*\))',
                         'the choice container must be a role="group"')
        self.assertRegex(body, r'setAttribute\(\s*"aria-labelledby"\s*,\s*"label-"\s*\+',
                         "the group must be labelled by the question label id")
        self.assertRegex(body, r'label\.id\s*=\s*"label-"\s*\+',
                         "the question label needs the id aria-labelledby points at")

    def test_choice_buttons_report_a_pressed_state(self):
        body = _function_body(_js(), "buildChoiceQuestion")
        self.assertRegex(body, r'setAttribute\(\s*"aria-pressed"\s*,\s*"false"\s*\)',
                         'a fresh choice button must start aria-pressed="false"')
        self.assertRegex(body, r'setAttribute\(\s*"aria-pressed"\s*,\s*"true"\s*\)',
                         'the chosen button must become aria-pressed="true"')
        # Position matters: the button must START unpressed (before the listener is
        # attached) and the click handler must then set true for the chosen button and
        # false for the released sibling. Collapsing the two "false" writes into one
        # must not be able to satisfy this.
        initial, _, handler = body.partition("addEventListener")
        self.assertIn('aria-pressed", "false"', initial,
                      'the initial aria-pressed="false" must be set at build time')
        self.assertIn('aria-pressed", "true"', handler,
                      'the click handler must press the chosen button')
        self.assertIn('aria-pressed", "false"', handler,
                      'the click handler must release the sibling button')

    def test_the_open_branch_keeps_its_textarea_labelled_by_id(self):
        """The open path is unchanged: its textarea id is what the label points at."""
        body = _function_body(_js(), "buildQuestions")
        self.assertRegex(body, r'input\.id\s*=\s*"answer-"\s*\+\s*question\.key',
                         "an open question still gets an id of answer-<key>")


class NoWhatWentWrongOnThePage(unittest.TestCase):
    def test_party_js_never_renders_the_removed_question(self):
        js = _js()
        self.assertNotIn("what_went_wrong", js,
                         "party.js still references the removed question key")

    def test_intake_labels_owner_test_will_be_rebaselined_not_deleted(self):
        """Guard: the label-owner test (test_session_six_fixes) must still exist
        and still compare party.js against INTAKE_QUESTIONS — re-baselined for the
        smaller table, not deleted."""
        source = (REPO / "tests" / "test_session_six_fixes.py").read_text(
            encoding="utf-8")
        self.assertIn("test_the_intake_labels_have_one_owner", source)
        self.assertIn("INTAKE_QUESTIONS", source)


if __name__ == "__main__":
    unittest.main()