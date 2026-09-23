"""Session five acceptance target: records the reader must not quietly misread.

Non-app test, written BEFORE the fix, so it is RED until the CodeBuddy build lane closes the
findings of the 2026-09-23 cross-family review. Every case here was reproduced by running it
before it was written down. None changes an outcome on the 18 shipped records; each one does
on a record the organisers could plausibly send (a GPS dropout, a rider who concedes
absence, a record without our extension block).

The rule behind all of them is the Evidence Pack's own contract: a field the agents argue
from is either right or null with a note saying why. A plausible wrong number is the worst
of the three, because the agents treat pack fields as established fact.

  1. MAJOR: one unusable GPS point silently shortened a route. RD-0101 with its middle point
     nulled reported a 16.67% deviation instead of 50%, with no note, in BOTH record shapes.
     Operator ruling 2026-09-23 (option a): the distance is unknown, and the case goes to a
     human under ESC-2, enforced in code beside the confidence and cap gates.
  2. MAJOR: the organiser reader invented "the rider says the driver never came" for any
     rider disputing a no-show charge without our extension block. What the rider claims is
     in their own words, for the Advocates to read; the structured field says "not stated".
  3. MINOR: a missing or unknown filed_by was silently relabelled "rider".
  4. MINOR: coordinates present but unusable produced a null distance with no note, or a
     note claiming the position was absent when it was present and malformed.
  5. MINOR: a record carrying both a cancellation fee and a waiting fee lost one of them.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.dispute import DisputeError, parse_dispute
from app.evidence import build_evidence_pack
from app.schemas import OUTCOME_WITHHELD, UNDER_REVIEW_MESSAGE

from tests.support import DEFAULT_THRESHOLD

REPO = Path(__file__).resolve().parent.parent
SYNTH = REPO / "data" / "packs" / "ryde-synth-v1" / "disputes"
ORG = REPO / "data" / "packs" / "organiser-style-v1" / "disputes"


def _record(folder: Path, name: str) -> dict:
    return json.loads((folder / name).read_text(encoding="utf-8"))


def _pack(record: dict) -> dict:
    return build_evidence_pack(parse_dispute(record)).to_dict()


def _all_notes(pack: dict) -> str:
    """Every note in the pack, top-level and per block, lower-cased."""
    found = list(pack.get("notes") or [])
    for value in pack.values():
        if isinstance(value, dict):
            found.extend(value.get("notes") or [])
    return " ".join(str(note) for note in found).lower()


def _run(record: dict, cap: float = 50.00):
    """Run the full pipeline on the mock LLM; returns (resolution, withheld payload or None)."""
    from app.events import EventLog
    from app.llm.mock import MockLLMClient
    from app.pipeline import run_dispute
    from app.policy import load_policy

    with tempfile.TemporaryDirectory() as tmp:
        run_dir = Path(tmp) / "run"
        case = run_dispute(
            dispute=parse_dispute(record),
            llm=MockLLMClient(),
            policy=load_policy(REPO / "docs" / "policy.md"),
            events=EventLog(run_dir, "session-five"),
            confidence_threshold=DEFAULT_THRESHOLD,
            autonomous_cap_sgd=cap,
        )
        data = case.to_dict()
        withheld = [e for e in data["events"] if e["type"] == "judge.ruling_withheld"]
        payload = None
        if withheld:
            payload = json.loads((run_dir / withheld[0]["payload_ref"]).read_text(encoding="utf-8"))
        return data["resolution"], payload


# The ways a trace point can be unusable. Each must void the distance, not shorten it.
def _null_point(point):
    point["lat"], point["lng"] = None, None


def _missing_lng(point):
    point.pop("lng", None)


def _string_coords(point):
    point["lat"], point["lng"] = str(point["lat"]), str(point["lng"])


def _out_of_range(point):
    point["lat"] = 999.0


BREAKAGES = {
    "null lat/lng": _null_point,
    "missing lng": _missing_lng,
    "string lat/lng": _string_coords,
    "lat out of range": _out_of_range,
}


class UnusableRoutePointTests(unittest.TestCase):
    """Finding 1: a route with an unusable point has an unknown length, not a shorter one."""

    def _synth_route(self, breakage):
        record = _record(SYNTH, "RD-0101.json")
        points = record["trip"]["actual_route"]
        breakage(points[len(points) // 2])
        return _pack(record)

    def _organiser_route(self, breakage):
        record = _record(ORG, "RD-0101.json")
        rows = record["gps_telemetry"]
        breakage(rows[len(rows) // 2])
        return _pack(record)

    def test_every_breakage_voids_the_distance_in_both_shapes(self):
        for shape, build in (("ryde-synth-v1", self._synth_route), ("organiser-style-v1", self._organiser_route)):
            for label, breakage in BREAKAGES.items():
                with self.subTest(shape=shape, breakage=label):
                    route = build(breakage)["route"]
                    self.assertIsNone(route["actual_distance_km"])
                    self.assertIsNone(route["deviation_km"])
                    self.assertIsNone(route["deviation_pct"])

    def test_a_non_object_point_voids_the_distance(self):
        record = _record(SYNTH, "RD-0101.json")
        record["trip"]["actual_route"][4] = "not a point"
        self.assertIsNone(_pack(record)["route"]["actual_distance_km"])

    def test_the_pack_says_why_the_distance_is_missing(self):
        pack = self._synth_route(_null_point)
        self.assertIn("unusable", _all_notes(pack))

    def test_no_fare_is_recomputed_from_a_voided_distance(self):
        fare = self._synth_route(_null_point).get("fare") or {}
        self.assertIsNone(fare.get("recomputed_sgd"))
        self.assertIsNone(fare.get("deviation_fare_delta_sgd"))

    def test_a_clean_trace_is_unchanged(self):
        # The fix must not cost the good case anything: RD-0101 is still 50% over.
        for folder in (SYNTH, ORG):
            with self.subTest(pack=folder.parent.name):
                self.assertEqual(50.0, _pack(_record(folder, "RD-0101.json"))["route"]["deviation_pct"])


class MissingDeviationGateTests(unittest.TestCase):
    """Finding 1, the decision half: ESC-2 is enforced in code, not asked of the model.

    The mock Judge answers at confidence 0.86 with a below-cap amount, so neither existing
    gate fires. Only a gate on the missing deviation can withhold these rulings.
    """

    def test_a_route_with_an_unusable_point_is_withheld_under_esc_2(self):
        record = _record(SYNTH, "RD-0101.json")
        points = record["trip"]["actual_route"]
        _null_point(points[len(points) // 2])
        resolution, payload = _run(record)

        self.assertEqual(OUTCOME_WITHHELD, resolution["outcome"])
        self.assertEqual(UNDER_REVIEW_MESSAGE, resolution["party_message"])
        self.assertIsNotNone(payload)
        self.assertEqual(["ESC-2"], payload["gates_failed"])

    def test_rd_0108_is_withheld_in_both_packs(self):
        # RD-0108 has no estimated distance. Its label has always been "escalated" under
        # EV-1 + ESC-2, and until now the mock ruled it: the label was enforced nowhere.
        for folder in (SYNTH, ORG):
            with self.subTest(pack=folder.parent.name):
                resolution, payload = _run(_record(folder, "RD-0108.json"))
                self.assertEqual(OUTCOME_WITHHELD, resolution["outcome"])
                self.assertEqual(["ESC-2"], payload["gates_failed"])

    def test_a_measurable_route_is_not_caught_by_the_new_gate(self):
        resolution, _payload = _run(_record(SYNTH, "RD-0101.json"))
        self.assertNotEqual(OUTCOME_WITHHELD, resolution["outcome"])

    def test_a_no_show_without_an_arrival_is_not_caught_by_the_new_gate(self):
        # NS-0204 has no recorded arrival, and that absence IS the evidence (NS-4: the
        # driver never came, refund). The gate is for route cases only.
        for folder in (SYNTH, ORG):
            with self.subTest(pack=folder.parent.name):
                resolution, _payload = _run(_record(folder, "NS-0204.json"))
                self.assertNotEqual(OUTCOME_WITHHELD, resolution["outcome"])


class RiderClaimNotInventedTests(unittest.TestCase):
    """Finding 2: the structured field states only what a record states."""

    def test_disp_002_leaves_the_claim_unstated(self):
        # The organisers' own record has no structured claim; the rider's words are in the
        # description, where the Advocates read them.
        pack = _pack(_record(ORG, "DISP-002.json"))
        self.assertIsNone(pack["cancellation"]["rider_claims_driver_absent"])

    def test_a_rider_who_concedes_absence_is_not_labelled_as_denying_it(self):
        record = _record(ORG, "DISP-002.json")
        record["dispute_ticket"]["description"] = (
            "I overslept and never made it down. But one minute is not a fair wait."
        )
        self.assertIsNot(True, _pack(record)["cancellation"]["rider_claims_driver_absent"])

    def test_a_stated_claim_still_passes_through(self):
        for value in (True, False):
            with self.subTest(value=value):
                record = _record(ORG, "DISP-002.json")
                record["ryde_extensions"] = {"rider_claims_driver_absent": value}
                self.assertIs(value, _pack(record)["cancellation"]["rider_claims_driver_absent"])


class FiledByTests(unittest.TestCase):
    """Finding 3: the filing party is a fact about the record, never a default."""

    def _synth(self, value):
        record = _record(SYNTH, "NS-0201.json")
        record["filed_by"] = value
        return record

    def _organiser(self, value):
        record = _record(ORG, "DISP-002.json")
        record["dispute_ticket"]["filed_by"] = value
        return record

    def test_a_missing_or_unknown_party_is_rejected(self):
        for shape, make in (("ryde-synth-v1", self._synth), ("organiser-style-v1", self._organiser)):
            for bad in (None, "", "support_agent", 5):
                with self.subTest(shape=shape, filed_by=bad):
                    with self.assertRaises(DisputeError):
                        parse_dispute(make(bad))

    def test_an_absent_key_is_rejected(self):
        record = _record(SYNTH, "NS-0201.json")
        del record["filed_by"]
        with self.assertRaises(DisputeError):
            parse_dispute(record)

    def test_case_and_whitespace_are_forgiven(self):
        for shape, make in (("ryde-synth-v1", self._synth), ("organiser-style-v1", self._organiser)):
            for raw, want in (("RIDER", "rider"), (" Driver ", "driver")):
                with self.subTest(shape=shape, filed_by=raw):
                    self.assertEqual(want, parse_dispute(make(raw)).filed_by)


class UnusablePickupCoordinateTests(unittest.TestCase):
    """Finding 4: a present-but-unusable position is said to be unusable, not absent."""

    def _pack_with(self, block_key, value):
        record = _record(SYNTH, "NS-0201.json")
        record["cancellation"][block_key] = value
        return _pack(record)

    def test_string_coordinates_are_reported_as_unusable(self):
        for block_key in ("pickup_point", "driver_gps_at_arrival"):
            with self.subTest(block=block_key):
                pack = self._pack_with(block_key, {"lat": "1.2847", "lng": "103.8382"})
                self.assertIsNone(pack["cancellation"]["driver_distance_from_pickup_m"])
                notes = _all_notes(pack)
                self.assertIn("unusable", notes)
                self.assertNotIn("no driver position", notes)

    def test_an_absent_position_still_says_absent(self):
        record = _record(SYNTH, "NS-0201.json")
        del record["cancellation"]["driver_gps_at_arrival"]
        pack = _pack(record)
        self.assertIsNone(pack["cancellation"]["driver_distance_from_pickup_m"])
        self.assertNotIn("unusable", _all_notes(pack))

    def test_organiser_string_pickup_is_reported_as_unusable(self):
        record = _record(ORG, "DISP-002.json")
        pickup = record["trip_data"]["pickup_location"]
        pickup["lat"], pickup["lng"] = str(pickup["lat"]), str(pickup["lng"])
        pack = _pack(record)
        self.assertIsNone(pack["cancellation"]["driver_distance_from_pickup_m"])
        self.assertIn("unusable", _all_notes(pack))


class TwoFeeTests(unittest.TestCase):
    """Finding 5: a record's fees are all carried; none is dropped for the other."""

    def test_both_fees_survive_with_a_note(self):
        record = _record(ORG, "DISP-002.json")
        record["trip_data"]["cancellation_fee"] = 6.61
        record["trip_data"]["waiting_fee"] = 5.00
        pack = _pack(record)
        c = pack["cancellation"]
        self.assertEqual(6.61, c["cancellation_fee_sgd"])
        self.assertEqual(5.00, c["waiting_fee_sgd"])
        self.assertIn("both", _all_notes(pack))

    def test_a_single_waiting_fee_keeps_the_twin_numbers(self):
        # NS-0207 is a waiting fee in both packs; the compared field must still match.
        synth = _pack(_record(SYNTH, "NS-0207.json"))["cancellation"]
        org = _pack(_record(ORG, "NS-0207.json"))["cancellation"]
        self.assertEqual(synth["cancellation_fee_sgd"], org["cancellation_fee_sgd"])
        self.assertEqual(5.00, org["waiting_fee_sgd"])


if __name__ == "__main__":
    unittest.main()
