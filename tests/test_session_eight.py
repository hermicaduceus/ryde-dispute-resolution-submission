"""Session eight acceptance target: W13 (follow-up questions built in code) + W11.

Written BEFORE the build, so it is RED until the CodeBuddy lane ships
docs/build-briefs/session-eight-brief.md. the operator ruled 2026-09-24 (W13 option a): an advocate no longer
writes follow-up questions. It picks slot ids from a fixed bank and code renders the
sentence, exactly like the decision message. Free text in `follow_up_questions` is
ignored. The word filter stays as a backstop, not the protection.
"""

from __future__ import annotations

import contextlib
import copy
import io
import json
import tempfile
import unittest

from app.dispute import parse_dispute
from app.evidence.compute import build_evidence_pack
from app.schemas import is_party_safe
from tests.support import ScriptedLLM
from tests.test_party_surface import (
    _JUDGE,
    ORG_DIR,
    SYNTH_DIR,
    _asking_advocate,
    _blank_org,
    _record,
    _run,
    _slot_advocate,
)

EXPECTED_BANK = {
    "route_deviation": {
        "route_shown": "What route did the app show you before the trip started?",
        "route_discussed": "Did you and the driver talk about taking a different route? If so, what was said?",
        "stops_or_changes": "Did you ask the driver to stop, wait or change the destination during the trip? If so, where?",
        "road_conditions": "Did the driver mention a road closure or diversion during the trip?",
        "pickup_dropoff": "Were you picked up and dropped off where your booking said? If not, where?",
    },
    "no_show_charge": {
        "waiting_place": "Where exactly were you waiting when the trip was meant to start?",
        "driver_contact": "Did the driver call or message you? If so, what was said?",
        "arrival_time": "Roughly what time did you reach the pickup point?",
        "cancel_reason": "Who cancelled the trip, and what was the reason?",
    },
}

#: Paraphrase leaks and leading questions. None carries a banned word, so all pass
#: is_party_safe today. That is the W13 hole.
PARAPHRASE_LEAKS = [
    "How sure are you that the driver took the long way?",
    "You cancelled well before pickup, correct?",
    "We think you are probably right; can you confirm the route?",
]


def _llm(rider_slots=(), driver_slots=(), rider_text=(), driver_text=()):
    return ScriptedLLM(
        {
            "rider_advocate": _slot_advocate(rider_slots, rider_text),
            "driver_advocate": _slot_advocate(driver_slots, driver_text),
            "judge": _JUDGE,
        }
    )


# ------------------------------------------------------------------- the bank


class W13Bank(unittest.TestCase):
    def test_bank_matches_the_ruled_wording_and_is_party_safe(self):
        from app.schemas import FOLLOW_UP_QUESTION_BANK, INTAKE_QUESTIONS

        self.assertEqual(set(INTAKE_QUESTIONS), set(FOLLOW_UP_QUESTION_BANK), "one bank per intake category")
        for category, items in FOLLOW_UP_QUESTION_BANK.items():
            self.assertEqual(EXPECTED_BANK[category], dict(items))
            for slot, sentence in items:
                with self.subTest(slot=slot):
                    self.assertTrue(is_party_safe(sentence), sentence)
                    self.assertNotRegex(slot, r"^form:", "bank ids must not collide with form ids")

    def test_slot_ids_are_bank_ids_then_form_ids_in_order(self):
        from app.schemas import follow_up_slot_ids

        self.assertEqual(
            list(EXPECTED_BANK["no_show_charge"])
            + ["form:where_were_you", "form:did_driver_contact_you", "form:safety_concern"],
            follow_up_slot_ids("no_show_charge"),
        )
        self.assertEqual([], follow_up_slot_ids("other"))

    def test_render_bank_and_form_slots(self):
        from app.schemas import FORM_SLOT_QUESTION_TEMPLATE, render_follow_up_slot

        self.assertEqual(EXPECTED_BANK["route_deviation"]["route_shown"],
                         render_follow_up_slot("route_deviation", "route_shown"))
        self.assertEqual(
            FORM_SLOT_QUESTION_TEMPLATE % "Where were you when the trip was meant to start?",
            render_follow_up_slot("no_show_charge", "form:where_were_you"),
        )
        self.assertTrue(is_party_safe(FORM_SLOT_QUESTION_TEMPLATE % "x"))

    def test_render_refuses_every_wrong_shape(self):
        from app.schemas import render_follow_up_slot

        bad = [
            ("route_deviation", "made_up"),
            ("route_deviation", "waiting_place"),         # real id, wrong category
            ("route_deviation", "form:where_were_you"),   # real field, wrong category
            ("route_deviation", "form:"),
            ("route_deviation", ""),
            ("route_deviation", None),
            ("route_deviation", 3),
            ("route_deviation", ["route_shown"]),
            ("other", "route_shown"),
            (None, "route_shown"),
        ]
        for category, slot in bad:
            with self.subTest(category=category, slot=slot):
                self.assertIsNone(render_follow_up_slot(category, slot))

    def test_driver_filed_disputes_get_form_slots_only(self):
        from app.schemas import render_follow_up_slot

        self.assertIsNone(render_follow_up_slot("route_deviation", "route_shown", filed_by="driver"))
        self.assertIsNone(render_follow_up_slot("route_deviation", "form:expected_route", filed_by="driver"))
        self.assertIsNotNone(render_follow_up_slot("route_deviation", "form:route_shown_to_driver", filed_by="driver"))


# ----------------------------------------------------------------- the pipeline


class W13Pipeline(unittest.TestCase):
    def test_paraphrase_leaks_never_reach_the_party(self):
        case = _run(_record(ORG_DIR, "RD-0101.json"), llm=_llm(rider_text=PARAPHRASE_LEAKS))
        resolution = case["resolution"]
        self.assertNotEqual("needs_info", resolution["outcome"])
        self.assertEqual([], resolution["questions_for_party"])
        self.assertEqual([], case["claims"]["rider"]["follow_up_questions"])
        blob = json.dumps(resolution)
        for leak in PARAPHRASE_LEAKS:
            self.assertNotIn(leak, blob)

    def test_free_text_beside_a_slot_is_ignored(self):
        case = _run(_record(ORG_DIR, "RD-0101.json"),
                    llm=_llm(rider_slots=["route_shown"], rider_text=PARAPHRASE_LEAKS))
        self.assertEqual([EXPECTED_BANK["route_deviation"]["route_shown"]],
                         case["resolution"]["questions_for_party"])

    def test_rendered_slots_filing_party_first(self):
        case = _run(_record(ORG_DIR, "RD-0101.json"),
                    llm=_llm(rider_slots=["route_discussed"], driver_slots=["road_conditions"]))
        bank = EXPECTED_BANK["route_deviation"]
        self.assertEqual("needs_info", case["resolution"]["outcome"])
        self.assertEqual([bank["route_discussed"], bank["road_conditions"]],
                         case["resolution"]["questions_for_party"])

    def test_unknown_slot_is_dropped_and_the_operator_sees_why(self):
        case = _run(_record(ORG_DIR, "RD-0101.json"), llm=_llm(rider_slots=["made_up", "route_shown"]))
        self.assertEqual([EXPECTED_BANK["route_deviation"]["route_shown"]],
                         case["resolution"]["questions_for_party"])
        notes = " ".join(case["claims"]["rider"]["validation"]["notes"])
        self.assertIn("made_up", notes)

    # Session eight review round (glm-5.3, reproduced by the planner). The W13 hole is a model
    # putting a sentence where an id belongs; behaviour was right, nothing pinned it.

    def test_a_sentence_smuggled_into_the_slots_never_reaches_the_party(self):
        smuggled = PARAPHRASE_LEAKS + [EXPECTED_BANK["route_deviation"]["route_shown"]]
        case = _run(_record(ORG_DIR, "RD-0101.json"), llm=_llm(rider_slots=smuggled))
        resolution = case["resolution"]
        self.assertNotEqual("needs_info", resolution["outcome"])
        self.assertEqual([], resolution["questions_for_party"])
        for leak in PARAPHRASE_LEAKS:
            self.assertNotIn(leak, json.dumps(resolution))

    def test_every_non_string_slot_shape_breaks_the_contract(self):
        from app.schemas import AdvocateCase, ContractError

        payload = {"requested_outcome": "refund", "requested_amount_sgd": 1.0,
                   "argument": "x", "claim_summary": "x"}
        wrong = [[5], [None], [True], [""], ["  "], [{"id": "route_shown"}],
                 ["route_shown", ["x"]], "route_shown", {"route_shown": 1}]
        for slots in wrong:
            with self.subTest(slots=slots):
                with self.assertRaises(ContractError):
                    AdvocateCase.from_payload(
                        dict(payload, follow_up_slots=slots), agent="rider_advocate",
                        party="rider", category="route_deviation", filed_by="rider")

    def test_a_flood_of_slot_ids_is_bounded(self):
        # NIT from the review: 50 unknown ids used to write 50 notes into the case file.
        # Only the first MAX_FOLLOW_UP_SLOTS ids are read; the rest are counted in one note.
        from app.schemas import MAX_FOLLOW_UP_SLOTS

        self.assertEqual(6, MAX_FOLLOW_UP_SLOTS)
        flood = ["made_up_%d" % i for i in range(50)]
        case = _run(_record(ORG_DIR, "RD-0101.json"), llm=_llm(rider_slots=flood + ["route_shown"]))
        rider = case["claims"]["rider"]
        self.assertEqual(flood[:MAX_FOLLOW_UP_SLOTS], rider["follow_up_slots"])
        self.assertEqual([], case["resolution"]["questions_for_party"])
        notes = rider["validation"]["notes"]
        self.assertLessEqual(len([n for n in notes if "slot" in n]), MAX_FOLLOW_UP_SLOTS + 1)
        self.assertTrue(any("45" in n for n in notes), notes)  # 51 sent, 6 read, 45 ignored

    def test_a_huge_slot_id_is_not_copied_whole_into_the_notes(self):
        huge = "x" * 5000
        case = _run(_record(ORG_DIR, "RD-0101.json"), llm=_llm(rider_slots=[huge]))
        notes = case["claims"]["rider"]["validation"]["notes"]
        self.assertTrue(notes)
        self.assertLess(max(len(n) for n in notes), 200, notes)

    def test_case_file_records_slots_and_rendered_questions(self):
        case = _run(_record(ORG_DIR, "RD-0101.json"), llm=_llm(rider_slots=["route_shown", "made_up"]))
        rider = case["claims"]["rider"]
        self.assertEqual(["route_shown", "made_up"], rider["follow_up_slots"])
        self.assertEqual([EXPECTED_BANK["route_deviation"]["route_shown"]], rider["follow_up_questions"])

    def test_driver_filed_dispute_is_asked_form_slots_only(self):
        from app.schemas import FORM_SLOT_QUESTION_TEMPLATE

        record = copy.deepcopy(_record(ORG_DIR, "RD-0101.json"))
        record["dispute_ticket"]["filed_by"] = "driver"
        case = _run(record, llm=_llm(driver_slots=["route_shown", "form:route_shown_to_driver"]))
        self.assertEqual(
            [FORM_SLOT_QUESTION_TEMPLATE % "What route did the app show you, and roughly how long was it?"],
            case["resolution"]["questions_for_party"],
        )


# --------------------------------------------------------- prompt + mock


class W13PromptAndMock(unittest.TestCase):
    def test_prompt_offers_slot_ids_not_free_text(self):
        llm = _llm()
        _run(_record(ORG_DIR, "RD-0101.json"), llm=llm)
        request = next(c for c in llm.calls if c.agent == "rider_advocate")
        self.assertIn("follow_up_slots", request.system_prompt)
        self.assertNotIn("follow_up_questions", request.system_prompt)
        for slot in list(EXPECTED_BANK["route_deviation"]) + ["form:expected_route"]:
            self.assertIn(slot, request.user_prompt)

    def test_mock_asks_through_a_form_slot(self):
        from app.schemas import FORM_SLOT_QUESTION_TEMPLATE

        case = _run(_blank_org(_record(ORG_DIR, "RD-0101.json"), "expected_route"))
        self.assertEqual(["form:expected_route"], case["claims"]["rider"]["follow_up_slots"])
        self.assertEqual(
            [FORM_SLOT_QUESTION_TEMPLATE % "What route did the app show you, and roughly how long was it?"],
            case["resolution"]["questions_for_party"],
        )


# ------------------------------------------------------------------------ W11


def _cli_header(pack: str, dispute_id: str) -> str:
    from app.cli import main

    with tempfile.TemporaryDirectory() as tmp:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(["--pack", pack, "--dispute", dispute_id, "--out", tmp, "--run-id", "t"])
    assert code == 0, code
    return next(line for line in out.getvalue().splitlines() if line.startswith("run:"))


class W11CliHeader(unittest.TestCase):
    def test_a_withheld_ruling_names_the_llm_that_ran(self):
        self.assertIn("llm: mock", _cli_header("ryde-synth-v1", "RD-0109"))

    def test_no_judge_run_still_says_n_a(self):
        self.assertIn("llm: n/a", _cli_header("ryde-synth-v1", "OS-0301"))

    # Session eight review round (glm-5.3, reproduced by the planner): the two outcomes the
    # first fix did not pin.

    def test_a_ruled_case_names_the_llm_that_ran(self):
        self.assertIn("llm: mock", _cli_header("ryde-synth-v1", "RD-0101"))

    def test_a_needs_info_stop_names_the_advocates_llm(self):
        # Both advocates ran before the pipeline stopped to ask; no Judge ran, so the
        # header must read the filing party's advocate, not print n/a.
        record = _blank_org(_record(ORG_DIR, "RD-0101.json"), "expected_route")
        with tempfile.TemporaryDirectory() as tmp:
            path = "%s/RD-0101-blank.json" % tmp
            with open(path, "w") as handle:
                json.dump(record, handle)
            header = _cli_header("organiser-style-v1", path)
        self.assertIn("llm: mock", header)


class W11PromoSign(unittest.TestCase):
    """Characterisation, GREEN on arrival: tools/build_corpus.py stores promo negative and
    the formula subtracts it, so abs() is deliberate. Removing abs() must turn this red."""

    def test_promo_is_subtracted_whatever_sign_it_is_stored_with(self):
        record = _record(SYNTH_DIR, "RD-0101.json")
        base = build_evidence_pack(parse_dispute(record)).fare.recomputed_sgd
        for stored in (-1.0, 1.0):
            with self.subTest(stored=stored):
                changed = copy.deepcopy(record)
                changed["trip"]["fare"]["breakdown"]["promo_sgd"] = stored
                fare = build_evidence_pack(parse_dispute(changed)).fare
                self.assertAlmostEqual(base - 1.0, fare.recomputed_sgd, places=2)


if __name__ == "__main__":
    unittest.main()
