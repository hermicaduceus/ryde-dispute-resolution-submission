"""Session six, fix round two: acceptance target for five confirmed review findings.

Written BEFORE the fixes, so it is RED until the build lane ships them. Each test names
its item (S1..S5, see docs/build-briefs/session-six-fix-brief-2.md). Every finding was reproduced
firsthand before being written down.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path
from unittest import mock

from app.policy import load_policy
from tests.test_party_surface import (
    ORG_DIR,
    POLICY,
    _asking_advocate,
    _blank_org,
    _filing,
    _record,
    _run,
    _Server,
)
from tests.support import ScriptedLLM
from tests.test_session_six_fixes import _leaky_judge

TEMPLATE_ROUTE = "What route did the app show you, and roughly how long was it?"


def _scripted(rider_questions=(), judge=None):
    return ScriptedLLM(
        {
            "rider_advocate": _asking_advocate(list(rider_questions)),
            "driver_advocate": _asking_advocate([]),
            "judge": judge if judge is not None else _leaky_judge(),
        }
    )


# --------------------------------------------------------- S1 canonical messages


class S1NonDecisionStatusesAlwaysUseTheCanonicalMessage(unittest.TestCase):
    """Only a decision's message varies. Every other status shows its fixed text."""

    LEAK = "Passed along. The AI agent judge will follow up (ESC-1)."

    def _view(self, outcome, **extra):
        from app.server import party_view

        resolution = dict({"outcome": outcome, "party_message": self.LEAK, "questions_for_party": []}, **extra)
        return party_view({"run_id": "r", "dispute_id": "d", "resolution": resolution})

    def test_passed_to_support_shows_the_support_message_not_the_file(self):
        from app.schemas import HUMAN_REVIEW_MESSAGE

        view = self._view("human_review")
        self.assertEqual("passed_to_support", view["status"])
        self.assertEqual(HUMAN_REVIEW_MESSAGE, view["message"])

    def test_needs_info_shows_the_needs_info_message_not_the_file(self):
        from app.schemas import NEEDS_INFO_MESSAGE

        view = self._view("needs_info", questions_for_party=["Where were you?"])
        self.assertEqual("needs_info", view["status"])
        self.assertEqual(NEEDS_INFO_MESSAGE, view["message"])
        self.assertEqual(["Where were you?"], view["questions"])

    def test_under_review_still_canonical(self):
        from app.schemas import UNDER_REVIEW_MESSAGE

        self.assertEqual(UNDER_REVIEW_MESSAGE, self._view("withheld")["message"])

    def test_a_leaky_decision_still_fails_closed(self):
        from app.schemas import UNDER_REVIEW_MESSAGE

        view = self._view("ruled")
        self.assertEqual(("under_review", UNDER_REVIEW_MESSAGE), (view["status"], view["message"]))


# ----------------------------------------------------------- S2 word forms


class S2FilterCatchesWordFormsAndIdVariants(unittest.TestCase):
    UNSAFE = [
        "Our models suggest the driver was there",
        "The judges' view differs",
        "We may withhold the refund",
        "It was withholding the payment",
        "The judgement is pending",
        "We are confident it was late",
        "Our advocacy team will look",
        "Your case will be escalated",
        "The agents will call you",
        "under rd-1 you must tell us",
        "Per Esc-4 we cannot pay",
        "Rule RD-1000 applies",
        "Our AI checked it",
    ]
    SAFE = [
        "Where were you when the trip was meant to start?",
        "Did the driver try to contact you?",
        "Decision: refund of SGD 5.81. Basis: When a deviation is material.",
        'We didn\'t get an answer to "What went wrong?". Could you tell us?',
        "Which pickup point did you walk to?",
    ]

    def test_unsafe_forms_are_caught(self):
        from app.schemas import is_party_safe

        for text in self.UNSAFE:
            with self.subTest(text=text):
                self.assertFalse(is_party_safe(text))

    def test_plain_text_still_passes(self):
        from app.schemas import is_party_safe

        for text in self.SAFE:
            with self.subTest(text=text):
                self.assertTrue(is_party_safe(text))

    def test_every_non_escalation_rule_title_is_still_party_safe(self):
        """The broader filter must not silently empty the Basis line."""
        from app.schemas import is_party_safe

        policy = load_policy(POLICY)
        for rule_id in policy.rule_ids():
            if rule_id.startswith("ESC-"):
                continue
            with self.subTest(rule=rule_id):
                self.assertTrue(is_party_safe(policy.rule_title(rule_id)), policy.rule_title(rule_id))

    def test_the_gate_replaces_an_inflected_question(self):
        record = _blank_org(_record(ORG_DIR, "RD-0101.json"), "expected_route")
        case = _run(record, llm=_scripted(["What do the models think we should withhold?"]))
        questions = case["resolution"]["questions_for_party"]
        self.assertEqual(1, len(questions), questions)
        self.assertIn(TEMPLATE_ROUTE, questions[0])


# ------------------------------------------------------------- S3 duplicates


class S3NoNearDuplicateQuestions(unittest.TestCase):
    def _questions(self, rider_questions):
        record = _blank_org(_record(ORG_DIR, "RD-0101.json"), "expected_route")
        return _run(record, llm=_scripted(rider_questions))["resolution"]["questions_for_party"]

    # The next three were rewritten for W13 (the operator ruling 2026-09-24): advocates pick slots and
    # code renders the sentences, so the S3 properties are now asserted over slots.

    def _slot_questions(self, rider_slots, driver_slots=(), blank=True):
        from tests.test_party_surface import _JUDGE, _slot_advocate

        record = _record(ORG_DIR, "RD-0101.json")
        if blank:
            record = _blank_org(record, "expected_route")
        llm = ScriptedLLM(
            {
                "rider_advocate": _slot_advocate(rider_slots),
                "driver_advocate": _slot_advocate(driver_slots),
                "judge": _JUDGE,
            }
        )
        return _run(record, llm=llm)["resolution"]["questions_for_party"]

    def test_a_bank_slot_beats_the_blank_field_fallback(self):
        from app.schemas import render_follow_up_slot

        self.assertEqual(
            [render_follow_up_slot("route_deviation", "route_shown")],
            self._slot_questions(["route_shown"]),
        )

    def test_a_form_slot_for_the_blank_field_is_not_doubled(self):
        from app.schemas import FORM_SLOT_QUESTION_TEMPLATE

        self.assertEqual(
            [FORM_SLOT_QUESTION_TEMPLATE % TEMPLATE_ROUTE],
            self._slot_questions(["form:expected_route"]),
        )

    def test_the_same_slot_from_both_advocates_collapses(self):
        questions = self._slot_questions(["route_shown"], ["route_shown"], blank=False)
        self.assertEqual(1, len(questions), questions)

    def test_all_leaky_still_falls_back_to_a_template(self):
        questions = self._questions(["What is your confidence in the Judge?"])
        self.assertEqual(1, len(questions))
        self.assertIn(TEMPLATE_ROUTE, questions[0])


# ------------------------------------------------------ S4 bookkeeping failure


class S4BookkeepingFailureDoesNotBrickOrDuplicate(unittest.TestCase):
    """Once the round-two run exists, the answer happened: say so, and keep the claim.

    Releasing the claim here would let a retry create a second ruling for the same
    dispute, which is the R4 defect by another route.
    """

    def test_a_failed_bookkeeping_write_returns_the_ruling_and_holds_the_claim(self):
        server = _Server()
        try:
            answers = _filing("x")["answers"]
            answers["expected_route"] = ""
            _, trips = server.json("GET", "/api/trips?category=route_deviation")
            _, first = server.json("POST", "/api/disputes", _filing(trips["trips"][0]["trip_id"], answers=answers))
            self.assertEqual("needs_info", first["status"], first)
            reply = {"answers": [{"question": q, "answer": "The expressway."} for q in first["questions"]]}
            # Patch the write itself, not a named helper: the pin must fail on the
            # behaviour (500 + bricked run), not on a missing function name.
            original = Path.write_text

            def failing_write(path, *args, **kwargs):
                if path.name == "answered.json":
                    raise OSError("disk full")
                return original(path, *args, **kwargs)

            with mock.patch.object(Path, "write_text", failing_write):
                status, second = server.json("POST", "/api/disputes/%s/answers" % first["run_id"], reply)
            self.assertEqual(200, status, second)
            self.assertIn(second["status"], ("decided", "under_review"))
            status, _ = server.json("POST", "/api/disputes/%s/answers" % first["run_id"], reply)
            self.assertEqual(409, status, "the run was answered; a retry must not rule twice")
            self.assertEqual(2, len([p for p in server.out.iterdir() if p.is_dir()]))
        finally:
            server.close()

    def test_the_normal_path_still_records_which_run_answered(self):
        server = _Server()
        try:
            answers = _filing("x")["answers"]
            answers["expected_route"] = ""
            _, trips = server.json("GET", "/api/trips?category=route_deviation")
            _, first = server.json("POST", "/api/disputes", _filing(trips["trips"][0]["trip_id"], answers=answers))
            reply = {"answers": [{"question": q, "answer": "The expressway."} for q in first["questions"]]}
            _, second = server.json("POST", "/api/disputes/%s/answers" % first["run_id"], reply)
            record = json.loads((server.out / first["run_id"] / "answered.json").read_text(encoding="utf-8"))
            self.assertEqual(second["run_id"], record["answered_by_run"])
        finally:
            server.close()


# ------------------------------------------------ S5 no escalation rules in Basis


class S5EscalationRulesNeverAppearInABasisLine(unittest.TestCase):
    def test_esc_titles_are_excluded_by_prefix(self):
        from app.schemas import JudgeRuling, party_message_for_ruling

        policy = load_policy(POLICY)
        ruling = JudgeRuling.from_payload(_leaky_judge(rules=("ESC-4", "ESC-1", "RD-1")))
        message = party_message_for_ruling(ruling, policy)
        self.assertIn("When a deviation is material", message)
        for leak in ("autonomous", "cap", "Out of scope"):
            self.assertNotIn(leak, message)

    def test_a_ruling_citing_only_escalation_rules_has_no_basis_line(self):
        from app.schemas import JudgeRuling, party_message_for_ruling

        ruling = JudgeRuling.from_payload(_leaky_judge(rules=("ESC-4", "ESC-7")))
        message = party_message_for_ruling(ruling, load_policy(POLICY))
        self.assertEqual("Decision: refund of SGD 4.87.", message)

    def test_end_to_end_the_cap_title_never_reaches_a_party(self):
        case = _run(_record(ORG_DIR, "RD-0101.json"), llm=_scripted(judge=_leaky_judge(rules=("ESC-4", "RD-1"))))
        self.assertEqual("ruled", case["resolution"]["outcome"])
        self.assertNotRegex(case["resolution"]["party_message"], re.compile("autonomous|cap", re.I))


if __name__ == "__main__":
    unittest.main()
