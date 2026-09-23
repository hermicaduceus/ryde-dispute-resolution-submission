"""The acceptance target for reading the organiser-style pack.

Non-app test, written BEFORE the reader exists, so it is RED until the CodeBuddy build lane
teaches app/ to read the organisers' record shape and to select a dataset pack.

The property it pins: a case and its organiser-style twin are the same facts in two
shapes (tests/test_organiser_pack.py proves that on the records), so the deterministic
Evidence Pack computed from each must agree on every number a ruling can rest on. A reader
that maps a field wrong (the wait measured from the wrong event, the arrival point taken
from the wrong telemetry row, a fare dropped) changes which rule fires, and it shows up
here as a mismatch on a named field rather than as a wrong ruling much later.

It also pins the pack selection contract: app/config.json names the default pack, the CLI
can override it per run, and a dispute can be named by id within the selected pack.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.dispute import load_dispute
from app.evidence import build_evidence_pack

REPO = Path(__file__).resolve().parent.parent
PACKS = REPO / "data" / "packs"
SYNTH = PACKS / "ryde-synth-v1" / "disputes"
ORG = PACKS / "organiser-style-v1" / "disputes"

# Evidence Pack fields a ruling can rest on. Everything else (generated_at, notes, the
# organiser-only extras a reader may add) is allowed to differ.
COMPARED = {
    "route": ("actual_distance_km", "estimated_distance_km", "deviation_km", "deviation_pct"),
    "duration": ("actual_minutes", "estimated_minutes", "delta_minutes", "delta_pct"),
    "fare": (
        "charged_sgd",
        "recomputed_sgd",
        "recomputed_estimated_route_sgd",
        "deviation_fare_delta_sgd",
        "difference_sgd",
        "component_sum_sgd",
        "breakdown_consistent",
    ),
    "cancellation": (
        "driver_arrived_at",
        "wait_started_at",
        "cancelled_at",
        "driver_wait_minutes",
        "arrival_to_cancel_minutes",
        "matching_to_cancel_minutes",
        "matching_anchor_source",
        "driver_marked_no_show",
        "rider_claims_driver_absent",
        "driver_distance_from_pickup_m",
        "cancellation_fee_sgd",
    ),
}


def _pack(path: Path):
    return build_evidence_pack(load_dispute(path), generated_at="2026-09-23T00:00:00+08:00").to_dict()


class OrganiserReaderEquivalenceTests(unittest.TestCase):
    def test_every_twin_yields_the_same_category_and_identity(self):
        for synth_path in sorted(SYNTH.glob("*.json")):
            with self.subTest(dispute_id=synth_path.stem):
                a = load_dispute(synth_path)
                b = load_dispute(ORG / synth_path.name)
                self.assertEqual(a.dispute_id, b.dispute_id)
                self.assertEqual(a.category, b.category)
                self.assertEqual(a.category_as_submitted, b.category_as_submitted)
                self.assertEqual(a.filed_by, b.filed_by)
                self.assertEqual(a.claim_amount_sgd, b.claim_amount_sgd)

    def test_every_twin_yields_the_same_evidence_numbers(self):
        for synth_path in sorted(SYNTH.glob("*.json")):
            dispute = load_dispute(synth_path)
            if not dispute.is_agent_handled:
                continue  # OS-0301 never reaches the Evidence Pack
            a, b = _pack(synth_path), _pack(ORG / synth_path.name)
            for block, fields in COMPARED.items():
                for name in fields:
                    with self.subTest(dispute_id=synth_path.stem, field="%s.%s" % (block, name)):
                        want = (a.get(block) or {}).get(name)
                        got = (b.get(block) or {}).get(name)
                        if isinstance(want, float) and isinstance(got, float):
                            self.assertAlmostEqual(want, got, places=3)
                        else:
                            self.assertEqual(want, got)

    def test_the_filing_window_is_established_from_either_shape(self):
        # The organiser shape files the date under dispute_ticket, ours at the top level.
        # Reading it from the raw record nulled the GEN-6 window for every organiser record
        # while the suite stayed green (found in build session four, pinned here).
        for synth_path in sorted(SYNTH.glob("*.json")):
            if not load_dispute(synth_path).is_agent_handled:
                continue
            a, b = _pack(synth_path)["filing"], _pack(ORG / synth_path.name)["filing"]
            for name in ("filed_at", "trip_reference_at", "days_since_trip", "window_established"):
                with self.subTest(dispute_id=synth_path.stem, field="filing.%s" % name):
                    self.assertEqual(a[name], b[name])
            with self.subTest(dispute_id=synth_path.stem, field="filing.window_established is true"):
                self.assertIs(True, b["window_established"])

    def test_profiles_yield_the_same_numbers(self):
        for synth_path in sorted(SYNTH.glob("*.json")):
            if not load_dispute(synth_path).is_agent_handled:
                continue
            a, b = _pack(synth_path)["profiles"], _pack(ORG / synth_path.name)["profiles"]
            for side in ("rider", "driver"):
                for name in ("party_id", "account_age_days", "trips_completed", "disputes_total", "disputes_upheld", "rating"):
                    with self.subTest(dispute_id=synth_path.stem, field="%s.%s" % (side, name)):
                        self.assertEqual(a[side][name], b[side][name])

    def test_chat_reaches_the_pack_unchanged(self):
        for synth_path in sorted(SYNTH.glob("*.json")):
            with self.subTest(dispute_id=synth_path.stem):
                a = load_dispute(synth_path).chat_log
                b = load_dispute(ORG / synth_path.name).chat_log
                self.assertEqual([(m["t"], m["sender"], m["text"]) for m in a], [(m["t"], m["sender"], m["text"]) for m in b])


class OrganiserSampleReaderTests(unittest.TestCase):
    """DISP-002 has no synth twin; pin the numbers against the organisers' own record."""

    def setUp(self):
        self.dispute = load_dispute(ORG / "DISP-002.json")
        self.pack = _pack(ORG / "DISP-002.json")

    def test_routes_to_the_agents_as_a_no_show(self):
        self.assertEqual("no_show_charge", self.dispute.category)
        self.assertTrue(self.dispute.is_agent_handled)

    def test_wait_runs_from_arrival_and_is_eight_minutes(self):
        c = self.pack["cancellation"]
        self.assertEqual("2026-09-13T08:43:00+08:00", c["driver_arrived_at"])
        self.assertEqual("2026-09-13T08:51:00+08:00", c["cancelled_at"])
        self.assertAlmostEqual(8.0, c["driver_wait_minutes"], places=3)

    def test_driver_was_at_the_pickup_point(self):
        # The telemetry row with status "arrived" sits on the pickup coordinates.
        self.assertAlmostEqual(0.0, self.pack["cancellation"]["driver_distance_from_pickup_m"], places=1)

    def test_fee_and_no_show_mark(self):
        c = self.pack["cancellation"]
        self.assertEqual(5.00, c["cancellation_fee_sgd"])
        self.assertIs(True, c["driver_marked_no_show"])

    def test_matching_is_anchored_on_the_driver_assigned_event(self):
        c = self.pack["cancellation"]
        self.assertEqual("2026-09-13T08:30:15+08:00", c["matching_anchor_at"])

    def test_the_case_policy_reaches_the_pack(self):
        # The organisers' per-case terms (5 min free, 8 min threshold, $5.00) must be
        # visible to the agents; the synth cases carry Ryde's 3-minute terms the same way.
        case_policy = self.pack["cancellation"]["case_policy"]
        self.assertEqual(5, case_policy["free_wait_time_min"])
        self.assertEqual(8, case_policy["no_show_threshold_min"])
        self.assertEqual(5.00, case_policy["cancellation_fee_after_wait"])

    def test_profiles_carry_the_fraud_flag(self):
        rider = self.pack["profiles"]["rider"]
        self.assertEqual("R-7823", rider["party_id"])
        self.assertEqual(4, rider["disputes_total"])
        self.assertEqual(1, rider["disputes_upheld"])
        self.assertEqual(1, rider["fraud_flags"])

    def test_call_attempts_are_not_lost(self):
        # A call is stronger evidence of a contact attempt than a message; the organiser
        # chat distinguishes them with "type", and that must survive into the dispute.
        types = [m.get("type") for m in self.dispute.chat_log]
        self.assertIn("call", types)


class PackSelectionTests(unittest.TestCase):
    def test_config_names_the_organiser_pack_as_default(self):
        from app.config import load_config

        config = load_config()
        self.assertEqual("organiser-style-v1", config.dataset_pack)
        self.assertEqual(PACKS / "organiser-style-v1", config.dataset_pack_dir)

    def test_cli_runs_a_dispute_by_id_from_the_selected_pack(self):
        from app.cli import main

        for pack, dispute_id in (("ryde-synth-v1", "NS-0201"), ("organiser-style-v1", "DISP-002")):
            with self.subTest(pack=pack), tempfile.TemporaryDirectory() as tmp:
                code = main(["--pack", pack, "--dispute", dispute_id, "--out", tmp, "--run-id", "t"])
                self.assertEqual(0, code)
                case_file = json.loads((Path(tmp) / "t" / "case_file.json").read_text(encoding="utf-8"))
                self.assertEqual(dispute_id, case_file["dispute_id"])

    def test_cli_still_accepts_a_path(self):
        from app.cli import main

        with tempfile.TemporaryDirectory() as tmp:
            code = main(["--dispute", str(SYNTH / "RD-0101.json"), "--out", tmp, "--run-id", "t"])
            self.assertEqual(0, code)

    def test_an_unknown_pack_fails_cleanly(self):
        from app.cli import main

        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(1, main(["--pack", "no-such-pack", "--dispute", "RD-0101", "--out", tmp]))


if __name__ == "__main__":
    unittest.main()
