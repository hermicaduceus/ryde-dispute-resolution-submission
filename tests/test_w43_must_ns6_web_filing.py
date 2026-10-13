"""W43 MUST lane (M1): NS-6 must fire on a no-show filed through the web form.

RED until the W43 MUST lane ships its brief. Written before the build, in the same shape as
the earlier acceptance files (test_w22_unreadable_numbers.py, test_input_integrity.py): the
tests pin the DEFECT, not a symbol a fix introduces.

The defect (Sol document review, A-F01, parent-reproduced):

  * `app/server.py` `_build_record` deletes `rider_claims_driver_absent` in both record
    formats because the web form never collected it, so the NS-6 gate in
    `app/agents/judge.py` cannot fire for a no-show filed through the form: a contested
    no-show can be ruled "no action" or given a short partial refund with no gate at all.
    The saved-corpus path IS protected (NS-0205 withholds correctly) — this is the web
    filing path only.

The contract these tests pin:

  * the rider no-show filing accepts ONE structured yes/no answer stating that the driver
    never showed up (server validation, same choice grammar as every other yes/no intake
    key), and the form renders it as a real Yes/No question;
  * the builder carries that answer into the record as the existing structured flag the
    NS-6 gate reads — never parsed out of the party's narrative, in either record shape;
  * unanswered is safe: the flag is not carried, and the record behaves exactly as it does
    today (no fabricated absence claim);
  * end to end, a contested no-show filed that way is withheld by NS-6 for a no-action
    ruling and for a short partial refund, exactly like the corpus record.

`ABSENCE_KEY` is the pack's own structured field name — the key the NS-6 gate already reads
on `cancellation.rider_claims_driver_absent` / `ryde_extensions.rider_claims_driver_absent`
(see data/packs/*/disputes/NS-020*.json) — not a symbol this file expects a fix to invent.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from app.dispute import parse_dispute
from app.events import EventLog
from app.pipeline import run_dispute
from app.policy import load_policy
from app.schemas import UNDER_REVIEW_MESSAGE
from app.server import _build_record, _validate_filing, _HTTPError

REPO = Path(__file__).resolve().parent.parent
ORG = REPO / "data" / "packs" / "organiser-style-v1" / "disputes"
SYNTH = REPO / "data" / "packs" / "ryde-synth-v1" / "disputes"
POLICY = REPO / "docs" / "policy.md"
PARTY_JS = REPO / "ui" / "party" / "party.js"

#: The structured field the NS-6 gate reads. The pack's own vocabulary, not a new name.
ABSENCE_KEY = "rider_claims_driver_absent"

#: NS-0205 in both packs: driver_marked_no_show true, no arrival position, fee 6.61, clean
#: rider record — the corpus case NS-6 withholds. Its structured absence flag is what a web
#: filing loses today.
NO_SHOW_TRIP = "T-NS0205"
NO_SHOW_FEE = 6.61

RIDER_NO_SHOW_ANSWERS = {
    "where_were_you": "At the taxi stand as booked.",
    "did_driver_contact_you": "No - he messaged that he was waiting, I did not see him.",
    "safety_concern": "No",
}

DESCRIPTION = "The driver says I did not show up, but I was there and he was not."


def _record(folder: Path, name: str) -> dict:
    return json.loads((folder / name).read_text(encoding="utf-8"))


def _filing(role="rider", category="no_show_charge", trip=NO_SHOW_TRIP, answers=None):
    return {
        "category": category,
        "filed_by": role,
        "trip_id": trip,
        "description": DESCRIPTION,
        "claim_amount_sgd": None,
        "answers": dict(RIDER_NO_SHOW_ANSWERS if answers is None else answers),
    }


def _with_answers(**extra) -> dict:
    answers = dict(RIDER_NO_SHOW_ANSWERS)
    answers.update(extra)
    return answers


def _build(pack_record: dict, answers: dict) -> dict:
    return _build_record(
        pack_record,
        dispute_id="PF-W43MUST",
        category="no_show_charge",
        filed_by="rider",
        description=DESCRIPTION,
        claim_amount_sgd=None,
        answers=answers,
    )


def _flag(record: dict):
    """The structured absence flag the built record carries, or None when it carries none."""
    if "dispute_ticket" in record:
        return record.get("ryde_extensions", {}).get(ABSENCE_KEY)
    return record.get("cancellation", {}).get(ABSENCE_KEY)


_ADVOCATE = {
    "claim_summary": "stand-in",
    "evidence_cited": [],
    "policy_rule_ids": [],
    "argument": "stand-in",
    "requested_outcome": "no action",
    "requested_amount_sgd": 0.0,
    "follow_up_slots": [],
}


def _judge(action="no action", amount=0.0, confidence=0.9):
    from tests.support import ScriptedLLM

    payload = {
        "action": action,
        "recommended_amount_sgd": amount,
        "confidence": confidence,
        "explanation": "stand-in",
        "cited_rule_ids": ["NS-2"],
        "cited_evidence_refs": ["cancellation.cancellation_fee_sgd"],
    }
    return ScriptedLLM({"rider_advocate": _ADVOCATE, "driver_advocate": _ADVOCATE,
                        "judge": payload})


def _run(record: dict, llm):
    """Run one filing through the real pipeline; returns (resolution, gates_failed)."""
    with tempfile.TemporaryDirectory() as tmp:
        events = EventLog(Path(tmp) / "run", "w43-must")
        case = run_dispute(
            dispute=parse_dispute(record),
            llm=llm,
            policy=load_policy(POLICY),
            events=events,
            confidence_threshold=0.65,
            autonomous_cap_sgd=50.0,
        ).to_dict()
        withheld = [event for event in events.events() if event.type == "judge.ruling_withheld"]
        gates = events.read_payload(withheld[0])["gates_failed"] if withheld else []
        return case["resolution"], gates


# ------------------------------------------------------------------ the server side


class TheRiderNoShowFilingAcceptsTheAbsenceAnswer(unittest.TestCase):
    """The structured question the NS-6 gate needs is part of the rider no-show filing."""

    def _accepted(self, body):
        try:
            return _validate_filing(body)
        except _HTTPError as error:
            self.fail("the rider no-show filing was refused: %s" % error)

    def test_the_absence_answer_is_accepted_and_kept_exactly(self):
        for value in ("Yes", "No", "Yes - he never came", "No - he was at the stand"):
            with self.subTest(value=value):
                filing = self._accepted(_filing(answers=_with_answers(**{ABSENCE_KEY: value})))
                self.assertEqual(value, filing["answers"][ABSENCE_KEY])

    def test_the_absence_answer_is_a_choice_not_prose(self):
        # The same grammar every other yes/no intake key obeys: a party states the absence
        # by choosing, so narrative text is refused before it can be read as a claim.
        for value in ("Maybe", "yes", "YES", "Yes -", "No - ", "he never showed up", " Yes"):
            with self.subTest(value=value):
                with self.assertRaises(_HTTPError) as caught:
                    _validate_filing(_filing(answers=_with_answers(**{ABSENCE_KEY: value})))
                self.assertEqual(400, caught.exception.status)

    def test_only_the_rider_no_show_filing_accepts_it(self):
        # Rider-only and no-show-only: a route filing, or a driver filing, may not carry it.
        cases = (
            ("driver", "no_show_charge", "T-NS0205",
             {"driver_waiting_place": "At the pickup point.", "safety_concern": "No"}),
            ("rider", "route_deviation", "T-RD0103",
             {"expected_route": "Expressway, about 11 km.", "safety_concern": "No"}),
        )
        for role, category, trip, answers in cases:
            with self.subTest(role=role, category=category):
                answers = dict(answers, **{ABSENCE_KEY: "Yes"})
                with self.assertRaises(_HTTPError) as caught:
                    _validate_filing(_filing(role=role, category=category, trip=trip,
                                            answers=answers))
                self.assertEqual(400, caught.exception.status)

    def test_an_unanswered_form_still_validates(self):
        filing = self._accepted(_filing())
        self.assertNotIn(ABSENCE_KEY, filing["answers"])


# ------------------------------------------------------------------ the builder


class TheBuilderCarriesTheStructuredAbsenceFlag(unittest.TestCase):
    """`_build_record` puts the party's answer where the NS-6 gate reads it."""

    def test_the_organiser_shape_carries_it_in_the_extension_block(self):
        # The web form serves the organisers' pack by default: ryde_extensions is where that
        # shape keeps the field, and the pack reader moves it onto the cancellation block.
        record = _build(_record(ORG, "NS-0205.json"), _with_answers(**{ABSENCE_KEY: "Yes"}))
        self.assertIs(True, record.get("ryde_extensions", {}).get(ABSENCE_KEY),
                      "the organiser-shape record must carry the rider's absence claim")

    def test_the_pack_shape_carries_it_on_the_cancellation_block(self):
        record = _build(_record(SYNTH, "NS-0205.json"), _with_answers(**{ABSENCE_KEY: "Yes"}))
        self.assertIs(True, record.get("cancellation", {}).get(ABSENCE_KEY),
                      "the pack-shape record must carry the rider's absence claim")

    def test_a_stated_choice_with_an_explanation_still_counts(self):
        for shape, source in (("organiser-style-v1", ORG), ("ryde-synth-v1", SYNTH)):
            with self.subTest(pack=shape):
                record = _build(_record(source, "NS-0205.json"),
                                _with_answers(**{ABSENCE_KEY: "Yes - he was not there"}))
                self.assertTrue(_flag(record))

    def test_a_rider_who_says_the_driver_was_there_states_false(self):
        # The party's own structured answer is carried either way; false can never open the
        # gate, and it must not read as "the rider said nothing" when they said "No".
        for shape, source in (("organiser-style-v1", ORG), ("ryde-synth-v1", SYNTH)):
            with self.subTest(pack=shape):
                record = _build(_record(source, "NS-0205.json"),
                                _with_answers(**{ABSENCE_KEY: "No"}))
                self.assertIs(False, _flag(record))

    def test_unanswered_leaves_the_record_exactly_as_before(self):
        # Default safe: the pack's own flag is still deleted and no claim is fabricated.
        for shape, source in (("organiser-style-v1", ORG), ("ryde-synth-v1", SYNTH)):
            pack_record = _record(source, "NS-0205.json")
            self.assertIs(True, _flag(pack_record), "the corpus record states the absent claim")
            for answers in (RIDER_NO_SHOW_ANSWERS, _with_answers(**{ABSENCE_KEY: ""})):
                with self.subTest(pack=shape, answers=sorted(answers)):
                    self.assertIsNone(_flag(_build(pack_record, answers)))

    def test_the_narrative_text_is_never_parsed_for_the_flag(self):
        # Standing ruling: party text is structured, never relayed or parsed. A description
        # that asserts absence in prose must not become a structured claim: only the choice
        # the party made does. The record's own narrative is prose like this one.
        self.assertIn("did not show up", DESCRIPTION)
        for shape, source in (("organiser-style-v1", ORG), ("ryde-synth-v1", SYNTH)):
            with self.subTest(pack=shape):
                record = _build(_record(source, "NS-0205.json"), RIDER_NO_SHOW_ANSWERS)
                self.assertEqual(DESCRIPTION, record["dispute_ticket"]["description"]
                                 if "dispute_ticket" in record else record["claim"]["text"])
                self.assertIsNone(_flag(record))


# ------------------------------------------------------------------ the gate, end to end


class AContestedNoShowFiledOnTheWebIsHeldByNS6(unittest.TestCase):
    """The defect itself: the web path reaches the NS-6 gate exactly like the corpus path."""

    def _web_filed(self, source: Path, answers: dict) -> dict:
        return _build(_record(source, "NS-0205.json"), answers)

    def test_a_no_action_ruling_is_withheld_for_both_shapes(self):
        for shape, source in (("organiser-style-v1", ORG), ("ryde-synth-v1", SYNTH)):
            with self.subTest(pack=shape):
                resolution, gates = _run(
                    self._web_filed(source, _with_answers(**{ABSENCE_KEY: "Yes"})),
                    _judge("no action", 0.0))
                self.assertEqual("withheld", resolution["outcome"], resolution)
                self.assertIsNone(resolution["ruling"])
                self.assertEqual(UNDER_REVIEW_MESSAGE, resolution["party_message"])
                self.assertIn("NS-6", gates, gates)

    def test_a_short_partial_refund_is_withheld_too(self):
        # The parent reproduced exactly this: an injected SGD 1.00 partial refund RULED on the
        # web-built record, because the gate needs the rider's structured claim.
        for shape, source in (("organiser-style-v1", ORG), ("ryde-synth-v1", SYNTH)):
            with self.subTest(pack=shape):
                resolution, gates = _run(
                    self._web_filed(source, _with_answers(**{ABSENCE_KEY: "Yes"})),
                    _judge("refund", 1.00))
                self.assertEqual("withheld", resolution["outcome"], resolution)
                self.assertIn("NS-6", gates, gates)

    def test_the_exact_full_fee_refund_is_still_allowed(self):
        # NS-6 is a gate, not a blanket: the one ruling it lets through is the exact fee.
        resolution, gates = _run(
            self._web_filed(ORG, _with_answers(**{ABSENCE_KEY: "Yes"})),
            _judge("refund", NO_SHOW_FEE))
        self.assertNotIn("NS-6", gates, resolution)
        self.assertEqual("ruled", resolution["outcome"], resolution)

    def test_an_unanswered_web_filing_is_not_gated(self):
        # The safe default and the anti-always-gate control: a filing that states no absence
        # behaves exactly as it does today.
        for shape, source in (("organiser-style-v1", ORG), ("ryde-synth-v1", SYNTH)):
            with self.subTest(pack=shape):
                resolution, gates = _run(self._web_filed(source, RIDER_NO_SHOW_ANSWERS),
                                         _judge("no action", 0.0))
                self.assertNotIn("NS-6", gates, resolution)
                self.assertEqual("ruled", resolution["outcome"], resolution)

    def test_a_driver_filing_is_never_gated_by_the_rider_absence_flag(self):
        driver_answers = {"driver_waiting_place": "At the pickup point.", "safety_concern": "No"}
        record = _build_record(
            _record(ORG, "NS-0205.json"), dispute_id="PF-W43MUST", category="no_show_charge",
            filed_by="driver", description="The rider did not show.", claim_amount_sgd=None,
            answers=driver_answers)
        resolution, gates = _run(record, _judge("no action", 0.0))
        self.assertNotIn("NS-6", gates, resolution)
        self.assertEqual("ruled", resolution["outcome"], resolution)


# ------------------------------------------------------------------ the form itself

_UI_DRIVER = r'''
const posted = [];
const fetch = (url, opts) => {
  if (url.indexOf("/api/trips") === 0) {
    return Promise.resolve({ ok: true, json: () => Promise.resolve({ trips: [
      { trip_id: "T-NS0205", label: "Orchard Boulevard to Jurong Point", date: "2026-09-14",
        kind_label: "No-show charge", fare_sgd: 6.61, charge_label: "fee" }] }) });
  }
  posted.push(JSON.parse(opts.body));
  return Promise.resolve({ ok: true, json: () => Promise.resolve(
    { run_id: "run", dispute_id: "PF-DEMO", status: "under_review", message: "m", questions: [] }) });
};
const tick = () => new Promise(r => setTimeout(r, 0));
(async () => {
  const opts = JSON.parse(process.env.W43);
  if (opts.role !== null) { doc.getElementById("form-steps").setAttribute("data-filed-by", opts.role); }
  ["step-trip", "step-details", "outcome", "outcome-questions", "category-error", "trip-error",
   "details-error", "answers-error"].forEach(id => { doc.getElementById(id).hidden = true; });
  vm.runInNewContext(fs.readFileSync(process.env.PARTY_JS, "utf8"),
    { document: doc, window: { scrollTo() {} }, fetch, Promise, setTimeout,
      encodeURIComponent, JSON, Array, Number, isFinite, String });
  doc.getElementById("category-options").children[opts.category].click();
  doc.getElementById("category-next").click(); await tick(); await tick();
  doc.getElementById("trip-options").children[0].click();
  doc.getElementById("trip-next").click(); await tick();
  // Every control carrying a question key, anywhere the page put it. The absence question
  // is deliberately NOT one of the questionnaire rows, so the search is not limited to
  // the question list: the page may render it in its own slot.
  const found = {};
  Object.keys(ids).forEach(function (id) {
    ids[id].querySelectorAll("[data-question-key]").forEach(function (node) {
      const key = node.getAttribute("data-question-key");
      const choice = node.getAttribute("data-choice");
      found[key] = found[key] || { choices: [], tagged: [], clicked: null };
      if (choice !== null) { found[key].choices.push(choice); }
      if (node.tagName === "TEXTAREA") { found[key].tagged.push("textarea"); }
    });
  });
  const rowKeys = doc.getElementById("question-list").children.map(function (field) {
    const input = field.querySelector("[data-question-key]");
    return input ? input.getAttribute("data-question-key") : null;
  });
  let clicked = null;
  (opts.steps || []).forEach(function (step) {
    const key = step[0], choice = step[1];
    Object.keys(ids).forEach(function (id) {
      ids[id].querySelectorAll("[data-question-key]").forEach(function (node) {
        if (node.getAttribute("data-question-key") === key
            && node.getAttribute("data-choice") === choice) {
          node.click();
          clicked = { key: key, choice: choice };
        }
      });
    });
  });
  doc.getElementById("description").value = "The driver says I did not show up, I say he was not there.";
  doc.getElementById("claim-amount").value = "";
  doc.getElementById("details-form").fire("submit"); await tick(); await tick();
  process.stdout.write(JSON.stringify({
    found: found, rowKeys: rowKeys, clicked: clicked,
    answers: posted.length ? posted[0].answers : null,
    category: posted.length ? posted[0].category : null,
    filedBy: posted.length ? posted[0].filed_by : null,
  }));
})().catch(e => { process.stderr.write(String(e.stack || e)); process.exit(1); });
'''


def _drive_ui(role, category, steps=()):
    """Drive ui/party/party.js on the project's shared minimal DOM (tests.w16_support.DOM)."""
    from tests.w16_support import DOM

    node = shutil.which("node")
    if not node:
        raise AssertionError("Node is required for the party-form behavioural pins")
    env = dict(os.environ, PARTY_JS=str(PARTY_JS),
               W43=json.dumps({"role": role, "category": category, "steps": list(steps)}))
    result = subprocess.run([node, "-e", DOM + _UI_DRIVER], env=env, text=True,
                            capture_output=True, timeout=30)
    if result.returncode != 0:
        raise AssertionError("the party page harness failed: " + result.stderr)
    return json.loads(result.stdout)


class TheRiderNoShowFormAsksTheAbsenceQuestion(unittest.TestCase):
    """The form half: a real Yes/No question, serialized only when the party chooses."""

    def test_the_rider_no_show_page_offers_the_structured_question(self):
        out = _drive_ui("rider", 1)
        self.assertIn(ABSENCE_KEY, out["found"],
                      "the rider no-show form must ask the structured absence question: %s"
                      % sorted(out["found"]))
        self.assertEqual(["No", "Yes"], sorted(out["found"][ABSENCE_KEY]["choices"]))

    def test_the_chosen_answer_is_serialized_into_the_filing(self):
        out = _drive_ui("rider", 1, [(ABSENCE_KEY, "Yes")])
        self.assertEqual({"key": ABSENCE_KEY, "choice": "Yes"}, out["clicked"],
                         "the page must render a clickable Yes for the absence question")
        self.assertEqual("Yes", out["answers"][ABSENCE_KEY], out["answers"])
        self.assertEqual("no_show_charge", out["category"])
        self.assertEqual("rider", out["filedBy"])

    def test_an_unanswered_absence_question_is_not_sent(self):
        # The safe default: no choice, no key, no claim.
        out = _drive_ui("rider", 1)
        self.assertNotIn(ABSENCE_KEY, out["answers"], out["answers"])

    def test_other_filings_do_not_ask_it(self):
        for role, category in (("driver", 1), ("rider", 0)):
            with self.subTest(role=role, category=category):
                self.assertNotIn(ABSENCE_KEY, _drive_ui(role, category)["found"])

    def test_the_pinned_questionnaire_rows_do_not_move(self):
        # The shared intake tables keep one owner (test_session_six_fixes,
        # test_w16_driver_contract); the extra structured question must not become a fourth
        # row of the rider no-show question list.
        out = _drive_ui("rider", 1)
        self.assertEqual(["where_were_you", "did_driver_contact_you", "safety_concern"],
                         out["rowKeys"])


if __name__ == "__main__":
    unittest.main()
