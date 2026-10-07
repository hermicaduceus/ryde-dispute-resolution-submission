"""Session twenty round three (W22 review fix): impossible fare inputs go to a human.

Written BEFORE the build, so it is RED until the CodeBuddy lane ships
docs/build-briefs/session-twenty-round-three-brief.md. Ruled by the operator on 2026-10-01 (late night)
after the round-two review reproduced, on this branch AND on main:

  RD-0106 with a promo of SGD 30 recomputes the fare as -14.24, reports a 33.40
  "overcharge" on a 19.16 charge, and RD-5 then ENFORCES it: a refund of SGD 33.40
  reaches the party, while the honest refund of the charge is withheld. A negative
  per-km rate does the same (26.36).

The ruling: impossible inputs are record defects exactly like unreadable ones.
  - A negative tariff rate, or a surge of zero or less, voids the recomputed fare with a
    note and is listed in fare.unreadable_inputs as "rates.<key>", so ESC-2 holds the case.
  - With every rate possible, a recomputed fare below zero can only come from a promo
    larger than the fare: it voids both recomputations with a note, and the promo is listed
    as "breakdown.<key>".
  - A zero rate is possible (a free component); only a surge must be above zero.

This is the LAST round on this defect class (operator ruling): a further finding of the
same kind becomes recorded residue unless it moves money on a corpus case.
"""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from app.dispute import parse_dispute
from app.events import EventLog
from app.evidence import build_evidence_pack
from app.llm.mock import MockLLMClient
from app.pipeline import run_dispute
from app.policy import load_policy
from app.schemas import UNDER_REVIEW_MESSAGE

from tests.support import ScriptedLLM

REPO = Path(__file__).resolve().parent.parent
SYNTH = REPO / "data" / "packs" / "ryde-synth-v1" / "disputes"
ORGANISER = REPO / "data" / "packs" / "organiser-style-v1" / "disputes"
POLICY = REPO / "docs" / "policy.md"


def _record(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _set(record: dict, path, value) -> dict:
    out = copy.deepcopy(record)
    node = out
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    return out


def _fare(record: dict):
    pack = build_evidence_pack(parse_dispute(record), generated_at="2026-10-01T00:00:00+00:00")
    return pack.fare, pack.notes


_ADVOCATE = {
    "claim_summary": "stand-in", "evidence_cited": [], "policy_rule_ids": [],
    "argument": "stand-in", "requested_outcome": "refund", "requested_amount_sgd": 1.0,
    "follow_up_slots": [],
}


def _run(record, amount):
    judge = {
        "action": "refund", "recommended_amount_sgd": amount, "confidence": 0.9,
        "explanation": "stand-in", "cited_rule_ids": ["RD-5"],
        "cited_evidence_refs": ["fare.charged_sgd"],
    }
    llm = ScriptedLLM({"rider_advocate": _ADVOCATE, "driver_advocate": _ADVOCATE, "judge": judge})
    with tempfile.TemporaryDirectory() as tmp:
        events = EventLog(Path(tmp) / "run", "s20c")
        case = run_dispute(
            dispute=parse_dispute(record), llm=llm, policy=load_policy(POLICY), events=events,
            confidence_threshold=0.65, autonomous_cap_sgd=50.0,
        ).to_dict()
        withheld = [e for e in events.events() if e.type == "judge.ruling_withheld"]
        gates = events.read_payload(withheld[0])["gates_failed"] if withheld else []
        summary = withheld[0].summary if withheld else None
    return case, gates, summary


RATE = ("trip", "fare", "rates")
PROMO = ("trip", "fare", "breakdown", "promo_sgd")


class ImpossibleRatesVoidTheFare(unittest.TestCase):
    def setUp(self):
        self.rd = _record(SYNTH / "RD-0106.json")

    def test_positive_control(self):
        fare, _notes = _fare(self.rd)
        self.assertEqual((15.76, 3.4, []), (fare.recomputed_sgd, fare.difference_sgd,
                                            fare.unreadable_inputs))

    def test_a_negative_rate_voids_and_is_listed(self):
        for rate in ("base_sgd", "per_km_sgd", "per_min_sgd"):
            with self.subTest(rate=rate):
                fare, notes = _fare(_set(self.rd, RATE + (rate,), -0.01))
                self.assertIsNone(fare.recomputed_sgd)
                self.assertIsNone(fare.recomputed_estimated_route_sgd)
                self.assertIsNone(fare.deviation_fare_delta_sgd)
                self.assertIsNone(fare.difference_sgd)
                self.assertIsNone(fare.difference_pct)
                self.assertEqual(["rates.%s" % rate], fare.unreadable_inputs)
                named = [n for n in notes if rate in n and "impossible" in n]
                self.assertEqual(1, len(named), notes)
                self.assertFalse([n for n in notes if "trip numbers" in n], notes)

    def test_a_zero_rate_is_possible(self):
        # A free component is a real tariff: only a negative rate is impossible.
        for rate in ("base_sgd", "per_km_sgd", "per_min_sgd"):
            with self.subTest(rate=rate):
                fare, _notes = _fare(_set(self.rd, RATE + (rate,), 0))
                self.assertIsNotNone(fare.recomputed_sgd)
                self.assertEqual([], fare.unreadable_inputs)

    def test_a_surge_of_zero_or_less_voids_and_is_listed(self):
        # A stated surge of 0 used to be read as "no surge" (1.0) and computed.
        for value in (0, 0.0, -1.0):
            with self.subTest(value=value):
                fare, notes = _fare(_set(self.rd, RATE + ("surge_multiplier",), value))
                self.assertIsNone(fare.recomputed_sgd)
                self.assertIsNone(fare.difference_sgd)
                self.assertEqual(["rates.surge_multiplier"], fare.unreadable_inputs)
                named = [n for n in notes if "surge_multiplier" in n and "impossible" in n]
                self.assertEqual(1, len(named), notes)

    def test_an_absent_surge_still_defaults_to_one(self):
        record = copy.deepcopy(self.rd)
        del record["trip"]["fare"]["rates"]["surge_multiplier"]
        fare, _notes = _fare(record)
        self.assertEqual(15.76, fare.recomputed_sgd)
        self.assertEqual([], fare.unreadable_inputs)

    def test_several_impossible_rates_are_listed_sorted_once(self):
        record = _set(_set(self.rd, RATE + ("surge_multiplier",), 0), RATE + ("base_sgd",), -1)
        fare, notes = _fare(record)
        self.assertEqual(["rates.base_sgd", "rates.surge_multiplier"], fare.unreadable_inputs)
        named = [n for n in notes if "impossible" in n]
        self.assertEqual(1, len(named), notes)

    def test_unreadable_and_impossible_together_are_listed_once_each(self):
        record = _set(_set(self.rd, RATE + ("per_km_sgd",), float("nan")),
                      RATE + ("base_sgd",), -1)
        fare, _notes = _fare(record)
        self.assertEqual(["rates.base_sgd", "rates.per_km_sgd"], fare.unreadable_inputs)
        self.assertIsNone(fare.recomputed_sgd)


class APromoLargerThanTheFareVoidsIt(unittest.TestCase):
    def setUp(self):
        self.rd = _record(SYNTH / "RD-0106.json")

    def test_a_promo_larger_than_the_fare_voids_both_recomputations(self):
        # The sign the record stores the promo with does not matter (it is subtracted).
        for value in (-30.0, 30.0, -100.0):
            with self.subTest(value=value):
                fare, notes = _fare(_set(self.rd, PROMO, value))
                self.assertIsNone(fare.recomputed_sgd)
                self.assertIsNone(fare.recomputed_estimated_route_sgd)
                self.assertIsNone(fare.deviation_fare_delta_sgd)
                self.assertIsNone(fare.difference_sgd)
                self.assertEqual(["breakdown.promo_sgd"], fare.unreadable_inputs)
                named = [n for n in notes if "promo is larger than the fare" in n]
                self.assertEqual(1, len(named), notes)
                # The rates and the trip numbers were there: saying otherwise misstates it.
                self.assertFalse([n for n in notes if "trip numbers" in n], notes)

    def test_a_promo_that_only_sinks_the_expected_route_still_voids_both(self):
        # 15.50 is below the 15.76 actual fare but above the 15.10 expected-route fare, so
        # only one recomputation goes negative; the promo feeds both, so neither is trusted.
        clean, _notes = _fare(self.rd)
        self.assertEqual((15.76, 15.1), (clean.recomputed_sgd, clean.recomputed_estimated_route_sgd))
        fare, _notes = _fare(_set(self.rd, PROMO, -15.5))
        self.assertIsNone(fare.recomputed_sgd)
        self.assertIsNone(fare.recomputed_estimated_route_sgd)
        self.assertEqual(["breakdown.promo_sgd"], fare.unreadable_inputs)

    def test_a_promo_equal_to_the_fare_is_a_zero_fare_not_a_negative_one(self):
        # A flat 3.20 fare with a 3.20 promo is a free trip: exactly zero is possible.
        record = self.rd
        for rate in ("per_km_sgd", "per_min_sgd"):
            record = _set(record, RATE + (rate,), 0)
        record = _set(record, RATE + ("base_sgd",), 3.2)
        record = _set(record, PROMO, -3.2)
        fare, _notes = _fare(record)
        self.assertEqual(0.0, fare.recomputed_sgd)
        self.assertEqual(0.0, fare.recomputed_estimated_route_sgd)
        self.assertEqual([], fare.unreadable_inputs)

    def test_a_promo_under_the_fare_is_fine(self):
        fare, _notes = _fare(_set(self.rd, PROMO, -2.0))
        self.assertEqual(13.76, fare.recomputed_sgd)
        self.assertEqual([], fare.unreadable_inputs)

    def test_the_promo_alias_is_listed_under_its_own_name(self):
        record = copy.deepcopy(self.rd)
        record["trip"]["fare"]["breakdown"]["discount_sgd"] = -30.0
        fare, _notes = _fare(record)
        self.assertEqual(["breakdown.discount_sgd"], fare.unreadable_inputs)


class Esc2HoldsImpossibleInputs(unittest.TestCase):
    """The review's repro, through the real pipeline: no refund reaches the party."""

    def setUp(self):
        self.rd = _record(SYNTH / "RD-0106.json")

    def _assert_held(self, record, amount):
        case, gates, summary = _run(record, amount)
        resolution = case["resolution"]
        self.assertEqual("withheld", resolution["outcome"])
        self.assertIsNone(resolution["ruling"])
        self.assertEqual(UNDER_REVIEW_MESSAGE, resolution["party_message"])
        self.assertEqual(["ESC-2"], gates)
        self.assertEqual(
            "Judge withheld the ruling: the fare inputs in the record could not be read (ESC-2)",
            summary)
        return case

    def test_the_review_repro_is_held(self):
        # Round two: a SGD 33.40 refund on a SGD 19.16 charge reached the party.
        for amount in (33.40, 19.16, 3.40):
            with self.subTest(amount=amount):
                self._assert_held(_set(self.rd, PROMO, -30.0), amount)

    def test_a_negative_rate_is_held(self):
        case = self._assert_held(_set(self.rd, RATE + ("per_km_sgd",), -2.0), 26.36)
        notes = [n for n in case["resolution"]["notes"] if "ESC-2" in n]
        self.assertEqual(1, len(notes))
        self.assertIn("fare.rates.per_km_sgd", notes[0])

    def test_a_zero_surge_is_held(self):
        self._assert_held(_set(self.rd, RATE + ("surge_multiplier",), 0), 3.40)

    def test_the_mock_is_held_too(self):
        with tempfile.TemporaryDirectory() as tmp:
            events = EventLog(Path(tmp) / "run", "s20c")
            case = run_dispute(
                dispute=parse_dispute(_set(self.rd, PROMO, -30.0)), llm=MockLLMClient(),
                policy=load_policy(POLICY), events=events,
                confidence_threshold=0.65, autonomous_cap_sgd=50.0).to_dict()
        self.assertEqual("withheld", case["resolution"]["outcome"])

    def test_no_show_cases_are_not_gated(self):
        ns = _record(SYNTH / "NS-0201.json")
        record = _set(ns, ("trip", "fare", "breakdown", "promo_sgd"), -30.0)
        self.assertIn("fare", record["trip"])
        case, gates, _summary = _run(record, 0.0)
        self.assertNotIn("ESC-2", gates)


class NoCorpusCaseIsTouched(unittest.TestCase):
    def test_no_corpus_record_has_an_impossible_input(self):
        records = sorted(SYNTH.glob("*.json")) + sorted(ORGANISER.glob("*.json"))
        self.assertEqual(35, len(records))
        for path in records:
            with self.subTest(record=path.name):
                pack = build_evidence_pack(parse_dispute(_record(path)), generated_at="x")
                if pack.fare is not None:
                    self.assertEqual([], pack.fare.unreadable_inputs)
                    self.assertFalse([n for n in pack.notes if "impossible" in n
                                      or "promo is larger" in n])
                    for figure in (pack.fare.recomputed_sgd,
                                   pack.fare.recomputed_estimated_route_sgd):
                        self.assertTrue(figure is None or figure >= 0, figure)


class DocsNameTheRule(unittest.TestCase):
    def test_policy_ev1_names_impossible_inputs(self):
        text = POLICY.read_text(encoding="utf-8")
        section = " ".join(text.split("### EV-1", 1)[1].split("\n### ", 1)[0].split())
        self.assertRegex(section, r"(?i)negative tariff rate")
        self.assertRegex(section, r"(?i)promo larger than the fare")
        self.assertIn("fare.unreadable_inputs", section)

    def test_architecture_evidence_row_names_impossible_inputs(self):
        text = (REPO / "docs" / "architecture.md").read_text(encoding="utf-8")
        row = [l for l in text.splitlines() if l.startswith("| Evidence layer |")]
        self.assertEqual(1, len(row))
        self.assertRegex(row[0], r"(?i)impossible")
        self.assertRegex(row[0], r"(?i)negative (tariff )?rate")


if __name__ == "__main__":
    unittest.main()
