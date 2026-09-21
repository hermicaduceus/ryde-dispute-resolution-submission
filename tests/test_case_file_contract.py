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
import tempfile
import unittest
from pathlib import Path

from app.dispute import load_dispute
from app.evidence import build_evidence_pack
from app.schemas import ContractError, JudgeRuling

REPO = Path(__file__).resolve().parent.parent
CORPUS = REPO / "data" / "disputes"


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


if __name__ == "__main__":
    unittest.main()
