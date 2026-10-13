"""W43 MUST lane (M3): the party view fails closed on every malformed shape.

RED until the W43 MUST lane ships its brief. Written before the build, pinning the DEFECT
rather than a symbol a fix introduces.

The defect (Sol document review, A-F03, parent-reproduced):

  * a persisted case file whose `resolution.outcome` is an unhashable value (a list or an
    object) raises `TypeError` inside `party_view` in `app/server.py`, because the member is
    used as a mapping key before it is type-checked. The HTTP handlers catch the TypeError as
    a generic 500, so the party sees an internal error instead of the neutral five-key
    under-review view every other malformed shape degrades to.

The contract these tests pin:

  * the whole family of wrong outcome shapes — `[]`, `[1,2]`, a list holding a known outcome,
    `{}`, a populated dict, null and numbers — degrades to the exact neutral five-key
    response, and never raises;
  * the shapes that already worked (an unknown outcome string, a top-level list case file)
    keep working, so the fix cannot be "reject everything";
  * the shapes that must still be served (a decided case, a needs_info case, a withheld case)
    are still served, so an always-false guard cannot pass.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from app.schemas import (
    DEMO_NOTICE_MESSAGE,
    NEEDS_INFO_MESSAGE,
    OUTCOME_NEEDS_INFO,
    OUTCOME_RULED,
    OUTCOME_WITHHELD,
    UNDER_REVIEW_MESSAGE,
)
from app.server import party_view

REPO = Path(__file__).resolve().parent.parent
SYNTH_DIR = REPO / "data" / "packs" / "ryde-synth-v1"

PARTY_VIEW_KEYS = ["run_id", "dispute_id", "status", "message", "questions"]
RUN_ID = "20261013T090000Z-abcd1234"
DISPUTE_ID = "PF-ABC12345"

#: The unhashable (and otherwise wrong) outcome members. A dict or a list cannot be a key.
WRONG_OUTCOMES = (
    [], [1, 2], ["ruled"], ["withheld"], [["ruled"]],
    {}, {"outcome": "ruled"}, {"0": "ruled"},
    None, 1, 1.5, True,
)
#: Controls: these two already degraded on HEAD and must keep degrading.
ALREADY_HANDLED = ("banana", "RULED", "")


def _case(outcome, **resolution_extra):
    resolution = {"outcome": outcome, "party_message": "Your refund is on its way.",
                  "questions_for_party": []}
    resolution.update(resolution_extra)
    return {"run_id": RUN_ID, "dispute_id": DISPUTE_ID, "resolution": resolution}


def _neutral(**overrides):
    view = {"run_id": RUN_ID, "dispute_id": DISPUTE_ID, "status": "under_review",
            "message": UNDER_REVIEW_MESSAGE, "questions": []}
    view.update(overrides)
    return view


class EveryWrongOutcomeShapeDegradesToTheNeutralView(unittest.TestCase):
    """The unhashable member is the hole; the whole wrong-shape family is pinned with it."""

    def _view(self, case_file):
        try:
            return party_view(case_file)
        except Exception as error:  # noqa: BLE001 - the crash IS the finding
            self.fail("party_view raised %r instead of failing closed to the neutral view"
                      % (error,))

    def test_the_unhashable_family_degrades(self):
        for outcome in WRONG_OUTCOMES:
            with self.subTest(outcome=repr(outcome)[:16]):
                self.assertEqual(_neutral(), self._view(_case(outcome)))

    def test_the_controls_still_degrade(self):
        for outcome in ALREADY_HANDLED:
            with self.subTest(outcome=repr(outcome)[:16]):
                self.assertEqual(_neutral(), self._view(_case(outcome)))

    def test_a_top_level_list_case_file_still_degrades(self):
        # The other side of the same finding: a non-array object is already refused.
        for case_file in ([], [1, 2], "case", 5, None):
            with self.subTest(case=repr(case_file)[:16]):
                self.assertEqual(_neutral(run_id="", dispute_id=""), self._view(case_file))

    def test_a_malformed_resolution_block_degrades(self):
        for resolution in ([], "resolution", 7, None):
            with self.subTest(resolution=repr(resolution)[:16]):
                case_file = {"run_id": RUN_ID, "dispute_id": DISPUTE_ID, "resolution": resolution}
                self.assertEqual(_neutral(), self._view(case_file))

    def test_the_neutral_view_is_exactly_the_five_keys(self):
        for outcome in WRONG_OUTCOMES:
            with self.subTest(outcome=repr(outcome)[:16]):
                view = self._view(_case(outcome))
                self.assertEqual(PARTY_VIEW_KEYS, list(view))
                self.assertNotIn("outcome", json.dumps(view))
                self.assertNotIn("ruling", json.dumps(view))

    def test_the_run_and_dispute_ids_survive_the_fallback(self):
        # The fallback keeps what the caller may safely show, and nothing else.
        for outcome in ([], {}, {"outcome": "ruled"}):
            with self.subTest(outcome=repr(outcome)[:16]):
                view = self._view(_case(outcome))
                self.assertEqual(RUN_ID, view["run_id"])
                self.assertEqual(DISPUTE_ID, view["dispute_id"])


class TheShapesThatMustStillBeServed(unittest.TestCase):
    """An always-false guard cannot pass: the good shapes are still served."""

    SAFE_DECISION = "We have refunded the fare that was charged."

    def test_a_decided_case_is_served(self):
        # A ruling that proves the real provider: no demo notice, the decision text stands.
        case = _case(OUTCOME_RULED, party_message=self.SAFE_DECISION)
        case["resolution"]["ruling"] = {"llm": {"provider": "tencent"}}
        view = party_view(case)
        self.assertEqual(PARTY_VIEW_KEYS, list(view))
        self.assertEqual("decided", view["status"])
        self.assertEqual(self.SAFE_DECISION, view["message"])
        self.assertEqual([], view["questions"])

    def test_an_unproven_decided_case_keeps_its_demo_notice(self):
        case = _case(OUTCOME_RULED, party_message=self.SAFE_DECISION)
        self.assertEqual(DEMO_NOTICE_MESSAGE + self.SAFE_DECISION, party_view(case)["message"])

    def test_a_needs_info_case_keeps_its_questions(self):
        case = _case(OUTCOME_NEEDS_INFO, party_message="",
                     questions_for_party=["Could you tell us a little more?"])
        view = party_view(case)
        self.assertEqual("needs_info", view["status"])
        self.assertEqual(NEEDS_INFO_MESSAGE, view["message"])
        self.assertEqual(["Could you tell us a little more?"], view["questions"])

    def test_a_withheld_case_shows_the_neutral_message(self):
        case = _case(OUTCOME_WITHHELD, party_message="internal words the party must not see.")
        view = party_view(case)
        self.assertEqual(PARTY_VIEW_KEYS, list(view))
        self.assertEqual("under_review", view["status"])
        self.assertEqual(UNDER_REVIEW_MESSAGE, view["message"])
        self.assertEqual([], view["questions"])

    def test_a_decided_case_with_a_blank_message_still_fails_closed(self):
        # The guard must not become "anything with a known outcome is fine".
        self.assertEqual(_neutral(), party_view(_case(OUTCOME_RULED, party_message="   ")))

    def test_a_decided_case_with_unsafe_text_still_fails_closed(self):
        for text in ("the judge withheld the ruling at confidence 0.9", "Basis: NS-2."):
            with self.subTest(text=text[:24]):
                self.assertEqual(_neutral(), party_view(_case(OUTCOME_RULED, party_message=text)))


class AStoredUnhashableOutcomeIsNotAnHTTP500(unittest.TestCase):
    """The user-visible half: the status endpoint answers, it does not blow up.

    Uses the project's own in-process test server (tests.w23_support.Server), exactly as the
    existing party-surface and human-decision suites do: ephemeral loopback, one thread,
    started and stopped inside the test. The run is a real party filing (the status lookup
    only serves party-filed runs) taken through the real pipeline on the mock.
    """

    def setUp(self):
        from tests.w23_support import Server

        self.server = Server(pack_dir=SYNTH_DIR)
        self.addCleanup(self.server.close)
        self.view = self.server.file(trip_id="T-RD0109", claim=55.16,
                                     category="route_deviation", filed_by="rider")
        self.case_path = self.server.run_dir(self.view["run_id"]) / "case_file.json"

    def _patch_outcome(self, outcome):
        case = json.loads(self.case_path.read_text(encoding="utf-8"))
        self.assertEqual(self.view["run_id"], case["run_id"])
        case["resolution"]["outcome"] = outcome
        self.case_path.write_text(json.dumps(case, indent=2) + "\n", encoding="utf-8")
        return case["dispute_id"]

    def test_the_status_endpoint_serves_the_neutral_view(self):
        dispute_id = self._patch_outcome([])
        status, payload = self.server.json("GET", "/api/disputes/%s" % dispute_id)
        self.assertEqual(200, status, payload)
        self.assertEqual(dispute_id, payload["dispute_id"])
        self.assertEqual(self.view["run_id"], payload["run_id"])
        self.assertEqual("under_review", payload["status"])
        self.assertEqual(UNDER_REVIEW_MESSAGE, payload["message"])
        self.assertEqual([], payload["questions"])
        self.assertEqual(PARTY_VIEW_KEYS, list(payload))

    def test_a_dict_outcome_is_answered_too(self):
        dispute_id = self._patch_outcome({"outcome": "ruled"})
        status, payload = self.server.json("GET", "/api/disputes/%s" % dispute_id)
        self.assertEqual(200, status, payload)
        self.assertEqual("under_review", payload["status"])
        self.assertEqual(UNDER_REVIEW_MESSAGE, payload["message"])
        self.assertEqual(PARTY_VIEW_KEYS, list(payload))

    def test_a_valid_run_is_still_served(self):
        # Positive control on the same endpoint: the untouched run answers as before, with
        # the same five keys and its own run id.
        status, payload = self.server.json("GET", "/api/disputes/%s" % self.view["dispute_id"])
        self.assertEqual(200, status, payload)
        self.assertEqual(self.view["run_id"], payload["run_id"])
        self.assertEqual(self.view["status"], payload["status"])
        self.assertEqual(PARTY_VIEW_KEYS, list(payload))


if __name__ == "__main__":
    unittest.main()
