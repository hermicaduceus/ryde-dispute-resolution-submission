"""W35 fix round R2, lane K (operator console + server): reviewer findings 2-6, fixed as classes.

Written RED-first against 55204c1. The findings (docs/build-briefs/w35-r2-K-brief.md has the
code; the contract is this file):

  K2  A review list (Recent runs, the queue, Overrides) is rendered, cleared and its status
      restored only by the NEWEST load of that list. An older response, success or failure
      (HTTP error or network error), never touches the list, whatever the newer one did.
  K3  While a list's load is in flight, that list is aria-busy="true" and its Open buttons are
      disabled, so no open can start against rows about to be replaced; the owning load's
      settle (success or failure) clears both. Any panels load (Refresh, or the reload after a
      recorded decision) first drops the pending opens, as Refresh always did.
  K4  Every read of a run's case file, decision file (and dispute record) goes through ONE
      helper, app.human_review.bounded_run_file(run_dir, name): the leaf must resolve inside
      the run directory, else it reads as missing. Escaping symlinks are not followed by the
      runs list, the queue, Overrides, /case, the decision POST, the answers POST or the
      party views; a symlink that stays inside the run directory still works.
  K5  load_decision fails closed on a deeply nested decision file (RecursionError): no
      decision, never HTTP 500.
  K6  The run-folder loader renders and attaches only a case object that carries a non-empty
      run_id, a non-empty dispute_id and a resolution object with a non-empty outcome; any
      other shape gets the existing plain case-object message and loads nothing.

Fake-DOM tests drive the real ui/app.js in Node (the driver of tests/test_w35_C.py, extended
with panel state); server tests use the real server on the mock model; the browser test
(RealBrowserK, needs PUPPETEER_MODULE and BROWSER_EXECUTABLE) runs tests/browser/w35_r2_K.cjs.

Run: env -u PYTHONPATH /usr/bin/python3 -B -m unittest tests.test_w35_r2_K -v
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from tests import test_w35_C as C
from tests.w23_b2_support import NODE
from tests.w23_support import Server, body as decision_body, strip_js_comments

REPO = Path(__file__).resolve().parent.parent
UI = REPO / "ui"
BROWSER_DIR = REPO / "tests" / "browser"

NOT_OBJECT = C.NOT_OBJECT
NOT_ATTACHED = C.NOT_ATTACHED
CASE_FAILED = C.CASE_FAILED
RUNS_UNAVAILABLE = C.RUNS_UNAVAILABLE
QUEUE_UNAVAILABLE = "The review queue is not available. Open the console from the running server to use it."
OVERRIDES_UNAVAILABLE = "Overrides are not available."
UNDER_REVIEW = "Your case is still under review. We will let you know as soon as a decision is made."

RUN_A, RUN_B, RUN_C = C.RUN_A, C.RUN_B, C.RUN_C

# app/agents/*, app/llm/*, docs/policy.md and data/ at 55204c1: sha256 over the sorted
# "<path>\0<sha256>\n" lines of their 49 files.
PROTECTED_TREE_SHA = "056bcf2ee57903367910ffa25ef621a7bd358f9430bbce8040466d2547e3f160"
PROTECTED_TREE_FILES = 49
# app/human_review.py at 55204c1 with load_decision removed (from "def load_decision(" up to the
# party-message section marker): everything else in the human-decision module is unchanged.
HUMAN_REVIEW_REST_SHA = "f1bf780bb4e28bafefe70162a939e7fa291f725b15d36968542ef9db85ed5f6d"


# ------------------------------------------------------------------ the fake-DOM driver

H2 = C.H
_old = 'payloadStatus:ids["payload-status"].textContent,'
assert H2.count(_old) == 1
H2 = H2.replace(
    _old,
    _old + 'panel:{busy:{queue:(ids["queue-content"]._attrs["aria-busy"]||null),overrides:(ids["overrides-content"]._attrs["aria-busy"]||null),'
    'runs:(ids["runs-content"]._attrs["aria-busy"]||null)},'
    'status:{queue:ids["queue-status"].textContent,overrides:ids["overrides-status"].textContent,runs:ids["runs-status"].textContent},'
    'queueIds:byClass("queue-row").map(n=>n.dataset.runId),runIds:byClass("run-row").map(n=>n.dataset.runId),'
    'overridesText:ids["overrides-content"].textContent,queueRows:byClass("queue-row").map(snap),'
    'decision:ids["decision-content"].textContent,resolution:ids["resolution-content"].textContent},',
)


def drive(routes, actions=(), search=""):
    scenario = {"routes": routes, "actions": list(actions), "search": search}
    env = dict(os.environ, APP_JS=str(UI / "app.js"), SCENARIO=json.dumps(scenario))
    result = subprocess.run([NODE, "-e", H2], env=env, capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise AssertionError("app.js W35 R2 K driver failed: " + result.stderr)
    return json.loads(result.stdout)


ok, wait, SNAP, REFRESH = C.ok, C.wait, C.SNAP, C.REFRESH
run_open, queue_open = C.run_open, C.queue_open
run_entry, queue_entry, case_for, folder = C.run_entry, C.queue_entry, C.case_for, C.folder
node, urls = C.node, C.urls


def http500(**extra):
    out = {"status": 500, "body": {}}
    out.update(extra)
    return out


def refused(**extra):
    out = {"reject": True}
    out.update(extra)
    return out


def rows(checkpoint, list_name):
    return checkpoint["runRows"] if list_name == "runs" else checkpoint["panel"]["queueRows"]


def child_text(row, class_name):
    for child in row["children"]:
        if class_name in child["className"].split():
            return child["text"]
    raise AssertionError("no .%s in the row" % class_name)


def child(row, class_name):
    for item in row["children"]:
        if class_name in item["className"].split():
            return item
    raise AssertionError("no .%s in the row" % class_name)


# ================================================================== K2: stale panel loads

PANELS = ("runs", "queue", "overrides")
OLDER = {"success": lambda payload: ok(payload, delay=250), "http500": lambda payload: http500(delay=250),
         "network": lambda payload: refused(delay=250)}


def _panel_routes(panel, older, newer):
    """Startup load = the older request (answers last), Refresh = the newer one (answers first).

    The older request carries run A / 7 approvals, the newer run B / 2 approvals, so the list
    that wins is readable from the page.
    """
    r = C.routes(runs=[], queue=[])
    if panel == "runs":
        key, old_body, new_body = "/api/review/runs", {"runs": [run_entry(RUN_A)]}, {"runs": [run_entry(RUN_B)]}
    elif panel == "queue":
        key, old_body, new_body = "/api/review/queue", {"cases": [queue_entry(RUN_A)]}, {"cases": [queue_entry(RUN_B)]}
    else:
        key = "/api/review/overrides"
        old_body, new_body = {"approved_count": 7, "groups": []}, {"approved_count": 2, "groups": []}
    newer_response = ok(new_body) if newer == "success" else http500()
    r[key] = [OLDER[older](old_body), newer_response]
    return r


def _panel_view(snapshot, panel):
    p = snapshot["panel"]
    ids = {"runs": p["runIds"], "queue": p["queueIds"], "overrides": []}[panel]
    return {"ids": ids, "status": p["status"][panel],
            "text": p["overridesText"] if panel == "overrides" else "", "busy": p["busy"][panel]}


UNAVAILABLE = {"runs": RUNS_UNAVAILABLE, "queue": QUEUE_UNAVAILABLE, "overrides": OVERRIDES_UNAVAILABLE}


class StalePanelLoads(unittest.TestCase):
    """K2: the whole schedule family, for each of the three review lists."""

    def schedule(self, panel, older, newer):
        out = drive(_panel_routes(panel, older, newer), [C.wait(20), REFRESH, wait(60), SNAP, wait(400), SNAP])
        return out["checkpoints"]

    def check(self, panel, older, newer):
        newer_ok, late = self.schedule(panel, older, newer)[0:2]
        # The checkpoint before the older response: the newer load's own result.
        before, after = _panel_view(newer_ok, panel), _panel_view(late, panel)
        if newer == "success":
            expected_ids = {"runs": [RUN_B], "queue": [RUN_B], "overrides": []}[panel]
            self.assertEqual(expected_ids, before["ids"], "the newer load rendered")
            if panel == "overrides":
                self.assertIn("Approved as proposed: 2", before["text"])
        else:
            self.assertEqual([], before["ids"])
            self.assertEqual(UNAVAILABLE[panel], before["status"], "the newer failure is shown")
        self.assertEqual("false", before["busy"], "the newer load's settle clears aria-busy")
        # The older response arrived in between: the list, its status and its busy mark are unchanged.
        self.assertEqual(before, after, "an older %s response (%s) touched the %s list" % (older, "after a newer " + newer, panel))

    def test_runs(self):
        for older in OLDER:
            for newer in ("success", "failure"):
                with self.subTest(older=older, newer=newer):
                    self.check("runs", older, newer)

    def test_queue(self):
        for older in OLDER:
            for newer in ("success", "failure"):
                with self.subTest(older=older, newer=newer):
                    self.check("queue", older, newer)

    def test_overrides(self):
        for older in OLDER:
            for newer in ("success", "failure"):
                with self.subTest(older=older, newer=newer):
                    self.check("overrides", older, newer)

    def test_an_older_runs_failure_does_not_claim_recent_runs_are_unavailable(self):
        """The reviewer's second schedule, spelled out: startup load fails late, Refresh succeeded."""
        _, late = self.schedule("runs", "http500", "success")[0:2]
        self.assertEqual([RUN_B], late["panel"]["runIds"])
        self.assertEqual("1 run, newest first.", late["panel"]["status"]["runs"])

    def test_the_older_response_does_not_open_a_stale_queue_entry(self):
        """The queue's entries feed Open on a run: a stale queue must not replace them."""
        r = C.routes(runs=[run_entry(RUN_A), run_entry(RUN_B, "ruled")], queue=[])
        r["/api/review/queue"] = [ok({"cases": [queue_entry(RUN_A)]}, delay=250), ok({"cases": []})]
        out = drive(r, [wait(20), REFRESH, wait(400), run_open(0), wait(60), SNAP])
        final = out["checkpoints"][0]
        self.assertEqual([], final["panel"]["queueIds"], "no stale queue row came back")
        self.assertEqual(RUN_A, final["loaded"])

    def test_three_overlapping_loads_the_last_one_wins(self):
        r = C.routes(runs=[], queue=[])
        r["/api/review/runs"] = [ok({"runs": [run_entry(RUN_A)]}, delay=300), ok({"runs": [run_entry(RUN_C)]}, delay=100),
                                 ok({"runs": [run_entry(RUN_B)]}, delay=200)]
        out = drive(r, [wait(10), REFRESH, wait(10), REFRESH, wait(500), SNAP])
        self.assertEqual([RUN_B], out["checkpoints"][0]["panel"]["runIds"])
        self.assertEqual("false", out["checkpoints"][0]["panel"]["busy"]["runs"])


# ================================================================== K3: refresh, then open


def _open_after_refresh_routes(list_name):
    """A refresh that is held 200 ms, and a first /case that fails, a second that works."""
    r = C.routes(queue=[queue_entry(RUN_A), queue_entry(RUN_B)])
    if list_name == "runs":
        r["/api/review/runs"] = [ok({"runs": [run_entry(RUN_A), run_entry(RUN_B, "ruled")]}),
                                 ok({"runs": [run_entry(RUN_A), run_entry(RUN_B, "ruled")]}, delay=200)]
    else:
        r["/api/review/queue"] = [ok({"cases": [queue_entry(RUN_A), queue_entry(RUN_B)]}),
                                  ok({"cases": [queue_entry(RUN_A), queue_entry(RUN_B)]}, delay=200)]
    r["/api/review/%s/case" % RUN_A] = [http500(delay=80), ok({"case_file": case_for(RUN_A), "human_decision": None}, delay=40)]
    return r


class RefreshThenOpen(unittest.TestCase):
    """K3: Refresh first, then Open, for both lists that have Open buttons."""

    @classmethod
    def setUpClass(cls):
        cls.out = {}
        for name, opener, button_cls, rows_key, status_cls in (
            ("runs", run_open, "runButtons", "runs", "run-open-status"),
            ("queue", queue_open, "queueButtons", "queue", "queue-open-status"),
        ):
            actions = [wait(30), REFRESH, wait(30), opener(0), wait(30), SNAP,   # during the held refresh
                       wait(300), SNAP,                                           # after it landed
                       opener(0), wait(30), SNAP, wait(200), SNAP,                # the open, then its failure
                       opener(0), wait(150), SNAP]                                # the retry works
            cls.out[name] = (drive(_open_after_refresh_routes(name), actions), button_cls, rows_key, status_cls)

    def cps(self, name):
        out, button_cls, rows_key, status_cls = self.out[name]
        return out, out["checkpoints"], button_cls, rows_key, status_cls

    def for_each_list(self, check):
        for name in ("runs", "queue"):
            with self.subTest(list=name):
                check(name)

    def test_buttons_are_disabled_and_the_panel_is_busy_while_the_refresh_loads(self):
        def check(name):
            _out, cps, button_cls, _rows, _status = self.cps(name)
            during = cps[0]
            buttons = during[button_cls]
            self.assertEqual(2, len(buttons))
            self.assertEqual([True, True], [b["disabled"] for b in buttons])
            self.assertEqual(["Open case"] * 2, [b["text"] for b in buttons])
            self.assertEqual("true", during["panel"]["busy"][name])
        self.for_each_list(check)

    def test_a_click_during_the_refresh_starts_no_open(self):
        def check(name):
            out, cps, _b, _r, _s = self.cps(name)
            during = cps[0]
            self.assertEqual([], [u for u in during["requests"] if u.endswith("/case")], "no case was requested")
            self.assertEqual("", during["status"], "nothing was reported either")
        self.for_each_list(check)

    def test_the_replacement_rows_are_enabled_and_the_panel_is_idle(self):
        def check(name):
            _out, cps, button_cls, _r, _s = self.cps(name)
            landed = cps[1]
            self.assertEqual([False, False], [b["disabled"] for b in landed[button_cls]])
            self.assertEqual(["Open case"] * 2, [b["text"] for b in landed[button_cls]])
            self.assertEqual("false", landed["panel"]["busy"][name])
            self.assertEqual([], [u for u in landed["requests"] if u.endswith("/case")])
        self.for_each_list(check)

    def test_every_open_button_is_disabled_from_the_moment_refresh_is_clicked(self):
        """Both lists are held: nothing has re-rendered yet, so only the begin of the load can disable them."""
        r = C.routes(queue=[queue_entry(RUN_A), queue_entry(RUN_B)])
        runs = [run_entry(RUN_A), run_entry(RUN_B, "ruled")]
        r["/api/review/runs"] = [ok({"runs": runs}), ok({"runs": runs}, delay=300)]
        r["/api/review/queue"] = [ok({"cases": [queue_entry(RUN_A), queue_entry(RUN_B)]}),
                                  ok({"cases": [queue_entry(RUN_A), queue_entry(RUN_B)]}, delay=300)]
        out = drive(r, [wait(30), SNAP, REFRESH, wait(40), SNAP, wait(400), SNAP])
        before, held, landed = out["checkpoints"]
        self.assertEqual([False, False], [b["disabled"] for b in before["runButtons"]], "enabled before the refresh")
        self.assertEqual([True, True], [b["disabled"] for b in held["runButtons"]])
        self.assertEqual([True, True], [b["disabled"] for b in held["queueButtons"]])
        self.assertEqual({"queue": "true", "overrides": "false", "runs": "true"}, held["panel"]["busy"])
        self.assertEqual([False, False], [b["disabled"] for b in landed["runButtons"]])
        self.assertEqual([False, False], [b["disabled"] for b in landed["queueButtons"]])

    def test_an_open_on_the_replacement_row_shows_its_pending_state(self):
        def check(name):
            _out, cps, button_cls, _r, _s = self.cps(name)
            pending = cps[2][button_cls][0]
            self.assertEqual("Opening…", pending["text"])
            self.assertTrue(pending["disabled"])
        self.for_each_list(check)

    def test_the_failure_lands_on_the_visible_replacement_row(self):
        def check(name):
            _out, cps, button_cls, rows_key, status_cls = self.cps(name)
            failed = cps[3]
            row = rows(failed, rows_key)[0]
            self.assertEqual(CASE_FAILED, child_text(row, status_cls), "the visible row carries the failure")
            self.assertEqual("Open case", failed[button_cls][0]["text"])
            self.assertFalse(failed[button_cls][0]["disabled"], "retry is possible")
            self.assertEqual(CASE_FAILED, failed["status"])
        self.for_each_list(check)

    def test_the_retry_opens_the_case_and_clears_the_row_failure(self):
        def check(name):
            _out, cps, _b, rows_key, status_cls = self.cps(name)
            final = cps[4]
            self.assertEqual(RUN_A, final["loaded"])
            self.assertEqual("Loaded %s." % RUN_A, final["status"])
            self.assertEqual("", child_text(rows(final, rows_key)[0], status_cls))
            self.assertEqual(2, len([r for r in final["requests"] if r.endswith("/%s/case" % RUN_A)]),
                             "two case requests in all: the failure and the retry")
        self.for_each_list(check)

    def test_a_refresh_that_fails_leaves_no_busy_mark_and_no_rows(self):
        r = C.routes()
        r["/api/review/runs"] = [ok({"runs": [run_entry(RUN_A)]}), http500(delay=60)]
        r["/api/review/queue"] = [ok({"cases": [queue_entry(RUN_A)]}), http500(delay=60)]
        r["/api/review/overrides"] = [ok({"approved_count": 0, "groups": []}), refused(delay=60)]
        out = drive(r, [wait(20), REFRESH, wait(20), SNAP, wait(200), SNAP])
        during, after = out["checkpoints"]
        self.assertEqual({"queue": "true", "overrides": "true", "runs": "true"}, during["panel"]["busy"])
        self.assertEqual({"queue": "false", "overrides": "false", "runs": "false"}, after["panel"]["busy"])
        self.assertEqual([], after["panel"]["runIds"])
        self.assertEqual(RUNS_UNAVAILABLE, after["panel"]["status"]["runs"])

    def test_an_older_response_settling_does_not_end_the_newer_loads_busy_state(self):
        """Refresh twice: the first refresh's response lands while the second is still loading."""
        r = C.routes()
        r["/api/review/runs"] = [ok({"runs": [run_entry(RUN_A)]}), ok({"runs": [run_entry(RUN_A)]}, delay=150),
                                 ok({"runs": [run_entry(RUN_B)]}, delay=400)]
        out = drive(r, [wait(20), REFRESH, wait(10), REFRESH, wait(250), run_open(0), wait(10), SNAP, wait(400), SNAP])
        mid, done = out["checkpoints"]
        self.assertEqual("true", mid["panel"]["busy"]["runs"], "the second refresh still owns the list")
        self.assertEqual([True], [b["disabled"] for b in mid["runButtons"]])
        self.assertEqual([], [u for u in mid["requests"] if u.endswith("/case")])
        self.assertEqual([RUN_B], done["panel"]["runIds"])
        self.assertEqual("false", done["panel"]["busy"]["runs"])

    def test_the_overrides_panel_is_marked_busy_too(self):
        r = C.routes()
        r["/api/review/overrides"] = [ok({"approved_count": 1, "groups": []}), ok({"approved_count": 3, "groups": []}, delay=120)]
        out = drive(r, [wait(20), REFRESH, wait(20), SNAP, wait(200), SNAP])
        during, after = out["checkpoints"]
        self.assertEqual("true", during["panel"]["busy"]["overrides"])
        self.assertEqual("false", after["panel"]["busy"]["overrides"])
        self.assertIn("Approved as proposed: 3", after["panel"]["overridesText"])

    def test_the_existing_invalidation_of_an_open_pending_at_refresh_stays(self):
        out = drive(C.routes(case_delay=250), [wait(20), run_open(1), wait(30), REFRESH, wait(30), SNAP, wait(400), SNAP])
        landed, late = out["checkpoints"]
        self.assertEqual(["Open case"] * 3, [b["text"] for b in landed["runButtons"]])
        self.assertEqual([False] * 3, [b["disabled"] for b in landed["runButtons"]])
        self.assertEqual("", late["loaded"], "the invalidated open never renders")

    def held_list_routes(self, list_name):
        """Three rows; B's case answers late (t+200ms); the second list load is held 350 ms."""
        r = C.routes(queue=[queue_entry(RUN_A), queue_entry(RUN_B)])
        runs = [run_entry(RUN_A), run_entry(RUN_B, "ruled")]
        queue = [queue_entry(RUN_A), queue_entry(RUN_B)]
        if list_name == "runs":
            r["/api/review/runs"] = [ok({"runs": runs}), ok({"runs": runs}, delay=350)]
        else:
            r["/api/review/queue"] = [ok({"cases": queue}), ok({"cases": queue}, delay=350)]
        r["/api/review/%s/case" % RUN_B][0]["delay"] = 200
        return r

    def test_an_open_pending_when_the_refresh_starts_cannot_be_revived_by_a_late_reply(self):
        """Open B, Refresh (held): the old open is dropped; its late reply must not re-enable the rows."""
        for name, opener, button_cls in (("runs", run_open, "runButtons"), ("queue", queue_open, "queueButtons")):
            with self.subTest(list=name):
                out = drive(self.held_list_routes(name), [wait(20), opener(1), wait(30), REFRESH, wait(250), SNAP, wait(300), SNAP])
                during, landed = out["checkpoints"]
                # The old open's reply (t~250) has arrived and been ignored; the list is still loading.
                self.assertEqual([True, True], [b["disabled"] for b in during[button_cls][:2]])
                self.assertEqual("true", during["panel"]["busy"][name])
                self.assertEqual([False, False], [b["disabled"] for b in landed[button_cls][:2]])
                self.assertEqual("", landed["loaded"])

    def test_the_currently_open_button_stays_disabled_while_the_list_loads(self):
        """A is open; B's open is dropped by Refresh and answers late: that must not enable A's button."""
        for name, opener, button_cls in (("runs", run_open, "runButtons"), ("queue", queue_open, "queueButtons")):
            with self.subTest(list=name):
                out = drive(self.held_list_routes(name), [wait(20), opener(0), wait(60), opener(1), wait(30), REFRESH,
                                                          wait(250), SNAP, wait(300), SNAP])
                during, landed = out["checkpoints"]
                self.assertEqual("Currently open", during[button_cls][0]["text"])
                self.assertEqual([True, True], [b["disabled"] for b in during[button_cls][:2]])
                self.assertEqual(RUN_A, during["loaded"])
                self.assertEqual("Currently open", landed[button_cls][0]["text"], "the open case stays marked after the reload")
                self.assertEqual([False, False], [b["disabled"] for b in landed[button_cls][:2]])


class DecisionReloadDropsPendingOpens(unittest.TestCase):
    """K3, other entry: the panels reload after a recorded decision replaces the queue rows too."""

    def test_an_open_pending_when_the_decision_reload_lands_is_not_orphaned(self):
        r = C.routes(runs=[], queue=[queue_entry(RUN_A), queue_entry(RUN_B)])
        r["/api/review/queue"] = [ok({"cases": [queue_entry(RUN_A), queue_entry(RUN_B)]}), ok({"cases": [queue_entry(RUN_B)]})]
        r["/api/review/%s/decision" % RUN_A] = [ok({"decision": {}, "party_view": {"message": "m"}}, delay=150)]
        r["/api/review/%s/case" % RUN_B][0]["delay"] = 400
        actions = [wait(20), queue_open(0), wait(30),
                   {"id": "decision-reject", "op": "check"},
                   {"id": "decision-reviewer", "op": "set", "value": "Ana"}, {"id": "decision-reason", "op": "set", "value": "x"},
                   {"id": "decision-form", "op": "submit"}, {"id": "decision-confirm-send", "op": "click"}, wait(20),
                   queue_open(1), wait(20), SNAP,               # B is opening, the POST is in flight
                   wait(250), SNAP,                             # the POST landed and the queue reloaded
                   wait(400), SNAP]                             # B's case answered
        out = drive(r, actions)
        opening, reloaded, late = out["checkpoints"]
        self.assertEqual("Opening…", opening["queueButtons"][1]["text"])
        self.assertIn("Decision recorded", reloaded["panel"]["decision"])
        self.assertEqual(["Open case"], [b["text"] for b in reloaded["queueButtons"]])
        self.assertEqual([False], [b["disabled"] for b in reloaded["queueButtons"]])
        self.assertEqual(RUN_A, late["loaded"], "the dropped open does not render behind a button that says Open case")


# ================================================================== K6: the folder loader


def _case_with(**changes):
    case = case_for("LOCAL-1")
    case.update(changes)
    return case


def _without(*keys):
    case = case_for("LOCAL-1")
    for key in keys:
        del case[key]
    return case


WRONG_SHAPES = {
    "empty object": "{}",
    "run_id only": '{"run_id": "partial"}',
    "no resolution": json.dumps(_without("resolution")),
    "no dispute_id": json.dumps(_without("dispute_id")),
    "no run_id": json.dumps(_without("run_id")),
    "resolution null": json.dumps(_case_with(resolution=None)),
    "resolution string": json.dumps(_case_with(resolution="withheld")),
    "resolution number": json.dumps(_case_with(resolution=3)),
    "resolution array": json.dumps(_case_with(resolution=[{"outcome": "ruled"}])),
    "resolution empty": json.dumps(_case_with(resolution={})),
    "no outcome": json.dumps(_case_with(resolution={"party_message": "x"})),
    "outcome empty": json.dumps(_case_with(resolution={"outcome": ""})),
    "outcome number": json.dumps(_case_with(resolution={"outcome": 3})),
    "outcome null": json.dumps(_case_with(resolution={"outcome": None})),
    "outcome array": json.dumps(_case_with(resolution={"outcome": ["ruled"]})),
    "dispute_id number": json.dumps(_case_with(dispute_id=123)),
    "dispute_id empty": json.dumps(_case_with(dispute_id="")),
    "dispute_id null": json.dumps(_case_with(dispute_id=None)),
    "dispute_id array": json.dumps(_case_with(dispute_id=["PF-1"])),
    "run_id empty": json.dumps(_case_with(run_id="")),
    "run_id number": json.dumps(_case_with(run_id=5)),
    "run_id null": json.dumps(_case_with(run_id=None)),
    "run_id object": json.dumps(_case_with(run_id={})),
}


class FolderLoaderCaseShape(unittest.TestCase):
    def test_every_wrong_shape_is_rejected_with_the_plain_message_and_loads_nothing(self):
        for label, raw in WRONG_SHAPES.items():
            with self.subTest(shape=label):
                extra = [{"path": "R1/payloads/0001-x.json", "body": {"a": 1}}]
                out = drive(C.routes(runs=[]), [folder("R1", raw=raw, extra=extra), wait(40)])
                self.assertEqual(NOT_OBJECT, node(out, "load-status")["text"])
                self.assertEqual("error", node(out, "load-status")["dataset"].get("state"))
                self.assertTrue(node(out, "case-workspace")["hidden"], "no workspace for a non-case")
                self.assertEqual("", node(out, "loaded-file")["text"], "nothing was rendered")
                self.assertEqual(NOT_ATTACHED, node(out, "payload-status")["text"], "nothing was attached")
                self.assertEqual([], [u for u in urls(out) if u.endswith("/prompts")], "no prompts request")
                self.assertEqual(["R1/case_file.json"], out["reads"], "only the case file was read")

    def test_a_wrong_shape_replaces_a_case_that_was_loaded_before(self):
        good = folder("GOOD", case_for("GOOD-1"))
        bad = folder("BAD", raw="{}")
        out = drive(C.routes(runs=[]), [good, wait(40), bad, wait(40)])
        self.assertEqual(NOT_OBJECT, node(out, "load-status")["text"])
        self.assertTrue(node(out, "case-workspace")["hidden"])
        self.assertEqual(NOT_ATTACHED, node(out, "payload-status")["text"])

    def test_the_valid_control_loads_and_attaches(self):
        out = drive(C.routes(runs=[]), [folder("R1", case_for("LOCAL-1")), wait(40)])
        self.assertEqual("Loaded R1/case_file.json.", node(out, "load-status")["text"])
        self.assertEqual("success", node(out, "load-status")["dataset"].get("state"))
        self.assertFalse(node(out, "case-workspace")["hidden"])
        self.assertEqual("Attached 3 run file(s); event payloads can be opened.", node(out, "payload-status")["text"])
        self.assertIn("/api/review/LOCAL-1/prompts", urls(out))

    def test_an_unknown_but_recorded_outcome_still_renders_with_its_warning(self):
        out = drive(C.routes(runs=[]), [folder("R1", _case_with(resolution={"outcome": "mystery"})), wait(40)])
        self.assertEqual("Loaded R1/case_file.json.", node(out, "load-status")["text"])
        self.assertFalse(node(out, "case-workspace")["hidden"])
        self.assertIn("UNKNOWN OUTCOME", node(out, "resolution-content")["text"])
        self.assertIn("Outcome: mystery", node(out, "resolution-content")["text"])

    def test_every_known_outcome_passes_the_guard(self):
        for outcome in ("ruled", "withheld", "human_review", "needs_info"):
            with self.subTest(outcome=outcome):
                out = drive(C.routes(runs=[]), [folder("R1", _case_with(resolution={"outcome": outcome})), wait(40)])
                self.assertEqual("Loaded R1/case_file.json.", node(out, "load-status")["text"])

    def test_optional_fields_stay_optional(self):
        minimal = {"run_id": "LOCAL-2", "dispute_id": "PF-2", "resolution": {"outcome": "ruled"}}
        out = drive(C.routes(runs=[]), [folder("R1", minimal), wait(40)])
        self.assertEqual("Loaded R1/case_file.json.", node(out, "load-status")["text"])
        self.assertEqual("success", node(out, "load-status")["dataset"].get("state"))

    def test_the_existing_messages_for_syntax_errors_and_non_objects_are_unchanged(self):
        for raw, message in (("{not json", C.NOT_JSON), ("[1, 2]", NOT_OBJECT), ("null", NOT_OBJECT), ('"x"', NOT_OBJECT)):
            with self.subTest(raw=raw):
                out = drive(C.routes(runs=[]), [folder("R1", raw=raw), wait(40)])
                self.assertEqual(message, node(out, "load-status")["text"])


# ================================================================== K4/K5: the server


def get(base, path):
    """(status, parsed body or None) for a GET; a 500 is a result here, not an exception."""
    try:
        with urllib.request.urlopen(base + path, timeout=60) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as err:
        raw = err.read()
        try:
            return err.code, json.loads(raw)
        except ValueError:
            return err.code, None


def post(base, path, body):
    req = urllib.request.Request(base + path, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as err:
        raw = err.read()
        try:
            return err.code, json.loads(raw)
        except ValueError:
            return err.code, None


DEEP = "[" * 1200 + "0" + "]" * 1200


class RunFixture(unittest.TestCase):
    """A real server with one real held run (a route-deviation filing the mock model withholds)."""

    def setUp(self):
        self.server = Server()
        self.addCleanup(self.server.close)
        self.outside = Path(tempfile.mkdtemp(prefix="w35k-outside-"))
        self.addCleanup(shutil.rmtree, self.outside, True)
        view = self.server.file(trip_id="T-RD0109", category="route_deviation", claim=55.16)
        self.run_id, self.dispute_id = view["run_id"], view["dispute_id"]
        self.base = self.server.base

    # ---------------------------------------------------------------- helpers
    def run_dir(self, run_id=None):
        return self.server.out / (run_id or self.run_id)

    def move_outside(self, name, run_id=None):
        """Replace <run>/<name> with a symlink to a byte-identical file outside the output folder."""
        leaf = self.run_dir(run_id) / name
        target = self.outside / ("%s-%s" % (run_id or self.run_id, name))
        target.write_bytes(leaf.read_bytes())
        leaf.unlink()
        leaf.symlink_to(target)
        self.assertTrue(leaf.is_symlink() and leaf.exists(), "fixture: the link resolves")
        return target

    def move_inside(self, name, run_id=None):
        """Replace <run>/<name> with a symlink to a byte-identical file inside the same run folder."""
        leaf = self.run_dir(run_id) / name
        target = self.run_dir(run_id) / ("store-" + name)
        target.write_bytes(leaf.read_bytes())
        leaf.unlink()
        leaf.symlink_to(target.name)
        self.assertTrue(leaf.is_symlink() and leaf.exists(), "fixture: the link resolves")

    def decide(self, run_id=None):
        status, _ = self.server.decide(run_id or self.run_id, decision_body("reject"))
        self.assertEqual(200, status, "fixture: the decision was recorded")

    def listed(self):
        status, data = get(self.base, "/api/review/runs")
        self.assertEqual(200, status, "the runs list answered")
        return {r["run_id"]: r for r in data["runs"]}

    def queued(self):
        status, data = get(self.base, "/api/review/queue")
        self.assertEqual(200, status, "the queue answered")
        return [c["run_id"] for c in data["cases"]]

    def rider_entries(self):
        status, data = get(self.base, "/api/demo/rider")
        self.assertEqual(200, status, "the rider account list answered")
        return {e["dispute_id"]: e for e in data["disputes"]}

    def second_run(self):
        view = self.server.file(trip_id="T-RD0109", category="route_deviation", claim=55.16)
        return view["run_id"], view["dispute_id"]


class EscapingCaseFile(RunFixture):
    """K4: <run>/case_file.json is a symlink to a file outside the run directory."""

    def test_the_fixture_is_listed_and_queued_before_the_link(self):
        self.assertIn(self.run_id, self.listed())
        self.assertIn(self.run_id, self.queued())

    def test_the_runs_list_does_not_follow_it(self):
        self.move_outside("case_file.json")
        self.assertNotIn(self.run_id, self.listed())

    def test_the_queue_does_not_follow_it(self):
        self.move_outside("case_file.json")
        self.assertNotIn(self.run_id, self.queued())

    def test_the_case_route_does_not_follow_it(self):
        self.move_outside("case_file.json")
        self.assertEqual(404, get(self.base, "/api/review/%s/case" % self.run_id)[0])

    def test_the_decision_route_does_not_follow_it_and_writes_nothing(self):
        self.move_outside("case_file.json")
        status, _ = post(self.base, "/api/review/%s/decision" % self.run_id, decision_body("reject"))
        self.assertEqual(404, status)
        self.assertFalse((self.run_dir() / "human_decision.json").exists())

    def test_the_answers_route_does_not_follow_it(self):
        self.move_outside("case_file.json")
        status, _ = post(self.base, "/api/disputes/%s/answers" % self.run_id,
                         {"answers": [{"question": "q", "answer": "a"}]})
        self.assertEqual(404, status, "an ordinary withheld run answers 409; a missing case file answers 404")

    def test_the_party_views_do_not_follow_it(self):
        self.move_outside("case_file.json")
        self.assertEqual(404, get(self.base, "/api/disputes/%s" % self.dispute_id)[0])
        self.assertNotIn(self.dispute_id, self.rider_entries())

    def test_the_overrides_list_does_not_follow_it(self):
        self.decide()
        status, before = get(self.base, "/api/review/overrides")
        self.assertEqual(1, sum(g["count"] for g in before["groups"]), "fixture: the rejection is an override")
        self.move_outside("case_file.json")
        status, after = get(self.base, "/api/review/overrides")
        self.assertEqual(200, status)
        self.assertEqual([], after["groups"])

    def test_a_link_to_another_runs_case_file_is_outside_this_run_too(self):
        other, _dispute = self.second_run()
        leaf = self.run_dir() / "case_file.json"
        leaf.unlink()
        leaf.symlink_to(self.run_dir(other) / "case_file.json")
        listed = self.listed()
        self.assertNotIn(self.run_id, listed)
        self.assertIn(other, listed)
        self.assertEqual(404, get(self.base, "/api/review/%s/case" % self.run_id)[0])

    def test_a_link_to_a_directory_or_a_loop_reads_as_missing(self):
        leaf = self.run_dir() / "case_file.json"
        leaf.unlink()
        leaf.symlink_to(self.run_dir())
        self.assertNotIn(self.run_id, self.listed())
        self.assertEqual(404, get(self.base, "/api/review/%s/case" % self.run_id)[0])
        leaf.unlink()
        leaf.symlink_to("case_file.json")
        self.assertNotIn(self.run_id, self.listed())
        self.assertEqual(404, get(self.base, "/api/review/%s/case" % self.run_id)[0])

    def test_a_link_that_stays_inside_the_run_folder_still_works(self):
        original = self.server.case(self.run_id)
        self.move_inside("case_file.json")
        self.assertIn(self.run_id, self.listed())
        self.assertIn(self.run_id, self.queued())
        status, data = get(self.base, "/api/review/%s/case" % self.run_id)
        self.assertEqual(200, status)
        self.assertEqual(original, data["case_file"])
        status, _ = post(self.base, "/api/disputes/%s/answers" % self.run_id,
                         {"answers": [{"question": "q", "answer": "a"}]})
        self.assertEqual(409, status, "an inside link is an ordinary case file: the run did not ask for information")
        status, _ = post(self.base, "/api/review/%s/decision" % self.run_id, decision_body("reject"))
        self.assertEqual(200, status, "an inside link is an ordinary case file")
        self.assertEqual(200, get(self.base, "/api/disputes/%s" % self.dispute_id)[0])
        self.assertIn(self.dispute_id, self.rider_entries())


class EscapingDisputeRecord(RunFixture):
    """The party record read shares the helper: an escaping dispute.json makes the run not party-filed."""

    def test_an_escaping_dispute_record_is_not_followed(self):
        self.assertIn(self.dispute_id, self.rider_entries())
        self.move_outside("dispute.json")
        self.assertNotIn(self.dispute_id, self.rider_entries())
        self.assertEqual(404, get(self.base, "/api/disputes/%s" % self.dispute_id)[0])

    def test_the_answers_route_does_not_follow_it(self):
        self.move_outside("dispute.json")
        status, _ = post(self.base, "/api/disputes/%s/answers" % self.run_id,
                         {"answers": [{"question": "q", "answer": "a"}]})
        self.assertEqual(404, status, "an ordinary withheld run answers 409; a missing dispute record answers 404")

    def test_an_inside_dispute_link_still_works(self):
        self.move_inside("dispute.json")
        self.assertIn(self.dispute_id, self.rider_entries())
        status, _ = post(self.base, "/api/disputes/%s/answers" % self.run_id,
                         {"answers": [{"question": "q", "answer": "a"}]})
        self.assertEqual(409, status)


class EscapingDecisionFile(RunFixture):
    """K4: <run>/human_decision.json is a symlink to a (valid) record outside the run directory."""

    def setUp(self):
        super().setUp()
        self.decide()
        self.assertTrue(self.listed()[self.run_id]["has_human_decision"], "fixture: decided")
        self.assertNotIn(self.run_id, self.queued(), "fixture: a decided run leaves the queue")

    def test_the_runs_list_does_not_follow_it(self):
        self.move_outside("human_decision.json")
        self.assertIs(False, self.listed()[self.run_id]["has_human_decision"])

    def test_the_queue_does_not_follow_it(self):
        self.move_outside("human_decision.json")
        self.assertIn(self.run_id, self.queued(), "without a decision the held run is waiting again")

    def test_the_case_route_does_not_follow_it(self):
        self.move_outside("human_decision.json")
        status, data = get(self.base, "/api/review/%s/case" % self.run_id)
        self.assertEqual(200, status)
        self.assertIsNone(data["human_decision"])

    def test_the_party_views_do_not_follow_it(self):
        self.move_outside("human_decision.json")
        status, view = get(self.base, "/api/disputes/%s" % self.dispute_id)
        self.assertEqual(200, status)
        self.assertNotEqual("decided", view["status"])
        self.assertEqual(UNDER_REVIEW, view["message"])
        self.assertNotEqual("decided", self.rider_entries()[self.dispute_id]["status"])

    def test_the_overrides_list_does_not_follow_it(self):
        self.move_outside("human_decision.json")
        status, data = get(self.base, "/api/review/overrides")
        self.assertEqual(200, status)
        self.assertEqual({"approved_count": 0, "groups": []}, data)

    def test_a_link_that_stays_inside_the_run_folder_still_works(self):
        self.move_inside("human_decision.json")
        self.assertIs(True, self.listed()[self.run_id]["has_human_decision"])
        self.assertNotIn(self.run_id, self.queued())
        status, data = get(self.base, "/api/review/%s/case" % self.run_id)
        self.assertEqual("reject", data["human_decision"]["decision"])
        self.assertEqual("decided", get(self.base, "/api/disputes/%s" % self.dispute_id)[1]["status"])


class DeeplyNestedDecisionFile(RunFixture):
    """K5: one 1200-deep decision file is no decision on every route, never a 500."""

    def setUp(self):
        super().setUp()
        (self.run_dir() / "human_decision.json").write_text(DEEP, encoding="utf-8")

    def test_the_runs_list_still_lists_the_run_without_a_decision(self):
        listed = self.listed()
        self.assertIn(self.run_id, listed)
        self.assertIs(False, listed[self.run_id]["has_human_decision"])

    def test_the_queue_still_holds_the_run(self):
        self.assertIn(self.run_id, self.queued())

    def test_the_case_route_opens_with_no_decision(self):
        status, data = get(self.base, "/api/review/%s/case" % self.run_id)
        self.assertEqual(200, status)
        self.assertIsNone(data["human_decision"])

    def test_the_party_status_route_reads_it_as_under_review(self):
        status, view = get(self.base, "/api/disputes/%s" % self.dispute_id)
        self.assertEqual(200, status)
        self.assertEqual(UNDER_REVIEW, view["message"])
        self.assertNotEqual("decided", view["status"])

    def test_the_account_lists_and_overrides_still_answer(self):
        self.assertNotEqual("decided", self.rider_entries()[self.dispute_id]["status"])
        self.assertEqual(200, get(self.base, "/api/demo/driver")[0])
        self.assertEqual((200, {"approved_count": 0, "groups": []}), get(self.base, "/api/review/overrides"))


class LoadDecisionAndTheHelper(unittest.TestCase):
    """The two functions themselves, on a scratch run folder."""

    VALID = {"schema_version": "1.0", "run_id": "r1", "dispute_id": "d1", "decision": "reject", "reviewer": "A",
             "reason": "r", "action": "no action", "amount_sgd": 0.0, "proposed": None, "decided_at": "2026-10-09T00:00:00+00:00"}

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="w35k-unit-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.run = self.tmp / "run"
        self.run.mkdir()
        self.outside = self.tmp / "outside"
        self.outside.mkdir()
        from app import human_review
        self.hr = human_review

    def write(self, text):
        (self.run / "human_decision.json").write_text(text, encoding="utf-8")

    def load(self, run=None):
        try:
            return self.hr.load_decision(self.run if run is None else run)
        except Exception as exc:  # noqa: BLE001 - the contract is: never raises
            self.fail("load_decision raised %s: %s" % (type(exc).__name__, str(exc)[:80]))

    def test_an_ordinary_valid_file_loads_as_before(self):
        self.write(json.dumps(self.VALID))
        self.assertEqual(self.VALID, self.load())
        self.assertEqual(self.VALID, self.load(str(self.run)), "a str path works as before")

    def test_missing_corrupt_and_wrong_shapes_are_no_decision(self):
        self.assertIsNone(self.load())
        for text in ("", "{not json", "[]", "null", "{}", '{"action": "refund"}'):
            with self.subTest(text=text[:20]):
                self.write(text)
                self.assertIsNone(self.load())
        (self.run / "human_decision.json").write_bytes(b"\xff\xfe{")
        self.assertIsNone(self.load(), "undecodable bytes")

    def test_a_deeply_nested_file_is_no_decision(self):
        for depth in (1000, 1200, 20000):
            with self.subTest(depth=depth):
                self.write("[" * depth + "0" + "]" * depth)
                self.assertIsNone(self.load())
        self.write('{"a":' * 5000 + "0" + "}" * 5000)
        self.assertIsNone(self.load())

    def test_a_link_out_is_no_decision_and_a_link_in_is_one(self):
        (self.outside / "d.json").write_text(json.dumps(self.VALID), encoding="utf-8")
        leaf = self.run / "human_decision.json"
        leaf.symlink_to(self.outside / "d.json")
        self.assertIsNone(self.load())
        leaf.unlink()
        (self.run / "inner.json").write_text(json.dumps(self.VALID), encoding="utf-8")
        leaf.symlink_to("inner.json")
        self.assertEqual(self.VALID, self.load())

    def helper(self):
        found = getattr(self.hr, "bounded_run_file", None)
        self.assertIsNotNone(found, "app/human_review.py defines bounded_run_file(run_dir, name)")

        def call(run_dir, name):
            try:
                return found(run_dir, name)
            except Exception as exc:  # noqa: BLE001 - the contract is: never raises, fails closed
                self.fail("bounded_run_file(%r) raised %s" % (name, type(exc).__name__))
        return call

    def test_the_helper_returns_the_resolved_path_of_an_ordinary_or_missing_leaf(self):
        helper = self.helper()
        (self.run / "case_file.json").write_text("{}", encoding="utf-8")
        self.assertEqual((self.run / "case_file.json").resolve(), helper(self.run, "case_file.json"))
        self.assertEqual((self.run / "nothing.json").resolve(), helper(self.run, "nothing.json"),
                         "a missing leaf is the caller's to report")
        self.assertEqual((self.run / "case_file.json").resolve(), helper(str(self.run), "case_file.json"))

    def test_the_helper_fails_closed_on_escapes_loops_and_the_run_directory_itself(self):
        helper = self.helper()
        (self.outside / "x.json").write_text("{}", encoding="utf-8")
        (self.run / "out.json").symlink_to(self.outside / "x.json")
        (self.run / "up.json").symlink_to("../outside/x.json")
        (self.run / "self.json").symlink_to(".")
        (self.run / "loop.json").symlink_to("loop.json")
        (self.run / "sibling.json").symlink_to(self.outside)
        for name in ("out.json", "up.json", "self.json", "loop.json", "sibling.json", "../outside/x.json"):
            with self.subTest(name=name):
                self.assertIsNone(helper(self.run, name))

    def test_the_helper_follows_a_link_that_stays_inside(self):
        helper = self.helper()
        (self.run / "real.json").write_text("{}", encoding="utf-8")
        (self.run / "link.json").symlink_to("real.json")
        self.assertEqual((self.run / "real.json").resolve(), helper(self.run, "link.json"))

    def test_the_helper_compares_resolved_paths_not_names(self):
        """A run folder reached through a symlink is its own boundary."""
        helper = self.helper()
        (self.run / "real.json").write_text("{}", encoding="utf-8")
        alias = self.tmp / "alias"
        alias.symlink_to(self.run)
        self.assertEqual((self.run / "real.json").resolve(), helper(alias, "real.json"))


class SourceShape(unittest.TestCase):
    def test_the_server_reads_case_files_only_through_one_function(self):
        source = (REPO / "app" / "server.py").read_text(encoding="utf-8")
        code = "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("#"))
        start = code.find("def _read_case_file(")
        self.assertGreaterEqual(start, 0, "app/server.py defines _read_case_file(run_dir)")
        end = code.find("\n\n\ndef ", start)
        rest = code[:start] + code[end:]
        self.assertEqual(1, len(re.findall(r"\bCASE_FILE_NAME\b", rest)),
                         "CASE_FILE_NAME appears only in its definition outside _read_case_file")
        self.assertEqual(1, len(re.findall(r"\bbounded_run_file\(", code)), "one call site of the helper in the server")
        self.assertIn("bounded_run_file", re.search(r"from \.human_review import \(([^)]*)\)", code).group(1))

    def test_load_decision_goes_through_the_helper(self):
        source = (REPO / "app" / "human_review.py").read_text(encoding="utf-8")
        start = source.index("def load_decision(")
        body = source[start:source.index("\n\n\n", start)]
        self.assertIn("bounded_run_file(", body)
        self.assertIn("RecursionError", body)


class NothingElseMoved(unittest.TestCase):
    def test_agents_llm_policy_and_data_are_byte_identical(self):
        lines = []
        for rel in ("app/agents", "app/llm", "docs/policy.md", "data"):
            path = REPO / rel
            files = [path] if path.is_file() else sorted(p for p in path.rglob("*") if p.is_file() and "__pycache__" not in p.parts)
            for file in files:
                lines.append("%s\0%s\n" % (file.relative_to(REPO).as_posix(), hashlib.sha256(file.read_bytes()).hexdigest()))
        self.assertEqual(PROTECTED_TREE_FILES, len(lines))
        self.assertEqual(PROTECTED_TREE_SHA, hashlib.sha256("".join(sorted(lines)).encode()).hexdigest())

    def test_human_review_changes_only_load_decision_and_its_bounding_helper(self):
        text = (REPO / "app" / "human_review.py").read_text(encoding="utf-8")
        start = text.find("def bounded_run_file(")
        if start < 0:
            start = text.index("def load_decision(")
        end = text.index("# -------------------------------------------------------------------- party message")
        self.assertEqual(HUMAN_REVIEW_REST_SHA, hashlib.sha256((text[:start] + text[end:]).encode("utf-8")).hexdigest())

    def test_the_decision_validity_rules_are_unchanged(self):
        from app.human_review import decision_record_is_valid
        good = LoadDecisionAndTheHelper.VALID
        self.assertTrue(decision_record_is_valid(good))
        for bad in ([], {}, {"action": "refund"}, dict(good, action="gift"), dict(good, amount_sgd=float("nan")),
                    dict(good, amount_sgd="3"), dict(good, amount_sgd=True)):
            self.assertFalse(decision_record_is_valid(bad), bad)


# ================================================================== real browser


def _browser_env():
    return os.environ.get("PUPPETEER_MODULE") and os.environ.get("BROWSER_EXECUTABLE")


@unittest.skipUnless(_browser_env(), "PUPPETEER_MODULE and BROWSER_EXECUTABLE are not set")
class RealBrowserK(unittest.TestCase):
    """tests/browser/w35_r2_K.cjs against the real server with real mock runs."""

    @classmethod
    def setUpClass(cls):
        cls.server = Server()
        cls.rd = cls.server.file(trip_id="T-RD0109", category="route_deviation", claim=55.16)
        cls.ns = cls.server.file(trip_id="T-NS0202", category="no_show_charge", claim=None)
        report_dir = Path(tempfile.mkdtemp(prefix="w35k-browser-"))
        cls.report = report_dir / "report.json"
        expect = {"queued": cls.rd["run_id"], "ruled": cls.ns["run_id"], "caseFailed": CASE_FAILED,
                  "notObject": NOT_OBJECT, "notAttached": NOT_ATTACHED, "runsUnavailable": RUNS_UNAVAILABLE,
                  "queueUnavailable": QUEUE_UNAVAILABLE, "overridesUnavailable": OVERRIDES_UNAVAILABLE,
                  "shapes": {name: raw for name, raw in WRONG_SHAPES.items()}}
        env = dict(os.environ, W35RK_EXPECT=json.dumps(expect))
        cls.result = subprocess.run([NODE, str(BROWSER_DIR / "w35_r2_K.cjs"), cls.server.base, str(cls.report)],
                                    env=env, capture_output=True, text=True, timeout=900)
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

    def test_stale_runs_loads_in_a_browser(self):
        self.scenario("stale-runs")

    def test_stale_queue_loads_in_a_browser(self):
        self.scenario("stale-queue")

    def test_stale_overrides_loads_in_a_browser(self):
        self.scenario("stale-overrides")

    def test_refresh_then_open_in_a_browser(self):
        self.scenario("refresh-then-open")

    def test_the_folder_picker_rejects_incomplete_case_files_in_a_browser(self):
        self.scenario("folder")

    def test_the_script_itself_finished_cleanly(self):
        self.assertEqual(0, self.result.returncode, (self.data.get("error") or self.result.stderr)[-3000:])
        self.assertTrue(self.data.get("passed"), self.data.get("error"))
        self.assertEqual([], self.data.get("pageErrors"))


if __name__ == "__main__":
    unittest.main()
