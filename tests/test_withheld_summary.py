"""Regression pin for the operator event summary on a withheld ruling."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.dispute import load_dispute
from app.events import EventLog
from app.llm.mock import MockLLMClient
from app.pipeline import run_dispute
from app.policy import load_policy

REPO = Path(__file__).resolve().parent.parent


class WithheldSummaryTest(unittest.TestCase):
    def test_withheld_event_names_the_gate_without_repeating_amounts(self):
        """The old event summary repeated both the candidate and cap amounts.

        The structured payload and reviewer notes remain the audit trail for figures;
        the compact event strip should explain the gate without restating them.
        """
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            case = run_dispute(
                dispute=load_dispute(REPO / "data" / "packs" / "ryde-synth-v1" / "disputes" / "RD-0109.json"),
                llm=MockLLMClient(),
                policy=load_policy(REPO / "docs" / "policy.md"),
                events=EventLog(tmp / "run", "withheld-summary-test"),
                confidence_threshold=0.65,
                autonomous_cap_sgd=50.00,
            )
            data = case.to_dict()
            event = next(
                event for event in data["events"] if event["type"] == "judge.ruling_withheld"
            )
            summary = event["summary"]
            self.assertIn("cap", summary.lower())
            self.assertIn("ESC-4", summary)
            self.assertNotIn("SGD", summary)
            self.assertNotIn("55.16", summary)
            self.assertNotIn("50.00", summary)

            payload = json.loads((tmp / "run" / event["payload_ref"]).read_text(encoding="utf-8"))
            self.assertEqual(["ESC-4"], payload["gates_failed"])
            self.assertEqual(50.00, payload["autonomous_cap_sgd"])
            self.assertEqual(55.16, payload["withheld_candidate"]["recommended_amount_sgd"])
            self.assertIn("SGD 55.16", " ".join(data["resolution"]["notes"]))


if __name__ == "__main__":
    unittest.main()
