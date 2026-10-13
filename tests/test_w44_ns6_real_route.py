"""W44 (S-F02): the real filing route keeps the NS-6 absence plumbing.

The W43 MUST acceptance tests exercise `_build_record` directly. The code review's
`route_mutation_survivor` probe removed the absence plumbing inside `_file_dispute`
and all 51 of them stayed green — the real route had no guard at all. This file closes
that hole: it files a contested no-show through the real `POST /api/disputes` route,
on the real server, and asserts the whole chain at once.

Per record shape (`organiser-style-v1` and `ryde-synth-v1`) and per scripted ruling
(no action, then a SGD 1.00 partial refund), the test asserts together:

  * HTTP 200 — the filing is accepted;
  * the stored `dispute.json` carries the boolean absence claim the NS-6 gate reads
    (`rider_claims_driver_absent` is True) — never a value parsed out of the narrative;
  * the run is WITHHELD and the withheld payload names the NS-6 gate;
  * the party view is the neutral under-review response;
  * the filer-visible answer text survives verbatim into the stored record and the
    case file's intake section.

One case per shape states the absence as "Yes - <explanation>", so the explained form
of the answer is proven to carry the claim too. One control pins that the one ruling
NS-6 lets through — the refund of exactly the SGD 6.61 fee — still rules.

Green on merged code: this pins behaviour W43 already ships, through the route the
W43 tests never touched.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from app.schemas import UNDER_REVIEW_MESSAGE
from tests.support import ScriptedLLM
from tests.w23_support import ORG_DIR, SYNTH_DIR, Server

#: The structured field the NS-6 gate reads, and the corpus case NS-6 withholds:
#: driver_marked_no_show true, no arrival position, fee 6.61, clean rider record.
ABSENCE_KEY = "rider_claims_driver_absent"
NO_SHOW_TRIP = "T-NS0205"
NO_SHOW_FEE = 6.61

DESCRIPTION = "The driver says I did not show up, but I was there and he was not."

#: The advocate stand-in both sides answer with (same shape the W43 tests script).
_ADVOCATE = {
    "claim_summary": "stand-in",
    "evidence_cited": [],
    "policy_rule_ids": [],
    "argument": "stand-in",
    "requested_outcome": "no action",
    "requested_amount_sgd": 0.0,
    "follow_up_slots": [],
}


def _judge(action="no action", amount=0.0):
    """The scripted ruling under test; confidence above the threshold, so only the
    Python gates can withhold it."""
    return ScriptedLLM({
        "rider_advocate": _ADVOCATE,
        "driver_advocate": _ADVOCATE,
        "judge": {
            "action": action,
            "recommended_amount_sgd": amount,
            "confidence": 0.9,
            "explanation": "stand-in",
            "cited_rule_ids": ["NS-2"],
            "cited_evidence_refs": ["cancellation.cancellation_fee_sgd"],
        },
    })


def _answers(absence: str) -> dict:
    return {
        "where_were_you": "At the taxi stand as booked.",
        "did_driver_contact_you": "No - he messaged that he was waiting, I did not see him.",
        "safety_concern": "No",
        ABSENCE_KEY: absence,
    }


def _filing(absence: str) -> dict:
    return {
        "category": "no_show_charge",
        "filed_by": "rider",
        "trip_id": NO_SHOW_TRIP,
        "description": DESCRIPTION,
        "claim_amount_sgd": None,
        "answers": _answers(absence),
    }


def _flag(record: dict):
    """Where the stored record carries the absence claim, per shape, or None."""
    if "dispute_ticket" in record:
        return record.get("ryde_extensions", {}).get(ABSENCE_KEY)
    return record.get("cancellation", {}).get(ABSENCE_KEY)


def _intake(record: dict) -> dict:
    """The stored record's intake answers, per shape."""
    if "dispute_ticket" in record:
        return record.get("ryde_extensions", {}).get("intake", {})
    return record.get("intake", {})


class AWebFiledContestedNoShowIsHeldByNS6(unittest.TestCase):
    """The defect itself: the real route reaches the NS-6 gate like the corpus path."""

    def _file(self, pack_dir: Path, absence: str, llm) -> tuple:
        """One real filing on its own server; returns (server, status, party view)."""
        server = Server(pack_dir=pack_dir, llm=llm)
        self.addCleanup(server.close)
        status, view = server.json("POST", "/api/disputes", _filing(absence))
        return server, status, view

    def _assert_withheld_for(self, pack_dir: Path, action: str, amount: float,
                             absence: str) -> None:
        server, status, view = self._file(pack_dir, absence, _judge(action, amount))
        self.assertEqual(200, status, "the filing must be accepted: %s" % view)
        run_dir = server.run_dir(view["run_id"])

        # The stored record carries the boolean claim where the NS-6 gate reads it.
        record = json.loads((run_dir / "dispute.json").read_text(encoding="utf-8"))
        self.assertIs(True, _flag(record),
                      "the stored record must carry the rider's absence claim: %s"
                      % json.dumps(_intake(record)))
        self.assertEqual(absence, _intake(record).get(ABSENCE_KEY),
                         "the filer's answer text must be preserved verbatim")

        # The case file carries the filer's own words into the intake section too.
        case = json.loads((run_dir / "case_file.json").read_text(encoding="utf-8"))
        self.assertEqual(absence, case["intake"]["form_answers"].get(ABSENCE_KEY),
                         "the case file must show the filer's answer text verbatim")

        # The run is withheld, and the NS-6 gate is the one that held it.
        resolution = case["resolution"]
        self.assertEqual("withheld", resolution["outcome"], resolution)
        self.assertIsNone(resolution["ruling"], "a withheld run delivers no ruling")
        withheld = [event for event in case["events"]
                    if event["type"] == "judge.ruling_withheld"]
        self.assertEqual(1, len(withheld), "the run must record exactly one withholding")
        payload = json.loads((run_dir / withheld[0]["payload_ref"]).read_text(encoding="utf-8"))
        self.assertIn("NS-6", payload["gates_failed"], payload["gates_failed"])

        # The party sees the neutral under-review view, and nothing else.
        self.assertEqual("under_review", view["status"], view)
        self.assertEqual(UNDER_REVIEW_MESSAGE, view["message"], view)
        self.assertEqual([], view["questions"], view)

    def test_no_action_and_a_short_partial_are_withheld_for_both_shapes(self):
        for shape, pack_dir in (("organiser-style-v1", ORG_DIR),
                                ("ryde-synth-v1", SYNTH_DIR)):
            with self.subTest(pack=shape, ruling="no action"):
                self._assert_withheld_for(pack_dir, "no action", 0.0, "Yes")
            with self.subTest(pack=shape, ruling="SGD 1.00 partial"):
                self._assert_withheld_for(pack_dir, "refund", 1.00,
                                          "Yes - he was never at the pickup point")

    def test_the_exact_full_fee_refund_still_rules(self):
        # NS-6 is a gate, not a blanket: the one ruling it lets through is the exact
        # fee, on the same shape the withheld cases above use.
        server, status, view = self._file(ORG_DIR, "Yes", _judge("refund", NO_SHOW_FEE))
        self.assertEqual(200, status, view)
        self.assertEqual("decided", view["status"], view)
        run_dir = server.run_dir(view["run_id"])
        case = json.loads((run_dir / "case_file.json").read_text(encoding="utf-8"))
        self.assertEqual("ruled", case["resolution"]["outcome"], case["resolution"])
        withheld = [event for event in case["events"]
                    if event["type"] == "judge.ruling_withheld"]
        self.assertEqual([], withheld, "the exact fee refund must not be withheld")


if __name__ == "__main__":
    unittest.main()
