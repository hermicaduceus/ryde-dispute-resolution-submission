"""Session ten acceptance target: W12 — a demo notice on party decisions made without
a real LLM provider.

The problem (W12, from the W5 review): the mock LLM prefixes its free-text fields with
"MOCK", but the party decision message is built in code from action + amount + rule
titles, so a mock ruling reads on the party page exactly like a real one:

    Decision: refund of SGD 5.81. Basis: ...

If a mock run is screenshotted or filmed, nothing on the party screen distinguishes it
from a live-model ruling. This file pins the fix BEFORE the build lane ships it (RED
until then) and must stay green after.

Design rules this file enforces (the operator-ruled shape, 2026-09-25 session ten):
  * The notice appears on the DECIDED party view whenever the ruling's LLM record
    does not PROVE a real provider. Fail-closed: only a non-array dict whose
    "provider" is the string "tencent" hides the notice — mock, missing, malformed,
    arrays and empty objects all show it.
  * Non-decided statuses show their canonical constants and never show the notice
    (nothing false can appear there, and a mock marker on "still under review" would
    be noise, not honesty).
  * The notice text is a FIXED constant in app/schemas.py, passes is_party_safe and
    the acceptance tests' forbidden-word regex, and never varies with input.
  * The five-key party view contract and ui/party/party.js are untouched: the notice
    rides the message the page already renders.
"""
from __future__ import annotations

import copy
import json
import unittest

from tests.test_party_surface import (
    FORBIDDEN_PARTY_WORDS,
    ORG_DIR,
    PARTY_VIEW_KEYS,
    _blank_org,
    _record,
    _run,
)

#: The provider the system's one real adapter (app/llm/tencent.py) reports.
REAL_PROVIDER = "tencent"

#: Every wrong shape of an LLM record must show the notice. Not "the one that
#: prompted the fix": the whole family, probed one by one (shape-check ruling).
WRONG_LLM_SHAPES = [
    None,                       # no record at all
    "mock",                     # a bare string
    [],                         # array: typeof === "object", truthy
    [1, 2],                     # non-empty array
    {},                         # empty object: truthy, carries nothing
    {"provider": "mock"},       # today's actual shape on every run
    {"provider": None},
    {"provider": ""},           # blank
    {"provider": "MOCK"},       # case variant
    {"provider": ["tencent"]},  # array inside the field
    {"provider": {"id": "tencent"}},  # object inside the field
    {"provider": 1},            # wrong type
]


def _decided(case: dict) -> dict:
    """A decided (ruled) case file from the organiser pack, precondition-checked."""
    assert case["resolution"]["outcome"] == "ruled", "fixture must be ruled"
    assert case["resolution"]["ruling"]["llm"]["provider"] == "mock", \
        "precondition: the mock run must report provider mock"
    return case


class DemoNoticeTest(unittest.TestCase):
    """The notice itself: fixed, party-safe, unmistakable."""

    def _constants(self):
        import app.schemas as schemas

        return schemas

    def _notice(self):
        return getattr(self._constants(), "DEMO_NOTICE_MESSAGE", "")

    def test_notice_is_a_fixed_party_safe_constant(self):
        schemas = self._constants()
        notice = getattr(schemas, "DEMO_NOTICE_MESSAGE", "")
        self.assertIsInstance(notice, str, "app/schemas.py must define DEMO_NOTICE_MESSAGE")
        self.assertTrue(notice.strip(), "the notice must not be blank")
        self.assertTrue(schemas.is_party_safe(notice),
                        "the notice must pass is_party_safe")
        self.assertIsNone(FORBIDDEN_PARTY_WORDS.search(notice),
                          "the notice must pass the acceptance forbidden-word regex")
        # Unmistakable: it must carry the word the operator console has always used.
        self.assertIn("demo", notice.lower(),
                      "the notice must say this is a demo/illustrative decision")

    def test_notice_goes_in_front_of_the_decision(self):
        """Mock-run decided views must lead with the notice, then the decision text."""
        from app.server import party_view

        view = party_view(_decided(_run(_record(ORG_DIR, "RD-0101.json"))))
        self.assertEqual("decided", view["status"])
        notice = self._notice()
        self.assertTrue(notice, "precondition: the notice constant must exist")
        self.assertTrue(view["message"].startswith(notice),
                        "the notice must be the first thing the party reads")
        self.assertIn("Decision:", view["message"],
                      "the decision text must still follow the notice")


class MockRunsShowTheNoticeTest(unittest.TestCase):
    """Every end-to-end mock run shows the notice on a decided view."""

    def test_mock_ruled_run_shows_notice(self):
        from app.server import party_view

        view = party_view(_run(_record(ORG_DIR, "RD-0101.json")))
        self.assertEqual("decided", view["status"])
        self.assertIn("demo", view["message"].lower())
        self.assertTrue(view["message"].startswith(self._notice()))
        self.assertEqual(PARTY_VIEW_KEYS, set(view), "five-key contract intact")

    def test_mock_withheld_run_has_no_notice(self):
        """A withheld run shows the neutral message; the notice is for decisions."""
        from app.server import party_view

        record = copy.deepcopy(_record(ORG_DIR, "RD-0101.json"))
        record["ryde_extensions"]["claim"]["amount_sgd"] = 83.47
        view = party_view(_run(record))
        self.assertEqual("under_review", view["status"])
        self.assertNotIn("demo", view["message"].lower())
        self.assertEqual([], view["questions"])

    def test_mock_needs_info_run_has_no_notice(self):
        from app.server import party_view

        view = party_view(_run(_blank_org(_record(ORG_DIR, "RD-0101.json"), "expected_route")))
        self.assertEqual("needs_info", view["status"])
        self.assertNotIn("demo", view["message"].lower())

    def _notice(self):
        import app.schemas as schemas

        return schemas.DEMO_NOTICE_MESSAGE


class FailClosedShapeTest(unittest.TestCase):
    """Only a proven real provider hides the notice. Every wrong shape shows it.

    The guard must be a shape check, not a type check: `[]` is an array and
    truthy, `{}` is truthy and carries nothing, and a guard written against
    `null` alone keeps the suite green while admitting all of them.
    """

    def _decided_case(self):
        return _decided(_run(_record(ORG_DIR, "RD-0101.json")))

    def _view_with_llm(self, llm) -> dict:
        from app.server import party_view

        case = copy.deepcopy(self._decided_case())
        case["resolution"]["ruling"]["llm"] = copy.deepcopy(llm)
        return party_view(case)

    def test_every_wrong_llm_shape_shows_the_notice(self):
        for shape in WRONG_LLM_SHAPES:
            with self.subTest(llm=shape):
                view = self._view_with_llm(shape)
                self.assertEqual("decided", view["status"],
                                 "a bad LLM record must not demote the decision")
                self.assertTrue(view["message"].startswith(_notice()),
                                "a bad LLM record must still show the notice")

    def test_proven_tencent_record_hides_the_notice(self):
        view = self._view_with_llm({"provider": REAL_PROVIDER, "model": "x", "usage": {},
                                    "finish_reason": "stop", "request_fingerprint": "abc"})
        self.assertEqual("decided", view["status"])
        self.assertFalse(view["message"].startswith(_notice()),
                         "a proven real-provider decision shows no notice")
        self.assertNotIn("demo", view["message"].lower())
        self.assertIn("Decision:", view["message"])

    def test_provider_string_must_be_exact(self):
        for variant in ("Tencent", "TENCENT", "tencent ", " tencent", "mock-tencent"):
            with self.subTest(provider=variant):
                view = self._view_with_llm({"provider": variant})
                self.assertTrue(view["message"].startswith(_notice()),
                                "an inexact provider string must not count as real")

    def test_malformed_ruling_object_array_shows_the_notice(self):
        from app.server import party_view

        case = copy.deepcopy(self._decided_case())
        for ruling in ([], [1, 2], None, "ruled", 0, False, {}):
            with self.subTest(ruling=ruling):
                case["resolution"]["ruling"] = copy.deepcopy(ruling)
                view = party_view(case)
                # A destroyed ruling fails closed to under_review (existing rule);
                # it must never render a clean decided message without the notice.
                if view["status"] == "decided":
                    self.assertTrue(view["message"].startswith(_notice()))

    def test_notice_never_varies_with_input(self):
        from app.server import party_view

        views = [party_view(self._view_helper(shape)) for shape in WRONG_LLM_SHAPES]
        prefixes = {v["message"][: len(_notice())] for v in views}
        self.assertEqual(1, len(prefixes),
                         "the notice is a fixed constant, not composed from input")

    def _view_helper(self, llm):
        case = copy.deepcopy(self._decided_case())
        case["resolution"]["ruling"]["llm"] = copy.deepcopy(llm)
        return case


def _notice():
    import app.schemas as schemas

    return getattr(schemas, "DEMO_NOTICE_MESSAGE", "")


class ContractIntactTest(unittest.TestCase):
    """What must NOT change: five keys, canonical non-decided messages, party.js."""

    def test_five_key_contract_still_holds(self):
        from app.server import party_view

        for name in ("RD-0101.json", "OS-0301.json"):
            view = party_view(_run(_record(ORG_DIR, name)))
            self.assertEqual(PARTY_VIEW_KEYS, set(view), name)

    def test_architecture_doc_states_the_notice(self):
        """The doc says the party message carries no MOCK marker; that goes false now."""
        from pathlib import Path

        repo = Path(__file__).resolve().parent.parent
        text = (repo / "docs" / "architecture.md").read_text(encoding="utf-8")
        self.assertIn("demo notice", text.lower(),
                      "architecture.md must state the party-view demo notice honestly")


if __name__ == "__main__":
    unittest.main()