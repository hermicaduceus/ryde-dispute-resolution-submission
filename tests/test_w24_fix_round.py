"""W24 fix round (lane B): the console deep link and the stale prompts panel.

Written RED-first by the planner's RED-test preparer against BASE 1ae5a84. The contract is
docs/build-briefs/w24-fix-brief.md; in short:

  1. `?run=<id>` with the review queue available (reviewUi present, fetch available): the deep-link
     open waits for the FIRST queue load (the one started at page load; a Refresh's load does not
     count) to settle, then opens the run with the queue entry object the queue currently shows
     for that run_id (the same object a queue click passes), or with {run_id} when the queue does
     not list it. A failed queue load opens with {run_id}. After `?run=<queued id>` the decision
     form and the queue row are exactly what a queue click produces.
  2. A user action before the deep link fires (a queue click, or a local file pick, whether the
     file then loads or fails) wins: the deep link then does nothing.
  3. An invalid id is unchanged (immediate "Unknown run.", nothing requested, nothing rendered);
     a deep link with no review queue (no reviewUi, or no fetch) is unchanged (opens at once).
  4. handleFile bumps state.promptsGeneration as soon as a local file is picked, so a pending
     /prompts reply for the previous case (late success or late failure) never renders, whether
     the local file then fails or loads.

The fake-DOM driver reuses tests.test_w24_prompt_panel's harness (that file and its .cjs are
frozen by sha256 in the W24 brief and re-pinned below) and adds four instrument-only switches:
a raw or delayed local-file read, a request that never answers (`hang`), a page without some
element ids (`missing`), and a page without fetch (`no_fetch`). None changes app.js.

Run: env -u PYTHONPATH /usr/bin/python3 -B -m unittest tests.test_w24_fix_round -v
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import tests.test_w24_prompt_panel as T
from tests.w23_b2_support import NODE, base_routes, ok, queue_row
from tests.w23_support import Server

REPO = Path(__file__).resolve().parent.parent
UI = REPO / "ui"

NO_PROPOSAL_NOTE = "No AI proposal to approve; use Change."
NOT_JSON = "The selected file is not valid JSON."
QUEUE_DOWN = "The review queue is not available. Open the console from the running server to use it."
CASE_FAILED = "The case could not be opened."

# Byte-frozen for this round, hashed at BASE 1ae5a84. ui/app.js is the only shipped file the fix may
# change; the W24 acceptance file and its browser script are frozen by the W24 brief.
FROZEN = {
    "app/server.py": "3bc4dd76729ffd50f7baead46979e43050aba4a847365e5837b1a5da082c9529",
    "app/prompt_view.py": "3b8472f60e51f99b98a1f96f4ba4fe403986701a3ad3bf74c23a73325db985f6",
    "ui/index.html": "bc77c119d2da0e199e8a987ce6cd2b3049ac4f6d08c189823a7217a3f71b1b0b",
    "ui/styles.css": "4b4e7477b6503bc9b85790519e7609e3e581ecc2a78d4efe0be7f6ec2a6c7be5",
    "ui/party/driver-filing.html": "4799ad45af51aa79ae22c718420cde9bd03a43e74338b20772207937418b0349",
    "ui/party/driver.html": "63b9c366f12477a9002c006fea71199f9e57e8e311d3170b55d54c671717454d",
    "ui/party/driver.js": "fff0dd47777ed9b872fa51deb51171a844f6b827e3c58d4ba90302cf0cbe70ff",
    "ui/party/index.html": "06fd4937b1419d397b2a8f5e61f58e772f9c6e2d55f2799e2b553046b2303c23",
    "ui/party/party.css": "f1893ba638858a9b6a3e1582f489e2ce261e064fc6de8f2b7fb6ec7f46952c51",
    "ui/party/party.js": "90d55dbf1730f9991234cc2772cae27051cf4c2f5d43d6fca96e7ce54ef7efc0",
    "ui/party/status.html": "eaf668aea171af8f5785890048040b947e44b39a300f6ec6b712853b6d6403a7",
    "ui/party/status.js": "127098b1603b45d2ecbd1be7550362e4b6db23920fd7292a4b9588e09465c43e",
    "tests/test_w24_prompt_panel.py": "31efc92273e62edbdee289f49ea7de0d5271b7321993070591db517e7fa77e84",
    "tests/browser/w24_prompt_panel.cjs": "ec6cfb27c98f1b57faadd290574b32cbbdf66dbdf90206813617752819a8d428",
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ----------------------------------------------------------- the fake-DOM driver

H = T.H
for old, new in (
    # A page can lack element ids (no review UI) ...
    ('const fs=require("fs"),vm=require("vm");',
     'const fs=require("fs"),vm=require("vm"); const MISSING=JSON.parse(process.env.MISSING||"[]");'),
    ('getElementById:id=>{if(!ids[id]){', 'getElementById:id=>{if(MISSING.includes(id))return null;if(!ids[id]){'),
    # ... or fetch.
    ('fetch,Promise,setTimeout,clearTimeout,', 'fetch:scenario.noFetch?undefined:fetch,Promise,setTimeout,clearTimeout,'),
    # A request that never answers: the "no late reply" control.
    ('let r=responseFor(String(url));', 'let r=responseFor(String(url));if(r.hang)return new Promise(()=>{});'),
    # A local file whose text is raw (invalid JSON) and/or arrives after a delay.
    ('text:()=>Promise.resolve(JSON.stringify(a.body))',
     'text:()=>{const t=a.raw!==undefined?a.raw:JSON.stringify(a.body);'
     'return a.textDelay?new Promise(r=>setTimeout(()=>r(t),a.textDelay)):Promise.resolve(t)}'),
):
    assert H.count(old) == 1, old
    H = H.replace(old, new)


def drive(routes, actions=(), search="", missing=(), no_fetch=False):
    scenario = {"routes": routes, "actions": list(actions), "search": search, "noFetch": no_fetch}
    env = dict(os.environ, APP_JS=str(UI / "app.js"), SCENARIO=json.dumps(scenario),
               MISSING=json.dumps(list(missing)))
    result = subprocess.run([NODE, "-e", H], env=env, capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise AssertionError("app.js fix-round driver failed: " + result.stderr)
    return json.loads(result.stdout)


def wait(ms):
    return {"op": "wait", "ms": ms}


OPEN = T.OPEN
OPEN_B = T.OPEN_B
SNAP = T.SNAP
REFRESH = {"id": "queue-refresh", "op": "click"}
APPROVE = {"id": "decision-approve", "op": "check"}
REVIEW = {"id": "decision-form", "op": "submit"}


def pick(name="local.json", body=None, raw=None, text_delay=0):
    action = {"id": "case-picker", "op": "pick", "name": name, "body": body}
    if raw is not None:
        action["raw"] = raw
    if text_delay:
        action["textDelay"] = text_delay
    return action


def urls(out):
    return [r["url"] for r in out["requests"]]


def case_requests(out):
    return [u for u in urls(out) if u.endswith("/case")]


def node(out, id_):
    found = out["ids"].get(id_)
    if found is None:
        raise AssertionError("#%s was never rendered" % id_)
    return found


def decision(out):
    """The decision form's observable state; AssertionError (never KeyError) when it is absent."""
    section = node(out, "decision-section")
    approve = out["ids"].get("decision-approve")
    return {
        "section_hidden": section["hidden"],
        "approve_present": approve is not None,
        "approve_disabled": None if approve is None else approve["disabled"],
        "notes": [n["text"] for n in out["classes"]["decision-note"]],
    }


def current_rows(out):
    return [b for b in out["classes"]["queue-open"] if b["attrs"].get("aria-current") == "true"]


def row_buttons(out):
    return [b["text"] for b in out["classes"]["queue-open"]]


def panel(out):
    return out["ids"].get("prompts-content", {"children": [], "text": ""})


def articles(snapshot):
    return T.by_tag(snapshot, "article")


def row(run_id, action="refund", amount=55.16, can_approve=True):
    proposed = None if action is None else {"action": action, "amount_sgd": amount}
    return queue_row(run_id=run_id, dispute_id="D-" + run_id, amount_sgd=amount, proposed=proposed,
                     can_approve=can_approve)


def routes_with(rows, *runs):
    """Queue rows as given; a withheld case file and a prompts view for every run named."""
    routes = base_routes(rows)
    for r in runs:
        routes["/api/review/%s/case" % r] = [ok({"case_file": T.case_for(r), "human_decision": None})]
        routes["/api/review/%s/prompts" % r] = [ok(T.view(r, r.lower()))]
    return routes


def confirm_text(out):
    return node(out, "decision-confirm")["text"]


# =================================================================== deep link


class DeepLinkUsesTheQueueEntry(unittest.TestCase):
    """P1+F2: `?run=<queued id>` must build the same decision form as a queue click."""

    def test_deep_link_to_a_queued_run_with_a_proposal_enables_approve(self):
        out = drive(T.routes_for("A"), [wait(80)], search="?run=A")
        self.assertIn("/api/review/A/case", urls(out))
        self.assertEqual("A", node(out, "loaded-file")["text"])
        state = decision(out)
        self.assertFalse(state["section_hidden"], "a withheld deep link gets the decision form")
        self.assertTrue(state["approve_present"], "the decision form has an Approve option")
        self.assertFalse(state["approve_disabled"], "Approve is enabled: the queue entry carries a proposal")
        self.assertEqual([], state["notes"], "no 'No AI proposal' note when a proposal exists")

    def test_deep_link_and_queue_click_produce_the_same_form_and_row_state(self):
        deep = drive(T.routes_for("A"), [wait(80)], search="?run=A")
        click = drive(T.routes_for("A"), [OPEN, wait(80)])
        self.assertFalse(decision(click)["approve_disabled"], "fixture: the click path enables Approve")
        for key in ("decision-section", "decision-content", "queue-content", "loaded-file", "load-status",
                    "prompts-content", "case-workspace"):
            with self.subTest(element=key):
                self.assertEqual(node(click, key), node(deep, key))
        self.assertEqual(1, len(current_rows(deep)), "exactly one row is current")
        self.assertEqual(["Currently open"], row_buttons(deep))

    def test_deep_link_uses_the_entry_whose_run_id_matches(self):
        rows = [row("B", "refund", 12.34), row("A", "compensation", 7.5)]
        out = drive(routes_with(rows, "A", "B"), [wait(80), APPROVE, REVIEW, wait(20)], search="?run=A")
        self.assertEqual("A", node(out, "loaded-file")["text"])
        self.assertFalse(decision(out)["approve_disabled"])
        text = confirm_text(out)
        self.assertIn("Amount: compensation of SGD 7.50", text)
        self.assertIn("AI proposed: compensation of SGD 7.50", text)
        self.assertNotIn("12.34", text)
        self.assertEqual(["Open case", "Currently open"], row_buttons(out))
        self.assertEqual(1, len(current_rows(out)))

    def test_approve_stays_disabled_when_the_matching_entry_cannot_approve(self):
        rows = [row("B", "refund", 12.34), row("A", None, None, can_approve=False)]
        out = drive(routes_with(rows, "A", "B"), [wait(80)], search="?run=A")
        self.assertEqual("A", node(out, "loaded-file")["text"])
        state = decision(out)
        self.assertFalse(state["section_hidden"])
        self.assertTrue(state["approve_disabled"], "can_approve false: Approve stays disabled")
        self.assertEqual([NO_PROPOSAL_NOTE], state["notes"])
        self.assertEqual(["Open case", "Currently open"], row_buttons(out))

    def test_deep_link_uses_the_entry_the_queue_shows_when_it_fires(self):
        # Two queue loads answer with different proposals for A: a Refresh's load settles first,
        # the first (page-load) load settles last. The deep link fires after the first load and
        # must use the entry of the row the queue SHOWS at that moment (the object a click on that
        # row passes), never an entry from a load the queue no longer shows.
        first = dict(ok({"cases": [row("A", "refund", 55.16)]}), delay=250)
        routes = routes_with([], "A")
        routes["/api/review/queue"] = [first, ok({"cases": [row("A", "refund", 12.34)]})]
        out = drive(routes, [wait(20), REFRESH, wait(400), APPROVE, REVIEW, wait(20)], search="?run=A")
        self.assertEqual(2, urls(out).count("/api/review/queue"), "fixture: the refresh ran")
        self.assertEqual(1, case_requests(out).count("/api/review/A/case"))
        shown = [n["text"] for n in out["classes"]["queue-amount"]]
        self.assertEqual(1, len(shown), "fixture: one queue row is shown")
        self.assertIn(shown[0], ("SGD 55.16 proposed", "SGD 12.34 proposed"))
        other = "12.34" if "55.16" in shown[0] else "55.16"
        text = confirm_text(out)
        self.assertIn("AI proposed: refund of " + shown[0][:-len(" proposed")], text)
        self.assertNotIn(other, text)

    def test_deep_link_to_a_run_not_in_the_queue_opens_with_its_run_id(self):
        out = drive(routes_with([row("B")], "A", "B"), [wait(80), APPROVE, REVIEW, wait(20)], search="?run=A")
        self.assertEqual(["/api/review/A/case"], case_requests(out))
        self.assertEqual("A", node(out, "loaded-file")["text"])
        self.assertFalse(node(out, "case-workspace")["hidden"])
        self.assertEqual(3, len(articles(panel(out))))
        state = decision(out)
        self.assertFalse(state["section_hidden"])
        self.assertTrue(state["approve_disabled"], "no queue entry: no proposal to approve")
        self.assertEqual([NO_PROPOSAL_NOTE], state["notes"])
        self.assertIn("AI proposed: no proposal on record", confirm_text(out))
        self.assertEqual(["Open case"], row_buttons(out))
        self.assertEqual([], current_rows(out))

    def test_deep_link_waits_for_the_first_queue_load(self):
        routes = T.routes_for("A")
        routes["/api/review/queue"] = [dict(ok({"cases": [row("A")]}), delay=200)]
        out = drive(routes, [SNAP, wait(100), SNAP, wait(400)], search="?run=A")
        self.assertEqual(2, len(out["checkpoints"]))
        for index, checkpoint in enumerate(out["checkpoints"]):
            with self.subTest(checkpoint=index):
                self.assertEqual([], [u for u in checkpoint["requests"] if u.endswith("/case")],
                                 "the deep link opened before the queue settled")
        self.assertEqual(["/api/review/A/case"], case_requests(out))
        self.assertFalse(decision(out)["approve_disabled"])
        self.assertEqual([], decision(out)["notes"])
        self.assertEqual(["Currently open"], row_buttons(out))

    def test_a_failed_queue_load_still_opens_the_run(self):
        for name, response in (("offline", {"reject": True, "delay": 120}), ("503", {"status": 503, "body": {}})):
            with self.subTest(queue=name):
                routes = T.routes_for("A")
                routes["/api/review/queue"] = [response]
                out = drive(routes, [wait(300)], search="?run=A")
                self.assertEqual(QUEUE_DOWN, node(out, "queue-status")["text"], "fixture: the queue failed")
                self.assertEqual(["/api/review/A/case"], case_requests(out))
                self.assertEqual("A", node(out, "loaded-file")["text"])
                self.assertEqual(3, len(articles(panel(out))))
                state = decision(out)
                self.assertFalse(state["section_hidden"])
                self.assertTrue(state["approve_disabled"])
                self.assertEqual([NO_PROPOSAL_NOTE], state["notes"])


class UserActionWinsOverTheDeepLink(unittest.TestCase):
    """A queue click or a local-file pick before the deep link fires: the deep link does nothing."""

    def slow_queue(self, *rows_runs, delay=300):
        routes = T.routes_for(*rows_runs)
        routes["/api/review/queue"] = [dict(ok({"cases": [row(r) for r in rows_runs]}), delay=delay)]
        return routes

    def test_a_local_file_picked_before_the_deep_link_fires_wins(self):
        routes = self.slow_queue("A")
        routes["/api/review/LOCAL-1/prompts"] = [ok(T.view("LOCAL-1", "l"))]
        out = drive(routes, [wait(30), pick(body=T.case_for("LOCAL-1")), wait(600)], search="?run=A")
        self.assertIn("/api/review/queue", urls(out))
        self.assertEqual([], case_requests(out), "the deep link fired after the user picked a file")
        self.assertEqual("local.json", node(out, "loaded-file")["text"])
        self.assertIn("SYS-l-", panel(out)["text"])
        self.assertNotIn("SYS-a-", panel(out)["text"])
        self.assertTrue(node(out, "decision-section")["hidden"], "a local file never gets the decision form")
        self.assertEqual([], current_rows(out))

    def test_a_bad_local_file_picked_before_the_deep_link_fires_still_wins(self):
        out = drive(self.slow_queue("A"), [wait(30), pick("bad.json", raw="{not valid json"), wait(600)],
                    search="?run=A")
        self.assertEqual(NOT_JSON, node(out, "load-status")["text"])
        self.assertEqual([], case_requests(out), "the deep link fired after the user picked a file")
        self.assertTrue(node(out, "case-workspace")["hidden"])
        self.assertEqual([], articles(panel(out)))
        self.assertEqual([], current_rows(out))

    def test_a_queue_open_before_the_first_queue_load_settles_wins(self):
        routes = T.routes_for("A", "B")
        rows = {"cases": [row("A"), row("B")]}
        routes["/api/review/queue"] = [dict(ok(rows), delay=300), ok(rows)]
        out = drive(routes, [wait(30), REFRESH, wait(60), OPEN_B, wait(600)], search="?run=A")
        self.assertEqual(2, urls(out).count("/api/review/queue"), "fixture: the refresh ran")
        self.assertEqual(["/api/review/B/case"], case_requests(out), "the deep link fired after a queue open")
        self.assertEqual("B", node(out, "loaded-file")["text"])
        self.assertIn("SYS-b-", panel(out)["text"])
        self.assertNotIn("SYS-a-", panel(out)["text"])
        self.assertEqual(["Open case", "Currently open"], row_buttons(out))

    def test_a_queue_open_while_the_deep_link_case_is_pending_wins(self):
        # Preserved behaviour: once the deep link has fired, the existing open generation guard
        # still lets a later queue click win over its slow /case answer.
        routes = T.routes_for("A", "B")
        routes["/api/review/A/case"] = [dict(ok({"case_file": T.case_for("A"), "human_decision": None}), delay=300)]
        out = drive(routes, [wait(60), OPEN_B, wait(600)], search="?run=A")
        self.assertIn("/api/review/A/case", urls(out))
        self.assertEqual("B", node(out, "loaded-file")["text"])
        self.assertIn("SYS-b-", panel(out)["text"])
        self.assertNotIn("SYS-a-", panel(out)["text"])
        self.assertEqual(["Open case", "Currently open"], row_buttons(out))


class DeepLinkUnchangedPaths(unittest.TestCase):
    """Behaviour the fix must PRESERVE (these pass on BASE)."""

    def test_an_invalid_id_is_rejected_at_once_even_with_a_slow_queue(self):
        routes = T.routes_for("A")
        routes["/api/review/queue"] = [dict(ok({"cases": [row("A")]}), delay=200)]
        out = drive(routes, [SNAP, wait(400)], search="?run=..%2Fx")
        self.assertEqual(T.UNKNOWN_RUN, out["checkpoints"][0]["status"], "Unknown run. is set at load")
        self.assertEqual(T.UNKNOWN_RUN, node(out, "load-status")["text"])
        self.assertEqual([], [u for u in urls(out) if u.endswith("/case") or u.endswith("/prompts")])
        self.assertTrue(node(out, "case-workspace")["hidden"])
        self.assertEqual(["Open case"], row_buttons(out))

    def test_without_a_review_queue_the_deep_link_opens_at_once_with_its_run_id(self):
        out = drive(T.routes_for("A"), [SNAP, wait(100)], search="?run=A", missing=["queue-refresh"])
        self.assertNotIn("/api/review/queue", urls(out), "fixture: no review UI, no queue load")
        self.assertIn("/api/review/A/case", out["checkpoints"][0]["requests"], "opened at once")
        self.assertEqual("A", node(out, "loaded-file")["text"])
        state = decision(out)
        self.assertFalse(state["section_hidden"])
        self.assertTrue(state["approve_disabled"])
        self.assertEqual([NO_PROPOSAL_NOTE], state["notes"])

    def test_without_fetch_the_deep_link_still_tries_at_once(self):
        out = drive(T.routes_for("A"), [SNAP, wait(100)], search="?run=A", no_fetch=True)
        self.assertEqual([], out["requests"])
        self.assertEqual(CASE_FAILED, out["checkpoints"][0]["status"])
        self.assertEqual(CASE_FAILED, node(out, "load-status")["text"])
        self.assertTrue(node(out, "case-workspace")["hidden"])


# ============================================================ F1: stale prompts


class LocalFilePickInvalidatesPendingPrompts(unittest.TestCase):
    """F1: picking a local file retires any pending /prompts reply for the previous case.

    Every run is compared with a CONTROL in which the previous case's /prompts never answers, so
    "nothing stale rendered" is measured against the state the page reaches with no late reply.
    """

    def run_failed_file(self, late):
        routes = T.routes_for("A")
        routes["/api/review/A/prompts"] = [late]
        return drive(routes, [OPEN, wait(60), pick("bad.json", raw="{not valid json"), wait(500)])

    def run_loaded_file(self, late):
        routes = T.routes_for("A")
        routes["/api/review/A/prompts"] = [late]
        routes["/api/review/LOCAL-1/prompts"] = [ok(T.view("LOCAL-1", "l"))]
        # A's reply lands at ~150 ms: after the pick (~60 ms), before the file is read (~360 ms).
        return drive(routes, [OPEN, wait(60), pick(body=T.case_for("LOCAL-1"), text_delay=300),
                              wait(150), SNAP, wait(450)])

    def assert_failed_file_control(self, control):
        self.assertEqual(NOT_JSON, node(control, "load-status")["text"])
        self.assertTrue(node(control, "case-workspace")["hidden"])
        self.assertEqual([], articles(panel(control)))
        self.assertEqual("", panel(control)["text"])

    def test_late_success_after_a_failed_local_file_never_renders(self):
        control = self.run_failed_file({"hang": True})
        self.assert_failed_file_control(control)
        out = self.run_failed_file(dict(ok(T.view("A", "a")), delay=300))
        self.assertEqual(0, len(articles(panel(out))), "the previous case's prompts rendered")
        self.assertNotIn("SYS-a-", panel(out)["text"])
        self.assertEqual(panel(control), panel(out))
        self.assertEqual(node(control, "load-status"), node(out, "load-status"))

    def test_late_failure_after_a_failed_local_file_never_renders(self):
        control = self.run_failed_file({"hang": True})
        self.assert_failed_file_control(control)
        out = self.run_failed_file({"reject": True, "delay": 300})
        self.assertNotIn(T.FAILURE, panel(out)["text"], "the previous case's failure rendered")
        self.assertEqual(panel(control), panel(out))
        self.assertEqual(node(control, "load-status"), node(out, "load-status"))

    def assert_loaded_file_control(self, control):
        self.assertEqual(1, len(control["checkpoints"]))
        self.assertEqual([], articles(control["checkpoints"][0]["prompts"]))
        self.assertEqual("", control["checkpoints"][0]["prompts"]["text"])
        self.assertEqual("local.json", node(control, "loaded-file")["text"])
        self.assertEqual(3, len(articles(panel(control))))
        self.assertIn("SYS-l-", panel(control)["text"])

    def test_late_success_after_a_loaded_local_file_never_renders(self):
        control = self.run_loaded_file({"hang": True})
        self.assert_loaded_file_control(control)
        out = self.run_loaded_file(dict(ok(T.view("A", "a")), delay=150))
        pending = out["checkpoints"][0]["prompts"]
        self.assertEqual(0, len(articles(pending)), "the previous case's prompts rendered after the pick")
        self.assertNotIn("SYS-a-", pending["text"])
        self.assertEqual(control["checkpoints"][0]["prompts"], pending)
        self.assertEqual(panel(control), panel(out))

    def test_late_failure_after_a_loaded_local_file_never_renders(self):
        control = self.run_loaded_file({"hang": True})
        self.assert_loaded_file_control(control)
        out = self.run_loaded_file({"reject": True, "delay": 150})
        pending = out["checkpoints"][0]["prompts"]
        self.assertNotIn(T.FAILURE, pending["text"], "the previous case's failure rendered after the pick")
        self.assertEqual(control["checkpoints"][0]["prompts"], pending)
        self.assertEqual(panel(control), panel(out))


# ======================================================================= freeze


class FixRoundFreeze(unittest.TestCase):
    def test_only_app_js_may_change(self):
        actual = {rel: _sha(REPO / rel) for rel in FROZEN}
        self.assertEqual(FROZEN, actual)


# ------------------------------------------------------------- the real browser

BROWSER_SCRIPT = REPO / "tests" / "browser" / "w24_fix_round.cjs"


@unittest.skipUnless(os.environ.get("PUPPETEER_MODULE") and os.environ.get("BROWSER_EXECUTABLE"),
                     "real-browser pass: set PUPPETEER_MODULE and BROWSER_EXECUTABLE (run by the planner)")
class RealBrowserDeepLinkApprove(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = Server()
        cls.run_id = cls.server.file()["run_id"]  # T-RD0109, claim 55.16: withheld by ESC-4

    @classmethod
    def tearDownClass(cls):
        cls.server.close()

    def test_deep_link_to_a_queued_run_enables_approve_at_390_and_1280(self):
        status, queue = self.server.json("GET", "/api/review/queue")
        self.assertEqual(200, status)
        entries = [c for c in queue.get("cases", []) if c.get("run_id") == self.run_id]
        self.assertEqual(1, len(entries), "fixture: the filed run is queued")
        self.assertIs(True, entries[0].get("can_approve"), "fixture: the queued run can be approved")
        self.assertIsInstance(entries[0].get("proposed"), dict, "fixture: the queued run carries a proposal")
        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "report.json"
            env = dict(os.environ, W24FIX_EXPECT=json.dumps({"run": self.run_id, "note": NO_PROPOSAL_NOTE}))
            result = subprocess.run([NODE, str(BROWSER_SCRIPT), self.server.base, str(report_path)],
                                    env=env, capture_output=True, text=True, timeout=240)
            self.assertTrue(report_path.exists(), "browser driver wrote no report: " + result.stderr[-2000:])
            report = json.loads(report_path.read_text(encoding="utf-8"))
        keep = os.environ.get("W24FIX_BROWSER_REPORT")
        if keep:
            Path(keep).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        self.assertTrue(report.get("passed"), json.dumps(report, indent=1)[:4000])
        self.assertEqual([1280, 390], [c.get("width") for c in report.get("cases", [])], "both widths ran")


if __name__ == "__main__":
    unittest.main()
