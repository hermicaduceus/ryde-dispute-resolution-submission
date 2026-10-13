"""W43 SHOULD RED acceptance (S2): RD-5's floor reads the overcharge the RECORDS prove.

Written BEFORE the build, so it is RED on the frozen baseline until the W43 SHOULD lane ships.
RD-5's floor (app/agents/judge.py, the gate block) compares the ruling against
``fare.difference_sgd``, which is computed from the tariff rates. A route record that proves an
overcharge through an INCONSISTENT BREAKDOWN alone — charged SGD 15.00, the recorded components
summing SGD 10.00, no rates at all — leaves ``difference_sgd`` None, so today a no-action ruling
and a short refund are both ruled with no gate firing, while README:159-160 promises RD-5
withholds a route ruling that "refunds less than the overcharge the records prove".

Two semantics must survive the widening: the de minimis line below which RD-5 does not gate,
and RD-4's ceiling (including its suppression when the difference is present but unreadable, so
one record defect never reads as two reasons).

Run: env -u PYTHONPATH /usr/bin/python3 -m unittest tests.test_w43_should_rd5_floor -v
"""
from __future__ import annotations

import dataclasses
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from app.dispute import parse_dispute
from app.events import EventLog
from app.evidence import build_evidence_pack
from app.llm.mock import MockLLMClient
from app.pipeline import run_dispute
from app.policy import load_policy
from app.schemas import OUTCOME_RULED, OUTCOME_WITHHELD, UNDER_REVIEW_MESSAGE, AdvocateCase

from tests.support import ScriptedLLM

REPO = Path(__file__).resolve().parent.parent
POLICY = REPO / "docs" / "policy.md"
RECORD = REPO / "data" / "packs" / "ryde-synth-v1" / "disputes" / "RD-0103.json"

#: The records: SGD 15.00 charged, the components summing to SGD 10.00, and no rates at all.
#: The breakdown is the only proof of the overcharge, and it proves SGD 5.00.
CHARGED_SGD = 15.00
COMPONENTS_SGD = {"base_sgd": 3.20, "distance_sgd": 3.40, "time_sgd": 3.40}
PROVEN_SGD = 5.00

#: The exact operator-visible words RD-5 uses when it withholds. The summary names the gate
#: and carries NO figure; the amount lives in the note.
RD5_SUMMARY = ("Judge withheld the ruling: the ruling refunds less than the overcharge the "
               "records prove (RD-5)")
RD5_NOTE_NO_ACTION = ("the ruling was not delivered: RD-5: the records prove an overcharge of "
                      "SGD 5.00; the proposed no action of SGD 0.00 does not refund it")
RD5_NOTE_SHORT_REFUND = ("the ruling was not delivered: RD-5: the records prove an overcharge of "
                         "SGD 5.00; the proposed refund of SGD 4.99 does not refund it")


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


def _ruling(action: str, amount: float, confidence: float = 0.9):
    return {
        "action": action,
        "recommended_amount_sgd": amount,
        "confidence": confidence,
        "explanation": "stand-in",
        "cited_rule_ids": ["RD-4", "EV-3"],
        "cited_evidence_refs": ["fare.charged_sgd"],
    }


def _breakdown_only_pack(*, charged: float = CHARGED_SGD, components=None):
    """A route-deviation case whose overcharge only its own inconsistent breakdown proves."""
    record = json.loads(RECORD.read_text(encoding="utf-8"))
    record["trip"]["fare"] = {
        "charged_sgd": charged,
        "breakdown": dict(components if components is not None else COMPONENTS_SGD),
    }
    return build_evidence_pack(parse_dispute(record))


def _replace_fare(pack, **changes):
    return dataclasses.replace(pack, fare=dataclasses.replace(pack.fare, **changes))


class _JudgeHarness(unittest.TestCase):
    """Runs the real Judge on the breakdown-only pack with a scripted ruling."""

    def judge(self, ruling, pack=None):
        tmp = Path(tempfile.mkdtemp(prefix="w43-s2-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        events = EventLog(tmp / "run", "w43-s2")
        judge = _judge_module().Judge(
            llm=ScriptedLLM({"judge": ruling}), events=events, policy=load_policy(POLICY)
        )
        resolution = judge.run(
            dispute=parse_dispute(json.loads(RECORD.read_text(encoding="utf-8"))),
            pack=pack if pack is not None else self.pack,
            rider_case=_advocate("rider"),
            driver_case=_advocate("driver"),
            confidence_threshold=0.65,
            autonomous_cap_sgd=50.0,
        )
        withheld = [e for e in events.events() if e.type == "judge.ruling_withheld"]
        payload = events.read_payload(withheld[0]) if withheld else None
        return resolution, payload, (withheld[0].summary if withheld else None)

    def setUp(self):
        self.pack = _breakdown_only_pack()


class Rd5BreakdownOnlyFloorTests(_JudgeHarness):
    def test_the_record_proves_the_overcharge_only_through_its_breakdown(self):
        """The premise, asserted rather than assumed: no rates, so no difference figure."""
        fare = self.pack.fare
        self.assertEqual(CHARGED_SGD, fare.charged_sgd)
        self.assertEqual(10.00, fare.component_sum_sgd)
        self.assertIs(False, fare.breakdown_consistent)
        self.assertIsNone(fare.difference_sgd, "no rates means no computed difference")
        self.assertIsNone(fare.recomputed_sgd)
        self.assertEqual([], fare.unreadable_inputs, "absence is not unreadability")
        self.assertEqual(6.0, self.pack.route.deviation_pct, "the deviation must be measurable")

    def test_a_no_action_ruling_on_a_breakdown_only_overcharge_is_withheld_by_rd5(self):
        resolution, payload, summary = self.judge(_ruling("no action", 0.0))
        self.assertEqual(OUTCOME_WITHHELD, resolution.outcome)
        self.assertEqual(["RD-5"], payload["gates_failed"])
        self.assertEqual(UNDER_REVIEW_MESSAGE, resolution.party_message)
        self.assertIsNone(resolution.ruling)
        self.assertEqual("no action", resolution.withheld_candidate.action)
        self.assertEqual([RD5_NOTE_NO_ACTION], resolution.notes)
        self.assertEqual(RD5_SUMMARY, summary)
        self.assertNotIn("SGD", summary, "the operator summary names the gate, never a figure")

    def test_a_refund_below_the_breakdown_only_proof_is_withheld_by_rd5(self):
        resolution, payload, summary = self.judge(_ruling("refund", 4.99))
        self.assertEqual(OUTCOME_WITHHELD, resolution.outcome)
        self.assertEqual(["RD-5"], payload["gates_failed"])
        self.assertEqual([RD5_NOTE_SHORT_REFUND], resolution.notes)
        self.assertEqual(RD5_SUMMARY, summary)

    def test_a_refund_of_exactly_the_proof_is_delivered(self):
        """The boundary: the floor is met at the proven figure, at the cent."""
        resolution, payload, _summary = self.judge(_ruling("refund", PROVEN_SGD))
        self.assertEqual(OUTCOME_RULED, resolution.outcome)
        self.assertIsNone(payload, "nothing may withhold a ruling that refunds the proof")
        self.assertEqual(PROVEN_SGD, resolution.ruling.recommended_amount_sgd)

    def test_a_refund_above_the_proof_is_held_by_rd4_alone(self):
        """RD-4 stays the ceiling, and the floor must not add a second reason."""
        resolution, payload, summary = self.judge(_ruling("refund", 6.00))
        self.assertEqual(OUTCOME_WITHHELD, resolution.outcome)
        self.assertEqual(["RD-4"], payload["gates_failed"])
        self.assertEqual(
            ["the ruling was not delivered: RD-4: the records prove an overpayment of SGD 5.00; "
             "the proposed refund of SGD 6.00 is more than that"], resolution.notes)
        self.assertIn("more than the records prove is owed (RD-4)", summary)

    def test_a_proof_below_the_de_minimis_line_is_not_gated(self):
        """0.99 proved by the breakdown alone stays below RD-5's de minimis SGD 1.00."""
        pack = _breakdown_only_pack(charged=10.99)
        self.assertEqual(10.00, pack.fare.component_sum_sgd)
        self.assertEqual(0.99, round(pack.fare.charged_sgd - pack.fare.component_sum_sgd, 2))
        resolution, payload, _summary = self.judge(_ruling("no action", 0.0), pack=pack)
        self.assertEqual(OUTCOME_RULED, resolution.outcome)
        self.assertIsNone(payload)

    def test_an_unreadable_difference_still_holds_and_still_suppresses_rd4(self):
        """A difference present but not finite can prove nothing either way: the existing
        unreadable branch holds the case, one reason only, and RD-4 stays suppressed."""
        pack = _replace_fare(self.pack, difference_sgd=float("nan"))
        resolution, payload, summary = self.judge(_ruling("refund", 0.50), pack=pack)
        self.assertEqual(OUTCOME_WITHHELD, resolution.outcome)
        self.assertEqual(["RD-5"], payload["gates_failed"])
        self.assertIn("not a finite number", resolution.notes[0])
        self.assertIn("could not be read (RD-5)", summary)

    def test_esc2_alone_holds_a_record_the_breakdown_also_proves(self):
        """Preserve pin (the W22 ESC-2 clause): one record defect reads as one reason. When
        ESC-2 already holds a route case, the widened floor must not add a second reason."""
        record = json.loads(RECORD.read_text(encoding="utf-8"))
        record["trip"]["fare"] = {"charged_sgd": CHARGED_SGD,
                                  "breakdown": dict(COMPONENTS_SGD)}
        record["trip"].pop("estimated_distance_km", None)
        record["trip"].pop("estimated_duration_min", None)
        pack = build_evidence_pack(parse_dispute(record))
        self.assertIsNone(pack.route.deviation_pct, "the deviation cannot be measured here")
        self.assertIsNone(pack.fare.difference_sgd)
        self.assertIs(False, pack.fare.breakdown_consistent)
        resolution, payload, _summary = self.judge(_ruling("no action", 0.0), pack=pack)
        self.assertEqual(OUTCOME_WITHHELD, resolution.outcome)
        self.assertEqual(["ESC-2"], payload["gates_failed"])

    def test_a_record_that_states_rates_keeps_the_difference_based_floor(self):
        """Preserve pin: the widening reads the breakdown only where the record states NO
        rates. With rates present, an unreadable difference is not this floor's reason."""
        pack = _replace_fare(self.pack, difference_sgd=None, rates={"per_km_sgd": 0.8})
        self.assertIs(False, pack.fare.breakdown_consistent)
        resolution, payload, _summary = self.judge(_ruling("no action", 0.0), pack=pack)
        self.assertEqual(OUTCOME_RULED, resolution.outcome)
        self.assertIsNone(payload)

    def test_no_show_case_with_an_inconsistent_breakdown_is_not_an_rd5_case(self):
        """Scope, not outcome: RD-5 gates route cases only. A no-show record whose own
        breakdown is inconsistent must not acquire a route floor from it."""
        record = json.loads(
            (REPO / "data" / "packs" / "ryde-synth-v1" / "disputes" / "NS-0205.json")
            .read_text(encoding="utf-8"))
        record["trip"]["fare"] = {"charged_sgd": 15.00, "breakdown": dict(COMPONENTS_SGD)}
        dispute = parse_dispute(record)
        pack = build_evidence_pack(dispute)
        self.assertIs(False, pack.fare.breakdown_consistent,
                      "the record the scope check rests on must carry the inconsistent sum")
        self.assertEqual(5.00, round(pack.fare.charged_sgd - pack.fare.component_sum_sgd, 2))
        tmp = Path(tempfile.mkdtemp(prefix="w43-s2-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        events = EventLog(tmp / "run", "w43-s2-ns")
        judge = _judge_module().Judge(
            llm=ScriptedLLM({"judge": _ruling("no action", 0.0)}), events=events,
            policy=load_policy(POLICY))
        judge.run(dispute=dispute, pack=pack, rider_case=_advocate("rider"),
                  driver_case=_advocate("driver"), confidence_threshold=0.65,
                  autonomous_cap_sgd=50.0)
        gates = [gate for e in events.events() if e.type == "judge.ruling_withheld"
                 for gate in events.read_payload(e)["gates_failed"]]
        self.assertNotIn("RD-5", gates)


class _JudgeScriptedMock(MockLLMClient):
    """The stock mock for both advocates, one scripted reply for the Judge."""

    provider_name = "scripted"

    def __init__(self, ruling):
        super().__init__()
        self.ruling = ruling

    def complete(self, request):
        if request.agent != "judge":
            return super().complete(request)
        from app.llm import LLMResponse

        return LLMResponse(text=json.dumps(self.ruling), provider=self.provider_name,
                           model="scripted-v0")


class Rd5BreakdownOnlyFloorEndToEndTests(unittest.TestCase):
    def test_the_party_is_held_by_rd5_end_to_end(self):
        record = json.loads(RECORD.read_text(encoding="utf-8"))
        record["trip"]["fare"] = {"charged_sgd": CHARGED_SGD,
                                  "breakdown": dict(COMPONENTS_SGD)}
        tmp = Path(tempfile.mkdtemp(prefix="w43-s2-e2e-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        run_dir = tmp / "run"
        events = EventLog(run_dir, "w43-s2-e2e")
        case = run_dispute(
            dispute=parse_dispute(record),
            llm=_JudgeScriptedMock(_ruling("no action", 0.0)),
            policy=load_policy(POLICY),
            events=events,
            confidence_threshold=0.65,
        )
        self.assertEqual(OUTCOME_WITHHELD, case.resolution["outcome"])
        self.assertEqual(UNDER_REVIEW_MESSAGE, case.resolution["party_message"])
        withheld = [events.read_payload(e) for e in events.events()
                    if e.type == "judge.ruling_withheld"]
        self.assertEqual(["RD-5"], withheld[0]["gates_failed"])


if __name__ == "__main__":
    unittest.main()
