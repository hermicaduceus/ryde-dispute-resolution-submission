"""W35 fix round R3: the two MINOR findings of the R2 review, each fixed as a class.

Written RED-first against 680ce9b. docs/build-briefs/w35-r3-brief.md has the code; this file is the
contract.

  R3-1  An open dropped by a panels load (Refresh, or the reload after a recorded decision) may still
        answer, success or failure, while a NEWER open of the same, already-current row is in flight.
        That newer open keeps its pending state ("Opening…", disabled) until its OWN response settles.
        The current-row branch of applyListSelection leaves a pending button's text and disabled
        state alone; the row stays the one marked current (is-open, aria-current="true").
  R3-2  decision_record_is_valid is total: an action that is not a string (a list, an object, a
        number, null, a bool) is "not a valid decision" and never raises. A stored
        human_decision.json carrying such an action reads as no decision, so the Recent runs list,
        the queue, Overrides, both demo accounts, the party status and the case GET keep answering
        200 with the case still under review; the decide-once refusal (409, file untouched) stays.

Fake-DOM tests drive the real ui/app.js in Node (the driver of tests/test_w35_r2_K.py); server tests use
the real server on the mock model; RealBrowserR3 (needs PUPPETEER_MODULE and BROWSER_EXECUTABLE) runs
tests/browser/w35_r3.cjs against the real server.

Run: env -u PYTHONPATH /usr/bin/python3 -B -m unittest tests.test_w35_r3 -v
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests import test_w35_C as C
from tests import test_w35_r2_K as K
from tests.w23_b2_support import NODE
from tests.w23_support import Server, body as decision_body

REPO = Path(__file__).resolve().parent.parent
BROWSER_DIR = REPO / "tests" / "browser"

RUN_A, RUN_B = C.RUN_A, C.RUN_B
ok, wait, SNAP, REFRESH = C.ok, C.wait, C.SNAP, C.REFRESH
run_entry, queue_entry, case_for = C.run_entry, C.queue_entry, C.case_for
drive = K.drive

CASE_A = "/api/review/%s/case" % RUN_A
STALE = {
    "success": lambda: ok({"case_file": case_for(RUN_A), "human_decision": None}, delay=400),
    "http500": lambda: {"status": 500, "body": {}, "delay": 400},
    "network": lambda: {"reject": True, "delay": 400},
}
LISTS = {
    # list name -> (open action, checkpoint key of its buttons, checkpoint key of its rows)
    "runs": (C.run_open, "runButtons", "runRows"),
    "queue": (C.queue_open, "queueButtons", "queueRows"),
}


def _rows(checkpoint, list_name):
    return checkpoint["runRows"] if list_name == "runs" else checkpoint["panel"]["queueRows"]


def _current_marks(checkpoint):
    """(list, run id) of every Open button carrying aria-current="true", in both lists."""
    marks = []
    for list_name, button_cls in (("runs", "run-open"), ("queue", "queue-open")):
        for row in _rows(checkpoint, list_name):
            for child in row["children"]:
                if button_cls in child["className"].split() and child["attrs"].get("aria-current") == "true":
                    marks.append((list_name, row["dataset"].get("runId")))
    return marks


def _button(checkpoint, list_name):
    """Run A's Open button in the named list (row 0)."""
    key = LISTS[list_name][1]
    return checkpoint[key][0]


# ================================================================== R3-1: the current row's newer open


class StaleOpenSparesTheNewerCurrentRowOpen(unittest.TestCase):
    """Open A; reopen A (held, the stale one); Refresh; reopen A from the replacement row (held longer);
    the stale reply lands; then the newer reply lands. Timeline (ms): open 20, reopen 70 (answers 470),
    Refresh 90 (the list answers ~190), newer reopen 260 (answers 1160)."""

    def routes(self, list_name, stale):
        r = C.routes(runs=[run_entry(RUN_A), run_entry(RUN_B, "ruled")],
                     queue=[queue_entry(RUN_A), queue_entry(RUN_B)])
        key = "/api/review/runs" if list_name == "runs" else "/api/review/queue"
        r[key] = [r[key][0], dict(r[key][0], delay=100)]
        r[CASE_A] = [ok({"case_file": case_for(RUN_A), "human_decision": None}),
                     STALE[stale](),
                     ok({"case_file": case_for(RUN_A), "human_decision": None}, delay=900)]
        return r

    def schedule(self, list_name, stale):
        opener = LISTS[list_name][0]
        return drive(self.routes(list_name, stale),
                     [wait(20), opener(0), wait(50), opener(0), wait(20), REFRESH, wait(170),
                      opener(0), wait(20), SNAP, wait(400), SNAP, wait(700), SNAP])

    def test_the_newer_open_stays_pending_when_the_stale_one_settles(self):
        for list_name in LISTS:
            for stale in STALE:
                with self.subTest(list=list_name, stale=stale):
                    out = self.schedule(list_name, stale)
                    pending, after_stale, landed = out["checkpoints"]
                    # The schedule itself: the list reloaded, the newer open is in flight, nothing re-rendered.
                    self.assertEqual("false", pending["panel"]["busy"][list_name])
                    self.assertEqual({"text": "Opening…", "disabled": True},
                                     {k: _button(pending, list_name)[k] for k in ("text", "disabled")})
                    self.assertEqual(3, [u for u in after_stale["requests"]].count(CASE_A),
                                     "first open, the dropped reopen and the newer reopen")
                    # The stale reply has arrived (t~470) and the newer one has not (t~1160).
                    self.assertEqual({"text": "Opening…", "disabled": True},
                                     {k: _button(after_stale, list_name)[k] for k in ("text", "disabled")},
                                     "the stale reply settled the newer open's button")
                    self.assertEqual(RUN_A, after_stale["loaded"])
                    # Its owner settles it.
                    self.assertEqual({"text": "Currently open", "disabled": False},
                                     {k: _button(landed, list_name)[k] for k in ("text", "disabled")})
                    self.assertEqual(RUN_A, landed["loaded"])

    def test_the_row_stays_the_one_marked_current_while_its_newer_open_is_pending(self):
        for list_name in LISTS:
            for stale in ("success", "http500"):
                with self.subTest(list=list_name, stale=stale):
                    out = self.schedule(list_name, stale)
                    for checkpoint in out["checkpoints"]:
                        self.assertEqual([(list_name, RUN_A)], _current_marks(checkpoint))
                        row = _rows(checkpoint, list_name)[0]
                        self.assertIn("is-open", row["className"].split())

    def test_a_current_row_with_no_open_in_flight_still_reads_currently_open(self):
        """The settle path is unchanged when nothing newer is pending: the dropped reopen lands, the row
        (re-rendered by Refresh) reads Currently open and is enabled once the list has landed."""
        for list_name in LISTS:
            for stale in STALE:
                with self.subTest(list=list_name, stale=stale):
                    opener = LISTS[list_name][0]
                    out = drive(self.routes(list_name, stale),
                                [wait(20), opener(0), wait(50), opener(0), wait(20), REFRESH, wait(170), SNAP,
                                 wait(400), SNAP])
                    for checkpoint in out["checkpoints"]:
                        self.assertEqual({"text": "Currently open", "disabled": False},
                                         {k: _button(checkpoint, list_name)[k] for k in ("text", "disabled")})
                        self.assertEqual(RUN_A, checkpoint["loaded"])

    def test_a_non_current_row_keeps_its_pending_open_as_before(self):
        """The sibling branch already respected a pending open; it must keep doing so."""
        r = C.routes(runs=[run_entry(RUN_A), run_entry(RUN_B, "ruled")])
        r["/api/review/runs"] = [r["/api/review/runs"][0], dict(r["/api/review/runs"][0], delay=100)]
        r["/api/review/%s/case" % RUN_B] = [{"status": 500, "body": {}, "delay": 400},
                                            ok({"case_file": case_for(RUN_B), "human_decision": None}, delay=900)]
        out = drive(r, [wait(20), C.run_open(1), wait(20), REFRESH, wait(170), C.run_open(1), wait(400), SNAP,
                        wait(700), SNAP])
        after_stale, landed = out["checkpoints"]
        self.assertEqual({"text": "Opening…", "disabled": True},
                         {k: after_stale["runButtons"][1][k] for k in ("text", "disabled")})
        self.assertEqual(RUN_B, landed["loaded"])


# ================================================================== R3-2: a non-string action

ACTION_SHAPES = {
    "list": [],
    "list-of-action": ["refund"],
    "object": {},
    "object-keyed-by-action": {"refund": 1},
    "null": None,
    "int": 3,
    "float": 3.0,
    "bool": True,
}


class DecisionRecordIsTotal(unittest.TestCase):
    VALID = K.LoadDecisionAndTheHelper.VALID

    def test_every_non_string_action_is_invalid_and_never_raises(self):
        from app.human_review import decision_record_is_valid
        for name, action in ACTION_SHAPES.items():
            with self.subTest(action=name):
                record = dict(self.VALID, action=action)
                try:
                    verdict = decision_record_is_valid(record)
                except Exception as exc:  # noqa: BLE001 - the contract is: never raises
                    self.fail("decision_record_is_valid raised %s for a %s action" % (type(exc).__name__, name))
                self.assertIs(False, verdict)

    def test_every_real_action_is_still_valid(self):
        from app.human_review import decision_record_is_valid
        from app.schemas import RulingAction
        self.assertTrue(len(list(RulingAction)) >= 3)
        for member in RulingAction:
            with self.subTest(action=member.value):
                self.assertIs(True, decision_record_is_valid(dict(self.VALID, action=member.value)))
        self.assertIs(False, decision_record_is_valid(dict(self.VALID, action="gift")))
        self.assertIs(False, decision_record_is_valid(dict(self.VALID, action=self.VALID["action"].upper())))

    def test_load_decision_reads_a_non_string_action_as_no_decision(self):
        from app.human_review import load_decision
        tmp = Path(tempfile.mkdtemp(prefix="w35r3-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        for name, action in ACTION_SHAPES.items():
            with self.subTest(action=name):
                (tmp / "human_decision.json").write_text(json.dumps(dict(self.VALID, action=action)), encoding="utf-8")
                try:
                    loaded = load_decision(tmp)
                except Exception as exc:  # noqa: BLE001 - the contract is: never raises
                    self.fail("load_decision raised %s for a %s action" % (type(exc).__name__, name))
                self.assertIsNone(loaded)
        (tmp / "human_decision.json").write_text(json.dumps(self.VALID), encoding="utf-8")
        self.assertEqual(self.VALID, load_decision(tmp), "a valid record still loads")


class NonStringActionOnTheServer(unittest.TestCase):
    """The reviewer's route list, on the real server: every view answers 200 and the case stays waiting."""

    @classmethod
    def setUpClass(cls):
        cls.server = Server()
        cls.held = cls.server.file()
        cls.leaf = cls.server.run_dir(cls.held["run_id"]) / "human_decision.json"

    @classmethod
    def tearDownClass(cls):
        cls.server.close()

    def tearDown(self):
        if self.leaf.exists():
            self.leaf.unlink()

    def paths(self):
        run_id = self.held["run_id"]
        return ["/api/review/runs", "/api/review/queue", "/api/review/overrides", "/api/demo/rider",
                "/api/demo/driver", "/api/disputes/" + self.held["dispute_id"], "/api/review/%s/case" % run_id]

    def test_every_view_answers_with_a_list_or_object_action_stored(self):
        for name in ("list", "object", "list-of-action", "object-keyed-by-action"):
            raw = json.dumps({"action": ACTION_SHAPES[name], "amount_sgd": 0})
            self.leaf.write_text(raw, encoding="utf-8")
            for path in self.paths():
                with self.subTest(action=name, path=path):
                    status, data = self.server.json("GET", path)
                    self.assertEqual(200, status, data)

    def test_the_case_stays_waiting_and_undecided(self):
        run_id = self.held["run_id"]
        for name in ("list", "object"):
            with self.subTest(action=name):
                raw = json.dumps({"action": ACTION_SHAPES[name], "amount_sgd": 0})
                self.leaf.write_text(raw, encoding="utf-8")
                status, queue = self.server.json("GET", "/api/review/queue")
                self.assertEqual(200, status)
                self.assertIn(run_id, [c.get("run_id") for c in queue.get("cases", [])], "still waiting for a person")
                status, case = self.server.json("GET", "/api/review/%s/case" % run_id)
                self.assertEqual(200, status)
                self.assertIsNone(case.get("human_decision"))
                status, party = self.server.json("GET", "/api/disputes/" + self.held["dispute_id"])
                self.assertEqual(200, status)
                self.assertNotEqual("decided", party.get("status"))

    def test_the_decide_once_refusal_still_holds_and_leaves_the_file_alone(self):
        for name in ("list", "object"):
            with self.subTest(action=name):
                raw = json.dumps({"action": ACTION_SHAPES[name], "amount_sgd": 0})
                self.leaf.write_text(raw, encoding="utf-8")
                status, _ = self.server.decide(self.held["run_id"], decision_body("reject"))
                self.assertEqual(409, status)
                self.assertEqual(raw, self.leaf.read_text(encoding="utf-8"))


# ================================================================== real browser


def _browser_env():
    return os.environ.get("PUPPETEER_MODULE") and os.environ.get("BROWSER_EXECUTABLE")


@unittest.skipUnless(_browser_env(), "PUPPETEER_MODULE and BROWSER_EXECUTABLE are not set")
class RealBrowserR3(unittest.TestCase):
    """tests/browser/w35_r3.cjs against the real server with real mock runs."""

    @classmethod
    def setUpClass(cls):
        cls.server = Server()
        cls.rd = cls.server.file(trip_id="T-RD0109", category="route_deviation", claim=55.16)
        cls.ns = cls.server.file(trip_id="T-NS0202", category="no_show_charge", claim=None)
        report_dir = Path(tempfile.mkdtemp(prefix="w35r3-browser-"))
        cls.report = report_dir / "report.json"
        env = dict(os.environ, W35R3_QUEUED=cls.rd["run_id"])
        cls.result = subprocess.run([NODE, str(BROWSER_DIR / "w35_r3.cjs"), cls.server.base, str(cls.report)],
                                    env=env, capture_output=True, text=True, timeout=600)
        cls.data = json.loads(cls.report.read_text()) if cls.report.is_file() else {}
        cls.report_dir = report_dir

    @classmethod
    def tearDownClass(cls):
        cls.server.close()
        shutil.rmtree(cls.report_dir, True)

    def scenario(self, name):
        self.assertTrue(self.data.get("scenarios"), (self.data.get("error") or self.result.stderr)[-3000:])
        results = [(k, v) for k, v in self.data["scenarios"].items() if k.startswith(name)]
        self.assertTrue(results, "the script ran no scenario named %s*" % name)
        for key, error in results:
            with self.subTest(scenario=key):
                self.assertIsNone(error)

    def test_a_stale_open_spares_the_newer_current_runs_open_in_a_browser(self):
        self.scenario("reused-current-runs")

    def test_a_stale_open_spares_the_newer_current_queue_open_in_a_browser(self):
        self.scenario("reused-current-queue")

    def test_the_script_itself_finished_cleanly(self):
        self.assertEqual(0, self.result.returncode, (self.data.get("error") or self.result.stderr)[-3000:])
        self.assertTrue(self.data.get("passed"), self.data.get("error"))
        self.assertEqual(8, len(self.data.get("scenarios", {})), "2 lists x 2 stale outcomes x 2 widths")
        self.assertEqual([], self.data.get("pageErrors"))


if __name__ == "__main__":
    unittest.main()
