"""Session six, fix round three (final): acceptance target for four confirmed findings.

Written BEFORE the fixes, so it is RED until the build lane ships them. Each test names its
item (T1..T4, see docs/session-six-fix-brief-3.md). Every item was reproduced firsthand
before it was written down.

This is the last round on the party-safety filter. The filter is a backstop: the real
protection is structural (decisions built in code, template fallback for questions, fixed
text on every non-decision screen). Known limits the filter deliberately does not chase are
listed in the brief, not pinned here.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from app.policy import load_policy
from tests.test_party_surface import ORG_DIR, POLICY, _blank_org, _filing, _record, _run, _Server
from tests.test_session_six_fixes_2 import _scripted

TRIP_ID_QUESTION = "Was your trip TRIP-2026-09945, the one to Tiong Bahru?"


# ------------------------------------------- T1 rule IDs: only our real prefixes


class T1RuleIdsMatchOnlyRealPolicyPrefixes(unittest.TestCase):
    """Round two's case-insensitive 4-digit pattern blocked the pack's own trip id."""

    PUBLIC_TOKENS = [
        TRIP_ID_QUESTION,
        "Were you picked up before 7pm on Sept-3?",
        "Did you travel during covid-19 restrictions?",
        "Was it the SG-50 promotion?",
        "Were you at Block AB-12?",
    ]

    def test_public_tokens_are_party_safe(self):
        from app.schemas import is_party_safe

        for text in self.PUBLIC_TOKENS:
            with self.subTest(text=text):
                self.assertTrue(is_party_safe(text))

    def test_every_real_rule_id_is_still_caught_in_any_case(self):
        """Derived from the policy itself, so a new prefix cannot slip past unnoticed."""
        from app.schemas import is_party_safe

        for rule_id in load_policy(POLICY).rule_ids():
            for form in (rule_id, rule_id.lower(), rule_id.title()):
                with self.subTest(form=form):
                    self.assertFalse(is_party_safe("Under %s you must tell us." % form))

    def test_a_long_rule_number_is_still_caught(self):
        from app.schemas import is_party_safe

        self.assertFalse(is_party_safe("Rule RD-1000 applies"))

    def test_a_decided_view_quoting_a_trip_id_stays_decided(self):
        from app.server import party_view

        message = "Decision: refund of SGD 5.81. Your trip TRIP-2026-09945."
        view = party_view(
            {"run_id": "r", "dispute_id": "d",
             "resolution": {"outcome": "ruled", "party_message": message, "questions_for_party": []}}
        )
        # W12 (session ten): this fixture carries no ruling record, so the LLM
        # provider is unproven and the decided view leads with the demo notice.
        # The T1 pin this test owns is unchanged: the trip id must not demote
        # the view — it stays decided with the decision text intact behind
        # the notice.
        import app.schemas as _schemas
        notice = getattr(_schemas, "DEMO_NOTICE_MESSAGE", "")
        self.assertEqual("decided", view["status"])
        self.assertTrue(view["message"].startswith(notice))
        self.assertTrue(view["message"].endswith(message))

    # test_a_model_question_quoting_the_trip_id_reaches_the_party was removed for W13 (the operator
    # ruling 2026-09-24): no model-written question reaches a party at all now. The
    # filter-level check on TRIP_ID_QUESTION above still pins T1.


# ------------------------------------------------ T2 four missed word forms


class T2FourMissedWordForms(unittest.TestCase):
    UNSAFE = [
        "Our agentic review flagged it.",
        "Our traffic modelling suggests the route was fine.",
        "The route was modelled as fine.",
        "Our A.I. checked it.",
        "Our A. I. checked it.",
        "We may withold the refund.",
        "The refund was witheld.",
    ]
    # Words that merely resemble a stem must keep passing.
    SAFE = [
        "Was it plan A. I walked to the pickup point.",
        "The fare said SGD 12.",
        "Did the driver stop at Main Street?",
        "Was the air-con working?",
        "Was the road being remodelled?",
        "Did a modal pop up in the app?",
        "Did the travel agency book it?",
    ]

    def test_the_missed_forms_are_caught(self):
        from app.schemas import is_party_safe

        for text in self.UNSAFE:
            with self.subTest(text=text):
                self.assertFalse(is_party_safe(text))

    def test_look_alike_plain_words_still_pass(self):
        from app.schemas import is_party_safe

        for text in self.SAFE:
            with self.subTest(text=text):
                self.assertTrue(is_party_safe(text))

    def test_every_non_escalation_rule_title_is_still_party_safe(self):
        from app.schemas import is_party_safe

        policy = load_policy(POLICY)
        for rule_id in policy.rule_ids():
            if not rule_id.startswith("ESC-"):
                with self.subTest(rule_id=rule_id):
                    self.assertTrue(is_party_safe(policy.rule_title(rule_id)))


# ------------------------------------- T3 any bookkeeping failure, not only OSError


class T3AnyBookkeepingFailureStillDeliversTheRuling(unittest.TestCase):
    def test_a_non_os_error_on_the_answered_write_still_returns_200_and_holds_the_claim(self):
        server = _Server()
        try:
            answers = _filing("x")["answers"]
            answers["expected_route"] = ""
            _, trips = server.json("GET", "/api/trips?category=route_deviation")
            _, first = server.json("POST", "/api/disputes", _filing(trips["trips"][0]["trip_id"], answers=answers))
            self.assertEqual("needs_info", first["status"], first)
            reply = {"answers": [{"question": q, "answer": "The expressway."} for q in first["questions"]]}
            original = Path.write_text

            def failing_write(path, *args, **kwargs):
                if path.name == "answered.json":
                    raise ValueError("unserialisable")
                return original(path, *args, **kwargs)

            with mock.patch.object(Path, "write_text", failing_write):
                status, second = server.json("POST", "/api/disputes/%s/answers" % first["run_id"], reply)
            self.assertEqual(200, status, second)
            status, _ = server.json("POST", "/api/disputes/%s/answers" % first["run_id"], reply)
            self.assertEqual(409, status, "the run was answered; a retry must not rule twice")
        finally:
            server.close()


# -------------------------- T4 a blank message on a non-decision file is irrelevant


class T4BlankMessageOnlyMattersForADecision(unittest.TestCase):
    """S1 made every non-decision message a constant, so the file's text is never shown."""

    def _view(self, outcome, message, questions=()):
        from app.server import party_view

        return party_view(
            {"run_id": "r", "dispute_id": "d",
             "resolution": {"outcome": outcome, "party_message": message, "questions_for_party": list(questions)}}
        )

    def test_needs_info_with_a_blank_message_keeps_its_safe_questions(self):
        from app.schemas import NEEDS_INFO_MESSAGE

        for message in ("", "   ", None):
            with self.subTest(message=message):
                view = self._view("needs_info", message, ["Where were you?"])
                self.assertEqual(
                    ("needs_info", NEEDS_INFO_MESSAGE, ["Where were you?"]),
                    (view["status"], view["message"], view["questions"]),
                )

    def test_human_review_with_a_missing_message_shows_the_support_message(self):
        from app.schemas import HUMAN_REVIEW_MESSAGE

        view = self._view("human_review", None)
        self.assertEqual(("passed_to_support", HUMAN_REVIEW_MESSAGE), (view["status"], view["message"]))

    def test_a_decision_with_a_blank_message_still_fails_closed(self):
        from app.schemas import UNDER_REVIEW_MESSAGE

        for message in ("", "   ", None):
            with self.subTest(message=message):
                view = self._view("ruled", message)
                self.assertEqual(("under_review", UNDER_REVIEW_MESSAGE), (view["status"], view["message"]))

    def test_a_leaky_question_still_fails_the_view_closed(self):
        view = self._view("needs_info", "", ["What is the Judge's confidence?"])
        self.assertEqual(("under_review", []), (view["status"], view["questions"]))


if __name__ == "__main__":
    unittest.main()
