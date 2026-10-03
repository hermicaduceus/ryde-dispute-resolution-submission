"""W23 B1 acceptance target: the human decision on a withheld case.

RED until the build lane ships app/human_review.py, app/events.append_event and the decision
endpoint (contract: W23 B1, the operator rulings 2026-10-01 and 2026-10-03).

Pinned here:
  * validate_decision: the check order, every wrong-shape input, the SGD 500 ceiling and the
    cent rounding at their boundaries, and that NO money gate is consulted again (4a).
  * record_decision: decide once (sequential and N=8 concurrent), nothing on disk for a refused
    body, case_file.json and dispute.json byte-identical, one event appended with seq = max+1.
  * The party message: exact text for approve / change / reject, the approve-only Basis line
    (the operator ruling 2026-10-03 option b), no reviewer name or reason, no demo notice.
  * party_view(case, human_decision, policy): the decision applies only to a withheld case and
    only when well formed.
"""

from __future__ import annotations

import concurrent.futures
import copy
import io
import json
import math
import os
import re
import tempfile
import unittest
from contextlib import redirect_stderr
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from tests.w23_support import (
    EVENT_KEYS,
    HUMAN_SENTENCE,
    ORG_DIR,
    PARTY_VIEW_KEYS,
    RECORD_KEYS,
    SENTINEL_REASON,
    SENTINEL_REVIEWER,
    UNDER_REVIEW,
    JudgeFails,
    JudgeScript,
    Server,
    body,
    events,
    judge_payload,
    pipeline_case,
    policy,
    sha,
)

RD123 = "When a deviation is material; A material deviation is not automatically a breach; Unjustified material deviation: remedy"

_CASES = {}


def _withheld():
    """Real pipeline: organiser RD-0109 with a 55.16 claim is held by ESC-4 on the mock."""
    if "withheld" not in _CASES:
        case = pipeline_case(ORG_DIR, "RD-0109.json", claim=55.16)
        assert case["resolution"]["outcome"] == "withheld", case["resolution"]["outcome"]
        _CASES["withheld"] = case
    return copy.deepcopy(_CASES["withheld"])


def _model_failure():
    """Real pipeline: the Judge call fails permanently, so there is no proposal."""
    if "failure" not in _CASES:
        case = pipeline_case(ORG_DIR, "RD-0109.json", claim=55.16, llm=JudgeFails())
        assert case["resolution"]["outcome"] == "withheld"
        assert case["resolution"]["withheld_candidate"] is None
        _CASES["failure"] = case
    return copy.deepcopy(_CASES["failure"])


def _rd4_held():
    """Real pipeline: organiser RD-0103 with a 5.81 claim is held by RD-4 alone on the mock."""
    if "rd4" not in _CASES:
        case = pipeline_case(ORG_DIR, "RD-0103.json", claim=5.81)
        assert case["resolution"]["outcome"] == "withheld"
        _CASES["rd4"] = case
    return copy.deepcopy(_CASES["rd4"])


def _ruled():
    if "ruled" not in _CASES:
        case = pipeline_case(ORG_DIR, "RD-0101.json")
        assert case["resolution"]["outcome"] == "ruled"
        _CASES["ruled"] = case
    return copy.deepcopy(_CASES["ruled"])


def _support():
    if "support" not in _CASES:
        case = pipeline_case(ORG_DIR, "OS-0301.json")
        assert case["resolution"]["outcome"] == "human_review"
        _CASES["support"] = case
    return copy.deepcopy(_CASES["support"])


def _with_candidate(case, **fields):
    """HAND-MADE SHAPE: a withheld candidate no Judge contract produces (bad types, sub-cent
    amounts). The pipeline rounds and type-checks before it stores, so only an edit reaches it."""
    case = copy.deepcopy(case)
    candidate = case["resolution"]["withheld_candidate"]
    if isinstance(candidate, dict):
        candidate.update(fields)
    return case


_DEFAULT = object()


def _validate(b, case=_DEFAULT):
    from app.human_review import validate_decision

    return validate_decision(b, _withheld() if case is _DEFAULT else case)


class _Refusal:
    def assertRefused(self, status, b, case=_DEFAULT, message=None):
        from app.human_review import HumanDecisionError

        with self.assertRaises(HumanDecisionError) as caught:
            _validate(b, case)
        self.assertEqual(status, caught.exception.status, b)
        self.assertIsInstance(caught.exception.message, str)
        self.assertTrue(caught.exception.message.strip())
        if message is not None:
            self.assertEqual(message, caught.exception.message)


# ------------------------------------------------------------------- constants


class Constants(unittest.TestCase):
    def test_module_constants(self):
        from app import human_review as hr

        self.assertEqual("human_decision.json", hr.HUMAN_DECISION_FILE_NAME)
        self.assertEqual(500.0, hr.HUMAN_AMOUNT_CEILING_SGD)
        self.assertEqual("A member of our team reviewed your case.", hr.HUMAN_REVIEWED_SENTENCE)
        self.assertEqual(("approve", "change", "reject"), hr.DECISIONS)
        self.assertEqual(80, hr.REVIEWER_MAX_CHARS)
        self.assertEqual(1000, hr.REASON_MAX_CHARS)
        self.assertTrue(issubclass(hr.HumanDecisionError, Exception))
        err = hr.HumanDecisionError(418, "teapot")
        self.assertEqual((418, "teapot"), (err.status, err.message))

    def test_event_type(self):
        from app.events import EventType

        self.assertEqual("human.decision_recorded", EventType.HUMAN_DECISION_RECORDED)


# ------------------------------------------------------------------- validation


class CaseMustBeWaiting(_Refusal, unittest.TestCase):
    MESSAGE = "this case is not waiting for a human decision"

    def test_non_withheld_case_files_are_409(self):
        ruled, support = _ruled(), _support()
        hand_made = [None, [], "withheld", 7, {}, {"resolution": None}, {"resolution": []},
                     {"resolution": "withheld"}, {"resolution": {}},
                     {"resolution": {"outcome": "Withheld"}}, {"resolution": {"outcome": "ruled"}}]
        for case in [ruled, support] + hand_made:
            with self.subTest(case=str(case)[:60]):
                self.assertRefused(409, body("change", action="refund", amount_sgd=5.0), case, self.MESSAGE)

    def test_the_case_check_comes_before_the_body_checks(self):
        for bad in ({}, {"decision": "nope"}, body("approve", reviewer="")):
            with self.subTest(bad=bad):
                self.assertRefused(409, bad, _ruled(), self.MESSAGE)


WRONG_TEXT = [("missing", None), ("None", None), ("bool", True), ("int", 5), ("float", 5.0),
              ("NaN", float("nan")), ("+inf", float("inf")), ("-inf", float("-inf")),
              ("list", ["Ana"]), ("dict", {"name": "Ana"}), ("blank", ""), ("spaces", "   "),
              ("whitespace", " \t\n ")]


class DecisionField(_Refusal, unittest.TestCase):
    def test_wrong_decisions_are_400(self):
        rows = [("missing", None), ("None", None), ("bool", True), ("int", 1), ("str number", "1"),
                ("Approve", "Approve"), ("APPROVE", "APPROVE"), ("padded", " approve"), ("blank", ""),
                ("spaces", "  "), ("list", ["approve"]), ("dict", {"decision": "approve"}),
                ("NaN", float("nan")), ("+inf", float("inf")), ("other", "escalate"), ("long", "approve" * 50)]
        for label, value in rows:
            b = body("reject")
            if label == "missing":
                del b["decision"]
            else:
                b["decision"] = value
            with self.subTest(label=label):
                self.assertRefused(400, b)

    def test_each_decision_is_accepted(self):
        self.assertEqual("approve", _validate(body("approve"))["decision"])
        self.assertEqual("change", _validate(body("change", action="refund", amount_sgd=5.0))["decision"])
        self.assertEqual("reject", _validate(body("reject"))["decision"])


class ReviewerAndReason(_Refusal, unittest.TestCase):
    def _family(self, key, limit):
        for label, value in WRONG_TEXT + [("over length", "x" * (limit + 1)),
                                          ("over length after strip", "  " + "x" * (limit + 1) + "  ")]:
            b = body("reject")
            if label == "missing":
                del b[key]
            else:
                b[key] = value
            with self.subTest(key=key, label=label):
                self.assertRefused(400, b)

    def test_reviewer_wrong_shapes(self):
        self._family("reviewer", 80)

    def test_reason_wrong_shapes(self):
        self._family("reason", 1000)

    def test_length_boundaries_count_after_the_strip(self):
        record = _validate(body("reject", reviewer="   " + "r" * 80 + "  ", reason="\n" + "q" * 1000 + " \t"))
        self.assertEqual("r" * 80, record["reviewer"])
        self.assertEqual("q" * 1000, record["reason"])

    def test_both_are_stored_stripped(self):
        record = _validate(body("reject", reviewer="  Ana Lim ", reason=" Not agreed.\n"))
        self.assertEqual(("Ana Lim", "Not agreed."), (record["reviewer"], record["reason"]))

    def test_reviewer_is_checked_before_the_proposal(self):
        # approve on a model-failure case would be 409; a bad reviewer must be refused first.
        self.assertRefused(400, body("approve", reviewer="  "), _model_failure())


class Approve(_Refusal, unittest.TestCase):
    NO_EXTRAS = "approve takes no action or amount; use change"
    NOTHING = "there is no proposed ruling to approve"

    def test_approve_takes_the_proposal(self):
        record = _validate(body("approve"))
        self.assertEqual(("refund", 55.16), (record["action"], record["amount_sgd"]))
        self.assertEqual({"action": "refund", "amount_sgd": 55.16}, record["proposed"])

    def test_approve_refuses_an_action_or_an_amount(self):
        for extra in ({"action": "refund"}, {"amount_sgd": 55.16}, {"action": None},
                      {"amount_sgd": None}, {"action": "refund", "amount_sgd": 55.16}):
            with self.subTest(extra=extra):
                self.assertRefused(400, body("approve", **extra), message=self.NO_EXTRAS)

    def test_extras_are_refused_before_the_missing_proposal(self):
        self.assertRefused(400, body("approve", amount_sgd=5.0), _model_failure(), self.NO_EXTRAS)

    def test_model_failure_case_has_nothing_to_approve(self):
        self.assertRefused(409, body("approve"), _model_failure(), self.NOTHING)

    def test_malformed_proposals_have_nothing_to_approve(self):
        base = _withheld()
        rows = [("array", []), ("empty", {}), ("string", "refund")]
        for label, candidate in rows:
            case = copy.deepcopy(base)
            case["resolution"]["withheld_candidate"] = candidate  # HAND-MADE SHAPE
            with self.subTest(label=label):
                self.assertRefused(409, body("approve"), case, self.NOTHING)
        for label, fields in [("bad action", {"action": "bribe"}), ("None action", {"action": None}),
                              ("bool amount", {"recommended_amount_sgd": True}),
                              ("str amount", {"recommended_amount_sgd": "55.16"}),
                              ("None amount", {"recommended_amount_sgd": None}),
                              ("NaN", {"recommended_amount_sgd": float("nan")}),
                              ("+inf", {"recommended_amount_sgd": float("inf")}),
                              ("-inf", {"recommended_amount_sgd": float("-inf")}),
                              ("huge int", {"recommended_amount_sgd": 10 ** 400}),
                              ("list", {"recommended_amount_sgd": [55.16]})]:
            with self.subTest(label=label):
                self.assertRefused(409, body("approve"), _with_candidate(base, **fields), self.NOTHING)

    def test_approve_rounds_the_proposal_to_the_cent(self):
        record = _validate(body("approve"), _with_candidate(_withheld(), recommended_amount_sgd=55.164))
        self.assertEqual(55.16, record["amount_sgd"])
        self.assertEqual({"action": "refund", "amount_sgd": 55.16}, record["proposed"])

    def test_approving_no_action_stores_zero(self):
        case = _with_candidate(_withheld(), action="no action", recommended_amount_sgd=3.0)
        record = _validate(body("approve"), case)
        self.assertEqual(("no action", 0.0), (record["action"], record["amount_sgd"]))

    def test_approve_has_the_same_ceiling(self):
        # the operator 2026-10-03: the SGD 500 ceiling covers every human decision. The model's
        # amount has no upper bound in the contract parse, so one click on a held SGD 600
        # proposal must not pay it; the reviewer uses change instead.
        above = "the proposed amount is above SGD 500.00; use change"
        self.assertEqual(500.0, _validate(body("approve"), _with_candidate(_withheld(), recommended_amount_sgd=500.00))["amount_sgd"])
        self.assertEqual(500.0, _validate(body("approve"), _with_candidate(_withheld(), recommended_amount_sgd=500.004))["amount_sgd"])
        self.assertRefused(400, body("approve"), _with_candidate(_withheld(), recommended_amount_sgd=500.006), above)
        self.assertRefused(400, body("approve"), _with_candidate(_withheld(), recommended_amount_sgd=600.0), above)
        compensation = _with_candidate(_withheld(), action="compensation", recommended_amount_sgd=500.01)
        self.assertRefused(400, body("approve"), compensation, above)


AMOUNT_WRONG = [("missing", None), ("None", None), ("True", True), ("False", False), ("str number", "5.00"),
                ("blank", ""), ("spaces", "  "), ("list", [5.0]), ("dict", {"v": 5.0}),
                ("NaN", float("nan")), ("+inf", float("inf")), ("-inf", float("-inf")),
                ("huge JSON int", 10 ** 400), ("negative", -1), ("negative cent", -0.01)]


class Change(_Refusal, unittest.TestCase):
    def test_action_parses_like_the_ruling_enum(self):
        for raw, wire in (("refund", "refund"), ("Refund", "refund"), ("COMPENSATION", "compensation"),
                          ("No_Action", "no action"), ("no-action", "no action"), ("no action", "no action")):
            amount = 0.0 if wire == "no action" else 12.5
            with self.subTest(raw=raw):
                self.assertEqual(wire, _validate(body("change", action=raw, amount_sgd=amount))["action"])

    def test_wrong_actions_are_400(self):
        for label, value in [("missing", None), ("None", None), ("bool", True), ("int", 1), ("blank", ""),
                             ("spaces", "  "), ("refunds", "refunds"), ("list", ["refund"]),
                             ("dict", {"a": "refund"}), ("NaN", float("nan")), ("long", "refund" * 200)]:
            b = body("change", amount_sgd=5.0)
            if label != "missing":
                b["action"] = value
            with self.subTest(label=label):
                self.assertRefused(400, b)

    def test_wrong_amounts_are_400_never_an_exception(self):
        for action in ("refund", "compensation", "no action"):
            for label, value in AMOUNT_WRONG:
                b = body("change", action=action)
                if label != "missing":
                    b["amount_sgd"] = value
                with self.subTest(action=action, label=label):
                    self.assertRefused(400, b)

    def test_the_ceiling_boundary(self):
        for action in ("refund", "compensation"):
            with self.subTest(action=action):
                self.assertEqual(500.0, _validate(body("change", action=action, amount_sgd=500.00))["amount_sgd"])
                self.assertEqual(500.0, _validate(body("change", action=action, amount_sgd=500))["amount_sgd"])
                self.assertRefused(400, body("change", action=action, amount_sgd=500.01))
                self.assertRefused(400, body("change", action=action, amount_sgd=501))

    def test_the_ceiling_is_checked_after_rounding(self):
        self.assertEqual(500.0, _validate(body("change", action="refund", amount_sgd=500.004))["amount_sgd"])
        self.assertRefused(400, body("change", action="refund", amount_sgd=500.006))

    def test_money_needs_an_amount_above_zero_after_rounding(self):
        for action in ("refund", "compensation"):
            with self.subTest(action=action):
                self.assertRefused(400, body("change", action=action, amount_sgd=0))
                self.assertRefused(400, body("change", action=action, amount_sgd=0.0))
                self.assertRefused(400, body("change", action=action, amount_sgd=0.004))
                self.assertEqual(0.01, _validate(body("change", action=action, amount_sgd=0.006))["amount_sgd"])
                self.assertEqual(0.01, _validate(body("change", action=action, amount_sgd=0.01))["amount_sgd"])

    def test_no_action_needs_zero_after_rounding(self):
        self.assertEqual(0.0, _validate(body("change", action="no action", amount_sgd=0))["amount_sgd"])
        self.assertEqual(0.0, _validate(body("change", action="no action", amount_sgd=0.004))["amount_sgd"])
        self.assertRefused(400, body("change", action="no action", amount_sgd=0.01))
        self.assertRefused(400, body("change", action="no action", amount_sgd=5))

    def test_amounts_are_rounded_floats(self):
        record = _validate(body("change", action="refund", amount_sgd=42.345678))
        self.assertEqual(42.35, record["amount_sgd"])
        record = _validate(body("change", action="compensation", amount_sgd=7))
        self.assertIs(float, type(record["amount_sgd"]))
        self.assertEqual(7.0, record["amount_sgd"])

    def test_no_money_gate_is_consulted(self):
        # 4a: the gate that held the case does not hold the person's decision.
        record = _validate(body("change", action="refund", amount_sgd=55.16))  # held by ESC-4
        self.assertEqual(("refund", 55.16), (record["action"], record["amount_sgd"]))
        record = _validate(body("change", action="refund", amount_sgd=5.56), _rd4_held())  # held by RD-4
        self.assertEqual(("refund", 5.56), (record["action"], record["amount_sgd"]))
        record = _validate(body("change", action="compensation", amount_sgd=120.0), _rd4_held())
        self.assertEqual(("compensation", 120.0), (record["action"], record["amount_sgd"]))

    def test_change_works_on_a_model_failure_case(self):
        record = _validate(body("change", action="refund", amount_sgd=20.0), _model_failure())
        self.assertEqual(("refund", 20.0, None), (record["action"], record["amount_sgd"], record["proposed"]))


class Reject(_Refusal, unittest.TestCase):
    def test_reject_is_no_action_zero(self):
        record = _validate(body("reject"))
        self.assertEqual(("no action", 0.0), (record["action"], record["amount_sgd"]))
        self.assertEqual({"action": "refund", "amount_sgd": 55.16}, record["proposed"])

    def test_reject_refuses_an_action_or_an_amount(self):
        for extra in ({"action": "no action"}, {"amount_sgd": 0.0}, {"action": None}, {"amount_sgd": None}):
            with self.subTest(extra=extra):
                self.assertRefused(400, body("reject", **extra))

    def test_reject_works_on_a_model_failure_case(self):
        record = _validate(body("reject"), _model_failure())
        self.assertEqual(("no action", 0.0, None), (record["action"], record["amount_sgd"], record["proposed"]))


class RecordShape(unittest.TestCase):
    def test_exact_keys_in_order_and_values(self):
        case = _withheld()
        case["run_id"], case["dispute_id"] = "run-for-shape", "PF-SHAPE001"
        before = datetime.now(timezone.utc).replace(microsecond=0)
        record = _validate(body("change", reviewer="Ana Lim", reason="Agreed detour.", action="refund",
                                amount_sgd=30.0), case)
        after = datetime.now(timezone.utc)
        self.assertEqual(RECORD_KEYS, list(record))
        self.assertEqual("1.0", record["schema_version"])
        self.assertEqual(("run-for-shape", "PF-SHAPE001"), (record["run_id"], record["dispute_id"]))
        self.assertEqual(("change", "Ana Lim", "Agreed detour.", "refund", 30.0),
                         (record["decision"], record["reviewer"], record["reason"], record["action"],
                          record["amount_sgd"]))
        self.assertEqual({"action": "refund", "amount_sgd": 55.16}, record["proposed"])
        stamp = datetime.fromisoformat(record["decided_at"].replace("Z", "+00:00"))
        self.assertEqual(timedelta(0), stamp.utcoffset())
        self.assertEqual(0, stamp.microsecond)
        self.assertRegex(record["decided_at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\+00:00|Z)$")
        self.assertTrue(before <= stamp <= after, (before, stamp, after))


# ------------------------------------------------------------------- the event log


class AppendEvent(unittest.TestCase):
    def test_seq_continues_from_the_highest_seq_on_disk(self):
        from app.events import append_event

        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            # HAND-MADE SHAPE: seqs out of order, so max, last and count all differ.
            lines = [json.dumps({"seq": n, "type": "x"}) for n in (1, 7, 3)]
            (run / "events.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
            before = (run / "events.jsonl").read_bytes()
            event = append_event(run, "r-1", "human.decision_recorded", from_="human_review", to="parties",
                                 summary="s", payload={"k": 1})
            self.assertEqual(8, event["seq"])
            after = (run / "events.jsonl").read_bytes()
            self.assertTrue(after.startswith(before))
            new_lines = after[len(before):].decode("utf-8").splitlines()
            self.assertEqual(1, len(new_lines))
            line = json.loads(new_lines[0])
            self.assertEqual(EVENT_KEYS, list(line))
            self.assertEqual(event, line)
            self.assertEqual("payloads/0008-human-decision-recorded.json", line["payload_ref"])
            self.assertEqual({"k": 1}, json.loads((run / line["payload_ref"]).read_text(encoding="utf-8")))
            self.assertEqual(("1.0", "r-1", "human.decision_recorded", "human_review", "parties", "s"),
                             (line["schema_version"], line["run_id"], line["type"], line["from"], line["to"],
                              line["summary"]))

    def test_a_fresh_log_starts_at_one_and_no_payload_means_no_ref(self):
        from app.events import append_event

        with tempfile.TemporaryDirectory() as tmp:
            event = append_event(Path(tmp), "r-2", "x.y", from_="a", to="b", summary="first")
            self.assertEqual((1, None), (event["seq"], event["payload_ref"]))
            self.assertEqual([event], events(Path(tmp)))
            self.assertFalse(list(Path(tmp).glob("payloads/*")))


# ------------------------------------------------------------------- storage over HTTP


class _ServerCase(unittest.TestCase):
    def setUp(self):
        self.server = Server()

    def tearDown(self):
        self.server.close()

    def _esc4(self, **kw):
        view = self.server.file("T-RD0109", 55.16, **kw)
        self.assertEqual("withheld", self.server.case(view["run_id"])["resolution"]["outcome"])
        return view


class DecideOnce(_ServerCase):
    ALREADY = "this case already has a human decision"

    def test_a_decision_is_stored_and_returned(self):
        view = self._esc4()
        run = self.server.run_dir(view["run_id"])
        status, headers, raw = self.server.raw("POST", "/api/review/%s/decision" % view["run_id"],
                                               body("change", action="refund", amount_sgd=42.5))
        self.assertEqual(200, status, raw)
        self.assertEqual("no-store", headers.get("Cache-Control"))
        payload = json.loads(raw)
        self.assertEqual(["decision", "party_view"], sorted(payload))
        record = payload["decision"]
        self.assertEqual(RECORD_KEYS, list(record))
        self.assertEqual((view["run_id"], view["dispute_id"]), (record["run_id"], record["dispute_id"]))
        self.assertEqual(record, json.loads((run / "human_decision.json").read_text(encoding="utf-8")))
        from app.human_review import load_decision

        self.assertEqual(record, load_decision(run))
        self.assertEqual(PARTY_VIEW_KEYS, list(payload["party_view"]))
        self.assertEqual({"run_id": view["run_id"], "dispute_id": view["dispute_id"], "status": "decided",
                          "message": "Decision: refund of SGD 42.50. " + HUMAN_SENTENCE, "questions": []},
                         payload["party_view"])

    def test_a_second_decision_is_409_and_changes_nothing(self):
        view = self._esc4()
        run = self.server.run_dir(view["run_id"])
        self.assertEqual(200, self.server.decide(view["run_id"], body("reject"))[0])
        stored = (run / "human_decision.json").read_bytes()
        log = (run / "events.jsonl").read_bytes()
        status, payload = self.server.decide(view["run_id"], body("change", action="refund", amount_sgd=9.0))
        self.assertEqual((409, {"error": self.ALREADY}), (status, payload))
        self.assertEqual(stored, (run / "human_decision.json").read_bytes())
        self.assertEqual(log, (run / "events.jsonl").read_bytes())

    def test_eight_concurrent_decisions_one_winner(self):
        view = self._esc4()
        run = self.server.run_dir(view["run_id"])
        before = set(os.listdir(run))
        reviewers = ["Reviewer %d" % i for i in range(8)]

        def post(name):
            return name, self.server.decide(view["run_id"], body("change", reviewer=name, action="refund",
                                                                 amount_sgd=10.0))

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(post, reviewers))
        statuses = sorted(status for _name, (status, _p) in results)
        self.assertEqual([200] + [409] * 7, statuses)
        for _name, (status, payload) in results:
            if status == 409:
                self.assertEqual({"error": self.ALREADY}, payload)
        winner = next(name for name, (status, _p) in results if status == 200)
        stored = json.loads((run / "human_decision.json").read_text(encoding="utf-8"))
        self.assertEqual(winner, stored["reviewer"])
        recorded = [e for e in events(run) if e["type"] == "human.decision_recorded"]
        self.assertEqual(1, len(recorded))
        self.assertEqual("human reviewer %s decided: change" % winner, recorded[0]["summary"])
        self.assertEqual(before | {"human_decision.json"}, set(os.listdir(run)),
                         "no temporary file may be left behind")

    def test_a_refused_body_touches_nothing(self):
        view = self._esc4()
        run = self.server.run_dir(view["run_id"])
        snapshot = {p.relative_to(run): p.read_bytes() for p in run.rglob("*") if p.is_file()}
        for bad in (body("change", action="refund", amount_sgd=500.01), body("approve", amount_sgd=1.0),
                    body("reject", reviewer=""), {"decision": "approve"}):
            with self.subTest(bad=bad):
                status, payload = self.server.decide(view["run_id"], bad)
                self.assertEqual(400, status)
                self.assertEqual(["error"], list(payload))
        self.assertEqual(snapshot, {p.relative_to(run): p.read_bytes() for p in run.rglob("*") if p.is_file()})

    def test_error_statuses_carry_the_message(self):
        view = self._esc4()
        status, payload = self.server.decide(view["run_id"], body("approve", action="refund"))
        self.assertEqual((400, {"error": "approve takes no action or amount; use change"}), (status, payload))
        ruled = self.server.file("T-RD0109", 5.81)
        status, payload = self.server.decide(ruled["run_id"], body("reject"))
        self.assertEqual((409, {"error": "this case is not waiting for a human decision"}), (status, payload))

    def test_huge_json_int_is_400_not_500(self):
        view = self._esc4()
        raw = ('{"decision": "change", "reviewer": "Ana", "reason": "r", "action": "refund", '
               '"amount_sgd": 1%s}' % ("0" * 400)).encode("utf-8")
        status, payload = self.server.json("POST", "/api/review/%s/decision" % view["run_id"], data=raw)
        self.assertEqual(400, status, payload)
        for literal in (b"NaN", b"Infinity", b"-Infinity"):
            raw = ('{"decision": "change", "reviewer": "Ana", "reason": "r", "action": "refund", '
                   '"amount_sgd": %s}' % literal.decode()).encode("utf-8")
            with self.subTest(literal=literal):
                self.assertEqual(400, self.server.json("POST", "/api/review/%s/decision" % view["run_id"],
                                                       data=raw)[0])
        self.assertFalse((self.server.run_dir(view["run_id"]) / "human_decision.json").exists())

    def test_bad_bodies_and_unknown_runs(self):
        view = self._esc4()
        self.assertEqual(400, self.server.json("POST", "/api/review/%s/decision" % view["run_id"], data=b"{nope")[0])
        self.assertEqual(400, self.server.json("POST", "/api/review/%s/decision" % view["run_id"], data=b"[]")[0])
        (self.server.out / "empty-dir").mkdir()
        corrupt = self.server.out / "corrupt-run"
        corrupt.mkdir()
        (corrupt / "case_file.json").write_text("{", encoding="utf-8")  # HAND-MADE SHAPE
        for run_id in ("nope", "..", "%2e%2e", "..%2F..%2Fapp", "a" * 129, "empty-dir", "corrupt-run"):
            with self.subTest(run_id=run_id):
                status, _ = self.server.decide(run_id, body("reject"))
                self.assertEqual(404, status)

    def test_cli_runs_take_a_decision_too(self):
        run_id = self.server.cli_run()
        self.assertFalse((self.server.run_dir(run_id) / "dispute.json").exists())
        status, payload = self.server.decide(run_id, body("reject"))
        self.assertEqual(200, status, payload)
        self.assertEqual("RD-0109", payload["decision"]["dispute_id"])


class DecisionLeavesTheRunIntact(_ServerCase):
    def test_case_file_and_dispute_are_byte_identical(self):
        view = self._esc4()
        run = self.server.run_dir(view["run_id"])
        case_hash, dispute_hash = sha(run / "case_file.json"), sha(run / "dispute.json")
        self.assertEqual(200, self.server.decide(view["run_id"], body("change", action="refund", amount_sgd=40.0))[0])
        self.assertEqual(case_hash, sha(run / "case_file.json"))
        self.assertEqual(dispute_hash, sha(run / "dispute.json"))

    def test_exactly_one_event_is_appended(self):
        view = self._esc4()
        run = self.server.run_dir(view["run_id"])
        before = (run / "events.jsonl").read_bytes()
        top = max(e["seq"] for e in events(run))
        _, payload = self.server.decide(view["run_id"], body("change", reviewer="  Ana Lim ",
                                                             reason="SENTINEL-REASON-7731", action="refund",
                                                             amount_sgd=40.0))
        after = (run / "events.jsonl").read_bytes()
        self.assertTrue(after.startswith(before), "existing lines must stay byte-identical")
        added = [json.loads(line) for line in after[len(before):].decode("utf-8").splitlines()]
        self.assertEqual(1, len(added))
        event = added[0]
        self.assertEqual(EVENT_KEYS, list(event))
        self.assertEqual(top + 1, event["seq"])
        self.assertEqual(("1.0", view["run_id"], "human.decision_recorded", "human_review", "parties"),
                         (event["schema_version"], event["run_id"], event["type"], event["from"], event["to"]))
        self.assertEqual("human reviewer Ana Lim decided: change", event["summary"])
        self.assertEqual(payload["decision"], json.loads((run / event["payload_ref"]).read_text(encoding="utf-8")))
        self.assertTrue((run / event["payload_ref"]).is_file())

    def test_the_summary_never_carries_the_amount_or_the_reason(self):
        for decision, extra, expected in (("approve", {}, "approve"), ("reject", {}, "reject"),
                                          ("change", {"action": "compensation", "amount_sgd": 77.25}, "change")):
            view = self._esc4()
            run = self.server.run_dir(view["run_id"])
            self.assertEqual(200, self.server.decide(view["run_id"], body(decision, reviewer="Bo",
                                                                          reason=SENTINEL_REASON, **extra))[0])
            summary = events(run)[-1]["summary"]
            with self.subTest(decision=decision):
                self.assertEqual("human reviewer Bo decided: %s" % expected, summary)
                for leak in ("55.16", "77.25", "SGD", SENTINEL_REASON):
                    self.assertNotIn(leak, summary)

    def test_a_failed_event_append_does_not_undo_the_decision(self):
        view = self._esc4()
        run = self.server.run_dir(view["run_id"])
        log = (run / "events.jsonl").read_bytes()
        with mock.patch("app.events.append_event", side_effect=RuntimeError("log unavailable")), \
                redirect_stderr(io.StringIO()):
            status, payload = self.server.decide(view["run_id"], body("reject"))
        self.assertEqual(200, status, payload)
        self.assertEqual(payload["decision"], json.loads((run / "human_decision.json").read_text(encoding="utf-8")))
        self.assertEqual(log, (run / "events.jsonl").read_bytes())

    def test_a_failed_event_append_is_logged_to_stderr(self):
        # Direct call, so the server's own request log cannot satisfy the check.
        from app.human_review import record_decision

        view = self._esc4()
        run = self.server.run_dir(view["run_id"])
        with mock.patch("app.events.append_event", side_effect=RuntimeError("log unavailable")), \
                redirect_stderr(io.StringIO()) as err:
            record = record_decision(run, self.server.case(view["run_id"]), body("reject"))
        self.assertEqual("reject", record["decision"])
        self.assertTrue(err.getvalue().strip(), "the failed append must be logged to stderr")


class LoadDecisionFailsClosed(unittest.TestCase):
    def test_every_bad_file_reads_as_none(self):
        from app.human_review import load_decision

        good = {"action": "refund", "amount_sgd": 5.0}
        rows = [("missing", None), ("empty", ""), ("corrupt", "{"), ("array", "[]"), ("null", "null"),
                ("string", '"refund"'), ("bad action", json.dumps(dict(good, action="bribe"))),
                ("No_Action", json.dumps(dict(good, action="No_Action"))),
                ("str amount", json.dumps(dict(good, amount_sgd="5"))),
                ("bool amount", json.dumps(dict(good, amount_sgd=True))),
                ("no amount", json.dumps({"action": "refund"})), ("NaN", '{"action": "refund", "amount_sgd": NaN}'),
                ("inf", '{"action": "refund", "amount_sgd": Infinity}'),
                ("-inf", '{"action": "refund", "amount_sgd": -Infinity}'),
                ("huge", '{"action": "refund", "amount_sgd": 1%s}' % ("0" * 400))]
        for label, text in rows:
            with tempfile.TemporaryDirectory() as tmp, self.subTest(label=label):
                if text is not None:
                    (Path(tmp) / "human_decision.json").write_text(text, encoding="utf-8")  # HAND-MADE SHAPE
                self.assertIsNone(load_decision(Path(tmp)))
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "human_decision.json").write_text(json.dumps(good), encoding="utf-8")
            self.assertEqual(good, load_decision(Path(tmp)))


# ------------------------------------------------------------------- the party message


class _FakePolicy:
    """A policy whose titles exercise the skip rules (unknown, empty, unsafe)."""

    TITLES = {"RD-1": "When a deviation is material", "RD-2": "", "RD-3": "The judge weighs the model",
              "GEN-2": "Every finding must rest on the Evidence Pack", "ESC-4": "Amount above the autonomous cap"}

    def rule_title(self, rule_id):
        if rule_id not in self.TITLES:
            raise KeyError(rule_id)
        return self.TITLES[rule_id]


class PartyMessage(unittest.TestCase):
    def _msg(self, decision, action, amount, cited=("RD-1", "RD-2", "RD-3"), pol="real"):
        from app.human_review import party_message_for_human_decision

        record = {"decision": decision, "reviewer": SENTINEL_REVIEWER, "reason": SENTINEL_REASON,
                  "action": action, "amount_sgd": amount}
        candidate = {"action": "refund", "recommended_amount_sgd": 55.16, "cited_rule_ids": list(cited)}
        return party_message_for_human_decision(record, candidate, policy() if pol == "real" else pol)

    def test_approve_keeps_the_basis_line(self):
        self.assertEqual("Decision: refund of SGD 55.16. Basis: %s. %s" % (RD123, HUMAN_SENTENCE),
                         self._msg("approve", "refund", 55.16))

    def test_basis_titles_follow_the_decided_message_rules(self):
        # ESC skipped by prefix, unknown skipped, at most three, citation order kept.
        self.assertEqual("Decision: refund of SGD 55.16. Basis: %s. %s" % (RD123, HUMAN_SENTENCE),
                         self._msg("approve", "refund", 55.16, ("ESC-4", "RD-1", "ZZ-9", "RD-2", "RD-3", "GEN-2")))
        self.assertEqual("Decision: refund of SGD 55.16. Basis: Unjustified material deviation: remedy; "
                         "When a deviation is material. " + HUMAN_SENTENCE,
                         self._msg("approve", "refund", 55.16, ("RD-3", "RD-1")))

    def test_empty_and_unsafe_titles_are_skipped(self):
        self.assertEqual("Decision: refund of SGD 55.16. Basis: When a deviation is material; Every finding "
                         "must rest on the Evidence Pack. " + HUMAN_SENTENCE,
                         self._msg("approve", "refund", 55.16, ("RD-2", "RD-3", "RD-1", "ESC-4", "GEN-2"),
                                   pol=_FakePolicy()))

    def test_approve_with_only_escalation_rules_has_no_basis(self):
        self.assertEqual("Decision: refund of SGD 55.16. " + HUMAN_SENTENCE,
                         self._msg("approve", "refund", 55.16, ("ESC-4", "ESC-2")))
        self.assertEqual("Decision: refund of SGD 55.16. " + HUMAN_SENTENCE,
                         self._msg("approve", "refund", 55.16, ("ESC-4",), pol=_FakePolicy()))

    def test_approve_without_a_policy_or_citations_has_no_basis(self):
        self.assertEqual("Decision: refund of SGD 55.16. " + HUMAN_SENTENCE,
                         self._msg("approve", "refund", 55.16, pol=None))
        self.assertEqual("Decision: refund of SGD 55.16. " + HUMAN_SENTENCE,
                         self._msg("approve", "refund", 55.16, ()))

    def test_approve_no_action_keeps_the_basis(self):
        self.assertEqual("Decision: no action. Basis: %s. %s" % (RD123, HUMAN_SENTENCE),
                         self._msg("approve", "no action", 0.0))

    def test_change_never_carries_a_basis(self):
        self.assertEqual("Decision: refund of SGD 5.56. " + HUMAN_SENTENCE, self._msg("change", "refund", 5.56))
        self.assertEqual("Decision: compensation of SGD 12.50. " + HUMAN_SENTENCE,
                         self._msg("change", "compensation", 12.5))
        self.assertEqual("Decision: no action. " + HUMAN_SENTENCE, self._msg("change", "no action", 0.0))

    def test_reject_never_carries_a_basis(self):
        self.assertEqual("Decision: no action. A member of our team reviewed your case.",
                         self._msg("reject", "no action", 0.0))

    def test_messages_are_party_safe_and_private(self):
        from app.schemas import is_party_safe

        for decision, action, amount in (("approve", "refund", 55.16), ("change", "compensation", 3.0),
                                         ("reject", "no action", 0.0)):
            message = self._msg(decision, action, amount)
            with self.subTest(decision=decision):
                self.assertTrue(is_party_safe(message), message)
                self.assertNotIn(SENTINEL_REASON, message)
                self.assertNotIn(SENTINEL_REVIEWER, message)
                self.assertNotIn("Demo notice", message)


# ------------------------------------------------------------------- party_view


class PartyViewWithDecision(unittest.TestCase):
    def _record(self, decision="change", action="refund", amount=42.5):
        return {"schema_version": "1.0", "decision": decision, "reviewer": SENTINEL_REVIEWER,
                "reason": SENTINEL_REASON, "action": action, "amount_sgd": amount}

    def test_a_decided_withheld_case(self):
        from app.server import party_view

        case = _withheld()
        view = party_view(case, self._record())
        self.assertEqual({"run_id": case["run_id"], "dispute_id": case["dispute_id"], "status": "decided",
                          "message": "Decision: refund of SGD 42.50. " + HUMAN_SENTENCE, "questions": []}, view)

    def test_approve_uses_the_case_candidate_and_the_policy(self):
        from app.server import party_view

        case = pipeline_case(ORG_DIR, "RD-0109.json", claim=55.16, llm=JudgeScript(judge_payload(
            cited=("ESC-4", "RD-1", "RD-2", "RD-3"))))
        self.assertEqual("withheld", case["resolution"]["outcome"])
        record = self._record("approve", "refund", 55.16)
        self.assertEqual("Decision: refund of SGD 55.16. Basis: %s. %s" % (RD123, HUMAN_SENTENCE),
                         party_view(case, record, policy())["message"])
        self.assertEqual("Decision: refund of SGD 55.16. " + HUMAN_SENTENCE, party_view(case, record)["message"])
        self.assertEqual("Decision: no action. " + HUMAN_SENTENCE,
                         party_view(case, self._record("reject", "no action", 0.0), policy())["message"])

    def test_malformed_decisions_are_ignored(self):
        from app.server import party_view

        case = _withheld()
        for bad in (None, [], {}, "refund", True, self._record(action="bribe"), self._record(amount="42.5"),
                    self._record(amount=True), self._record(amount=float("nan")), self._record(amount=float("inf")),
                    {"amount_sgd": 1.0}):
            with self.subTest(bad=str(bad)[:50]):
                view = party_view(case, bad)
                self.assertEqual(("under_review", UNDER_REVIEW, []), (view["status"], view["message"], view["questions"]))

    def test_a_decision_on_a_case_that_is_not_withheld_is_ignored(self):
        from app.server import party_view

        for case in (_ruled(), _support()):
            with self.subTest(outcome=case["resolution"]["outcome"]):
                self.assertEqual(party_view(case), party_view(case, self._record(), policy()))

    def test_no_demo_notice_on_a_human_decision(self):
        from app.schemas import DEMO_NOTICE_MESSAGE
        from app.server import party_view

        self.assertNotIn(DEMO_NOTICE_MESSAGE.strip(), party_view(_withheld(), self._record())["message"])


class NothingLeaksToParties(_ServerCase):
    PARTY_PATHS = ("/api/demo/rider", "/api/demo/driver")

    def _party_blobs(self, dispute_id):
        blobs = []
        for path in ("/api/disputes/%s" % dispute_id,) + self.PARTY_PATHS:
            status, _h, raw = self.server.raw("GET", path)
            self.assertEqual(200, status, path)
            blobs.append((path, raw.decode("utf-8")))
        return blobs

    def test_withheld_figures_never_reach_a_party_before_a_decision(self):
        view = self._esc4()
        confidence = self.server.case(view["run_id"])["resolution"]["withheld_candidate"]["confidence"]
        for path, blob in self._party_blobs(view["dispute_id"]):
            with self.subTest(path=path):
                for leak in ("55.16", "confidence", "withheld", repr(confidence), "ESC-4"):
                    self.assertNotIn(leak, blob)

    def test_the_reviewer_and_reason_never_reach_a_party(self):
        view = self._esc4()
        self.server.file("T-RD0109", 5.81)
        status, payload = self.server.decide(view["run_id"], body("change", reviewer=SENTINEL_REVIEWER,
                                                                  reason=SENTINEL_REASON, action="refund",
                                                                  amount_sgd=31.25))
        self.assertEqual(200, status)
        self.assertNotIn(SENTINEL_REASON, json.dumps(payload["party_view"]))
        for path, blob in self._party_blobs(view["dispute_id"]):
            with self.subTest(path=path):
                self.assertNotIn(SENTINEL_REASON, blob)
                self.assertNotIn(SENTINEL_REVIEWER, blob)
                self.assertNotIn("Ana Lim", blob)
                self.assertIn("Decision: refund of SGD 31.25. " + HUMAN_SENTENCE, blob)


class ServerPassesItsPolicy(unittest.TestCase):
    """The decided view built from an approve carries the Basis, so the server must hand the
    loaded policy to every party view it builds from a human decision."""

    def test_every_party_surface_shows_the_basis_after_an_approve(self):
        server = Server(llm=JudgeScript(judge_payload(cited=("ESC-4", "RD-1", "RD-2", "RD-3"))))
        try:
            view = server.file("T-RD0109", 55.16)
            self.assertEqual("withheld", server.case(view["run_id"])["resolution"]["outcome"])
            expected = "Decision: refund of SGD 55.16. Basis: %s. %s" % (RD123, HUMAN_SENTENCE)
            status, payload = server.decide(view["run_id"], body("approve"))
            self.assertEqual(200, status, payload)
            self.assertEqual(expected, payload["party_view"]["message"])
            self.assertEqual(expected, server.json("GET", "/api/disputes/%s" % view["dispute_id"])[1]["message"])
            for path in ("/api/demo/rider", "/api/demo/driver"):
                entries = server.json("GET", path)[1]["disputes"]
                with self.subTest(path=path):
                    self.assertEqual([expected], [e["message"] for e in entries if e["dispute_id"] == view["dispute_id"]])
        finally:
            server.close()


if __name__ == "__main__":
    unittest.main()
