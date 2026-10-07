"""Session A acceptance target (W22): the two money gates ruled in the 2026-10-01 grill.

Written BEFORE the build, so it is RED until the CodeBuddy lane ships
docs/build-briefs/session-nineteen-brief.md. Both gates live in app/agents/judge.py beside the
confidence, ESC-4 and ESC-2 gates. Both WITHHOLD; neither ever rewrites a ruling.

NS-6 (grill Q11, Q11b-d): a contested no-show (driver marked a no-show, rider says the
driver was absent) with NO recorded driver position at arrival. The fee has no GPS proof,
so the ruling must be a refund of exactly the fee. Automatic only when the fee is at most
SGD 10, the rider's fraud flags are recorded and zero, and no more than half the rider's
past disputes were rejected (rejected = total - upheld). Otherwise always withheld.

RD-5 (grill Q12, Q12b, Q12c): on a route-deviation case where fare.difference_sgd proves
an overcharge of at least the de minimis SGD 1.00, a ruling that refunds less (or
nothing) is withheld.
"""

from __future__ import annotations

import dataclasses
import json
import tempfile
import unittest
from pathlib import Path

from app.dispute import load_dispute
from app.events import EventLog
from app.evidence import build_evidence_pack
from app.llm.mock import MockLLMClient
from app.pipeline import run_dispute
from app.policy import load_policy
from app.schemas import OUTCOME_RULED, OUTCOME_WITHHELD, UNDER_REVIEW_MESSAGE, AdvocateCase

from tests.support import ScriptedLLM

REPO = Path(__file__).resolve().parent.parent
PACKS = REPO / "data" / "packs"
SYNTH = PACKS / "ryde-synth-v1" / "disputes"
ORGANISER = PACKS / "organiser-style-v1" / "disputes"
POLICY = REPO / "docs" / "policy.md"


def _judge_module():
    import app.agents.judge as judge  # lazy, so each test is RED on its own

    return judge


def _advocate(party: str) -> AdvocateCase:
    return AdvocateCase(
        party=party,
        agent="%s_advocate" % party,
        claim_summary="stand-in",
        argument="stand-in",
        requested_outcome="no action",
        requested_amount_sgd=0.0,
    )


def _ruling(action: str, amount: float, confidence: float = 0.9, rules=("NS-6", "GEN-3"),
            refs=("cancellation.cancellation_fee_sgd",)):
    return {
        "action": action,
        "recommended_amount_sgd": amount,
        "confidence": confidence,
        "explanation": "stand-in",
        "cited_rule_ids": list(rules),
        "cited_evidence_refs": list(refs),
    }


def _replace_cancellation(pack, **changes):
    return dataclasses.replace(pack, cancellation=dataclasses.replace(pack.cancellation, **changes))


def _replace_rider(pack, **changes):
    rider = dataclasses.replace(pack.profiles.rider, **changes)
    return dataclasses.replace(pack, profiles=dataclasses.replace(pack.profiles, rider=rider))


def _replace_fare(pack, **changes):
    return dataclasses.replace(pack, fare=dataclasses.replace(pack.fare, **changes))


class _JudgeHarness(unittest.TestCase):
    """Runs the real Judge on a real (optionally edited) pack with a scripted ruling."""

    record = SYNTH / "NS-0205.json"

    def setUp(self):
        self.dispute = load_dispute(self.record)
        self.pack = build_evidence_pack(self.dispute)
        self.policy = load_policy(POLICY)

    def judge(self, ruling, pack=None, threshold=0.65, cap=50.0):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(__import__("shutil").rmtree, tmp, True)
        events = EventLog(tmp / "run", "w22-gate")
        judge = _judge_module().Judge(llm=ScriptedLLM({"judge": ruling}), events=events, policy=self.policy)
        resolution = judge.run(
            self.dispute,
            pack if pack is not None else self.pack,
            _advocate("rider"),
            _advocate("driver"),
            confidence_threshold=threshold,
            autonomous_cap_sgd=cap,
        )
        withheld = [e for e in events.events() if e.type == "judge.ruling_withheld"]
        gates = events.read_payload(withheld[0])["gates_failed"] if withheld else []
        return resolution, gates

    def assertRuled(self, resolution, gates):
        self.assertEqual(OUTCOME_RULED, resolution.outcome, gates)
        self.assertEqual([], gates)
        self.assertIsNotNone(resolution.ruling)

    def assertWithheldBy(self, resolution, gates, expected_gates, candidate_amount):
        self.assertEqual(OUTCOME_WITHHELD, resolution.outcome)
        self.assertEqual(expected_gates, gates)
        self.assertIsNone(resolution.ruling)
        self.assertEqual(UNDER_REVIEW_MESSAGE, resolution.party_message)
        self.assertTrue(resolution.escalated_for_human_review)
        # Never rewritten: the human receives exactly what the Judge proposed.
        self.assertEqual(candidate_amount, resolution.withheld_candidate.recommended_amount_sgd)


# ------------------------------------------------------------------ NS-6


class ContestedNoShowGate(_JudgeHarness):
    def test_the_real_case_meets_the_preconditions(self):
        c = self.pack.cancellation
        self.assertEqual((True, True, None, 6.61),
                         (c.driver_marked_no_show, c.rider_claims_driver_absent,
                          c.driver_distance_from_pickup_m, c.cancellation_fee_sgd))
        r = self.pack.profiles.rider
        self.assertEqual((0, 2, 1), (r.fraud_flags, r.disputes_total, r.disputes_upheld))

    def test_full_refund_of_the_fee_is_issued(self):
        self.assertRuled(*self.judge(_ruling("refund", 6.61)))

    def test_no_action_is_withheld(self):
        res, gates = self.judge(_ruling("no action", 0.0))
        self.assertWithheldBy(res, gates, ["NS-6"], 0.0)

    def test_compensation_is_withheld(self):
        res, gates = self.judge(_ruling("compensation", 6.61))
        self.assertWithheldBy(res, gates, ["NS-6", "NS-8"], 6.61)

    def test_a_partial_refund_is_withheld(self):
        res, gates = self.judge(_ruling("refund", 6.60))
        self.assertWithheldBy(res, gates, ["NS-6"], 6.60)

    def test_a_refund_above_the_fee_is_withheld(self):
        res, gates = self.judge(_ruling("refund", 6.62))
        self.assertWithheldBy(res, gates, ["NS-6", "NS-8"], 6.62)

    def test_the_fee_is_compared_to_the_cent(self):
        self.assertRuled(*self.judge(_ruling("refund", 6.614)))
        # The pack side is rounded too: an unrounded fee still matches its cent value.
        pack = _replace_cancellation(self.pack, cancellation_fee_sgd=6.6149)
        self.assertRuled(*self.judge(_ruling("refund", 6.61), pack=pack))

    def test_a_fee_of_exactly_ten_is_still_automatic(self):
        pack = _replace_cancellation(self.pack, cancellation_fee_sgd=10.0)
        self.assertRuled(*self.judge(_ruling("refund", 10.0), pack=pack))

    def test_a_fee_above_ten_is_withheld_even_for_a_full_refund(self):
        pack = _replace_cancellation(self.pack, cancellation_fee_sgd=10.01)
        res, gates = self.judge(_ruling("refund", 10.01), pack=pack)
        self.assertWithheldBy(res, gates, ["NS-6"], 10.01)

    def test_an_unrecorded_fee_is_withheld(self):
        pack = _replace_cancellation(self.pack, cancellation_fee_sgd=None)
        res, gates = self.judge(_ruling("refund", 6.61), pack=pack)
        self.assertWithheldBy(res, gates, ["NS-6", "NS-8"], 6.61)

    def test_fraud_flags_other_than_a_recorded_zero_are_withheld(self):
        for flags in (1, 3, None):
            with self.subTest(fraud_flags=flags):
                pack = _replace_rider(self.pack, fraud_flags=flags)
                res, gates = self.judge(_ruling("refund", 6.61), pack=pack)
                self.assertWithheldBy(res, gates, ["NS-6"], 6.61)

    def test_exactly_half_rejected_is_automatic(self):
        for total, upheld in ((2, 1), (4, 2), (0, 0)):
            with self.subTest(total=total, upheld=upheld):
                pack = _replace_rider(self.pack, disputes_total=total, disputes_upheld=upheld)
                self.assertRuled(*self.judge(_ruling("refund", 6.61), pack=pack))

    def test_more_than_half_rejected_is_withheld(self):
        for total, upheld in ((3, 1), (2, 0), (5, 2), (1, 0)):
            with self.subTest(total=total, upheld=upheld):
                pack = _replace_rider(self.pack, disputes_total=total, disputes_upheld=upheld)
                res, gates = self.judge(_ruling("refund", 6.61), pack=pack)
                self.assertWithheldBy(res, gates, ["NS-6"], 6.61)

    def test_a_missing_or_impossible_dispute_history_is_withheld(self):
        for total, upheld in ((None, 1), (2, None), (None, None), (1, 2), (-1, 0)):
            with self.subTest(total=total, upheld=upheld):
                pack = _replace_rider(self.pack, disputes_total=total, disputes_upheld=upheld)
                res, gates = self.judge(_ruling("refund", 6.61), pack=pack)
                self.assertWithheldBy(res, gates, ["NS-6"], 6.61)

    def test_a_missing_rider_profile_is_withheld(self):
        pack = dataclasses.replace(self.pack, profiles=dataclasses.replace(self.pack.profiles, rider=None))
        res, gates = self.judge(_ruling("refund", 6.61), pack=pack)
        self.assertWithheldBy(res, gates, ["NS-6"], 6.61)
        pack = dataclasses.replace(self.pack, profiles=None)
        res, gates = self.judge(_ruling("refund", 6.61), pack=pack)
        self.assertWithheldBy(res, gates, ["NS-6"], 6.61)

    def test_an_ineligible_case_is_withheld_whatever_the_ruling(self):
        pack = _replace_rider(self.pack, fraud_flags=1)
        for ruling in (_ruling("refund", 6.61), _ruling("no action", 0.0), _ruling("refund", 3.0)):
            with self.subTest(ruling=ruling["action"], amount=ruling["recommended_amount_sgd"]):
                res, gates = self.judge(ruling, pack=pack)
                self.assertWithheldBy(res, gates, ["NS-6"], ruling["recommended_amount_sgd"])


class ContestedNoShowScope(_JudgeHarness):
    """The gate fires ONLY on the contested, unrecorded-position shape."""

    def test_a_recorded_position_leaves_the_ruling_to_ns3(self):
        for distance in (18.1, 884.9, 0.0):
            with self.subTest(distance=distance):
                pack = _replace_cancellation(self.pack, driver_distance_from_pickup_m=distance)
                self.assertRuled(*self.judge(_ruling("no action", 0.0), pack=pack))

    def test_an_uncontested_shape_is_not_gated(self):
        for marked, absent in ((False, True), (True, False), (None, True), (True, None)):
            with self.subTest(marked=marked, absent=absent):
                pack = _replace_cancellation(
                    self.pack, driver_marked_no_show=marked, rider_claims_driver_absent=absent
                )
                self.assertRuled(*self.judge(_ruling("no action", 0.0), pack=pack))

    def test_a_route_case_is_never_gated_by_ns6(self):
        # A real route-deviation pack (RD-0101) carrying the contested no-show shape grafted
        # in: NS-6 keys on the dispute's category and must stay out of route cases.
        route = load_dispute(SYNTH / "RD-0101.json")
        pack = dataclasses.replace(build_evidence_pack(route), cancellation=self.pack.cancellation,
                                   profiles=self.pack.profiles)
        self.assertIsNone(pack.cancellation.driver_distance_from_pickup_m)
        self.dispute = route
        self.assertRuled(*self.judge(_ruling("refund", 5.81), pack=pack))
        # The same grafted pack under the no-show category IS gated: the graft is live.
        self.dispute = load_dispute(SYNTH / "NS-0205.json")
        res, gates = self.judge(_ruling("refund", 5.81), pack=pack)
        self.assertEqual(["NS-6"], gates)

    def test_the_corpus_no_show_cases_outside_the_shape_are_unchanged(self):
        # NS-0201 (18 m, earned) and NS-0204 (never arrived, not marked) rule as before.
        for name, ruling in (("NS-0201.json", _ruling("no action", 0.0)),
                             ("NS-0204.json", _ruling("refund", 6.61))):
            with self.subTest(case=name):
                dispute = load_dispute(SYNTH / name)
                self.dispute = dispute
                self.assertRuled(*self.judge(ruling, pack=build_evidence_pack(dispute)))

    def test_the_eligibility_helper_is_public_and_pure(self):
        eligible = _judge_module().ns6_auto_refund_eligible
        self.assertTrue(eligible(self.pack))
        self.assertFalse(eligible(_replace_rider(self.pack, fraud_flags=None)))
        self.assertEqual(10.00, _judge_module().CONTESTED_NO_SHOW_AUTO_LIMIT_SGD)

    def test_the_eligibility_helper_refuses_a_fee_that_is_missing_or_not_positive(self):
        # The gate also checks the fee before accepting a full refund, so a helper that
        # called an unrecorded fee eligible would stay hidden behind it. Pin the helper.
        eligible = _judge_module().ns6_auto_refund_eligible
        for fee in (None, 0, 0.0, -6.61, True):
            with self.subTest(fee=fee):
                self.assertFalse(eligible(_replace_cancellation(self.pack, cancellation_fee_sgd=fee)))
        self.assertTrue(eligible(_replace_cancellation(self.pack, cancellation_fee_sgd=0.01)))


# ------------------------------------------------------------------ RD-5


class ProvenOverchargeGate(_JudgeHarness):
    record = SYNTH / "RD-0106.json"

    def _rd(self, action, amount, confidence=0.9):
        return _ruling(action, amount, confidence, rules=("EV-3", "RD-5"), refs=("fare.difference_sgd",))

    def test_the_real_case_proves_an_overcharge(self):
        self.assertEqual(3.40, self.pack.fare.difference_sgd)

    def test_refunding_the_proven_overcharge_is_issued(self):
        self.assertRuled(*self.judge(self._rd("refund", 3.40)))

    def test_refunding_more_than_the_overcharge_is_withheld_by_rd4(self):
        # Q12 still holds (pay the proven overcharge even above the claim), but since W28
        # (the operator 2026-10-02, option A) a refund ABOVE what the records prove is held by RD-4,
        # not by RD-5. RD-5 itself still only polices the short side.
        res, gates = self.judge(self._rd("refund", 5.00))
        self.assertWithheldBy(res, gates, ["RD-4"], 5.00)

    def test_refunding_less_is_withheld(self):
        for amount in (0.66, 3.39, 1.00):
            with self.subTest(amount=amount):
                res, gates = self.judge(self._rd("refund", amount))
                self.assertWithheldBy(res, gates, ["RD-5"], amount)

    def test_no_action_and_compensation_are_withheld(self):
        res, gates = self.judge(self._rd("no action", 0.0))
        self.assertWithheldBy(res, gates, ["RD-5"], 0.0)
        # Since W28 (2026-10-02) compensation on a route case is also held by RD-4, after RD-5.
        res, gates = self.judge(self._rd("compensation", 3.40))
        self.assertWithheldBy(res, gates, ["RD-5", "RD-4"], 3.40)

    def test_compared_to_the_cent(self):
        self.assertRuled(*self.judge(self._rd("refund", 3.396)))
        # The pack side is rounded too: 3.4049 is a 3.40 overcharge, and 3.40 covers it.
        pack = _replace_fare(self.pack, difference_sgd=3.4049)
        self.assertRuled(*self.judge(self._rd("refund", 3.40), pack=pack))

    def test_the_de_minimis_floor(self):
        # Q12c: the gate fires at >= SGD 1.00, so code and GEN-4 agree.
        pack = _replace_fare(self.pack, difference_sgd=1.00)
        res, gates = self.judge(self._rd("no action", 0.0), pack=pack)
        self.assertWithheldBy(res, gates, ["RD-5"], 0.0)
        for difference in (0.99, 0.40, 0.0, -5.56, None):
            with self.subTest(difference=difference):
                pack = _replace_fare(self.pack, difference_sgd=difference)
                self.assertRuled(*self.judge(self._rd("no action", 0.0), pack=pack))

    def test_a_missing_fare_block_is_held_by_esc2_not_rd5(self):
        # Superseded 2026-10-01 (session twenty): a route case whose fare block is
        # missing has no provable charged fare, which EV-1 sends to ESC-2. RD-5 still
        # does not fire: there is no overcharge figure for it to read.
        pack = dataclasses.replace(self.pack, fare=None)
        res, gates = self.judge(self._rd("no action", 0.0), pack=pack)
        self.assertWithheldBy(res, gates, ["ESC-2"], 0.0)

    def test_route_cases_only(self):
        # A no-show dispute judged against a pack that DOES prove an overcharge: the
        # RD-5 gate keys on the dispute's category and must not reach outside route cases.
        overcharge_pack = self.pack
        self.assertEqual(3.40, overcharge_pack.fare.difference_sgd)
        self.dispute = load_dispute(SYNTH / "NS-0201.json")
        self.assertRuled(*self.judge(_ruling("no action", 0.0), pack=overcharge_pack))

    def test_de_minimis_constant(self):
        self.assertEqual(1.00, _judge_module().DE_MINIMIS_SGD)


class GateOrder(_JudgeHarness):
    """gates_failed keeps the existing order and appends NS-6, then RD-5."""

    def test_confidence_before_ns6(self):
        res, gates = self.judge(_ruling("no action", 0.0, confidence=0.3))
        self.assertWithheldBy(res, gates, ["confidence", "NS-6"], 0.0)

    def test_confidence_before_rd5(self):
        self.dispute = load_dispute(SYNTH / "RD-0106.json")
        pack = build_evidence_pack(self.dispute)
        res, gates = self.judge(_ruling("refund", 2.0, confidence=0.3, rules=("RD-5",),
                                        refs=("fare.difference_sgd",)), pack=pack)
        self.assertWithheldBy(res, gates, ["confidence", "RD-5"], 2.0)

    def test_esc4_before_ns6(self):
        pack = _replace_rider(self.pack, fraud_flags=1)
        res, gates = self.judge(_ruling("refund", 60.0), pack=pack)
        self.assertWithheldBy(res, gates, ["ESC-4", "NS-6", "NS-8"], 60.0)

    def _summary(self, dispute, pack, ruling):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(__import__("shutil").rmtree, tmp, True)
        events = EventLog(tmp / "run", "w22-summary")
        judge = _judge_module().Judge(llm=ScriptedLLM({"judge": ruling}), events=events,
                                      policy=self.policy)
        judge.run(dispute, pack, _advocate("rider"), _advocate("driver"),
                  confidence_threshold=0.65, autonomous_cap_sgd=50.0)
        return next(e for e in events.events() if e.type == "judge.ruling_withheld").summary

    def test_every_new_withheld_summary_names_its_gate_and_no_figure(self):
        rd = load_dispute(SYNTH / "RD-0106.json")
        cases = (
            ("NS-6 eligible, short ruling", self.dispute, self.pack, _ruling("no action", 0.0), "NS-6"),
            ("NS-6 ineligible", self.dispute, _replace_rider(self.pack, fraud_flags=1),
             _ruling("refund", 6.61), "NS-6"),
            ("RD-5 short refund", rd, build_evidence_pack(rd), _ruling("refund", 0.66), "RD-5"),
        )
        for name, dispute, pack, ruling, gate in cases:
            with self.subTest(case=name):
                summary = self._summary(dispute, pack, ruling)
                self.assertIn(gate, summary)
                for figure in ("SGD", "6.61", "3.40", "0.66", "10.00"):
                    self.assertNotIn(figure, summary)


# --------------------------------------------------------- end to end on the mock


class EndToEnd(unittest.TestCase):
    def _run(self, path):
        with tempfile.TemporaryDirectory() as tmp:
            return run_dispute(
                dispute=load_dispute(path),
                llm=MockLLMClient(),
                policy=load_policy(POLICY),
                events=EventLog(Path(tmp) / "run", "w22-e2e"),
                confidence_threshold=0.65,
                autonomous_cap_sgd=50.0,
            ).to_dict()

    def test_ns0205_is_refunded_in_both_packs(self):
        for path in (SYNTH / "NS-0205.json", ORGANISER / "NS-0205.json"):
            with self.subTest(pack=path.parent.parent.name):
                resolution = self._run(path)["resolution"]
                self.assertEqual(("ruled", "refund", 6.61),
                                 (resolution["outcome"], resolution["ruling"]["action"],
                                  resolution["ruling"]["recommended_amount_sgd"]))

    def test_rd0106_short_refund_is_held_for_a_human_in_both_packs(self):
        # The mock refunds the claimed 0.66; the records prove 3.40.
        for path in (SYNTH / "RD-0106.json", ORGANISER / "RD-0106.json"):
            with self.subTest(pack=path.parent.parent.name):
                data = self._run(path)
                resolution = data["resolution"]
                self.assertEqual("withheld", resolution["outcome"])
                self.assertIsNone(resolution["ruling"])
                self.assertEqual(0.66, resolution["withheld_candidate"]["recommended_amount_sgd"])
                self.assertEqual(UNDER_REVIEW_MESSAGE, resolution["party_message"])
                withheld = [e for e in data["events"] if e["type"] == "judge.ruling_withheld"]
                self.assertEqual(1, len(withheld))
                self.assertIn("RD-5", withheld[0]["summary"])


if __name__ == "__main__":
    unittest.main()
