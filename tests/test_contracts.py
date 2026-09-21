"""The frozen output contracts: the Judge schema, advocate cases, and the resolution."""

from __future__ import annotations

import unittest

from app.schemas import (
    UNDER_REVIEW_MESSAGE,
    AdvocateCase,
    ContractError,
    JudgeRuling,
    Resolution,
    RulingAction,
    party_message_for_ruling,
)

VALID_RULING = {
    "action": "refund",
    "recommended_amount_sgd": 4.87,
    "confidence": 0.82,
    "explanation": "The deviation was material and no justification was recorded.",
    "cited_rule_ids": ["RD-1", "RD-2"],
}


class RulingActionTest(unittest.TestCase):
    def test_the_three_actions_from_the_statement(self):
        self.assertEqual([member.value for member in RulingAction], ["refund", "compensation", "no action"])

    def test_parsing_tolerates_case_and_separator_drift(self):
        for raw in ("no action", "No Action", "no_action", "NO-ACTION", "  no action  "):
            self.assertIs(RulingAction.parse(raw), RulingAction.NO_ACTION)

    def test_an_action_outside_the_enum_is_refused(self):
        with self.assertRaises(ContractError):
            RulingAction.parse("partial refund")


class JudgeRulingTest(unittest.TestCase):
    def test_a_valid_payload_produces_the_contract(self):
        ruling = JudgeRuling.from_payload(VALID_RULING)
        self.assertEqual(ruling.action, "refund")
        self.assertEqual(ruling.recommended_amount_sgd, 4.87)
        self.assertEqual(ruling.confidence, 0.82)
        self.assertEqual(ruling.cited_rule_ids, ["RD-1", "RD-2"])

    def test_confidence_outside_zero_to_one_is_refused(self):
        for bad in (1.5, -0.1):
            payload = dict(VALID_RULING, confidence=bad)
            with self.assertRaises(ContractError):
                JudgeRuling.from_payload(payload)

    def test_a_missing_explanation_is_refused(self):
        payload = dict(VALID_RULING)
        del payload["explanation"]
        with self.assertRaises(ContractError):
            JudgeRuling.from_payload(payload)

    def test_a_missing_action_is_refused(self):
        payload = dict(VALID_RULING)
        del payload["action"]
        with self.assertRaises(ContractError):
            JudgeRuling.from_payload(payload)

    def test_a_negative_amount_is_refused(self):
        with self.assertRaises(ContractError):
            JudgeRuling.from_payload(dict(VALID_RULING, recommended_amount_sgd=-1.0))

    def test_no_action_forces_a_zero_amount_and_records_it(self):
        payload = dict(VALID_RULING, action="no action", recommended_amount_sgd=4.87)
        ruling = JudgeRuling.from_payload(payload)
        self.assertEqual(ruling.recommended_amount_sgd, 0.0)
        self.assertTrue(any("forced to 0.00" in note for note in ruling.validation["notes"]))

    def test_a_ruling_with_no_cited_rules_is_flagged(self):
        payload = dict(VALID_RULING, cited_rule_ids=[])
        ruling = JudgeRuling.from_payload(payload)
        self.assertTrue(any("no policy rule IDs cited" in note for note in ruling.validation["notes"]))


class AdvocateCaseTest(unittest.TestCase):
    PAYLOAD = {
        "claim_summary": "The rider was charged for a longer trip than the app showed.",
        "evidence_cited": ["route.deviation_km", "fare.deviation_fare_delta_sgd"],
        "policy_rule_ids": ["RD-1"],
        "argument": "The deviation is 25.54 percent, above the threshold in RD-1.",
        "requested_outcome": "refund",
        "requested_amount_sgd": 4.87,
        "follow_up_questions": [],
    }

    def test_a_valid_payload_produces_the_contract(self):
        case = AdvocateCase.from_payload(self.PAYLOAD, party="rider", agent="rider_advocate")
        self.assertEqual(case.party, "rider")
        self.assertEqual(case.evidence_cited, ["route.deviation_km", "fare.deviation_fare_delta_sgd"])
        self.assertEqual(case.requested_outcome, "refund")

    def test_a_missing_argument_is_refused(self):
        payload = dict(self.PAYLOAD)
        del payload["argument"]
        with self.assertRaises(ContractError):
            AdvocateCase.from_payload(payload, party="rider", agent="rider_advocate")

    def test_follow_up_questions_default_to_empty(self):
        payload = dict(self.PAYLOAD)
        del payload["follow_up_questions"]
        case = AdvocateCase.from_payload(payload, party="rider", agent="rider_advocate")
        self.assertEqual(case.follow_up_questions, [])


class ResolutionTest(unittest.TestCase):
    def test_a_withheld_resolution_carries_no_ruling(self):
        resolution = Resolution(
            dispute_id="RD-1",
            outcome="withheld",
            party_message=UNDER_REVIEW_MESSAGE,
            confidence_threshold=0.65,
            withheld_candidate=JudgeRuling.from_payload(VALID_RULING),
            escalated_for_human_review=True,
        )
        payload = resolution.to_dict()
        self.assertIsNone(payload["ruling"])
        self.assertFalse(payload["delivered_to_parties"])
        self.assertEqual(payload["withheld_candidate"]["action"], "refund")

    def test_the_under_review_message_is_neutral(self):
        lowered = UNDER_REVIEW_MESSAGE.lower()
        for forbidden in ("ai", "model", "agent", "confidence", "likely", "probably"):
            self.assertNotIn(forbidden, lowered)

    def test_the_party_message_states_the_action_and_amount(self):
        message = party_message_for_ruling(JudgeRuling.from_payload(VALID_RULING))
        self.assertIn("refund", message)
        self.assertIn("4.87", message)
        self.assertIn("material", message)

    def test_a_no_action_message_carries_no_amount(self):
        message = party_message_for_ruling(
            JudgeRuling.from_payload(dict(VALID_RULING, action="no action", recommended_amount_sgd=0.0))
        )
        self.assertIn("no action", message)
        self.assertNotIn("SGD", message)


if __name__ == "__main__":
    unittest.main()
