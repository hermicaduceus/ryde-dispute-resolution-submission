"""The pipeline end to end, on the example disputes, with mocked LLM responses.

These tests exercise the plumbing the real build depends on: the event stream, the
confidence gate, category routing, citation checking, and the contract failures that must
stop a run rather than be papered over.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.agents import AgentError
from app.events import EventLog
from app.llm import MockLLMClient
from app.schemas import HUMAN_REVIEW_MESSAGE, UNDER_REVIEW_MESSAGE

from .support import (
    NO_SHOW,
    OUT_OF_SCOPE,
    ROUTE_DEVIATION,
    ScriptedLLM,
    event_types,
    events_by_type,
    run_fixture,
)

RIDER_CASE = {
    "claim_summary": "The trip ran 1.635 km longer than the estimate.",
    "evidence_cited": ["route.deviation_km", "fare.deviation_fare_delta_sgd"],
    "policy_rule_ids": ["RD-1"],
    "argument": "The deviation exceeds the threshold in RD-1.",
    "requested_outcome": "refund",
    "requested_amount_sgd": 4.87,
    "follow_up_questions": [],
}
DRIVER_CASE = {
    "claim_summary": "The fare charged matches the trip driven.",
    "evidence_cited": ["fare.difference_sgd"],
    "policy_rule_ids": ["RD-2"],
    "argument": "The recomputed fare equals the charge.",
    "requested_outcome": "no action",
    "requested_amount_sgd": 0.0,
    "follow_up_questions": [],
}


class PipelineTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.run_dir = Path(self._tmp.name) / "run"

    def tearDown(self):
        self._tmp.cleanup()


class RouteDeviationRunTest(PipelineTestCase):
    def setUp(self):
        super().setUp()
        self.case_file = run_fixture(ROUTE_DEVIATION, self.run_dir)

    def test_the_run_ends_in_a_ruling_delivered_to_the_parties(self):
        resolution = self.case_file.resolution
        self.assertEqual(resolution["outcome"], "ruled")
        self.assertTrue(resolution["delivered_to_parties"])
        self.assertEqual(resolution["ruling"]["action"], "refund")
        self.assertEqual(resolution["ruling"]["recommended_amount_sgd"], 4.87)
        self.assertIn("4.87", resolution["party_message"])

    def test_the_evidence_pack_is_in_the_case_file(self):
        self.assertEqual(self.case_file.evidence_pack["route"]["deviation_km"], 1.635)
        self.assertEqual(self.case_file.evidence_pack["fare"]["deviation_fare_delta_sgd"], 4.87)

    def test_both_advocates_submitted_a_case(self):
        self.assertIsNotNone(self.case_file.rider_case)
        self.assertIsNotNone(self.case_file.driver_case)
        self.assertEqual(self.case_file.rider_case["party"], "rider")
        self.assertEqual(self.case_file.driver_case["party"], "driver")

    def test_the_event_stream_is_the_expected_sequence(self):
        self.assertEqual(
            event_types(self.case_file),
            [
                "run.started",
                "dispute.filed",
                "evidence.pack_built",
                "case.assigned",
                "case.assigned",
                "advocate.case_submitted",
                "advocate.case_submitted",
                "judge.deliberation_started",
                "judge.ruling_issued",
                "party.notified",
                "run.completed",
            ],
        )

    def test_advocate_traffic_is_addressed_to_the_judge(self):
        submitted = events_by_type(self.case_file, "advocate.case_submitted")
        self.assertEqual({event["from"] for event in submitted}, {"rider_advocate", "driver_advocate"})
        self.assertEqual({event["to"] for event in submitted}, {"judge"})

    def test_artifacts_are_on_disk(self):
        case_path = self.case_file.write(self.run_dir)
        self.assertTrue(case_path.exists())
        self.assertTrue((self.run_dir / "events.jsonl").exists())
        self.assertTrue(list((self.run_dir / "payloads").glob("*.json")))
        written = json.loads(case_path.read_text(encoding="utf-8"))
        self.assertEqual(written["dispute_id"], "RD-0001")

    def test_every_event_payload_ref_resolves(self):
        log = EventLog(self.run_dir, "test-run")
        for raw in EventLog.read_events(self.run_dir):
            if raw["payload_ref"]:
                self.assertTrue((self.run_dir / raw["payload_ref"]).exists())


class NoShowRunTest(PipelineTestCase):
    def test_no_show_case_runs_end_to_end(self):
        case_file = run_fixture(NO_SHOW, self.run_dir)
        self.assertEqual(case_file.category, "no_show_charge")
        self.assertEqual(case_file.resolution["outcome"], "ruled")
        self.assertEqual(case_file.evidence_pack["cancellation"]["driver_wait_minutes"], 6.5)
        self.assertEqual(case_file.evidence_pack["cancellation"]["driver_distance_from_pickup_m"], 650.7)


class ConfidenceGateTest(PipelineTestCase):
    def test_below_the_threshold_the_judge_does_not_rule(self):
        case_file = run_fixture(
            ROUTE_DEVIATION, self.run_dir, llm=MockLLMClient(judge_confidence=0.4), threshold=0.65
        )
        resolution = case_file.resolution
        self.assertEqual(resolution["outcome"], "withheld")
        self.assertIsNone(resolution["ruling"])
        self.assertEqual(resolution["party_message"], UNDER_REVIEW_MESSAGE)
        self.assertTrue(resolution["escalated_for_human_review"])

    def test_the_withheld_candidate_is_kept_for_the_human_reviewer(self):
        case_file = run_fixture(
            ROUTE_DEVIATION, self.run_dir, llm=MockLLMClient(judge_confidence=0.4), threshold=0.65
        )
        candidate = case_file.resolution["withheld_candidate"]
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate["confidence"], 0.4)
        self.assertEqual(candidate["action"], "refund")

    def test_the_parties_are_told_nothing_about_the_case_when_it_is_withheld(self):
        case_file = run_fixture(
            ROUTE_DEVIATION, self.run_dir, llm=MockLLMClient(judge_confidence=0.4), threshold=0.65
        )
        message = case_file.resolution["party_message"].lower()
        for forbidden in ("ai", "model", "agent", "confidence", "refund", "compensation", "no action"):
            self.assertNotIn(forbidden, message)

    def test_the_withholding_is_visible_in_the_event_stream(self):
        case_file = run_fixture(
            ROUTE_DEVIATION, self.run_dir, llm=MockLLMClient(judge_confidence=0.4), threshold=0.65
        )
        withheld = events_by_type(case_file, "judge.ruling_withheld")
        self.assertEqual(len(withheld), 1)
        self.assertEqual(withheld[0]["from"], "judge")
        self.assertEqual(withheld[0]["to"], "parties")
        self.assertNotIn("judge.ruling_issued", event_types(case_file))

    def test_confidence_exactly_at_the_threshold_rules(self):
        case_file = run_fixture(
            ROUTE_DEVIATION, self.run_dir, llm=MockLLMClient(judge_confidence=0.65), threshold=0.65
        )
        self.assertEqual(case_file.resolution["outcome"], "ruled")

    def test_the_threshold_comes_from_the_caller_not_the_code(self):
        strict = run_fixture(
            ROUTE_DEVIATION, self.run_dir / "strict", llm=MockLLMClient(judge_confidence=0.8), threshold=0.9
        )
        loose = run_fixture(
            ROUTE_DEVIATION, self.run_dir / "loose", llm=MockLLMClient(judge_confidence=0.8), threshold=0.5
        )
        self.assertEqual(strict.resolution["outcome"], "withheld")
        self.assertEqual(loose.resolution["outcome"], "ruled")


class CategoryRoutingTest(PipelineTestCase):
    def test_a_category_outside_the_locked_two_goes_to_human_review(self):
        case_file = run_fixture(OUT_OF_SCOPE, self.run_dir)
        self.assertEqual(case_file.category, "other")
        self.assertEqual(case_file.resolution["outcome"], "human_review")
        self.assertEqual(case_file.resolution["party_message"], HUMAN_REVIEW_MESSAGE)
        self.assertIsNone(case_file.resolution["ruling"])

    def test_no_agent_is_involved_for_a_human_review_case(self):
        llm = MockLLMClient()
        case_file = run_fixture(OUT_OF_SCOPE, self.run_dir, llm=llm)
        self.assertEqual(llm.calls, [])
        self.assertEqual(
            event_types(case_file),
            [
                "run.started",
                "dispute.filed",
                "dispute.routed_to_human_review",
                "party.notified",
                "run.completed",
            ],
        )
        self.assertIsNone(case_file.evidence_pack)


class CitationCheckingTest(PipelineTestCase):
    def test_an_invented_evidence_reference_is_recorded_not_dropped(self):
        llm = ScriptedLLM(
            {
                "rider_advocate": dict(RIDER_CASE, evidence_cited=["fare.made_up_field"], policy_rule_ids=["XX-9"]),
                "driver_advocate": DRIVER_CASE,
                "judge": {
                    "action": "refund",
                    "recommended_amount_sgd": 4.87,
                    "confidence": 0.8,
                    "explanation": "RD-1 applies.",
                    "cited_rule_ids": ["RD-1"],
                },
            }
        )
        case_file = run_fixture(ROUTE_DEVIATION, self.run_dir, llm=llm)
        validation = case_file.rider_case["validation"]
        self.assertEqual(validation["unknown_evidence_refs"], ["fare.made_up_field"])
        self.assertEqual(validation["unknown_rule_ids"], ["XX-9"])
        # The model's own claim is kept as well as the finding against it.
        self.assertEqual(case_file.rider_case["evidence_cited"], ["fare.made_up_field"])

    def test_a_judge_citing_an_invented_rule_is_recorded(self):
        llm = ScriptedLLM(
            {
                "rider_advocate": RIDER_CASE,
                "driver_advocate": DRIVER_CASE,
                "judge": {
                    "action": "refund",
                    "recommended_amount_sgd": 4.87,
                    "confidence": 0.8,
                    "explanation": "Ruling on RD-99.",
                    "cited_rule_ids": ["RD-99"],
                },
            }
        )
        case_file = run_fixture(ROUTE_DEVIATION, self.run_dir, llm=llm)
        self.assertEqual(case_file.resolution["ruling"]["validation"]["unknown_rule_ids"], ["RD-99"])


class ContractFailureTest(PipelineTestCase):
    def test_an_out_of_range_confidence_stops_the_run(self):
        llm = ScriptedLLM(
            {
                "rider_advocate": RIDER_CASE,
                "driver_advocate": DRIVER_CASE,
                "judge": {
                    "action": "refund",
                    "recommended_amount_sgd": 4.87,
                    "confidence": 1.5,
                    "explanation": "Confidence out of range.",
                    "cited_rule_ids": ["RD-1"],
                },
            }
        )
        with self.assertRaises(AgentError):
            run_fixture(ROUTE_DEVIATION, self.run_dir, llm=llm)

    def test_an_invalid_action_stops_the_run(self):
        llm = ScriptedLLM(
            {
                "rider_advocate": RIDER_CASE,
                "driver_advocate": DRIVER_CASE,
                "judge": {
                    "action": "partial refund",
                    "recommended_amount_sgd": 2.0,
                    "confidence": 0.9,
                    "explanation": "Not a valid action.",
                    "cited_rule_ids": ["RD-1"],
                },
            }
        )
        with self.assertRaises(AgentError):
            run_fixture(ROUTE_DEVIATION, self.run_dir, llm=llm)

    def test_a_non_json_response_stops_the_run(self):
        llm = ScriptedLLM(
            {
                "rider_advocate": "I think the rider is right.",
                "driver_advocate": DRIVER_CASE,
                "judge": RIDER_CASE,
            }
        )
        with self.assertRaises(AgentError):
            run_fixture(ROUTE_DEVIATION, self.run_dir, llm=llm)

    def test_the_event_log_survives_a_failed_run(self):
        llm = ScriptedLLM({"rider_advocate": RIDER_CASE, "driver_advocate": DRIVER_CASE})
        with self.assertRaises(AgentError):
            run_fixture(ROUTE_DEVIATION, self.run_dir, llm=llm)
        self.assertTrue((self.run_dir / "events.jsonl").exists())
        self.assertGreaterEqual(len(EventLog.read_events(self.run_dir)), 4)


class PartySpectatorTest(PipelineTestCase):
    def test_only_the_filing_of_the_dispute_comes_from_a_party(self):
        case_file = run_fixture(ROUTE_DEVIATION, self.run_dir)
        from_parties = [event for event in case_file.events if event["from"] in ("rider", "driver")]
        self.assertEqual([event["type"] for event in from_parties], ["dispute.filed"])

    def test_no_event_is_addressed_to_an_agent_from_a_party(self):
        case_file = run_fixture(NO_SHOW, self.run_dir)
        agents = {"rider_advocate", "driver_advocate", "judge"}
        for event in case_file.events:
            if event["to"] in agents:
                self.assertNotIn(event["from"], ("rider", "driver"))


class AgentPromptTest(PipelineTestCase):
    def test_the_hard_rules_reach_the_model(self):
        llm = MockLLMClient()
        run_fixture(ROUTE_DEVIATION, self.run_dir, llm=llm)
        for request in llm.calls:
            self.assertIn("Never do arithmetic", request.system_prompt)
            self.assertIn("CITABLE EVIDENCE REFS", request.user_prompt)
            self.assertIn("POLICY RULE IDS", request.user_prompt)

    def test_each_agent_sees_only_what_it_should(self):
        llm = MockLLMClient()
        run_fixture(ROUTE_DEVIATION, self.run_dir, llm=llm)
        by_agent = {request.agent: request for request in llm.calls}

        # An advocate sees the evidence pack and the policy, but not the other advocate's case.
        self.assertNotIn("DRIVER ADVOCATE CASE", by_agent["rider_advocate"].user_prompt)
        self.assertIn("EVIDENCE PACK", by_agent["rider_advocate"].user_prompt)

        # The judge sees both cases.
        judge_prompt = by_agent["judge"].user_prompt
        self.assertIn("RIDER ADVOCATE CASE", judge_prompt)
        self.assertIn("DRIVER ADVOCATE CASE", judge_prompt)

    def test_the_mock_only_ever_cites_refs_that_resolve(self):
        case_file = run_fixture(ROUTE_DEVIATION, self.run_dir)
        for case in (case_file.rider_case, case_file.driver_case):
            self.assertEqual(case["validation"]["unknown_evidence_refs"], [])
            self.assertEqual(case["validation"]["unknown_rule_ids"], [])


if __name__ == "__main__":
    unittest.main()
