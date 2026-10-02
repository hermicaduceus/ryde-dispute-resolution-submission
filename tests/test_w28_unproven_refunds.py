"""W28 acceptance target: a route refund may never be more than the records prove.

Written BEFORE the build, so it is RED until the CodeBuddy lane ships
docs/session-twenty-one-brief.md.

Found by the live eval of 2026-10-02 (real Tencent ADP model, build 3cbbda2): two route
cases paid the rider money the policy says is not owed, and no code gate stopped either.

- RD-0105: refund 5.56 at confidence 0.95. The rider paid the quoted fare exactly
  (charged 14.21 == quoted 14.21), so RD-4 says no action. The model read
  deviation_fare_delta_sgd (what the detour WOULD have cost on a metered fare).
- RD-0107: refund 4.91 at confidence 0.85, citing RD-5. difference_sgd is 0.00 and the
  breakdown is consistent; the deviation is 0.2 km / 2.8%, below RD-1. RD-6 applies.

Rulings (the operator, 2026-10-02):
- Option A: one gate, both directions. A route REFUND above what the records prove the
  rider overpaid is withheld for a human, whether the proof is zero or merely smaller.
- Hold: a record with no tariff rates proves no detour overcharge, so a detour refund on it
  is held (this supersedes the 10-01 "absent input stays with the model" for refunds only).
  A refund the BREAKDOWN itself proves (EV-3: line items add up to less than the charge)
  still goes out without rates. "No action" is never held by this gate.

What the records prove (app/agents/judge.py, provable_refund_sgd), the max of, never < 0:
  1. fare.difference_sgd                                  (RD-5, pricing error)
  2. charged - component_sum, when breakdown_consistent is False   (EV-3 / RD-5)
  3. charged - recomputed_estimated_route_sgd, when RD-1 says the deviation is material
                                                          (RD-3 / RD-4, the quoted fare)
rounded to the cent. A missing or unreadable figure contributes nothing.

The gate is labelled RD-4 in gates_failed. Compensation (money to the driver) on a route
case is always held: a route record proves nothing owed to the driver. It is skipped when
ESC-2 already holds the case or difference_sgd is present but unreadable (the RD-5
unreadable branch), so one record defect reads as one reason.
"""

from __future__ import annotations

import copy
import dataclasses
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path

from app.dispute import load_dispute, parse_dispute
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
README = REPO / "README.md"
ARCH = REPO / "docs" / "architecture.md"
MERMAID = re.compile(r"```mermaid\n(.*?)```", re.DOTALL)


def _judge_module():
    import app.agents.judge as judge  # lazy, so each test is RED on its own

    return judge


def _record(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _without_rates(record: dict) -> dict:
    out = copy.deepcopy(record)
    del out["trip"]["fare"]["rates"]
    return out


def _pack_of(record: dict):
    return build_evidence_pack(parse_dispute(record), generated_at="2026-10-02T00:00:00+00:00")


def _advocate(party: str) -> AdvocateCase:
    return AdvocateCase(
        party=party,
        agent="%s_advocate" % party,
        claim_summary="stand-in",
        argument="stand-in",
        requested_outcome="no action",
        requested_amount_sgd=0.0,
    )


def _ruling(action: str, amount: float, confidence: float = 0.9):
    return {
        "action": action,
        "recommended_amount_sgd": amount,
        "confidence": confidence,
        "explanation": "stand-in",
        "cited_rule_ids": ["RD-1", "RD-3"],
        "cited_evidence_refs": ["route.deviation_km"],
    }


def _replace(pack, block: str, **changes):
    return dataclasses.replace(pack, **{block: dataclasses.replace(getattr(pack, block), **changes)})


class _Harness(unittest.TestCase):
    """Runs the real Judge on a real (optionally edited) pack with a scripted ruling."""

    record = SYNTH / "RD-0101.json"

    def setUp(self):
        self.dispute = load_dispute(self.record)
        self.pack = build_evidence_pack(self.dispute)
        self.policy = load_policy(POLICY)

    def judge(self, ruling, pack=None, dispute=None, threshold=0.65, cap=50.0):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        events = EventLog(tmp / "run", "w28-gate")
        judge = _judge_module().Judge(llm=ScriptedLLM({"judge": ruling}), events=events,
                                      policy=self.policy)
        resolution = judge.run(
            dispute if dispute is not None else self.dispute,
            pack if pack is not None else self.pack,
            _advocate("rider"),
            _advocate("driver"),
            confidence_threshold=threshold,
            autonomous_cap_sgd=cap,
        )
        withheld = [e for e in events.events() if e.type == "judge.ruling_withheld"]
        gates = events.read_payload(withheld[0])["gates_failed"] if withheld else []
        summary = withheld[0].summary if withheld else None
        return resolution, gates, summary

    def assertRuled(self, resolution, gates, _summary=None):
        self.assertEqual(OUTCOME_RULED, resolution.outcome, gates)
        self.assertEqual([], gates)
        self.assertIsNotNone(resolution.ruling)

    def assertHeld(self, resolution, gates, expected_gates, candidate_amount):
        self.assertEqual(OUTCOME_WITHHELD, resolution.outcome)
        self.assertEqual(expected_gates, gates)
        self.assertIsNone(resolution.ruling)
        self.assertEqual(UNDER_REVIEW_MESSAGE, resolution.party_message)
        self.assertTrue(resolution.escalated_for_human_review)
        # Never rewritten: the human receives exactly what the Judge proposed.
        self.assertEqual(candidate_amount, resolution.withheld_candidate.recommended_amount_sgd)


# ------------------------------------------------------------------ RD-1 helper


class DeviationIsMaterial(unittest.TestCase):
    """RD-1 in code: >= 20% AND >= 1.0 km, or >= 5.0 km whatever the percentage."""

    def setUp(self):
        self.pack = build_evidence_pack(load_dispute(SYNTH / "RD-0101.json"))

    def material(self, km, pct):
        return _judge_module().deviation_is_material(
            _replace(self.pack, "route", deviation_km=km, deviation_pct=pct))

    def test_constants(self):
        judge = _judge_module()
        self.assertEqual((20.0, 1.0, 5.0), (judge.MATERIAL_DEVIATION_PCT,
                                            judge.MATERIAL_DEVIATION_KM,
                                            judge.MATERIAL_DEVIATION_GROSS_KM))

    def test_first_limb_boundaries(self):
        self.assertTrue(self.material(1.0, 20.0))
        self.assertFalse(self.material(1.0, 19.99))
        self.assertFalse(self.material(0.99, 20.0))
        self.assertFalse(self.material(0.99, 19.99))

    def test_gross_limb_boundaries(self):
        self.assertTrue(self.material(5.0, 1.0))
        self.assertFalse(self.material(4.99, 1.0))

    def test_gross_limb_needs_no_percentage(self):
        self.assertTrue(self.material(6.5, None))
        self.assertTrue(self.material(6.5, float("nan")))

    def test_missing_figures_are_not_material(self):
        # pct=+inf is the value that separates "is a figure" from "is not None": NaN
        # already compares False, so only infinity would read as a material percentage.
        for km, pct in ((None, 50.0), (float("nan"), 50.0), (float("inf"), 50.0),
                        (True, 50.0), (3.2, None), (3.2, float("nan")), (3.2, float("inf")),
                        (3.2, True)):
            with self.subTest(km=km, pct=pct):
                self.assertFalse(self.material(km, pct))

    def test_no_route_block_is_not_material(self):
        self.assertFalse(_judge_module().deviation_is_material(
            dataclasses.replace(self.pack, route=None)))

    def test_every_corpus_route_case(self):
        expected = {"RD-0101": True, "RD-0102": True, "RD-0103": False, "RD-0104": True,
                    "RD-0105": True, "RD-0106": False, "RD-0107": False, "RD-0108": False,
                    "RD-0109": True}
        got = {cid: _judge_module().deviation_is_material(
            build_evidence_pack(load_dispute(SYNTH / ("%s.json" % cid)))) for cid in expected}
        self.assertEqual(expected, got)


# ------------------------------------------------------------------ what the records prove


class ProvableRefund(unittest.TestCase):
    def provable(self, pack):
        return _judge_module().provable_refund_sgd(pack)

    def test_every_corpus_route_case_on_both_packs(self):
        expected = {"RD-0101": 5.81, "RD-0102": 5.86, "RD-0103": 0.0, "RD-0104": 7.70,
                    "RD-0105": 0.0, "RD-0106": 3.40, "RD-0107": 0.0, "RD-0108": 0.0,
                    "RD-0109": 55.16}
        for folder in (SYNTH, ORGANISER):
            for cid, amount in expected.items():
                with self.subTest(pack=folder.parent.name, case=cid):
                    pack = build_evidence_pack(load_dispute(folder / ("%s.json" % cid)))
                    self.assertEqual(amount, self.provable(pack))

    def test_a_fixed_fare_paid_as_quoted_proves_nothing(self):
        # RD-0105: material deviation, charged == quoted; the delta is not money paid.
        pack = build_evidence_pack(load_dispute(SYNTH / "RD-0105.json"))
        self.assertEqual(5.56, pack.fare.deviation_fare_delta_sgd)
        self.assertEqual(pack.fare.charged_sgd, pack.fare.recomputed_estimated_route_sgd)
        self.assertEqual(0.0, self.provable(pack))

    def test_a_traffic_delay_proves_nothing(self):
        # RD-0107: immaterial deviation, consistent breakdown, zero difference.
        pack = build_evidence_pack(load_dispute(SYNTH / "RD-0107.json"))
        self.assertEqual(4.91, pack.fare.deviation_fare_delta_sgd)
        self.assertEqual(0.0, self.provable(pack))

    def test_the_largest_proof_wins(self):
        pack = build_evidence_pack(load_dispute(SYNTH / "RD-0101.json"))  # quote proof 5.81
        self.assertEqual(7.0, self.provable(_replace(pack, "fare", difference_sgd=7.0)))
        self.assertEqual(5.81, self.provable(_replace(pack, "fare", difference_sgd=2.0)))

    def test_a_charge_below_the_quote_proves_nothing(self):
        pack = build_evidence_pack(load_dispute(SYNTH / "RD-0101.json"))
        self.assertEqual(0.0, self.provable(_replace(pack, "fare", charged_sgd=10.0)))

    def test_a_negative_difference_proves_nothing(self):
        pack = build_evidence_pack(load_dispute(SYNTH / "RD-0103.json"))
        self.assertEqual(0.0, self.provable(_replace(pack, "fare", difference_sgd=-3.0)))

    def test_the_quote_proof_needs_a_material_deviation(self):
        pack = build_evidence_pack(load_dispute(SYNTH / "RD-0101.json"))
        immaterial = _replace(pack, "route", deviation_km=0.5, deviation_pct=7.0)
        self.assertEqual(0.0, self.provable(immaterial))

    def test_rounded_to_the_cent(self):
        # 18.6251 - 12.82 = 5.8051: the proof is 5.81, so a 5.81 refund must pass.
        pack = build_evidence_pack(load_dispute(SYNTH / "RD-0101.json"))
        self.assertEqual(5.81, self.provable(_replace(pack, "fare", charged_sgd=18.6251)))

    def test_missing_or_unreadable_figures_prove_nothing(self):
        pack = build_evidence_pack(load_dispute(SYNTH / "RD-0101.json"))
        # +inf on the charge and -inf on the quote are the values that separate "is a
        # figure" from "is not None": max() already absorbs NaN, and charged - inf floors to 0.
        for change in ({"charged_sgd": None}, {"recomputed_estimated_route_sgd": None},
                       {"charged_sgd": float("nan")}, {"charged_sgd": float("inf")},
                       {"recomputed_estimated_route_sgd": float("inf")},
                       {"recomputed_estimated_route_sgd": float("-inf")},
                       {"charged_sgd": True}):
            with self.subTest(change=change):
                self.assertEqual(0.0, self.provable(_replace(pack, "fare", **change)))
        self.assertEqual(0.0, self.provable(dataclasses.replace(pack, fare=None)))

    def test_an_unreadable_difference_contributes_nothing(self):
        pack = build_evidence_pack(load_dispute(SYNTH / "RD-0103.json"))
        for value in (float("nan"), float("inf"), True):
            with self.subTest(value=value):
                self.assertEqual(0.0, self.provable(_replace(pack, "fare", difference_sgd=value)))

    def test_no_rates_no_detour_proof(self):
        # the operator "Hold": without rates there is no quoted fare, so the detour proves nothing.
        pack = _pack_of(_without_rates(_record(SYNTH / "RD-0101.json")))
        self.assertIsNone(pack.fare.recomputed_estimated_route_sgd)
        self.assertEqual(0.0, self.provable(pack))

    def test_no_rates_the_breakdown_still_proves_an_overcharge(self):
        # EV-3: the line items add up to 15.76 against a 19.16 charge.
        pack = _pack_of(_without_rates(_record(SYNTH / "RD-0106.json")))
        self.assertIsNone(pack.fare.difference_sgd)
        self.assertIs(False, pack.fare.breakdown_consistent)
        self.assertEqual(3.40, self.provable(pack))

    def test_the_breakdown_proof_needs_an_inconsistent_breakdown(self):
        pack = _pack_of(_without_rates(_record(SYNTH / "RD-0106.json")))
        for flag in (True, None):
            with self.subTest(breakdown_consistent=flag):
                self.assertEqual(0.0, self.provable(
                    _replace(pack, "fare", breakdown_consistent=flag)))

    def test_the_breakdown_proof_needs_both_figures(self):
        pack = _pack_of(_without_rates(_record(SYNTH / "RD-0106.json")))
        for change in ({"component_sum_sgd": None}, {"component_sum_sgd": float("nan")},
                       {"component_sum_sgd": float("-inf")}, {"charged_sgd": None},
                       {"charged_sgd": float("inf")}):
            with self.subTest(change=change):
                self.assertEqual(0.0, self.provable(_replace(pack, "fare", **change)))


# ------------------------------------------------------------------ the gate


class TheTwoLiveMisses(_Harness):
    """The exact rulings the real model produced on 2026-10-02."""

    def test_rd0105_fixed_fare_refund_is_held(self):
        for folder in (SYNTH, ORGANISER):
            with self.subTest(pack=folder.parent.name):
                dispute = load_dispute(folder / "RD-0105.json")
                res, gates, _ = self.judge(_ruling("refund", 5.56, 0.95),
                                           pack=build_evidence_pack(dispute), dispute=dispute)
                self.assertHeld(res, gates, ["RD-4"], 5.56)

    def test_rd0107_traffic_delay_refund_is_held(self):
        for folder in (SYNTH, ORGANISER):
            with self.subTest(pack=folder.parent.name):
                dispute = load_dispute(folder / "RD-0107.json")
                res, gates, _ = self.judge(_ruling("refund", 4.91, 0.85),
                                           pack=build_evidence_pack(dispute), dispute=dispute)
                self.assertHeld(res, gates, ["RD-4"], 4.91)

    def test_the_correct_rulings_still_go_out(self):
        for cid in ("RD-0105", "RD-0107"):
            with self.subTest(case=cid):
                dispute = load_dispute(ORGANISER / ("%s.json" % cid))
                self.assertRuled(*self.judge(_ruling("no action", 0.0),
                                             pack=build_evidence_pack(dispute), dispute=dispute))


class RefundBoundaries(_Harness):
    record = SYNTH / "RD-0101.json"  # proves 5.81

    def test_the_proven_refund_goes_out(self):
        self.assertRuled(*self.judge(_ruling("refund", 5.81)))

    def test_one_cent_over_is_held(self):
        res, gates, _ = self.judge(_ruling("refund", 5.82))
        self.assertHeld(res, gates, ["RD-4"], 5.82)

    def test_the_eight_dollar_example_is_held(self):
        res, gates, _ = self.judge(_ruling("refund", 8.00))
        self.assertHeld(res, gates, ["RD-4"], 8.00)

    def test_less_than_proven_is_not_this_gates_concern(self):
        self.assertRuled(*self.judge(_ruling("refund", 5.80)))

    def test_no_action_is_never_held_here(self):
        self.assertRuled(*self.judge(_ruling("no action", 0.0)))

    def test_cent_rounding_on_the_record_side(self):
        pack = _replace(self.pack, "fare", charged_sgd=18.6251)  # proves 5.8051 -> 5.81
        self.assertRuled(*self.judge(_ruling("refund", 5.81), pack=pack))


class PricingErrorCase(_Harness):
    record = SYNTH / "RD-0106.json"  # difference 3.40, immaterial deviation

    def test_the_proven_overcharge_goes_out(self):
        self.assertRuled(*self.judge(_ruling("refund", 3.40)))

    def test_more_than_the_overcharge_is_held_by_rd4_only(self):
        res, gates, _ = self.judge(_ruling("refund", 3.41))
        self.assertHeld(res, gates, ["RD-4"], 3.41)

    def test_less_than_the_overcharge_is_held_by_rd5_only(self):
        res, gates, _ = self.judge(_ruling("refund", 0.66))
        self.assertHeld(res, gates, ["RD-5"], 0.66)


class NoRatesRecords(_Harness):
    """the operator 2026-10-02, "Hold": no rates means no detour proof."""

    def run_case(self, cid, action, amount):
        record = _without_rates(_record(SYNTH / ("%s.json" % cid)))
        dispute = parse_dispute(record)
        return self.judge(_ruling(action, amount), pack=_pack_of(record), dispute=dispute)

    def test_a_detour_refund_is_held(self):
        res, gates, _ = self.run_case("RD-0101", "refund", 5.81)
        self.assertHeld(res, gates, ["RD-4"], 5.81)

    def test_no_action_goes_out(self):
        self.assertRuled(*self.run_case("RD-0101", "no action", 0.0))

    def test_a_breakdown_proven_refund_goes_out(self):
        self.assertRuled(*self.run_case("RD-0106", "refund", 3.40))

    def test_more_than_the_breakdown_proves_is_held(self):
        res, gates, _ = self.run_case("RD-0106", "refund", 3.41)
        self.assertHeld(res, gates, ["RD-4"], 3.41)


class Compensation(_Harness):
    def test_compensation_on_a_route_case_is_held(self):
        res, gates, _ = self.judge(_ruling("compensation", 2.00))
        self.assertHeld(res, gates, ["RD-4"], 2.00)
        note = next(n for n in res.notes if "RD-4" in n)
        self.assertIn("driver", note)

    def test_compensation_beside_a_short_rd5_hold_names_both(self):
        # RD-5 holding the short side must not suppress RD-4: only an UNREADABLE record does.
        dispute = load_dispute(SYNTH / "RD-0106.json")
        res, gates, _ = self.judge(_ruling("compensation", 2.00),
                                   pack=build_evidence_pack(dispute), dispute=dispute)
        self.assertHeld(res, gates, ["RD-5", "RD-4"], 2.00)


class OtherGatesAndScope(_Harness):
    def test_above_the_cap_and_proven_is_esc4_only(self):
        dispute = load_dispute(SYNTH / "RD-0109.json")
        res, gates, _ = self.judge(_ruling("refund", 55.16),
                                   pack=build_evidence_pack(dispute), dispute=dispute)
        self.assertHeld(res, gates, ["ESC-4"], 55.16)

    def test_above_the_cap_and_unproven_names_both_in_order(self):
        dispute = load_dispute(SYNTH / "RD-0109.json")
        res, gates, _ = self.judge(_ruling("refund", 60.00),
                                   pack=build_evidence_pack(dispute), dispute=dispute)
        self.assertHeld(res, gates, ["ESC-4", "RD-4"], 60.00)

    def test_low_confidence_and_unproven_names_both(self):
        dispute = load_dispute(SYNTH / "RD-0105.json")
        res, gates, _ = self.judge(_ruling("refund", 5.56, 0.4),
                                   pack=build_evidence_pack(dispute), dispute=dispute)
        self.assertHeld(res, gates, ["confidence", "RD-4"], 5.56)

    def test_esc2_holds_alone_on_an_unmeasured_deviation(self):
        dispute = load_dispute(SYNTH / "RD-0108.json")
        res, gates, _ = self.judge(_ruling("refund", 7.10),
                                   pack=build_evidence_pack(dispute), dispute=dispute)
        self.assertHeld(res, gates, ["ESC-2"], 7.10)

    def test_esc2_holds_alone_on_an_unproven_charge(self):
        pack = _replace(self.pack, "fare", charged_sgd=None)
        res, gates, _ = self.judge(_ruling("refund", 5.81), pack=pack)
        self.assertHeld(res, gates, ["ESC-2"], 5.81)

    def test_an_unreadable_difference_is_rd5_alone(self):
        dispute = load_dispute(SYNTH / "RD-0103.json")
        pack = _replace(build_evidence_pack(dispute), "fare", difference_sgd=float("nan"))
        res, gates, _ = self.judge(_ruling("refund", 0.74), pack=pack, dispute=dispute)
        self.assertHeld(res, gates, ["RD-5"], 0.74)

    def test_no_show_cases_are_out_of_scope(self):
        # Graft the RD-0105 route and fare blocks onto a real no-show pack. Under the
        # no-show category the refund of the fee goes out; under the route category the
        # SAME pack is held by RD-4, so the graft is live and only the category differs.
        rd = build_evidence_pack(load_dispute(SYNTH / "RD-0105.json"))
        ns_dispute = load_dispute(SYNTH / "NS-0205.json")
        grafted = dataclasses.replace(build_evidence_pack(ns_dispute), route=rd.route, fare=rd.fare)
        self.assertRuled(*self.judge(_ruling("refund", 6.61), pack=grafted, dispute=ns_dispute))
        res, gates, _ = self.judge(_ruling("refund", 6.61), pack=grafted,
                                   dispute=load_dispute(SYNTH / "RD-0105.json"))
        self.assertIn("RD-4", gates)


class WhatTheHumanAndTheOperatorSee(_Harness):
    record = SYNTH / "RD-0105.json"

    def test_the_summary_names_the_gate_and_no_figure(self):
        _res, gates, summary = self.judge(_ruling("refund", 5.56))
        self.assertEqual(["RD-4"], gates)
        self.assertIn("(RD-4)", summary)
        self.assertNotIn("SGD", summary)
        self.assertNotIn("5.56", summary)

    def test_the_note_carries_both_figures(self):
        res, _gates, _ = self.judge(_ruling("refund", 5.56))
        note = next(n for n in res.notes if "RD-4" in n)
        self.assertIn("5.56", note)
        self.assertIn("0.00", note)

    def test_the_party_sees_only_the_holding_message(self):
        res, _gates, _ = self.judge(_ruling("refund", 5.56))
        self.assertEqual(UNDER_REVIEW_MESSAGE, res.party_message)
        self.assertNotIn("5.56", res.party_message)

    # Review round (2026-10-03, glm-5.3 S21-1..S21-4): the fragment checks above stay green
    # when the two figures are swapped or the wording changes, so the human would read
    # "proves SGD 5.56; the proposed refund of SGD 0.00". Pin the exact text the brief gives.
    def test_the_summary_is_exactly_the_brief_text(self):
        _res, _gates, summary = self.judge(_ruling("refund", 5.56))
        self.assertEqual(
            "Judge withheld the ruling: the ruling pays more than the records prove is owed (RD-4)",
            summary)

    def test_the_note_names_the_proof_first_and_the_refund_second(self):
        res, _gates, _ = self.judge(_ruling("refund", 5.56))
        self.assertEqual(
            ["the ruling was not delivered: RD-4: the records prove an overpayment of SGD 0.00; "
             "the proposed refund of SGD 5.56 is more than that"],
            [n for n in res.notes if "RD-4" in n])

    def test_the_note_order_holds_on_a_nonzero_proof(self):
        dispute = load_dispute(SYNTH / "RD-0101.json")
        res, gates, _ = self.judge(_ruling("refund", 6.00), pack=build_evidence_pack(dispute),
                                   dispute=dispute)
        self.assertEqual(["RD-4"], gates)
        self.assertEqual(
            ["the ruling was not delivered: RD-4: the records prove an overpayment of SGD 5.81; "
             "the proposed refund of SGD 6.00 is more than that"],
            [n for n in res.notes if "RD-4" in n])

    def test_the_compensation_note_is_exactly_the_brief_text(self):
        dispute = load_dispute(SYNTH / "RD-0101.json")
        res, _gates, _ = self.judge(_ruling("compensation", 2.00),
                                    pack=build_evidence_pack(dispute), dispute=dispute)
        self.assertEqual(
            ["the ruling was not delivered: RD-4: a route-deviation record proves nothing owed "
             "to the driver; the proposed compensation of SGD 2.00 is not supported"],
            [n for n in res.notes if "RD-4" in n])


class ThroughThePipeline(unittest.TestCase):
    """The real pipeline on the mock: the mock's own unproven refunds are now held."""

    def test_the_mock_refunds_are_held_on_both_packs(self):
        for folder in (SYNTH, ORGANISER):
            for cid in ("RD-0103", "RD-0105", "RD-0107"):
                with self.subTest(pack=folder.parent.name, case=cid):
                    with tempfile.TemporaryDirectory() as tmp:
                        events = EventLog(Path(tmp) / "run", "w28-pipe")
                        case = run_dispute(dispute=load_dispute(folder / ("%s.json" % cid)),
                                           llm=MockLLMClient(), policy=load_policy(POLICY),
                                           events=events, confidence_threshold=0.65,
                                           autonomous_cap_sgd=50.0).to_dict()
                        withheld = [e for e in events.events()
                                    if e.type == "judge.ruling_withheld"]
                        self.assertEqual("withheld", case["resolution"]["outcome"])
                        self.assertEqual(["RD-4"],
                                         events.read_payload(withheld[0])["gates_failed"])


# ------------------------------------------------------------------ docs


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _section(text: str, heading: str) -> str:
    match = re.search(r"^## %s[ \t]*\n(.*?)(?=^## |\Z)" % re.escape(heading), text, re.M | re.S)
    if match is None:
        raise AssertionError("no '## %s' section" % heading)
    return match.group(1)


class Docs(unittest.TestCase):
    def test_policy_rd4_states_the_enforcement(self):
        text = _text(POLICY)
        body = re.search(r"^### RD-4 .*?(?=^### |\Z)", text, re.M | re.S).group(0)
        self.assertIn("Enforcement (2026-10-02)", body)
        for needle in ("withholds", "compensation", "recomputed_estimated_route_sgd",
                       "difference_sgd", "breakdown"):
            self.assertIn(needle, body, needle)

    def test_architecture_has_nine_gates_and_an_rd4_row(self):
        gates = _section(_text(ARCH), "Gates enforced in code")
        self.assertTrue(gates.lstrip().startswith("Nine gates"), "the count sentence leads")
        rows = [l for l in gates.splitlines() if l.startswith("| ") and "---" not in l][1:]
        self.assertEqual(9, len(rows))
        row = next((r for r in rows if "RD-4" in r.split("|")[1]), None)
        self.assertIsNotNone(row, "a table row whose first cell names RD-4")
        self.assertIn("`app/agents/judge.py`", row)
        for needle in ("recomputed_estimated_route_sgd", "difference_sgd", "compensation"):
            self.assertIn(needle, row, needle)

    def test_the_diagram_gate_node_names_rd4(self):
        for path in (ARCH, README):
            with self.subTest(doc=path.name):
                block = MERMAID.findall(_text(path))[0]
                line = next(l for l in block.splitlines() if l.strip().startswith("J --> G{"))
                self.assertIn("RD-4", line)

    def test_readme_gate_paragraph_names_six_gates(self):
        body = _section(_text(README), "Run")
        para = next(p for p in body.split("\n\n") if "enforced in Python" in p)
        self.assertRegex(para, r"(?i)\bsix gates\b")
        self.assertIn("RD-4", para)


if __name__ == "__main__":
    unittest.main()
