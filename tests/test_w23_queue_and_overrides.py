"""W23 B1 acceptance target: the review queue and the overrides data.

RED until the build lane ships GET /api/review/queue and GET /api/review/overrides
(contract W23 B1 section 3 items 5-6, the operator rulings 2026-10-03 items 6-8).

Pinned: the queue entry shape; the safety pattern (^\\s*yes\\b, case-insensitive) on a table that
includes "Yesterday"; the amount source order (proposed, then claimed, then none); held_by from
the real withheld event payload and from the real model-failure event; waiting time; every sort
key with ties; and the overrides grouping, which counts approvals and never groups them.
"""

from __future__ import annotations

import json
import time
import unittest
from datetime import datetime, timedelta, timezone

from tests.w23_support import (
    QUEUE_KEYS,
    JudgeFails,
    JudgeScript,
    MockLLMClient,
    Server,
    body,
    judge_payload,
)


def _stamp(seconds_ago):
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).isoformat(timespec="seconds")


class _ServerCase(unittest.TestCase):
    def setUp(self):
        self.server = Server()

    def tearDown(self):
        self.server.close()

    def queue(self):
        status, headers, raw = self.server.raw("GET", "/api/review/queue")
        self.assertEqual((200, "no-store"), (status, headers.get("Cache-Control")))
        payload = json.loads(raw)
        self.assertEqual(["cases"], list(payload))
        return payload["cases"]

    def entry(self, run_id):
        found = [c for c in self.queue() if c["run_id"] == run_id]
        self.assertEqual(1, len(found), run_id)
        return found[0]

    def set_claim(self, run_id, value):
        """HAND-MADE SHAPE: a claim figure the pipeline never records (it stores 0.0 for none)."""
        path = self.server.run_dir(run_id) / "case_file.json"
        case = json.loads(path.read_text(encoding="utf-8"))
        case["intake"]["claim_amount_sgd"] = value
        path.write_text(json.dumps(case), encoding="utf-8")

    def restamp(self, run_id, generated_at):
        """HAND-MADE SHAPE: the case file's generated_at moved, to place the run in time."""
        path = self.server.run_dir(run_id) / "case_file.json"
        case = json.loads(path.read_text(encoding="utf-8"))
        case["generated_at"] = generated_at
        path.write_text(json.dumps(case), encoding="utf-8")


class QueueEntries(_ServerCase):
    def test_an_entry_from_a_real_esc4_hold(self):
        view = self.server.file("T-RD0109", 55.16)
        entry = self.entry(view["run_id"])
        self.assertEqual(QUEUE_KEYS, list(entry))
        self.assertEqual({"run_id": view["run_id"], "dispute_id": view["dispute_id"], "category": "route_deviation",
                          "safety": False, "amount_sgd": 55.16, "amount_source": "proposed",
                          "waiting_seconds": entry["waiting_seconds"], "held_by": ["ESC-4"],
                          "proposed": {"action": "refund", "amount_sgd": 55.16}, "can_approve": True}, entry)
        self.assertIsInstance(entry["waiting_seconds"], int)
        self.assertTrue(0 <= entry["waiting_seconds"] < 120)

    def test_held_by_keeps_every_gate_in_order(self):
        view = self.server.file("T-RD0103", 55.16)
        self.assertEqual(["ESC-4", "RD-4"], self.entry(view["run_id"])["held_by"])
        view = self.server.file("T-RD0103", 5.81)
        self.assertEqual(["RD-4"], self.entry(view["run_id"])["held_by"])
        view = self.server.file("T-RD0108", 55.16)  # cap first, then ESC-2: not alphabetical
        self.assertEqual(["ESC-4", "ESC-2"], self.entry(view["run_id"])["held_by"])

    def test_only_undecided_withheld_runs_are_queued(self):
        held = self.server.file("T-RD0109", 55.16)
        ruled = self.server.file("T-RD0109", 5.81)
        asking = self.server.file("T-RD0109", 5.81, expected_route="")
        support = self.server.file("T-RD0109", None, category="safety_incident")
        cli = self.server.cli_run()  # a command-line run is queued too
        self.assertEqual(sorted([held["run_id"], cli]), sorted(c["run_id"] for c in self.queue()))
        for view in (ruled, asking, support):
            self.assertNotIn(view["run_id"], [c["run_id"] for c in self.queue()])
        self.assertEqual(200, self.server.decide(held["run_id"], body("reject"))[0])
        self.assertEqual([cli], [c["run_id"] for c in self.queue()])

    def test_an_invalid_decision_file_keeps_the_case_queued(self):
        view = self.server.file("T-RD0109", 55.16)
        # HAND-MADE SHAPE: a decision file no writer produces.
        (self.server.run_dir(view["run_id"]) / "human_decision.json").write_text('{"action": "bribe"}', encoding="utf-8")
        self.assertEqual([view["run_id"]], [c["run_id"] for c in self.queue()])


class SafetyFlag(_ServerCase):
    def test_the_safety_pattern(self):
        rows = [("Yes", True), ("yes - he shouted at me", True), ("YES", True), ("  yes", True), ("Yes!", True),
                ("yEs, he braked hard", True), ("No", False), ("Yesterday he was rude", False),
                ("yess", False), ("no, yes", False), ("Not yes", False)]
        runs = []
        for answer, expected in rows:
            view = self.server.file("T-RD0109", 55.16, safety=answer)
            self.assertEqual("withheld", self.server.case(view["run_id"])["resolution"]["outcome"], answer)
            runs.append((answer, expected, view["run_id"]))
        by_run = {c["run_id"]: c["safety"] for c in self.queue()}
        for answer, expected, run_id in runs:
            with self.subTest(answer=answer):
                self.assertIs(expected, by_run[run_id])

    def test_a_blank_answer_is_not_a_safety_case(self):
        # A blank answer is asked about first; its round-two run is the one that waits.
        first = self.server.file("T-RD0109", 55.16, safety="")
        self.assertEqual("needs_info", first["status"])
        reply = {"answers": [{"question": q, "answer": "I have nothing more to add"} for q in first["questions"]]}
        status, second = self.server.json("POST", "/api/disputes/%s/answers" % first["run_id"], reply)
        self.assertEqual(200, status, second)
        self.assertEqual("", self.server.case(second["run_id"])["intake"]["form_answers"]["safety_concern"])
        self.assertIs(False, self.entry(second["run_id"])["safety"])

    def test_a_missing_answer_is_not_a_safety_case(self):
        answers = {"expected_route": "Expressway.", "was_route_agreed": "No", "asked_driver_to_stop": "No"}
        view = self.server.file("T-RD0109", 55.16, answers=answers)
        self.assertNotIn("safety_concern", self.server.case(view["run_id"])["intake"]["form_answers"])
        self.assertIs(False, self.entry(view["run_id"])["safety"])


class AmountAndProposal(_ServerCase):
    def test_the_proposal_beats_the_claim(self):
        self.server.set_llm(JudgeScript(judge_payload(amount=60.0)))
        view = self.server.file("T-RD0109", 55.16)
        entry = self.entry(view["run_id"])
        self.assertEqual((60.0, "proposed", {"action": "refund", "amount_sgd": 60.0}, True),
                         (entry["amount_sgd"], entry["amount_source"], entry["proposed"], entry["can_approve"]))

    def test_a_no_action_proposal_is_an_amount_of_zero(self):
        view = self.server.file("T-RD0108", None)
        entry = self.entry(view["run_id"])
        self.assertEqual((0.0, "proposed", {"action": "no action", "amount_sgd": 0.0}, ["ESC-2"]),
                         (entry["amount_sgd"], entry["amount_source"], entry["proposed"], entry["held_by"]))

    def test_model_failure_falls_back_to_the_claim(self):
        self.server.set_llm(JudgeFails())
        view = self.server.file("T-RD0109", 12.34)
        entry = self.entry(view["run_id"])
        self.assertEqual((12.34, "claimed", None, False, ["model_failure"]),
                         (entry["amount_sgd"], entry["amount_source"], entry["proposed"], entry["can_approve"],
                          entry["held_by"]))

    def test_a_claim_that_is_not_a_figure_is_none(self):
        self.server.set_llm(JudgeFails())
        view = self.server.file("T-RD0109", None)
        # The pipeline always records a claim figure (0.0 when none was stated): that is a claim.
        self.assertEqual((0.0, "claimed"), (self.entry(view["run_id"])["amount_sgd"],
                                            self.entry(view["run_id"])["amount_source"]))
        for label, value in (("null", None), ("string", "12.34"), ("bool", True), ("NaN", float("nan")),
                             ("inf", float("inf")), ("list", [12.34])):
            self.set_claim(view["run_id"], value)
            entry = self.entry(view["run_id"])
            with self.subTest(label=label):
                self.assertEqual((None, None, None, False),
                                 (entry["amount_sgd"], entry["amount_source"], entry["proposed"], entry["can_approve"]))


class HeldByFailsSoft(_ServerCase):
    def test_unreadable_event_records_give_an_empty_list(self):
        view = self.server.file("T-RD0109", 55.16)
        run = self.server.run_dir(view["run_id"])
        withheld = [json.loads(line) for line in (run / "events.jsonl").read_text(encoding="utf-8").splitlines()
                    if json.loads(line)["type"] == "judge.ruling_withheld"][0]
        (run / withheld["payload_ref"]).unlink()  # HAND-MADE SHAPE: payload lost
        self.assertEqual([], self.entry(view["run_id"])["held_by"])
        other = self.server.file("T-RD0109", 55.16)
        (self.server.run_dir(other["run_id"]) / "events.jsonl").unlink()  # HAND-MADE SHAPE: log lost
        self.assertEqual([], self.entry(other["run_id"])["held_by"])


class WaitingTime(_ServerCase):
    def test_waiting_is_floored_seconds_and_never_negative(self):
        old = self.server.file("T-RD0109", 55.16)
        future = self.server.file("T-RD0109", 55.16)
        self.restamp(old["run_id"], _stamp(3600))
        self.restamp(future["run_id"], _stamp(-7200))
        waiting = self.entry(old["run_id"])["waiting_seconds"]
        self.assertTrue(3600 <= waiting < 3700, waiting)
        self.assertEqual(0, self.entry(future["run_id"])["waiting_seconds"])


class QueueOrder(_ServerCase):
    def test_safety_then_amount_then_waiting_then_run_id(self):
        s = self.server
        safety_small = s.file("T-RD0103", 5.81, safety="Yes")
        big_new = s.file("T-RD0109", 55.16)
        big_old = s.file("T-RD0109", 55.16)
        mid_a = s.file("T-RD0103", 5.81)
        mid_b = s.file("T-RD0103", 5.81)
        zero = s.file("T-RD0108", None)
        s.set_llm(JudgeFails())
        none = s.file("T-RD0109", None)
        s.set_llm(MockLLMClient())
        self.restamp(safety_small["run_id"], _stamp(10))
        self.restamp(big_new["run_id"], _stamp(100))
        self.restamp(big_old["run_id"], _stamp(7200))
        tie = _stamp(500)
        self.restamp(mid_a["run_id"], tie)
        self.restamp(mid_b["run_id"], tie)
        self.set_claim(none["run_id"], None)
        self.assertIsNone(self.entry(none["run_id"])["amount_sgd"], "precondition")
        self.restamp(none["run_id"], _stamp(90000))   # None counts as 0: sorts with zero, by waiting
        self.restamp(zero["run_id"], _stamp(50000))
        mids = sorted([mid_a["run_id"], mid_b["run_id"]])
        expected = [safety_small["run_id"], big_old["run_id"], big_new["run_id"]] + mids + [none["run_id"], zero["run_id"]]
        cases = self.queue()
        self.assertEqual(expected, [c["run_id"] for c in cases])
        self.assertEqual([True, False, False, False, False, False, False], [c["safety"] for c in cases])
        self.assertEqual(cases[3]["waiting_seconds"], cases[4]["waiting_seconds"], "precondition: a real tie")


class Overrides(_ServerCase):
    def _get(self):
        status, headers, raw = self.server.raw("GET", "/api/review/overrides")
        self.assertEqual((200, "no-store"), (status, headers.get("Cache-Control")))
        payload = json.loads(raw)
        self.assertEqual(["approved_count", "groups"], sorted(payload))
        return payload

    def test_empty(self):
        self.assertEqual({"approved_count": 0, "groups": []}, self._get())

    def test_approvals_are_counted_and_departures_grouped(self):
        s = self.server
        approve_a, approve_b = s.file("T-RD0109", 55.16), s.file("T-RD0109", 55.16)
        change_old, change_new = s.file("T-RD0109", 55.16), s.file("T-RD0109", 55.16)
        reject_one = s.file("T-RD0109", 55.16)
        comp = s.file("T-RD0109", 55.16)
        rd4 = s.file("T-RD0103", 5.81)
        no_show = s.file("T-NS0201", 60.0, category="no_show_charge")
        self.assertEqual("withheld", s.case(no_show["run_id"])["resolution"]["outcome"], "precondition")
        undecided = s.file("T-RD0109", 55.16)
        for view in (approve_a, approve_b):
            self.assertEqual(200, s.decide(view["run_id"], body("approve"))[0])
        # Decided in this order, a second apart, so the oldest-first order differs from folder order.
        self.assertEqual(200, s.decide(change_new["run_id"], body("change", reviewer="Cy", reason="r1",
                                                                  action="refund", amount_sgd=30.0))[0])
        time.sleep(1.1)
        self.assertEqual(200, s.decide(change_old["run_id"], body("change", reviewer="Di", reason="r2",
                                                                  action="Refund", amount_sgd=42.0))[0])
        for view, b in ((reject_one, body("reject")),
                        (comp, body("change", action="compensation", amount_sgd=10.0)),
                        (rd4, body("change", action="refund", amount_sgd=5.56)),
                        (no_show, body("reject"))):
            self.assertEqual(200, s.decide(view["run_id"], b)[0])
        payload = self._get()
        self.assertEqual(2, payload["approved_count"])
        groups = payload["groups"]
        for group in groups:
            self.assertEqual(["category", "held_by", "decision", "action", "count", "decisions"], list(group))
            self.assertEqual(group["count"], len(group["decisions"]))
            for d in group["decisions"]:
                self.assertEqual(["run_id", "dispute_id", "reviewer", "reason", "action", "amount_sgd", "proposed",
                                  "decided_at"], list(d))
        summary = [(g["category"], g["held_by"], g["decision"], g["action"], g["count"]) for g in groups]
        no_show_held = self.entry_free_held_by(no_show["run_id"])
        self.assertEqual(("route_deviation", ["ESC-4"], "change", "refund", 2), summary[0])
        self.assertEqual(("no_show_charge", no_show_held, "reject", "no action", 1), summary[1])
        self.assertEqual({("route_deviation", ("ESC-4",), "change", "compensation", 1),
                          ("route_deviation", ("RD-4",), "change", "refund", 1),
                          ("route_deviation", ("ESC-4",), "reject", "no action", 1)},
                         {(a, tuple(b), c, d, e) for a, b, c, d, e in summary[2:]})
        self.assertEqual([r for r in summary[2:] if r[2] == "change"] + [r for r in summary[2:] if r[2] == "reject"],
                         summary[2:], "same count and category: decision order")
        first = groups[0]["decisions"]
        self.assertEqual([change_new["run_id"], change_old["run_id"]], [d["run_id"] for d in first])
        self.assertEqual({"run_id": change_new["run_id"], "dispute_id": change_new["dispute_id"], "reviewer": "Cy",
                          "reason": "r1", "action": "refund", "amount_sgd": 30.0,
                          "proposed": {"action": "refund", "amount_sgd": 55.16}},
                         {k: v for k, v in first[0].items() if k != "decided_at"})
        every = [d["run_id"] for g in groups for d in g["decisions"]]
        for view in (approve_a, approve_b, undecided):
            self.assertNotIn(view["run_id"], every)

    def entry_free_held_by(self, run_id):
        run = self.server.run_dir(run_id)
        for line in (run / "events.jsonl").read_text(encoding="utf-8").splitlines():
            event = json.loads(line)
            if event["type"] == "judge.ruling_withheld":
                return json.loads((run / event["payload_ref"]).read_text(encoding="utf-8"))["gates_failed"]
        return []

    def test_groups_sort_by_count_then_category(self):
        s = self.server
        route = [s.file("T-RD0109", 55.16) for _ in range(2)]
        no_show = s.file("T-NS0201", 60.0, category="no_show_charge")
        for view in route + [no_show]:
            self.assertEqual(200, s.decide(view["run_id"], body("reject"))[0])
        cats = [(g["category"], g["count"]) for g in self._get()["groups"]]
        self.assertEqual([("route_deviation", 2), ("no_show_charge", 1)], cats)
        # one more no-show reject in the same held_by group ties the counts: category order decides
        extra = s.file("T-NS0201", 60.0, category="no_show_charge")
        self.assertEqual(200, s.decide(extra["run_id"], body("reject"))[0])
        cats = [(g["category"], g["count"]) for g in self._get()["groups"]]
        self.assertEqual([("no_show_charge", 2), ("route_deviation", 2)], cats)


if __name__ == "__main__":
    unittest.main()
