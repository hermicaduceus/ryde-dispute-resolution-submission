"""The case file's shape is a contract the UI renders against.

`ui/` reads `case_file.json`. Every field it displays must exist, be named consistently,
and be reachable from the citation surface — otherwise the UI is built against a shape
that drifts underneath it.

These tests were added when the case-file contract was frozen ahead of the UI build, and
they cover three fields an adversarial review found MISSING: the Judge could not cite the
evidence behind its ruling (so a case file could not explain itself), and three policy
rules referenced facts the Evidence Pack had no way to express, which made those rules
unenforceable no matter how well the model reasoned.
"""

from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path

from app.dispute import load_dispute
from app.evidence import build_evidence_pack
from app.schemas import ContractError, JudgeRuling

REPO = Path(__file__).resolve().parent.parent
CORPUS = REPO / "data" / "disputes"

#: Sentinel meaning "remove this key entirely", distinct from setting it to None.
_ABSENT = object()


def _pack(name: str) -> dict:
    return build_evidence_pack(load_dispute(CORPUS / name)).to_dict()


class JudgeCitesItsEvidenceTest(unittest.TestCase):
    """GEN-2: a ruling must name the pack fields it rests on.

    Without this the case-file view can show WHAT was decided but never WHY, and the
    human receiving an escalation has nothing to check the reasoning against.
    """

    def _payload(self, **overrides):
        payload = {
            "action": "refund",
            "recommended_amount_sgd": 5.81,
            "confidence": 0.9,
            "explanation": "test",
            "cited_rule_ids": ["GEN-1"],
            "cited_evidence_refs": ["route.deviation_km", "fare.deviation_fare_delta_sgd"],
        }
        payload.update(overrides)
        return payload

    def test_the_ruling_carries_its_cited_evidence(self):
        ruling = JudgeRuling.from_payload(self._payload(), agent="judge")
        self.assertEqual(
            ["route.deviation_km", "fare.deviation_fare_delta_sgd"], ruling.cited_evidence_refs
        )

    def test_the_cited_evidence_survives_serialisation(self):
        """The UI reads the serialised dict, not the dataclass."""
        ruling = JudgeRuling.from_payload(self._payload(), agent="judge")
        self.assertIn("cited_evidence_refs", ruling.to_dict())
        self.assertEqual(2, len(ruling.to_dict()["cited_evidence_refs"]))

    def test_an_uncited_ruling_is_flagged_not_rejected(self):
        """Missing citations make a ruling unreviewable, not invalid — say so in the file."""
        ruling = JudgeRuling.from_payload(
            self._payload(cited_evidence_refs=[]), agent="judge"
        )
        self.assertEqual([], ruling.cited_evidence_refs)
        self.assertTrue(
            any("evidence" in note for note in ruling.validation["notes"]),
            "a ruling citing no evidence was recorded as if fully grounded",
        )

    def test_a_malformed_citation_list_is_rejected(self):
        """A bare string is not a citation list. Reject it rather than coercing.

        Coercing would invent a citation the model never made; the same rule already
        governs cited_rule_ids, so the two stay consistent.
        """
        with self.assertRaises(ContractError):
            JudgeRuling.from_payload(
                self._payload(cited_evidence_refs="route.deviation_km"), agent="judge"
            )

    def test_an_end_to_end_run_records_the_judges_citations(self):
        from app.events import EventLog
        from app.llm.mock import MockLLMClient
        from app.pipeline import run_dispute
        from app.policy import load_policy

        with tempfile.TemporaryDirectory() as tmp:
            case = run_dispute(
                dispute=load_dispute(CORPUS / "RD-0101.json"),
                llm=MockLLMClient(),
                policy=load_policy(REPO / "docs" / "policy.md"),
                events=EventLog(Path(tmp) / "run", "citation-test"),
                confidence_threshold=0.65,
            )
        ruling = case.to_dict()["resolution"]["ruling"]

        self.assertTrue(
            ruling["cited_evidence_refs"],
            "the pipeline produced a ruling with no evidence citations",
        )
        self.assertEqual(
            [],
            ruling["validation"]["unknown_evidence_refs"],
            "the judge cited pack fields that do not exist",
        )

    def test_every_cited_ref_resolves_against_the_pack(self):
        """A citation the pack cannot resolve is worse than none: it looks grounded."""
        from app.events import EventLog
        from app.llm.mock import MockLLMClient
        from app.pipeline import run_dispute
        from app.policy import load_policy

        pack_refs = set(build_evidence_pack(load_dispute(CORPUS / "NS-0201.json")).field_refs())
        with tempfile.TemporaryDirectory() as tmp:
            case = run_dispute(
                dispute=load_dispute(CORPUS / "NS-0201.json"),
                llm=MockLLMClient(),
                policy=load_policy(REPO / "docs" / "policy.md"),
                events=EventLog(Path(tmp) / "run", "citation-test"),
                confidence_threshold=0.65,
            )
        for ref in case.to_dict()["resolution"]["ruling"]["cited_evidence_refs"]:
            self.assertIn(ref, pack_refs, "the judge cited %r, which is not a pack field" % ref)


class FilingWindowFieldTest(unittest.TestCase):
    """GEN-6 needs elapsed days computed, because the Judge may not do arithmetic."""

    def test_the_pack_computes_days_since_the_trip(self):
        filing = _pack("RD-0101.json")["filing"]
        self.assertIsNotNone(filing["days_since_trip"])
        self.assertTrue(filing["window_established"])

    def test_a_missing_filing_date_is_reported_not_guessed(self):
        record = json.loads((CORPUS / "RD-0101.json").read_text())
        del record["filed_at"]
        from app.dispute import parse_dispute

        pack = build_evidence_pack(parse_dispute(record)).to_dict()
        self.assertIsNone(pack["filing"]["days_since_trip"])
        self.assertFalse(
            pack["filing"]["window_established"],
            "an unmeasurable filing window was reported as established",
        )
        self.assertTrue(
            any("filing window" in note for note in pack["notes"]),
            "the window could not be established and nothing said so",
        )

    def test_the_filing_days_are_citable(self):
        refs = build_evidence_pack(load_dispute(CORPUS / "RD-0101.json")).field_refs()
        self.assertIn("filing.days_since_trip", refs)

    def test_the_reference_timestamp_prefers_the_end_of_the_trip(self):
        """GEN-6 runs from the trip, and a trip ends at dropoff."""
        filing = _pack("RD-0101.json")["filing"]
        record = json.loads((CORPUS / "RD-0101.json").read_text())
        self.assertEqual(record["trip"]["dropoff_at"], filing["trip_reference_at"])

    def test_a_cancelled_trip_measures_from_the_cancellation(self):
        """A no-show has no dropoff, so the chain must reach cancelled_at.

        Without this the fallback silently skips to booking time, which for an advance
        booking can be days earlier and would misplace the filing window entirely.
        """
        filing = _pack("NS-0201.json")["filing"]
        record = json.loads((CORPUS / "NS-0201.json").read_text())
        self.assertEqual(record["cancellation"]["cancelled_at"], filing["trip_reference_at"])


class MatchingToCancelFieldTest(unittest.TestCase):
    """NS-1's free window runs from matching, which nothing previously measured."""

    def test_the_pack_computes_minutes_from_matching_to_cancellation(self):
        cancellation = _pack("NS-0206.json")["cancellation"]
        self.assertIsNotNone(cancellation["matching_to_cancel_minutes"])

    def test_the_free_window_case_measures_inside_three_minutes(self):
        """NS-0206's whole label depends on this number being under 3."""
        cancellation = _pack("NS-0206.json")["cancellation"]
        self.assertLessEqual(
            cancellation["matching_to_cancel_minutes"],
            3.0,
            "NS-0206 is labelled a refund under NS-1's 3-minute free window, but the pack "
            "measures the cancellation outside it",
        )

    def test_a_late_cancellation_measures_outside_the_window(self):
        cancellation = _pack("NS-0204.json")["cancellation"]
        self.assertGreater(cancellation["matching_to_cancel_minutes"], 3.0)

    def test_the_interval_is_citable(self):
        refs = build_evidence_pack(load_dispute(CORPUS / "NS-0206.json")).field_refs()
        self.assertIn("cancellation.matching_to_cancel_minutes", refs)


class ServiceTypeFieldTest(unittest.TestCase):
    """GEN-1 excludes RydeTAXI from Section 4, which needs the service visible."""

    def test_the_pack_carries_the_service_type(self):
        self.assertEqual("RydeX", _pack("NS-0201.json")["service_type"])

    def test_the_service_type_varies_across_the_corpus(self):
        """A field with one value everywhere proves nothing about the rule that reads it."""
        services = {
            build_evidence_pack(load_dispute(path)).to_dict()["service_type"]
            for path in CORPUS.glob("*.json")
        }
        self.assertGreater(
            len({s for s in services if s}), 1, "every corpus case uses the same service type"
        )

    def test_a_missing_service_type_is_reported_not_guessed(self):
        record = json.loads((CORPUS / "NS-0201.json").read_text())
        del record["trip"]["service_type"]
        from app.dispute import parse_dispute

        pack = build_evidence_pack(parse_dispute(record)).to_dict()
        self.assertIsNone(pack["service_type"])
        self.assertTrue(
            any("service type" in note for note in pack["notes"]),
            "an unknown service type was silently treated as ordinary",
        )

    def test_a_service_alias_is_normalised(self):
        record = json.loads((CORPUS / "NS-0201.json").read_text())
        record["trip"]["service_type"] = "ryde taxi"
        from app.dispute import parse_dispute

        self.assertEqual(
            "RydeTAXI", build_evidence_pack(parse_dispute(record)).to_dict()["service_type"]
        )


class CaseFileShapeTest(unittest.TestCase):
    """The keys the UI will render must be present and stable."""

    def _case_file(self, name: str) -> dict:
        from app.events import EventLog
        from app.llm.mock import MockLLMClient
        from app.pipeline import run_dispute
        from app.policy import load_policy

        with tempfile.TemporaryDirectory() as tmp:
            case = run_dispute(
                dispute=load_dispute(CORPUS / name),
                llm=MockLLMClient(),
                policy=load_policy(REPO / "docs" / "policy.md"),
                events=EventLog(Path(tmp) / "run", "shape-test"),
                confidence_threshold=0.65,
            )
        return case.to_dict()

    def test_the_case_file_has_the_sections_the_ui_renders(self):
        case = self._case_file("RD-0101.json")
        for key in ("run_id", "dispute_id", "category", "evidence_pack", "claims", "resolution", "events"):
            self.assertIn(key, case, "the case file lost the %r section" % key)

    def test_both_advocate_claims_are_present_and_distinguishable(self):
        claims = self._case_file("RD-0101.json")["claims"]
        self.assertIn("rider", claims)
        self.assertIn("driver", claims)
        self.assertNotEqual(
            claims["rider"]["requested_outcome"],
            claims["driver"]["requested_outcome"],
            "both advocates asked for the same thing, so the view has no argument to show",
        )

    def test_the_evidence_pack_carries_the_three_new_fields(self):
        pack = self._case_file("NS-0201.json")["evidence_pack"]
        self.assertIn("service_type", pack)
        self.assertIn("filing", pack)
        self.assertIn("matching_to_cancel_minutes", pack["cancellation"])

    def test_the_resolution_shows_which_outcome_it_is(self):
        case = self._case_file("RD-0101.json")["resolution"]
        self.assertIn(case["outcome"], ("ruled", "withheld", "human_review"))
        self.assertTrue(case["party_message"])

    def test_a_withheld_case_file_exposes_the_candidate_separately_from_the_ruling(self):
        """The UI must be able to show a human the withheld ruling without showing parties."""
        case = self._case_file("RD-0109.json")["resolution"]
        self.assertEqual("withheld", case["outcome"])
        self.assertIsNone(case.get("ruling"))
        self.assertIsNotNone(case["withheld_candidate"])

    def test_every_event_carries_what_a_timeline_needs(self):
        for event in self._case_file("RD-0101.json")["events"]:
            for key in ("seq", "ts", "type", "from", "to", "summary"):
                self.assertIn(key, event, "event %r cannot be rendered on a timeline" % event)


class MatchingAnchorProvenanceTest(unittest.TestCase):
    """Booking time is not matching time, and the pack must not conflate them.

    NS-1's free window is 3 minutes wide and runs from matching. Booking happens first,
    so measuring from booking overstates the interval and can deny a rider a free
    cancellation they were entitled to. The substitution is allowed, but never silent.
    """

    def _pack_with(self, **changes):
        record = json.loads((CORPUS / "NS-0206.json").read_text())
        for key, value in changes.items():
            if value is _ABSENT:
                record["cancellation"].pop(key, None)
            else:
                record["cancellation"][key] = value
        from app.dispute import parse_dispute

        return build_evidence_pack(parse_dispute(record)).to_dict()

    def test_the_anchor_actually_used_is_named(self):
        cancellation = _pack("NS-0206.json")["cancellation"]
        self.assertEqual("matched_at", cancellation["matching_anchor_source"])
        self.assertIsNotNone(cancellation["matching_anchor_at"])

    def test_the_corpus_measures_from_a_real_matching_time(self):
        """If the corpus had no matched_at, every label would rest on a proxy."""
        for path in CORPUS.glob("NS-*.json"):
            cancellation = build_evidence_pack(load_dispute(path)).to_dict()["cancellation"]
            self.assertEqual(
                "matched_at",
                cancellation["matching_anchor_source"],
                "%s measures NS-1's window from a proxy, so its label is not trustworthy"
                % path.name,
            )

    def test_booking_time_and_matching_time_are_distinct_in_the_corpus(self):
        """Equal timestamps would make a proxy bug invisible."""
        record = json.loads((CORPUS / "NS-0206.json").read_text())
        self.assertNotEqual(
            record["trip"]["requested_at"],
            record["cancellation"]["matched_at"],
            "booking and matching coincide, so measuring from the wrong one looks correct",
        )

    def test_falling_back_to_booking_time_is_flagged(self):
        pack = self._pack_with(matched_at=_ABSENT)
        cancellation = pack["cancellation"]

        self.assertEqual("trip.requested_at", cancellation["matching_anchor_source"])
        self.assertTrue(
            any("proxy" in note for note in cancellation["notes"]),
            "the interval was measured from booking time and nothing said so",
        )

    def test_the_proxy_produces_a_longer_interval_than_the_truth(self):
        """The direction of the error matters: it is never in the rider's favour."""
        real = _pack("NS-0206.json")["cancellation"]["matching_to_cancel_minutes"]
        proxy = self._pack_with(matched_at=_ABSENT)["cancellation"][
            "matching_to_cancel_minutes"
        ]
        self.assertGreater(proxy, real)

    def test_the_anchor_is_citable(self):
        refs = build_evidence_pack(load_dispute(CORPUS / "NS-0206.json")).field_refs()
        self.assertIn("cancellation.matching_anchor_source", refs)


class ThresholdRoundingTest(unittest.TestCase):
    """Rounding must never carry a value across a policy boundary it did not cross.

    Both fields feed an upper-bound test the Judge applies literally and cannot
    recompute, so the displayed figure must not flatter the claim.
    """

    def test_a_cancellation_just_over_three_minutes_does_not_read_as_three(self):
        record = json.loads((CORPUS / "NS-0206.json").read_text())
        record["cancellation"]["cancelled_at"] = "2026-09-14T19:03:02+08:00"
        from app.dispute import parse_dispute

        minutes = build_evidence_pack(parse_dispute(record)).to_dict()["cancellation"][
            "matching_to_cancel_minutes"
        ]
        self.assertGreater(
            minutes,
            3.0,
            "3 min 2 s displayed as inside NS-1's free window, which it is not",
        )

    def test_a_filing_just_over_thirty_days_does_not_read_as_thirty(self):
        record = json.loads((CORPUS / "RD-0101.json").read_text())
        record["filed_at"] = "2026-10-14T10:01:07+08:00"  # 30 days + 7 seconds
        from app.dispute import parse_dispute

        days = build_evidence_pack(parse_dispute(record)).to_dict()["filing"][
            "days_since_trip"
        ]
        self.assertGreater(
            days, 30.0, "a filing outside GEN-6's window displayed as inside it"
        )

    def test_the_precision_is_fine_enough_to_matter(self):
        """A coarser field would hide the boundary cases above."""
        record = json.loads((CORPUS / "NS-0206.json").read_text())
        record["cancellation"]["cancelled_at"] = "2026-09-14T19:02:30+08:00"
        from app.dispute import parse_dispute

        self.assertEqual(
            2.5,
            build_evidence_pack(parse_dispute(record)).to_dict()["cancellation"][
                "matching_to_cancel_minutes"
            ],
            "sub-minute precision was lost, so a 3-minute threshold cannot be applied",
        )

    def test_the_filing_window_keeps_sub_day_precision(self):
        """Whole-day granularity would put a same-day filing a day out."""
        record = json.loads((CORPUS / "RD-0101.json").read_text())
        record["filed_at"] = "2026-09-20T10:01:00+08:00"  # exactly 6 days later
        from app.dispute import parse_dispute

        self.assertEqual(
            6.0,
            build_evidence_pack(parse_dispute(record)).to_dict()["filing"]["days_since_trip"],
            "an exact 6-day interval did not report as 6.0",
        )

        record["filed_at"] = "2026-09-20T22:01:00+08:00"  # 6.5 days
        self.assertEqual(
            6.5,
            build_evidence_pack(parse_dispute(record)).to_dict()["filing"]["days_since_trip"],
            "day precision was lost, so GEN-6's boundary cannot be applied",
        )


class ServiceTypeNormalisationTest(unittest.TestCase):
    """Every alias in the table must be reachable, and casing must not defeat it."""

    CASES = [
        ("RydeX", "RydeX"),
        ("RYDEX", "RydeX"),
        ("ryde x", "RydeX"),
        ("ryde-x", "RydeX"),
        ("Ryde_XL", "RydeXL"),
        ("ryde xl", "RydeXL"),
        ("RydeTaxi", "RydeTAXI"),
        ("ryde-taxi", "RydeTAXI"),
        ("taxi", "RydeTAXI"),
        ("ryde  pool", "RydePOOL"),
        ("RYDEEXEC", "RydeEXEC"),
    ]

    def _service_for(self, value):
        record = json.loads((CORPUS / "NS-0201.json").read_text())
        record["trip"]["service_type"] = value
        from app.dispute import parse_dispute

        return build_evidence_pack(parse_dispute(record)).to_dict()["service_type"]

    def test_every_alias_form_normalises(self):
        for given, expected in self.CASES:
            self.assertEqual(
                expected, self._service_for(given), "%r did not normalise" % given
            )

    def test_an_unrecognised_service_is_passed_through_not_discarded(self):
        """The record did state a service; nulling it would claim otherwise."""
        self.assertEqual("GrabShare", self._service_for("GrabShare"))

    def test_every_table_entry_is_reachable(self):
        """A key the lookup can never match is dead code pretending to be coverage."""
        from app.evidence.compute import _SERVICE_TYPES

        for key in _SERVICE_TYPES:
            self.assertEqual(
                key,
                re.sub(r"[\s_-]+", "", key.lower()),
                "table key %r is not in normalised form, so the lookup can never match it"
                % key,
            )


class NoteplacementTest(unittest.TestCase):
    """A null must be explained where it is rendered, not only at the top level."""

    def test_an_unverifiable_filing_window_explains_itself_in_place(self):
        record = json.loads((CORPUS / "RD-0101.json").read_text())
        del record["filed_at"]
        from app.dispute import parse_dispute

        filing = build_evidence_pack(parse_dispute(record)).to_dict()["filing"]
        self.assertIsNone(filing["days_since_trip"])
        self.assertTrue(
            filing["notes"], "the filing block shows an unexplained null to anything rendering it"
        )

    def test_an_unparseable_filing_date_is_not_displayed_as_a_date(self):
        record = json.loads((CORPUS / "RD-0101.json").read_text())
        record["filed_at"] = "not-a-date"
        from app.dispute import parse_dispute

        filing = build_evidence_pack(parse_dispute(record)).to_dict()["filing"]
        self.assertIsNone(
            filing["filed_at"], "garbage was carried into the pack looking like a timestamp"
        )
        self.assertIsNone(filing["days_since_trip"])


class SchemaVersionTest(unittest.TestCase):
    def test_the_pack_declares_a_version_reflecting_its_current_shape(self):
        """Additive changes still change the shape a consumer must handle."""
        from app.evidence.schema import EVIDENCE_SCHEMA_VERSION

        pack = _pack("NS-0201.json")
        self.assertEqual(EVIDENCE_SCHEMA_VERSION, pack["schema_version"])
        self.assertNotEqual(
            "1.0",
            EVIDENCE_SCHEMA_VERSION,
            "the pack gained service_type, filing and the matching anchor since 1.0",
        )


class HumanReviewShapeTest(unittest.TestCase):
    """The third outcome renders differently and was previously unpinned."""

    def _human_review_case(self):
        from app.events import EventLog
        from app.llm.mock import MockLLMClient
        from app.pipeline import run_dispute
        from app.policy import load_policy

        with tempfile.TemporaryDirectory() as tmp:
            case = run_dispute(
                dispute=load_dispute(CORPUS / "OS-0301.json"),
                llm=MockLLMClient(),
                policy=load_policy(REPO / "docs" / "policy.md"),
                events=EventLog(Path(tmp) / "run", "human-review-test"),
                confidence_threshold=0.65,
            )
        return case.to_dict()

    def test_an_out_of_scope_case_is_routed_without_a_ruling(self):
        case = self._human_review_case()
        self.assertEqual("human_review", case["resolution"]["outcome"])
        self.assertIsNone(case["resolution"].get("ruling"))

    def test_the_view_can_tell_why_there_is_no_evidence_or_argument(self):
        """Null sections must be distinguishable from a failed run."""
        case = self._human_review_case()
        self.assertIsNone(case["evidence_pack"])
        self.assertTrue(
            case["resolution"]["party_message"],
            "the parties were told nothing about an out-of-scope filing",
        )


if __name__ == "__main__":
    unittest.main()
