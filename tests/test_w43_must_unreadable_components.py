"""W43 MUST lane (M2): a value that is not a finite number voids what it feeds.

RED until the W43 MUST lane ships its brief. Written before the build, in the shape of the
earlier input-integrity files: each test pins the DEFECT, not a symbol a fix introduces.

The defect (Sol document review, A-F02, parent-reproduced):

  * `app/evidence/compute.py` `_is_non_finite_number` returns false for strings, booleans
    and null, so `_finite_mapping` silently drops a non-numeric rate component and the rate
    lookup defaults to zero: `per_km_sgd="unreadable"` recomputed SGD 7.45 on RD-0103 with a
    difference of 4.24 and `fare.unreadable_inputs` EMPTY, so an injected 4.24 refund reached
    the party instead of being withheld by ESC-2. NaN/Infinity are handled correctly; the
    hole is `not-a-number-at-all`.
  * `app/dispute.py` `_organiser_to_record` drops a malformed (non-object) `gps_telemetry`
    row before the evidence layer sees it, so an 11-row organiser trace silently became a
    10-row one and still computed a distance, with no note.

The contract these tests pin:

  * a fare/rate component that is not a finite number — a string, a boolean, null, NaN,
    Infinity, or an integer too large for a float — is unreadable: it voids the value it
    feeds, adds a note, and is named in `fare.unreadable_inputs`, exactly as NaN already is;
  * the ESC-2 gate withholds a route ruling built on such a record (it already withholds
    when `unreadable_inputs` is non-empty; the fix feeds it);
  * a malformed GPS row is not silently dropped from the trace: the trace is voided with a
    note, as it already is when a row is present but its coordinates are unusable.

`UNREADABLE` here is the family the review found missing. `isinstance(True, int)` is True in
Python, so the boolean cases are stated explicitly.
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
POLICY = REPO / "docs" / "policy.md"
SYNTH = REPO / "data" / "packs" / "ryde-synth-v1" / "disputes"
ORG = REPO / "data" / "packs" / "organiser-style-v1" / "disputes"

RATES = ("base_sgd", "per_km_sgd", "per_min_sgd", "surge_multiplier")
COMPONENTS = ("base_sgd", "distance_sgd", "time_sgd")

#: The parent's repro value, and the rest of the not-a-number-at-all family.
NOT_A_NUMBER = ("unreadable", "", "   ", "7.5", [1], {"a": 1})
BOOLEANS = (True, False)
NULL = (None,)
FAMILY = NOT_A_NUMBER + BOOLEANS + NULL
#: What the code already refuses, and what these values must now be treated like.
ALREADY_REFUSED = (float("nan"), float("inf"), float("-inf"), 10 ** 400, -(10 ** 400))


def _record(folder: Path, name: str) -> dict:
    return json.loads((folder / name).read_text(encoding="utf-8"))


def _set(record: dict, path, value) -> dict:
    out = copy.deepcopy(record)
    node = out
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    return out


def _pack(record: dict):
    return build_evidence_pack(parse_dispute(record), generated_at="2026-10-13T00:00:00+00:00")


def _route_fields(pack) -> tuple:
    """(actual, estimated, deviation, pct) of one pack's route block."""
    route = pack.route
    return (route.actual_distance_km, route.estimated_distance_km,
            route.deviation_km, route.deviation_pct)


def _notes(pack) -> str:
    """Every note in the pack, top-level and per block, joined and lower-cased."""
    found = list(pack.notes or [])
    for value in pack.to_dict().values():
        if isinstance(value, dict):
            found.extend(value.get("notes") or [])
    return " ".join(str(note) for note in found).lower()


_ADVOCATE = {
    "claim_summary": "stand-in",
    "evidence_cited": [],
    "policy_rule_ids": [],
    "argument": "stand-in",
    "requested_outcome": "refund",
    "requested_amount_sgd": 1.0,
    "follow_up_slots": [],
}


def _scripted(amount, action="refund", rules=("RD-5",), refs=("fare.charged_sgd",)):
    return ScriptedLLM({"rider_advocate": _ADVOCATE, "driver_advocate": _ADVOCATE,
                        "judge": {
                            "action": action, "recommended_amount_sgd": amount,
                            "confidence": 0.9, "explanation": "stand-in",
                            "cited_rule_ids": list(rules),
                            "cited_evidence_refs": list(refs),
                        }})


def _run(record: dict, llm):
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


# ------------------------------------------------------------- the evidence layer


class ANonNumericRateIsUnreadable(unittest.TestCase):
    """A rate the record states but cannot read is missing, not zero."""

    def setUp(self):
        self.rd = _record(SYNTH, "RD-0103.json")

    def test_the_review_repro_voids_the_fare_instead_of_freeing_the_distance(self):
        # The parent's repro exactly: recomputed 7.45, difference 4.24, unreadable_inputs [].
        pack = _pack(_set(self.rd, ("trip", "fare", "rates", "per_km_sgd"), "unreadable"))
        fare = pack.fare
        self.assertIsNone(fare.recomputed_sgd)
        self.assertIsNone(fare.recomputed_estimated_route_sgd)
        self.assertIsNone(fare.difference_sgd)
        self.assertIsNone(fare.deviation_fare_delta_sgd)
        self.assertNotIn("per_km_sgd", fare.rates)
        self.assertEqual(["rates.per_km_sgd"], fare.unreadable_inputs)
        named = [n for n in pack.notes if "per_km_sgd" in n and "not a finite number" in n]
        self.assertEqual(1, len(named), pack.notes)

    def test_every_rate_of_the_family_is_unreadable(self):
        for rate in RATES:
            for value in FAMILY:
                with self.subTest(rate=rate, value=repr(value)[:12]):
                    fare = _pack(_set(self.rd, ("trip", "fare", "rates", rate), value)).fare
                    self.assertIsNone(fare.recomputed_sgd)
                    self.assertIsNone(fare.difference_sgd)
                    self.assertNotIn(rate, fare.rates)
                    self.assertEqual(["rates.%s" % rate], fare.unreadable_inputs)

    def test_the_family_gets_exactly_the_treatment_the_non_finite_values_get(self):
        # The contract is "the same treatment the code already gives NaN/Infinity", so the
        # two packs are compared field by field rather than asserted twice by hand.
        for rate in RATES:
            reference = _pack(_set(self.rd, ("trip", "fare", "rates", rate), float("nan"))).fare
            for value in FAMILY + ALREADY_REFUSED:
                with self.subTest(rate=rate, value=repr(value)[:12]):
                    fare = _pack(_set(self.rd, ("trip", "fare", "rates", rate), value)).fare
                    self.assertEqual(reference.recomputed_sgd, fare.recomputed_sgd)
                    self.assertEqual(reference.difference_sgd, fare.difference_sgd)
                    self.assertEqual(reference.unreadable_inputs, fare.unreadable_inputs)
                    self.assertEqual(reference.rates, fare.rates)

    def test_several_broken_rates_are_listed_sorted_and_noted_once(self):
        record = _set(_set(self.rd, ("trip", "fare", "rates", "base_sgd"), True),
                      ("trip", "fare", "rates", "surge_multiplier"), "surge")
        pack = _pack(record)
        self.assertEqual(["rates.base_sgd", "rates.surge_multiplier"],
                         pack.fare.unreadable_inputs)
        self.assertEqual(1, len([n for n in pack.notes if "not a finite number" in n]),
                         pack.notes)

    def test_a_clean_record_still_recomputes(self):
        # Positive control: the widened family must not cost the ordinary record anything.
        # RD-0103 recomputes to its own charged fare; the 0.74 delta is the difference
        # between the actual-route and estimated-route recomputations.
        fare = _pack(self.rd).fare
        self.assertEqual((11.69, 11.69, 10.95, 0.74, []),
                         (fare.charged_sgd, fare.recomputed_sgd,
                          fare.recomputed_estimated_route_sgd,
                          fare.deviation_fare_delta_sgd, fare.unreadable_inputs))


class ANonNumericComponentVoidsTheBreakdownSum(unittest.TestCase):
    """A component the record states but cannot read makes the summed breakdown unknown."""

    def setUp(self):
        self.rd = _record(SYNTH, "RD-0103.json")

    def test_each_component_of_the_family_voids_the_sum_with_a_note(self):
        for component in COMPONENTS:
            for value in FAMILY:
                with self.subTest(component=component, value=repr(value)[:12]):
                    pack = _pack(_set(self.rd, ("trip", "fare", "breakdown", component), value))
                    self.assertIsNone(pack.fare.component_sum_sgd)
                    self.assertIsNone(pack.fare.breakdown_consistent)
                    named = [n for n in pack.notes
                             if component in n and "not a finite number" in n]
                    self.assertEqual(1, len(named), pack.notes)

    def test_a_broken_non_promo_component_is_not_a_fare_formula_input(self):
        # Parity with the existing NaN pin: only the formula's own inputs are listed.
        for value in FAMILY:
            with self.subTest(value=repr(value)[:12]):
                pack = _pack(_set(self.rd, ("trip", "fare", "breakdown", "distance_sgd"), value))
                self.assertEqual([], pack.fare.unreadable_inputs)

    def test_a_broken_promo_is_a_fare_formula_input(self):
        for value in FAMILY:
            with self.subTest(value=repr(value)[:12]):
                pack = _pack(_set(self.rd, ("trip", "fare", "breakdown", "promo_sgd"), value))
                self.assertEqual(["breakdown.promo_sgd"], pack.fare.unreadable_inputs)
                self.assertIsNone(pack.fare.recomputed_sgd)
                self.assertIsNone(pack.fare.difference_sgd)


class Esc2WithholdsARouteRulingBuiltOnANonNumericRate(unittest.TestCase):
    """The decision half: the existing gate, fed by the fix, stops the false refund."""

    def setUp(self):
        self.rd = _record(SYNTH, "RD-0103.json")

    def test_the_repro_refund_is_held(self):
        # 4.24 is exactly the difference the false recomputation produced; it reached the
        # party on HEAD because unreadable_inputs stayed empty.
        for value in ("unreadable", True, None):
            with self.subTest(value=repr(value)[:12]):
                record = _set(self.rd, ("trip", "fare", "rates", "per_km_sgd"), value)
                resolution, gates = _run(record, _scripted(4.24))
                self.assertEqual("withheld", resolution["outcome"], resolution)
                self.assertIsNone(resolution["ruling"])
                self.assertEqual(UNDER_REVIEW_MESSAGE, resolution["party_message"])
                self.assertEqual(["ESC-2"], gates)

    def test_the_note_names_the_input_and_the_pack(self):
        record = _set(self.rd, ("trip", "fare", "rates", "per_km_sgd"), "unreadable")
        resolution, _gates = _run(record, _scripted(4.24))
        notes = [n for n in resolution["notes"] if "ESC-2" in n]
        self.assertEqual(1, len(notes), resolution["notes"])
        self.assertIn("fare.rates.per_km_sgd", notes[0])

    def test_a_clean_record_is_not_held_by_esc2(self):
        # Positive control: the gate must not fire on the untouched record. RD-0103's own
        # records prove no overcharge at all, so the ruling is a plain no-action one.
        resolution, gates = _run(self.rd, _scripted(
            0.0, action="no action", rules=("RD-3",), refs=("route.deviation_pct",)))
        self.assertNotIn("ESC-2", gates, resolution)
        self.assertEqual("ruled", resolution["outcome"], resolution)

    def test_a_no_show_case_is_not_gated_on_fare_inputs(self):
        # Parity with the existing NaN pin: ESC-2 is a route gate.
        ns = _record(SYNTH, "NS-0205.json")
        resolution, gates = _run(ns, MockLLMClient())
        self.assertNotIn("ESC-2", gates, resolution)


class AMalformedOrganiserGpsRowIsNotSilentlyDropped(unittest.TestCase):
    """The organiser trace: one row the reader cannot use makes the length unknown."""

    def setUp(self):
        self.record = _record(ORG, "RD-0101.json")
        self.rows = self.record["gps_telemetry"]

    def _with_row(self, index, value) -> dict:
        return _set(self.record, ("gps_telemetry", index), value)

    def test_a_non_object_row_voids_the_trace_instead_of_shortening_it(self):
        for value in ("not a point", 5, None, [1, 2], True, {"lat": None, "lng": None}):
            with self.subTest(value=repr(value)[:12]):
                pack = _pack(self._with_row(len(self.rows) // 2, value))
                self.assertIsNone(pack.route.actual_distance_km)
                self.assertIsNone(pack.route.deviation_km)
                self.assertIsNone(pack.route.deviation_pct)
                self.assertIn("unusable", _notes(pack))

    def test_the_malformed_row_is_not_dropped_from_the_parsed_trace(self):
        # The defect is the DROP, so this asserts the parser keeps every row it was given:
        # the evidence layer is then the one that voids the length, with a note.
        for index in (0, 3, len(self.rows) - 1):
            with self.subTest(index=index):
                record = self._with_row(index, "not a point")
                trace = parse_dispute(record).trip["actual_route"]
                self.assertEqual(len(self.rows), len(trace))

    def test_the_untouched_organiser_trace_still_measures(self):
        # Positive control: RD-0101 is 50% over in both shapes and must stay so.
        pack = _pack(self.record)
        self.assertEqual(50.0, pack.route.deviation_pct)
        self.assertNotIn("unusable", _notes(pack))

    def test_the_two_shapes_report_the_same_thing(self):
        # Parity: the pack shape already voids on a non-object point; the organiser shape
        # must not report a shorter, plausible distance for the same defect.
        synth = _set(_record(SYNTH, "RD-0101.json"), ("trip", "actual_route", 4), "not a point")
        organiser = self._with_row(4, "not a point")
        self.assertEqual(_route_fields(_pack(synth)), _route_fields(_pack(organiser)))


if __name__ == "__main__":
    unittest.main()
