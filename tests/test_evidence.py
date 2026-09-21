"""The deterministic Evidence Pack: arithmetic, citation surface, and failure modes."""

from __future__ import annotations

import unittest

from app.dispute import parse_dispute
from app.evidence import EvidenceInputError, build_evidence_pack, haversine_km

from .support import NO_SHOW, ROUTE_DEVIATION, load_fixture_dispute


class RouteDeviationEvidenceTest(unittest.TestCase):
    def setUp(self):
        self.pack = build_evidence_pack(load_fixture_dispute(ROUTE_DEVIATION))

    def test_route_deviation_is_computed_from_the_gps_points(self):
        self.assertAlmostEqual(self.pack.route.actual_distance_km, 8.035, places=3)
        self.assertEqual(self.pack.route.estimated_distance_km, 6.4)
        self.assertAlmostEqual(self.pack.route.deviation_km, 1.635, places=3)
        self.assertAlmostEqual(self.pack.route.deviation_pct, 25.54, places=2)
        self.assertEqual(self.pack.route.point_count, 8)

    def test_duration_is_compared_with_the_estimate(self):
        self.assertEqual(self.pack.duration.actual_minutes, 27.0)
        self.assertEqual(self.pack.duration.estimated_minutes, 16.0)
        self.assertEqual(self.pack.duration.delta_minutes, 11.0)
        self.assertEqual(self.pack.duration.delta_pct, 68.75)

    def test_fare_is_recomputed_and_reconciles_with_the_charge(self):
        self.assertEqual(self.pack.fare.charged_sgd, 18.65)
        self.assertEqual(self.pack.fare.recomputed_sgd, 18.65)
        self.assertEqual(self.pack.fare.recomputed_estimated_route_sgd, 13.78)
        self.assertEqual(self.pack.fare.deviation_fare_delta_sgd, 4.87)
        self.assertEqual(self.pack.fare.difference_sgd, 0.0)
        self.assertTrue(self.pack.fare.breakdown_consistent)
        self.assertEqual(self.pack.fare.component_sum_sgd, 18.65)

    def test_chat_signals_are_counted(self):
        self.assertEqual(self.pack.chat.message_count, 5)
        self.assertEqual(self.pack.chat.rider_messages, 2)
        self.assertEqual(self.pack.chat.driver_messages, 3)
        self.assertEqual(self.pack.chat.negative_messages, 1)
        self.assertEqual(self.pack.chat.negative_messages_by_party["rider"], 1)
        self.assertIn("heuristic", self.pack.chat.method)

    def test_profile_rates_are_derived(self):
        self.assertAlmostEqual(self.pack.profiles.rider.upheld_rate, 1 / 3, places=4)
        self.assertAlmostEqual(self.pack.profiles.driver.upheld_rate, 2 / 7, places=4)

    def test_the_pack_carries_no_cancellation_for_a_route_case(self):
        self.assertIsNone(self.pack.cancellation)


class NoShowEvidenceTest(unittest.TestCase):
    def setUp(self):
        self.pack = build_evidence_pack(load_fixture_dispute(NO_SHOW))

    def test_wait_is_derived_from_the_timestamps(self):
        self.assertEqual(self.pack.cancellation.driver_wait_minutes, 6.5)
        self.assertEqual(self.pack.cancellation.arrival_to_cancel_minutes, 6.5)

    def test_distance_between_recorded_arrival_and_pickup_point(self):
        self.assertAlmostEqual(self.pack.cancellation.driver_distance_from_pickup_m, 650.7, places=1)

    def test_fee_and_flags_are_passed_through(self):
        self.assertEqual(self.pack.cancellation.cancellation_fee_sgd, 4.0)
        self.assertTrue(self.pack.cancellation.driver_marked_no_show)
        self.assertTrue(self.pack.cancellation.rider_claims_driver_absent)

    def test_unrecomputable_fare_is_null_and_explained(self):
        self.assertEqual(self.pack.fare.charged_sgd, 4.0)
        self.assertIsNone(self.pack.fare.recomputed_sgd)
        self.assertTrue(any("could not be recomputed" in note for note in self.pack.notes))

    def test_route_evidence_is_null_rather_than_guessed(self):
        self.assertIsNone(self.pack.route.actual_distance_km)
        self.assertEqual(self.pack.route.point_count, 0)


class CitationSurfaceTest(unittest.TestCase):
    def setUp(self):
        self.pack = build_evidence_pack(load_fixture_dispute(ROUTE_DEVIATION))

    def test_refs_are_dotted_paths_to_computed_fields(self):
        refs = self.pack.field_refs()
        self.assertIn("fare.deviation_fare_delta_sgd", refs)
        self.assertIn("route.deviation_pct", refs)
        self.assertEqual(refs, sorted(refs))

    def test_provenance_and_free_text_are_not_citable(self):
        refs = self.pack.field_refs()
        for forbidden in ("generated_at", "dispute_id", "schema_version", "method"):
            self.assertFalse(
                any(ref == forbidden or ref.endswith("." + forbidden) for ref in refs),
                "%s should not be citable" % forbidden,
            )
        self.assertFalse(any(ref.startswith("notes") for ref in refs))

    def test_value_at_resolves_a_real_ref(self):
        self.assertEqual(self.pack.value_at("fare.deviation_fare_delta_sgd"), 4.87)

    def test_value_at_rejects_an_invented_ref(self):
        with self.assertRaises(KeyError):
            self.pack.value_at("fare.overcharge_made_up")


class DeterminismTest(unittest.TestCase):
    def test_same_dispute_produces_an_identical_pack(self):
        dispute = load_fixture_dispute(ROUTE_DEVIATION)
        first = build_evidence_pack(dispute, generated_at="fixed").to_dict()
        second = build_evidence_pack(dispute, generated_at="fixed").to_dict()
        self.assertEqual(first, second)


class FailureModeTest(unittest.TestCase):
    def test_route_case_without_a_trip_is_refused(self):
        dispute = parse_dispute({"dispute_id": "X-1", "category": "route_deviation"})
        with self.assertRaises(EvidenceInputError):
            build_evidence_pack(dispute)

    def test_no_show_case_without_a_cancellation_record_is_refused(self):
        dispute = parse_dispute({"dispute_id": "X-2", "category": "no_show_charge"})
        with self.assertRaises(EvidenceInputError):
            build_evidence_pack(dispute)


class HaversineTest(unittest.TestCase):
    def test_one_degree_of_latitude_is_about_111_km(self):
        distance = haversine_km({"lat": 1.0, "lng": 103.0}, {"lat": 2.0, "lng": 103.0})
        self.assertAlmostEqual(distance, 111.19, places=1)

    def test_missing_coordinates_return_none(self):
        self.assertIsNone(haversine_km({"lat": 1.0}, {"lat": 2.0, "lng": 103.0}))


if __name__ == "__main__":
    unittest.main()
