"""The gates that stand between a ruling and the parties, and the input sanity checks.

Every test here was written because a review found the behaviour MISSING, not because
the behaviour looked worth confirming. Each one fails on the code as it stood before
2026-09-21 evening:

  - ESC-4's SGD 50 cap existed only in the policy document and the corpus labels.
    Nothing enforced it: a live run of RD-0109 delivered "refund of SGD 55.16" to the
    parties at confidence 0.86.
  - Out-of-order timestamps produced negative durations that flowed into the fare
    formula, yielding a precise, confident, wrong overcharge figure.
  - The judge contract accepted NaN and Infinity, so a party could be told
    "Decision: refund of SGD nan."

A gate a model is merely ASKED to respect in a prompt is not a gate. These check the
ones enforced in Python.
"""

from __future__ import annotations

import json
import math
import tempfile
import unittest
from pathlib import Path

from app.dispute import parse_dispute
from app.evidence import build_evidence_pack
from app.schemas import (
    OUTCOME_RULED,
    OUTCOME_WITHHELD,
    UNDER_REVIEW_MESSAGE,
    ContractError,
    JudgeRuling,
)

from tests.support import DEFAULT_THRESHOLD, load_fixture_dispute, run_fixture

REPO = Path(__file__).resolve().parent.parent
CORPUS = REPO / "data" / "disputes"


def _load_record(name: str) -> dict:
    return json.loads((CORPUS / name).read_text(encoding="utf-8"))


class AutonomousCapGateTest(unittest.TestCase):
    """ESC-4: a remedy above the cap is prepared, never issued."""

    def _run(self, record: dict, cap: float):
        from app.events import EventLog
        from app.llm.mock import MockLLMClient
        from app.pipeline import run_dispute
        from app.policy import load_policy

        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            return run_dispute(
                dispute=parse_dispute(record),
                llm=MockLLMClient(),
                policy=load_policy(REPO / "docs" / "policy.md"),
                events=EventLog(run_dir, "cap-test"),
                confidence_threshold=DEFAULT_THRESHOLD,
                autonomous_cap_sgd=cap,
            )

    def test_an_above_cap_refund_is_withheld_even_at_high_confidence(self):
        """The regression this suite exists for: SGD 55.16 was delivered to the parties."""
        case = self._run(_load_record("RD-0109.json"), cap=50.00)
        resolution = case.to_dict()["resolution"]

        self.assertEqual(OUTCOME_WITHHELD, resolution["outcome"])
        self.assertTrue(resolution["escalated_for_human_review"])
        self.assertEqual(UNDER_REVIEW_MESSAGE, resolution["party_message"])
        self.assertIsNone(resolution.get("ruling"))

    def test_the_withheld_amount_never_reaches_the_parties(self):
        case = self._run(_load_record("RD-0109.json"), cap=50.00)
        resolution = case.to_dict()["resolution"]
        candidate = resolution["withheld_candidate"]

        self.assertGreater(candidate["recommended_amount_sgd"], 50.00)
        self.assertNotIn("55", resolution["party_message"])
        self.assertNotIn(str(candidate["recommended_amount_sgd"]), resolution["party_message"])

    def test_the_gate_fires_on_the_cap_and_not_on_confidence(self):
        """The candidate must be confident — proving the CAP withheld it, not the gate above."""
        case = self._run(_load_record("RD-0109.json"), cap=50.00)
        resolution = case.to_dict()["resolution"]
        candidate = resolution["withheld_candidate"]

        self.assertGreaterEqual(candidate["confidence"], DEFAULT_THRESHOLD)
        notes = " ".join(resolution.get("notes") or [])
        self.assertIn("cap", notes.lower())

    def test_raising_the_cap_lets_the_same_ruling_through(self):
        """Proves the cap is the operative control, not an unrelated blocker."""
        case = self._run(_load_record("RD-0109.json"), cap=500.00)
        resolution = case.to_dict()["resolution"]

        self.assertEqual(OUTCOME_RULED, resolution["outcome"])
        self.assertGreater(resolution["ruling"]["recommended_amount_sgd"], 50.00)

    def test_a_below_cap_ruling_is_unaffected(self):
        case = self._run(_load_record("RD-0101.json"), cap=50.00)
        resolution = case.to_dict()["resolution"]

        self.assertEqual(OUTCOME_RULED, resolution["outcome"])
        self.assertLessEqual(resolution["ruling"]["recommended_amount_sgd"], 50.00)

    def test_the_event_log_records_which_gate_failed(self):
        """A human reviewing the queue must see WHY it landed there.

        Events store payloads by reference, so this reads the referenced file: that
        indirection is the contract, and a test that only checked the summary line would
        not prove the structured reason survives to disk.
        """
        from app.events import EventLog
        from app.llm.mock import MockLLMClient
        from app.pipeline import run_dispute
        from app.policy import load_policy

        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            case = run_dispute(
                dispute=parse_dispute(_load_record("RD-0109.json")),
                llm=MockLLMClient(),
                policy=load_policy(REPO / "docs" / "policy.md"),
                events=EventLog(run_dir, "cap-test"),
                confidence_threshold=DEFAULT_THRESHOLD,
                autonomous_cap_sgd=50.00,
            )
            withheld = [
                e for e in case.to_dict()["events"] if e["type"] == "judge.ruling_withheld"
            ]
            self.assertEqual(1, len(withheld))
            self.assertIn("cap", withheld[0]["summary"].lower())

            payload = json.loads(
                (run_dir / withheld[0]["payload_ref"]).read_text(encoding="utf-8")
            )
            self.assertIn("ESC-4", payload["gates_failed"])
            self.assertEqual(50.00, payload["autonomous_cap_sgd"])


class ConfigCapTest(unittest.TestCase):
    """The cap is configuration, and bad configuration must fail loudly."""

    def _write_config(self, tmp: Path, **overrides) -> Path:
        base = json.loads((REPO / "app" / "config.json").read_text(encoding="utf-8"))
        base.update(overrides)
        path = tmp / "config.json"
        path.write_text(json.dumps(base), encoding="utf-8")
        return path

    def test_the_shipped_config_states_the_policy_cap(self):
        data = json.loads((REPO / "app" / "config.json").read_text(encoding="utf-8"))
        self.assertEqual(50.00, data["autonomous_cap_sgd"])

    def test_a_missing_cap_defaults_to_the_policy_value(self):
        """An older config file must not silently disable the gate."""
        from app.config import load_config

        with tempfile.TemporaryDirectory() as tmp:
            base = json.loads((REPO / "app" / "config.json").read_text(encoding="utf-8"))
            del base["autonomous_cap_sgd"]
            path = Path(tmp) / "config.json"
            path.write_text(json.dumps(base), encoding="utf-8")
            self.assertEqual(50.00, load_config(path).autonomous_cap_sgd)

    def test_a_non_positive_cap_is_rejected(self):
        from app.config import ConfigError, load_config

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_config(Path(tmp), autonomous_cap_sgd=0)
            with self.assertRaises(ConfigError):
                load_config(path)

    def test_a_non_numeric_cap_is_rejected(self):
        from app.config import ConfigError, load_config

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_config(Path(tmp), autonomous_cap_sgd="fifty")
            with self.assertRaises(ConfigError):
                load_config(path)


class FiniteNumberContractTest(unittest.TestCase):
    """NaN and Infinity survive json.loads and defeat every range check."""

    def _payload(self, amount):
        return {
            "action": "refund",
            "recommended_amount_sgd": amount,
            "confidence": 0.9,
            "explanation": "test",
            "cited_rule_ids": ["GEN-1"],
        }

    def test_nan_is_rejected(self):
        with self.assertRaises(ContractError):
            JudgeRuling.from_payload(self._payload(float("nan")), agent="judge")

    def test_infinity_is_rejected(self):
        with self.assertRaises(ContractError):
            JudgeRuling.from_payload(self._payload(float("inf")), agent="judge")

    def test_negative_infinity_is_rejected(self):
        with self.assertRaises(ContractError):
            JudgeRuling.from_payload(self._payload(float("-inf")), agent="judge")

    def test_nan_confidence_is_rejected(self):
        """NaN confidence is worse than a low one: it passes a >= threshold comparison."""
        payload = self._payload(10.0)
        payload["confidence"] = float("nan")
        with self.assertRaises(ContractError):
            JudgeRuling.from_payload(payload, agent="judge")

    def test_nan_parsed_from_json_text_is_rejected(self):
        """json.loads accepts the bare tokens NaN and Infinity — the realistic route in."""
        payload = json.loads(
            '{"action":"refund","recommended_amount_sgd":NaN,"confidence":0.9,'
            '"explanation":"t","cited_rule_ids":["GEN-1"]}'
        )
        self.assertTrue(math.isnan(payload["recommended_amount_sgd"]))
        with self.assertRaises(ContractError):
            JudgeRuling.from_payload(payload, agent="judge")

    def test_an_ordinary_amount_still_passes(self):
        ruling = JudgeRuling.from_payload(self._payload(12.34), agent="judge")
        self.assertEqual(12.34, ruling.recommended_amount_sgd)


class MalformedRecordSanityTest(unittest.TestCase):
    """A broken record must yield null fields and a note, never a confident wrong number.

    Silently producing a wrong number is worse than crashing: the agents argue from pack
    fields as established fact, so fiction in a field becomes fiction in a ruling.
    """

    def test_a_dropoff_before_its_pickup_produces_no_duration(self):
        record = _load_record("RD-0101.json")
        record["trip"]["pickup_at"], record["trip"]["dropoff_at"] = (
            record["trip"]["dropoff_at"],
            record["trip"]["pickup_at"],
        )
        pack = build_evidence_pack(parse_dispute(record)).to_dict()

        self.assertIsNone((pack.get("duration") or {}).get("actual_minutes"))
        self.assertTrue(
            any("backwards" in note for note in pack.get("notes") or []),
            "the reversed timestamps were discarded without telling anyone",
        )

    def test_a_backwards_trip_does_not_recompute_a_fare(self):
        """The specific regression: -31 minutes recomputed to SGD 3.13 and read as a 15.50 overcharge."""
        record = _load_record("RD-0101.json")
        record["trip"]["pickup_at"], record["trip"]["dropoff_at"] = (
            record["trip"]["dropoff_at"],
            record["trip"]["pickup_at"],
        )
        fare = build_evidence_pack(parse_dispute(record)).to_dict().get("fare") or {}

        self.assertIsNone(fare.get("recomputed_sgd"))
        self.assertIsNone(fare.get("difference_sgd"))

    def test_an_out_of_range_coordinate_is_not_a_long_trip(self):
        record = _load_record("RD-0101.json")
        record["trip"]["actual_route"][3]["lat"] = 999.0
        pack = build_evidence_pack(parse_dispute(record)).to_dict()
        route = pack.get("route") or {}

        self.assertLess(
            route.get("actual_distance_km") or 0.0,
            100.0,
            "a lat of 999 produced a plausible-looking distance instead of being rejected",
        )

    def test_a_negative_estimated_distance_does_not_reduce_the_fare(self):
        record = _load_record("RD-0101.json")
        record["trip"]["estimated_distance_km"] = -6.4
        fare = build_evidence_pack(parse_dispute(record)).to_dict().get("fare") or {}

        self.assertIsNone(fare.get("recomputed_estimated_route_sgd"))

    def test_a_zero_surge_does_not_produce_a_negative_fare(self):
        record = _load_record("RD-0101.json")
        record["trip"]["fare"]["rates"]["surge_multiplier"] = 0
        fare = build_evidence_pack(parse_dispute(record)).to_dict().get("fare") or {}

        recomputed = fare.get("recomputed_sgd")
        self.assertTrue(
            recomputed is None or recomputed >= 0.0,
            "a zero surge produced a negative fare of %r" % recomputed,
        )

    def test_a_backwards_cancellation_produces_no_negative_wait(self):
        record = _load_record("NS-0201.json")
        cancellation = record["cancellation"]
        cancellation["driver_arrived_at"], cancellation["cancelled_at"] = (
            cancellation["cancelled_at"],
            cancellation["driver_arrived_at"],
        )
        cancellation["wait_started_at"] = cancellation["driver_arrived_at"]
        pack = build_evidence_pack(parse_dispute(record)).to_dict()
        wait = (pack.get("cancellation") or {}).get("driver_wait_minutes")

        self.assertTrue(
            wait is None or wait >= 0.0,
            "a reversed cancellation produced a wait of %r minutes, which NS-2 would "
            "then compare against its 3-minute minimum as if it were a short wait" % wait,
        )

    def test_every_corpus_case_still_computes_its_numbers(self):
        """The sanity checks must not have made the real corpus unusable."""
        for path in sorted(CORPUS.glob("RD-*.json")):
            pack = build_evidence_pack(parse_dispute(json.loads(path.read_text()))).to_dict()
            self.assertIsNotNone(
                (pack.get("route") or {}).get("actual_distance_km"),
                "%s lost its computed distance to an input guard" % path.name,
            )


if __name__ == "__main__":
    unittest.main()
