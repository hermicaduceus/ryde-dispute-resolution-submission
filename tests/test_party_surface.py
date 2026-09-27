"""Session six acceptance target: the party-facing surface (intake form, follow-up, outcome).

Non-app test, written BEFORE the build, so it is RED until the CodeBuddy build lane ships
docs/session-six-brief.md. It pins the Python contract only; the pages themselves are
verified in a real browser by the planner lane.

Operator rulings behind it (2026-09-23):
  * Follow-up questions are IN, as a stop-and-ask: when an advocate needs more from the
    filing party, the run stops BEFORE the Judge with a fourth outcome, `needs_info`.
    The party's answers start a fresh run that goes to the Judge. One round only, enforced
    in code: a dispute that already carries follow-up answers never stops again.
  * The party only ever receives an allowlisted view: status, neutral message, questions.
    A withheld ruling's amount and the Judge's confidence must be structurally absent.
  * The mock asks the filing party one question per BLANK intake answer, so the path can be
    demoed before a real model exists. No shipped record has a blank answer, so none of the
    35 existing case runs may change.
"""

from __future__ import annotations

import copy
import json
import re
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from app.dispute import DisputeError, parse_dispute
from app.events import EventLog
from app.llm.mock import MockLLMClient
from app.pipeline import run_dispute
from app.policy import load_policy

from tests.support import DEFAULT_THRESHOLD, ScriptedLLM

REPO = Path(__file__).resolve().parent.parent
SYNTH_DIR = REPO / "data" / "packs" / "ryde-synth-v1"
ORG_DIR = REPO / "data" / "packs" / "organiser-style-v1"
POLICY = REPO / "docs" / "policy.md"
PARTY_UI = REPO / "ui" / "party"

PARTY_VIEW_KEYS = {"run_id", "dispute_id", "status", "message", "questions"}
PARTY_STATUSES = {"decided", "under_review", "passed_to_support", "needs_info"}
TRIP_KEYS_ALLOWED = {"trip_id", "label", "kind", "kind_label", "pickup", "dropoff", "date",
                     "fare_sgd", "charge_label"}
FORBIDDEN_PARTY_WORDS = re.compile(
    r"\b(ai|agent|agents|advocate|advocates|judge|confidence|withheld|escalat\w*|model)\b",
    re.IGNORECASE,
)


def _record(pack_dir: Path, name: str) -> dict:
    return json.loads((pack_dir / "disputes" / name).read_text(encoding="utf-8"))


def _blank_org(record: dict, key: str) -> dict:
    record = copy.deepcopy(record)
    record["ryde_extensions"]["intake"][key] = "   "
    return record


def _blank_synth(record: dict, key: str) -> dict:
    record = copy.deepcopy(record)
    record["intake"][key] = ""
    return record


def _run(record: dict, llm=None, cap: float = 50.00) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        case = run_dispute(
            dispute=parse_dispute(record),
            llm=llm if llm is not None else MockLLMClient(),
            policy=load_policy(POLICY),
            events=EventLog(Path(tmp) / "run", "session-six"),
            confidence_threshold=DEFAULT_THRESHOLD,
            autonomous_cap_sgd=cap,
        )
        return case.to_dict()


def _asking_advocate(questions):
    def respond(request):
        return {
            "claim_summary": "scripted",
            "evidence_cited": [],
            "policy_rule_ids": [],
            "argument": "scripted",
            "requested_outcome": "no action",
            "requested_amount_sgd": 0.0,
            "follow_up_questions": list(questions),
        }

    return respond


def _slot_advocate(slots, free_text=()):
    """An advocate that picks follow-up slots (W13). `free_text` is sent too, so a test can
    prove the old free-text field is ignored."""
    def respond(request):
        return {
            "claim_summary": "scripted",
            "evidence_cited": [],
            "policy_rule_ids": [],
            "argument": "scripted",
            "requested_outcome": "no action",
            "requested_amount_sgd": 0.0,
            "follow_up_slots": list(slots),
            "follow_up_questions": list(free_text),
        }

    return respond


_JUDGE = {
    "action": "no action",
    "recommended_amount_sgd": 0.0,
    "confidence": 0.9,
    "explanation": "scripted judge",
    "cited_rule_ids": [],
    "cited_evidence_refs": [],
}


def _types(case: dict):
    return [event["type"] for event in case["events"]]


# --------------------------------------------------------------------- pipeline


class NeedsInfoOutcome(unittest.TestCase):
    """A blank intake answer stops the run before the Judge, in both record shapes."""

    def _assert_needs_info(self, case: dict):
        from app.schemas import NEEDS_INFO_MESSAGE, OUTCOME_NEEDS_INFO

        resolution = case["resolution"]
        self.assertEqual(OUTCOME_NEEDS_INFO, resolution["outcome"])
        self.assertEqual("needs_info", OUTCOME_NEEDS_INFO)
        self.assertEqual(NEEDS_INFO_MESSAGE, resolution["party_message"])
        self.assertIsNone(resolution["ruling"])
        self.assertIsNone(resolution["withheld_candidate"])
        self.assertFalse(resolution["delivered_to_parties"])
        self.assertFalse(resolution["escalated_for_human_review"])
        questions = resolution["questions_for_party"]
        self.assertIsInstance(questions, list)
        self.assertTrue(1 <= len(questions) <= 3, questions)
        self.assertTrue(all(isinstance(q, str) and q.strip() for q in questions))
        self.assertFalse(
            [t for t in _types(case) if t.startswith("judge.")],
            "the Judge must not run when the party is being asked for more",
        )
        self.assertIn("advocate.follow_up_requested", _types(case))
        self.assertIn("party.notified", _types(case))

    def test_organiser_shape_blank_answer_asks(self):
        self._assert_needs_info(_run(_blank_org(_record(ORG_DIR, "RD-0101.json"), "expected_route")))

    def test_synth_shape_blank_answer_asks(self):
        self._assert_needs_info(_run(_blank_synth(_record(SYNTH_DIR, "RD-0101.json"), "expected_route")))

    def test_no_show_blank_answer_asks(self):
        self._assert_needs_info(_run(_blank_org(_record(ORG_DIR, "NS-0201.json"), "where_were_you")))

    def test_needs_info_message_is_neutral(self):
        from app.schemas import NEEDS_INFO_MESSAGE

        self.assertTrue(NEEDS_INFO_MESSAGE.strip())
        self.assertIsNone(FORBIDDEN_PARTY_WORDS.search(NEEDS_INFO_MESSAGE), NEEDS_INFO_MESSAGE)

    def test_questions_are_capped_at_three_across_both_advocates(self):
        # W13 (session eight): advocates pick slots; code renders the sentences.
        from app.schemas import render_follow_up_slot

        rider_slots = ["route_shown", "route_discussed", "stops_or_changes"]
        llm = ScriptedLLM(
            {
                "rider_advocate": _slot_advocate(rider_slots),
                "driver_advocate": _slot_advocate(["road_conditions", "pickup_dropoff"]),
                "judge": _JUDGE,
            }
        )
        case = _run(_record(ORG_DIR, "RD-0101.json"), llm=llm)
        questions = case["resolution"]["questions_for_party"]
        self.assertEqual("needs_info", case["resolution"]["outcome"])
        self.assertEqual(
            [render_follow_up_slot("route_deviation", s) for s in rider_slots],
            questions,
            "filing party's own advocate first, cap 3",
        )
        self.assertFalse([c for c in llm.calls if c.agent == "judge"])


class OneRoundOnly(unittest.TestCase):
    """The round limit is a code gate: answers present means the Judge always runs."""

    def _with_answers_org(self, record: dict) -> dict:
        record = copy.deepcopy(record)
        record["ryde_extensions"]["follow_up_answers"] = [
            {"question": "Which route did the app show?", "answer": "The expressway."}
        ]
        return record

    def test_gate_holds_even_when_advocates_keep_asking(self):
        llm = ScriptedLLM(
            {
                "rider_advocate": _slot_advocate(["route_shown"]),
                "driver_advocate": _slot_advocate(["route_shown"]),
                "judge": _JUDGE,
            }
        )
        case = _run(self._with_answers_org(_record(ORG_DIR, "RD-0101.json")), llm=llm)
        resolution = case["resolution"]
        self.assertNotEqual("needs_info", resolution["outcome"])
        self.assertTrue([c for c in llm.calls if c.agent == "judge"], "the Judge must run in round two")
        self.assertEqual([], resolution["questions_for_party"])
        self.assertTrue(
            any("follow-up" in str(note).lower() for note in resolution["notes"]),
            "the operator must see that further questions were not sent",
        )

    def test_mock_does_not_ask_again_once_answered(self):
        record = self._with_answers_org(_blank_org(_record(ORG_DIR, "RD-0101.json"), "expected_route"))
        case = _run(record)
        self.assertNotEqual("needs_info", case["resolution"]["outcome"])

    def test_answers_reach_the_case_file_and_the_dispute(self):
        record = self._with_answers_org(_record(ORG_DIR, "RD-0101.json"))
        dispute = parse_dispute(record)
        self.assertEqual("The expressway.", dispute.follow_up_answers[0]["answer"])
        case = _run(record)
        self.assertEqual(
            [{"question": "Which route did the app show?", "answer": "The expressway."}],
            case["intake"]["follow_up_answers"],
        )

    def test_synth_shape_carries_answers_at_top_level(self):
        record = copy.deepcopy(_record(SYNTH_DIR, "RD-0101.json"))
        record["follow_up_answers"] = [{"question": "q?", "answer": "a"}]
        self.assertEqual([{"question": "q?", "answer": "a"}], parse_dispute(record).follow_up_answers)

    def test_malformed_answers_are_rejected(self):
        for bad in ("x", 3, {"question": "q"}, [1], [{"question": "q"}], [{"question": 1, "answer": "a"}]):
            record = copy.deepcopy(_record(SYNTH_DIR, "RD-0101.json"))
            record["follow_up_answers"] = bad
            with self.subTest(bad=bad), self.assertRaises(DisputeError):
                parse_dispute(record)


class ExistingCorpusUnchanged(unittest.TestCase):
    """No shipped record has a blank answer, so none may stop for questions."""

    def test_no_shipped_case_needs_info_and_new_keys_exist(self):
        for pack_dir in (SYNTH_DIR, ORG_DIR):
            for path in sorted((pack_dir / "disputes").glob("*.json")):
                with self.subTest(pack=pack_dir.name, case=path.name):
                    case = _run(json.loads(path.read_text(encoding="utf-8")))
                    self.assertIn(case["resolution"]["outcome"], ("ruled", "withheld", "human_review"))
                    self.assertEqual([], case["resolution"]["questions_for_party"])
                    self.assertEqual([], case["intake"]["follow_up_answers"])


# -------------------------------------------------------------------- party view


class PartyView(unittest.TestCase):
    """An allowlist, fail-closed. Nothing the Judge withheld may reach the party."""

    def _view(self, case: dict) -> dict:
        from app.server import party_view

        return party_view(case)

    def test_each_outcome_maps_to_a_party_status(self):
        from app.schemas import HUMAN_REVIEW_MESSAGE, UNDER_REVIEW_MESSAGE

        ruled = _run(_record(ORG_DIR, "RD-0101.json"))
        view = self._view(ruled)
        self.assertEqual(PARTY_VIEW_KEYS, set(view))
        self.assertEqual("decided", view["status"])
        # W12 (session ten): a mock run is an unproven provider, so the decided
        # view leads with the fixed demo notice and the decision text follows.
        import app.schemas as _schemas
        notice = getattr(_schemas, "DEMO_NOTICE_MESSAGE", "")
        self.assertTrue(notice, "DEMO_NOTICE_MESSAGE must exist once W12 lands")
        self.assertTrue(view["message"].startswith(notice))
        self.assertTrue(view["message"].endswith(ruled["resolution"]["party_message"]))
        self.assertEqual([], view["questions"])

        support = self._view(_run(_record(ORG_DIR, "OS-0301.json")))
        self.assertEqual(("passed_to_support", HUMAN_REVIEW_MESSAGE), (support["status"], support["message"]))

        asking = _run(_blank_org(_record(ORG_DIR, "RD-0101.json"), "expected_route"))
        view = self._view(asking)
        self.assertEqual("needs_info", view["status"])
        self.assertEqual(asking["resolution"]["questions_for_party"], view["questions"])

        record = copy.deepcopy(_record(ORG_DIR, "RD-0101.json"))
        record["ryde_extensions"]["claim"]["amount_sgd"] = 83.47
        withheld = _run(record)
        self.assertEqual("withheld", withheld["resolution"]["outcome"], "precondition: cap gate fires")
        view = self._view(withheld)
        self.assertEqual(PARTY_VIEW_KEYS, set(view))
        self.assertEqual(("under_review", UNDER_REVIEW_MESSAGE), (view["status"], view["message"]))
        text = json.dumps(view).lower()
        for leak in ("83.47", "confidence", "0.86", "withheld", "esc-", "refund"):
            self.assertNotIn(leak, text)

    def test_malformed_case_files_fail_closed(self):
        from app.schemas import UNDER_REVIEW_MESSAGE

        good = _run(_record(ORG_DIR, "RD-0101.json"))
        broken_resolutions = [None, [], [1, 2], {}, "ruled", 0, False, {"outcome": "ruled"},
                              {"outcome": "ruled", "party_message": ""}, {"outcome": "mystery", "party_message": "x"},
                              {"outcome": "needs_info", "party_message": "x", "questions_for_party": "q"}]
        for resolution in broken_resolutions:
            case = dict(good, resolution=resolution)
            with self.subTest(resolution=resolution):
                view = self._view(case)
                self.assertEqual(PARTY_VIEW_KEYS, set(view))
                self.assertEqual("under_review", view["status"])
                self.assertEqual(UNDER_REVIEW_MESSAGE, view["message"])
                self.assertEqual([], view["questions"])
        for case in (None, [], {}, "x"):
            with self.subTest(case=case):
                self.assertEqual("under_review", self._view(case)["status"])


# ------------------------------------------------------------------------ server


class _Server:
    def __init__(self, pack_dir=None):
        from app.server import make_server

        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)
        self.httpd = make_server(port=0, pack_dir=pack_dir, out_dir=self.out, llm=MockLLMClient())
        self.base = "http://127.0.0.1:%d" % self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.tmp.cleanup()

    def request(self, method, path, body=None, raw=None):
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        req = urllib.request.Request(self.base + path, data=data, method=method)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as err:
            return err.code, err.read()

    def json(self, method, path, body=None):
        status, payload = self.request(method, path, body)
        return status, (json.loads(payload) if payload else None)


def _filing(trip_id, category="route_deviation", claim=5.81, answers=None, description="He went a long way round."):
    return {
        "category": category,
        "filed_by": "rider",
        "trip_id": trip_id,
        "description": description,
        "claim_amount_sgd": claim,
        "answers": answers if answers is not None else {
            "expected_route": "Expressway, about 6.4 km.",
            "was_route_agreed": "No",
            "asked_driver_to_stop": "No",
            "safety_concern": "No",
        },
    }


class ServerEndToEnd(unittest.TestCase):
    def setUp(self):
        self.server = _Server()

    def tearDown(self):
        self.server.close()

    def _trip(self, category="route_deviation"):
        status, body = self.server.json("GET", "/api/trips?category=%s" % category)
        self.assertEqual(200, status)
        self.assertTrue(body["trips"])
        return body["trips"][0]["trip_id"]

    def test_binds_loopback_only(self):
        self.assertEqual("127.0.0.1", self.server.httpd.server_address[0])

    def test_trip_list_exposes_trip_facts_only(self):
        for category in ("route_deviation", "no_show_charge", "safety_incident"):
            status, body = self.server.json("GET", "/api/trips?category=%s" % category)
            self.assertEqual(200, status)
            self.assertTrue(body["trips"], category)
            for trip in body["trips"]:
                self.assertTrue(set(trip) <= TRIP_KEYS_ALLOWED, set(trip) - TRIP_KEYS_ALLOWED)

    def test_ruled_filing_round_trip(self):
        status, view = self.server.json("POST", "/api/disputes", _filing(self._trip()))
        self.assertEqual(200, status, view)
        self.assertEqual(PARTY_VIEW_KEYS, set(view))
        self.assertEqual("decided", view["status"])
        run_dir = self.server.out / view["run_id"]
        self.assertTrue((run_dir / "case_file.json").is_file())
        self.assertTrue((run_dir / "dispute.json").is_file())

    def test_follow_up_round_trip_and_single_round(self):
        answers = _filing(self._trip())["answers"]
        answers["expected_route"] = ""
        status, first = self.server.json("POST", "/api/disputes", _filing(self._trip(), answers=answers))
        self.assertEqual((200, "needs_info"), (status, first["status"]), first)
        self.assertTrue(first["questions"])
        reply = {"answers": [{"question": q, "answer": "The expressway."} for q in first["questions"]]}
        status, second = self.server.json("POST", "/api/disputes/%s/answers" % first["run_id"], reply)
        self.assertEqual(200, status, second)
        self.assertNotEqual(first["run_id"], second["run_id"])
        self.assertEqual(first["dispute_id"], second["dispute_id"])
        self.assertIn(second["status"], ("decided", "under_review"))
        status, _ = self.server.json("POST", "/api/disputes/%s/answers" % first["run_id"], reply)
        self.assertEqual(409, status, "a run can be answered once")
        status, _ = self.server.json("POST", "/api/disputes/%s/answers" % second["run_id"], reply)
        self.assertEqual(409, status, "a run that did not ask cannot be answered")

    def test_answers_must_match_the_questions_asked(self):
        answers = _filing(self._trip())["answers"]
        answers["expected_route"] = ""
        _, first = self.server.json("POST", "/api/disputes", _filing(self._trip(), answers=answers))
        for bad in ({}, {"answers": []}, {"answers": [{"question": "not asked?", "answer": "x"}]},
                    {"answers": "x"}, {"answers": [{"question": first["questions"][0]}]}):
            with self.subTest(bad=bad):
                status, _ = self.server.json("POST", "/api/disputes/%s/answers" % first["run_id"], bad)
                self.assertEqual(400, status)

    def test_out_of_scope_categories_pass_to_support(self):
        for category in ("safety_incident", "property_damage_mess", "other"):
            with self.subTest(category=category):
                filing = _filing(self._trip(category), category=category, claim=None, answers={})
                status, view = self.server.json("POST", "/api/disputes", filing)
                self.assertEqual((200, "passed_to_support"), (status, view["status"]), view)

    def test_capped_claim_is_under_review_with_nothing_leaked(self):
        status, raw = self.server.request("POST", "/api/disputes", _filing(self._trip(), claim=83.47))
        self.assertEqual(200, status)
        view = json.loads(raw)
        self.assertEqual("under_review", view["status"])
        for leak in (b"83.47", b"confidence", b"0.86", b"withheld"):
            self.assertNotIn(leak, raw.lower())

    def test_invalid_filings_are_rejected(self):
        trip = self._trip()
        cases = [
            dict(_filing(trip), category="hack"),
            dict(_filing(trip), description=""),
            dict(_filing(trip), description="x" * 2001),
            dict(_filing(trip), filed_by="judge"),
            dict(_filing(trip), claim_amount_sgd=-1),
            dict(_filing(trip), claim_amount_sgd=501),
            dict(_filing(trip), claim_amount_sgd="5"),
            dict(_filing(trip), answers={"not_a_question": "x"}),
            dict(_filing(trip), answers={"safety_concern": 5}),
            dict(_filing(trip), trip_id="T-DOES-NOT-EXIST"),
        ]
        for body in cases:
            with self.subTest(body={k: body[k] for k in body if k != "answers"}):
                status, _ = self.server.json("POST", "/api/disputes", body)
                self.assertIn(status, (400, 404))
        status, _ = self.server.request("POST", "/api/disputes", raw=b"{not json")
        self.assertEqual(400, status)

    def test_oversize_body_is_refused(self):
        status, _ = self.server.request("POST", "/api/disputes", raw=b"{" + b" " * (70 * 1024) + b"}")
        self.assertEqual(413, status)

    def test_run_id_and_static_paths_cannot_escape(self):
        for path in ("/api/disputes/..%2F..%2Fapp/answers", "/api/disputes/../../app/answers",
                     "/api/disputes/%2e%2e/answers", "/api/disputes/nope/answers"):
            with self.subTest(path=path):
                status, _ = self.server.json("POST", path, {"answers": [{"question": "q", "answer": "a"}]})
                self.assertIn(status, (400, 404))
        for path in ("/../app/config.json", "/%2e%2e/app/config.json", "/..%2Fapp%2Fconfig.json",
                     "/party/../../app/config.json", "/%2e%2e/.env"):
            with self.subTest(path=path):
                status, body = self.server.request("GET", path)
                self.assertEqual(404, status)
                self.assertNotIn(b"confidence_threshold", body)

    def test_party_page_is_served(self):
        status, body = self.server.request("GET", "/party/")
        self.assertEqual(200, status)
        self.assertIn(b"<html", body.lower())


class SwappedPackStillWorks(unittest.TestCase):
    def test_synth_pack_filing(self):
        server = _Server(pack_dir=SYNTH_DIR)
        try:
            _, trips = server.json("GET", "/api/trips?category=route_deviation")
            status, view = server.json("POST", "/api/disputes", _filing(trips["trips"][0]["trip_id"]))
            self.assertEqual((200, "decided"), (status, view["status"]), view)
        finally:
            server.close()


# ------------------------------------------------------------------ party pages


class PartyPagesSpeakPlainly(unittest.TestCase):
    """The party never reads about agents, a Judge, confidence or withholding."""

    def _files(self):
        files = [p for p in PARTY_UI.glob("*") if p.suffix in (".html", ".js", ".css")]
        self.assertTrue((PARTY_UI / "index.html").is_file())
        return files

    def test_no_system_vocabulary_in_party_pages(self):
        for path in self._files():
            if path.suffix == ".css":
                continue
            text = path.read_text(encoding="utf-8")
            if path.suffix == ".html":
                text = re.sub(r"<[^>]+>", " ", text)
            else:
                pairs = re.findall(r"\"([^\"\\]*)\"|'([^'\\]*)'", text)
                text = " ".join(a or b for a, b in pairs)
            with self.subTest(file=path.name):
                self.assertIsNone(FORBIDDEN_PARTY_WORDS.search(text), FORBIDDEN_PARTY_WORDS.findall(text))

    def test_no_html_injection_sinks(self):
        for path in self._files():
            if path.suffix != ".js":
                continue
            text = path.read_text(encoding="utf-8")
            with self.subTest(file=path.name):
                for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval("):
                    self.assertNotIn(sink, text)


if __name__ == "__main__":
    unittest.main()
