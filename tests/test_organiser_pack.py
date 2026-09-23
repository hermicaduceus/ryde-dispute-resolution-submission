"""The organiser-style pack: same facts as ryde-synth-v1, in the organisers' shape.

Non-app test. The organiser pack is a TRANSFORM of the synthesised corpus, so its value
depends on one property: every number a ruling could rest on is identical to its
ryde-synth-v1 twin. A conversion that shifts a timestamp by a minute or rounds a fare
silently changes which rule fires, and the ground-truth label copied across becomes a lie.
These tests compare the two packs field by field, so that drift fails here rather than in
an evaluation score.

They also pin the organisers' own sample: it must sit in the pack byte-for-byte as the
organisers wrote it, and its expected ruling must never leak into the record.
"""

from __future__ import annotations

import json
import math
import re
import unittest
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PACKS = REPO / "data" / "packs"
SYNTH = PACKS / "ryde-synth-v1"
ORG = PACKS / "organiser-style-v1"
SAMPLE_MD = REPO / "tools" / "organiser_samples" / "DISP-002.md"

ORGANISER_TOP_LEVEL = {
    "dispute_ticket",
    "rider_profile",
    "driver_profile",
    "trip_data",
    "gps_telemetry",
    "chat_logs",
    "app_events",
}


def _load(pack: Path):
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted((pack / "disputes").glob("*.json"))}


def _labels(pack: Path):
    data = json.loads((pack / "ground-truth.json").read_text(encoding="utf-8"))
    return {c["dispute_id"]: c for c in data["cases"]}


def _haversine_km(a, b):
    (lat1, lng1), (lat2, lng2) = a, b
    p1, p2 = math.radians(lat1), math.radians(lat2)
    h = math.sin(math.radians(lat2 - lat1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lng2 - lng1) / 2) ** 2
    return 2 * 6371.0088 * math.asin(math.sqrt(h))


def _length(points):
    return sum(_haversine_km((points[i]["lat"], points[i]["lng"]), (points[i + 1]["lat"], points[i + 1]["lng"])) for i in range(len(points) - 1))


class PackLayoutTests(unittest.TestCase):
    def test_both_packs_exist_with_manifest_and_labels(self):
        for pack in (SYNTH, ORG):
            with self.subTest(pack=pack.name):
                manifest = json.loads((pack / "pack.json").read_text(encoding="utf-8"))
                self.assertEqual(pack.name, manifest["name"])
                self.assertEqual(len(_load(pack)), manifest["case_count"])
                self.assertEqual(set(_load(pack)), set(_labels(pack)), "records and labels disagree")

    def test_the_old_flat_layout_is_gone(self):
        # Two copies of the corpus is exactly the drift the pack layout exists to prevent.
        self.assertFalse((REPO / "data" / "disputes").exists())
        self.assertFalse((REPO / "data" / "ground-truth.json").exists())

    def test_organiser_pack_is_the_synth_pack_plus_organiser_samples(self):
        synth, org = set(_load(SYNTH)), set(_load(ORG))
        self.assertTrue(synth < org)
        self.assertEqual({"DISP-002"}, org - synth)

    def test_labels_for_shared_cases_are_identical(self):
        # Our cases carry Ryde's published terms in both packs, so no label may change.
        synth, org = _labels(SYNTH), _labels(ORG)
        for dispute_id, label in synth.items():
            with self.subTest(dispute_id=dispute_id):
                self.assertEqual(label, org[dispute_id])


class OrganiserSampleTests(unittest.TestCase):
    def test_disp_002_is_byte_for_byte_the_organisers_json(self):
        block = re.search(r"```json\n(.*?)```", SAMPLE_MD.read_text(encoding="utf-8"), re.S).group(1)
        self.assertEqual(block, (ORG / "disputes" / "DISP-002.json").read_text(encoding="utf-8"))

    def test_disp_002_record_does_not_carry_its_expected_ruling(self):
        # The verdict ("Expected ruling: UPHELD") lives only in the markdown around the JSON.
        text = (ORG / "disputes" / "DISP-002.json").read_text(encoding="utf-8").lower()
        for leak in ("expected", "ruling", "evidence summary"):
            self.assertNotIn(leak, text)

    def test_disp_002_label_matches_the_organisers_stated_ruling(self):
        label = _labels(ORG)["DISP-002"]
        self.assertEqual("ruled", label["expected_outcome"])
        self.assertEqual("no action", label["expected_action"])  # charge upheld = no refund
        self.assertIn("UPHELD", label["label_source"])

    def test_disp_002_wait_arithmetic_behind_the_label(self):
        # The label's rationale rests on these three numbers; recompute them from the record.
        trip = _load(ORG)["DISP-002"]["trip_data"]
        t = datetime.fromisoformat
        self.assertEqual(8.0, (t(trip["cancellation_time"]) - t(trip["driver_arrival_time"])).total_seconds() / 60)
        self.assertEqual(6.0, (t(trip["cancellation_time"]) - t(trip["scheduled_time"])).total_seconds() / 60)
        self.assertEqual(8, _load(ORG)["DISP-002"]["cancellation_policy"]["no_show_threshold_min"])


class OrganiserShapeTests(unittest.TestCase):
    def setUp(self):
        self.synth = _load(SYNTH)
        self.org = _load(ORG)

    def test_every_converted_case_has_the_organiser_top_level_blocks(self):
        for dispute_id in self.synth:
            with self.subTest(dispute_id=dispute_id):
                self.assertTrue(ORGANISER_TOP_LEVEL <= set(self.org[dispute_id]))

    def test_ticket_identity_and_category_carry_over(self):
        for dispute_id, s in self.synth.items():
            with self.subTest(dispute_id=dispute_id):
                ticket = self.org[dispute_id]["dispute_ticket"]
                self.assertEqual(s["dispute_id"], ticket["dispute_id"])
                self.assertEqual(s["category"], ticket["dispute_type"])
                self.assertEqual(s["filed_by"], ticket["filed_by"])
                self.assertEqual(s["filed_at"], ticket["filed_at"])
                self.assertEqual(s["trip"]["trip_id"], ticket["trip_id"])

    def test_claim_and_intake_are_preserved_in_extensions(self):
        for dispute_id, s in self.synth.items():
            with self.subTest(dispute_id=dispute_id):
                ext = self.org[dispute_id]["ryde_extensions"]
                self.assertEqual(s["claim"], ext["claim"])
                self.assertEqual(s["intake"], ext["intake"])

    def test_profiles_carry_identical_numbers(self):
        for dispute_id, s in self.synth.items():
            with self.subTest(dispute_id=dispute_id):
                o = self.org[dispute_id]
                for side, key, upheld_key in (("rider", "rider_profile", "upheld"), ("driver", "driver_profile", "upheld_against")):
                    src, dst = s["profiles"][side], o[key]
                    self.assertEqual(src["party_id"], dst["%s_id" % side])
                    self.assertEqual(src["account_age_days"], dst["account_age_days"])
                    self.assertEqual(src["trips_completed"], dst["total_trips"])
                    self.assertEqual(src["rating"], dst["avg_rating"])
                    hist = dst["dispute_history"]
                    self.assertEqual(src["disputes_total"], hist["total_disputes"])
                    self.assertEqual(src["disputes_upheld"], hist[upheld_key])
                    self.assertEqual(src["disputes_total"] - src["disputes_upheld"], hist["rejected"])
                    # A fraud flag would be new evidence the synth twin does not carry.
                    self.assertEqual(0, dst["fraud_flags"])

    def test_chat_is_the_same_messages(self):
        for dispute_id, s in self.synth.items():
            with self.subTest(dispute_id=dispute_id):
                got = [(m["timestamp"], m["sender"], m["content"]) for m in self.org[dispute_id]["chat_logs"]]
                want = [(m["t"], m["sender"], m["text"]) for m in s["chat_log"]]
                self.assertEqual(want, got)
                self.assertTrue(all(m["type"] == "message" for m in self.org[dispute_id]["chat_logs"]))

    def test_route_cases_keep_every_number_the_evidence_pack_uses(self):
        for dispute_id, s in self.synth.items():
            if s["category"] != "route_deviation":
                continue
            with self.subTest(dispute_id=dispute_id):
                trip, org_trip = s["trip"], self.org[dispute_id]["trip_data"]
                self.assertEqual(trip["fare"], org_trip["fare"])
                self.assertEqual(trip["pickup_at"], org_trip["pickup_time"])
                self.assertEqual(trip["dropoff_at"], org_trip["dropoff_time"])
                self.assertEqual(trip["requested_at"], org_trip["requested_time"])
                self.assertEqual(trip["estimated_duration_min"], org_trip["estimated_duration_min"])
                # RD-0108 is the case whose missing estimate forces an escalation.
                self.assertEqual("estimated_distance_km" in trip, "estimated_distance_km" in org_trip)
                if "estimated_distance_km" in trip:
                    self.assertEqual(trip["estimated_distance_km"], org_trip["estimated_distance_km"])
                telemetry = self.org[dispute_id]["gps_telemetry"]
                self.assertEqual([p["t"] for p in trip["actual_route"]], [p["timestamp"] for p in telemetry])
                self.assertAlmostEqual(_length(trip["actual_route"]), _length(telemetry), delta=0.001)

    def test_long_routes_now_stay_in_singapore(self):
        # ryde-synth-v1's two longest traces walk out into Johor. The organiser pack names
        # places, so it re-walks them; every point must sit inside Singapore's bounding box.
        for dispute_id in ("RD-0104", "RD-0109"):
            with self.subTest(dispute_id=dispute_id):
                for p in self.org[dispute_id]["gps_telemetry"]:
                    self.assertTrue(1.20 <= p["lat"] <= 1.48 and 103.60 <= p["lng"] <= 104.05, p)

    def test_no_show_cases_keep_every_number_the_evidence_pack_uses(self):
        for dispute_id, s in self.synth.items():
            c = s.get("cancellation")
            if c is None:
                continue
            with self.subTest(dispute_id=dispute_id):
                o = self.org[dispute_id]
                trip = o["trip_data"]
                self.assertEqual(c.get("driver_arrived_at"), trip.get("driver_arrival_time"))
                self.assertEqual(c.get("wait_started_at"), trip.get("driver_wait_start"))
                end = trip.get("cancellation_time") or trip.get("rider_boarded_time")
                self.assertEqual(c["cancelled_at"], end)
                fee = trip.get("cancellation_fee", trip.get("waiting_fee"))
                self.assertEqual(c["cancellation_fee_sgd"], fee)
                self.assertEqual(c["rider_claims_driver_absent"], o["ryde_extensions"]["rider_claims_driver_absent"])
                self.assertEqual(c["driver_marked_no_show"], trip.get("cancellation_reason") == "rider_no_show")
                matched = [e for e in o["app_events"] if e["event_type"] == "driver_assigned"]
                self.assertEqual([c["matched_at"]], [e["timestamp"] for e in matched])
                self.assertEqual(ORG_POLICY_KEYS, set(o["cancellation_policy"]) & ORG_POLICY_KEYS)

    def test_arrival_position_is_the_synth_position_or_absent(self):
        # Where synth recorded the driver's GPS at arrival, the organiser trace's arrived
        # point is that exact coordinate. Where synth recorded none, there is NO trace: an
        # invented one would settle NS-3 on evidence the synth twin does not contain.
        for dispute_id, s in self.synth.items():
            c = s.get("cancellation")
            if c is None:
                continue
            with self.subTest(dispute_id=dispute_id):
                telemetry = self.org[dispute_id]["gps_telemetry"]
                gps = c.get("driver_gps_at_arrival")
                if gps is None:
                    self.assertEqual([], telemetry)
                    continue
                arrived = [p for p in telemetry if p["status"] == "arrived"]
                self.assertEqual(1, len(arrived))
                self.assertEqual((gps["lat"], gps["lng"]), (arrived[0]["lat"], arrived[0]["lng"]))
                self.assertEqual(c["driver_arrived_at"], arrived[0]["timestamp"])
                pickup = self.org[dispute_id]["trip_data"]["pickup_location"]
                self.assertEqual((c["pickup_point"]["lat"], c["pickup_point"]["lng"]), (pickup["lat"], pickup["lng"]))

    def test_synthetic_cases_carry_ryde_terms_not_the_organisers(self):
        for dispute_id, o in self.org.items():
            if dispute_id.startswith("DISP-") or "cancellation_policy" not in o:
                continue
            with self.subTest(dispute_id=dispute_id):
                policy = o["cancellation_policy"]
                self.assertEqual(3, policy["free_wait_time_min"])
                self.assertEqual(3, policy["no_show_threshold_min"])

    def test_descriptions_introduce_no_number(self):
        for dispute_id, s in self.synth.items():
            with self.subTest(dispute_id=dispute_id):
                description = self.org[dispute_id]["dispute_ticket"]["description"]
                source = " ".join([s["claim"]["text"]] + [str(v) for v in s["intake"].values()])
                for number in re.findall(r"\d+(?:\.\d+)?", description):
                    self.assertIn(number, source)
                self.assertNotIn("$", description)

    def test_no_label_key_leaks_into_any_organiser_record(self):
        for dispute_id in self.org:
            with self.subTest(dispute_id=dispute_id):
                blob = (ORG / "disputes" / ("%s.json" % dispute_id)).read_text(encoding="utf-8")
                for key in ("expected_outcome", "expected_action", "expected_amount_sgd", "decisive_rule_ids", "rationale"):
                    self.assertNotIn('"%s"' % key, blob)


ORG_POLICY_KEYS = {"free_wait_time_min", "no_show_threshold_min", "cancellation_fee_after_wait"}


if __name__ == "__main__":
    unittest.main()
