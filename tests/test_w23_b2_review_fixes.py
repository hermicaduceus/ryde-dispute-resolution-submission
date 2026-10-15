"""W23 B2 review-round pins: findings N1, N2, N3, N5, N6 and hardening S1.

Each test here fails on the pre-fix build for the reason named in its docstring.
Source: cross-family review `drafts/reviews/2026-10-04-session-twenty-three-opus55-review.md`
(a second-model / the vendor), every finding reproduced by the planner before these pins were written.
"""
import json
import tempfile
import unittest
from pathlib import Path

from tests.w23_b2_support import HARNESS, NODE, REPO, base_routes, bad, case_file, drive, ok, queue_row
from tests.w23_support import Server

import os
import subprocess


# --------------------------------------------------------------- N1 (JS race)
# The shared harness has no delay/wait support, so this module drives app.js
# through a small extension it owns: a route may carry `delay` (ms), and actions
# may `wait`. Nothing in tests/w23_b2_support is modified.
DELAYED = HARNESS.replace(
    'const fetch=(url,opts)=>{opts=opts||{};requests.push({url:String(url),method:opts.method||"GET",body:opts.body?JSON.parse(opts.body):null});let r=responseFor(String(url));if(r.reject)return Promise.reject(new Error("offline"));return Promise.resolve({ok:r.status===undefined?r.ok!==false:r.status>=200&&r.status<300,status:r.status||200,json:()=>Promise.resolve(r.body)});};',
    'const fetch=(url,opts)=>{opts=opts||{};requests.push({url:String(url),method:opts.method||"GET",body:opts.body?JSON.parse(opts.body):null});let r=responseFor(String(url));if(r.reject)return Promise.reject(new Error("offline"));const resp={ok:r.status===undefined?r.ok!==false:r.status>=200&&r.status<300,status:r.status||200,json:()=>Promise.resolve(r.body)};return r.delay?new Promise(res=>setTimeout(()=>res(resp),r.delay)):Promise.resolve(resp);};')
DELAYED = DELAYED.replace(
    'else if(a.op==="set"){n.value=a.value}',
    'else if(a.op==="set"){n.value=a.value}else if(a.op==="wait"){await new Promise(r=>setTimeout(r,a.ms))}')
DELAYED = DELAYED.replace(
    'process.stdout.write(JSON.stringify({ids:',
    'process.stdout.write(JSON.stringify({unhandled:UNHANDLED,ids:')
DELAYED = DELAYED.replace(
    '(async()=>{vm.runInNewContext',
    'const UNHANDLED=[];process.on("unhandledRejection",e=>UNHANDLED.push(String(e&&e.message||e)));(async()=>{vm.runInNewContext')
assert "r.delay" in DELAYED and 'a.op==="wait"' in DELAYED and "UNHANDLED" in DELAYED


def drive_delayed(routes, actions=()):
    scenario = {"routes": routes, "actions": list(actions)}
    env = dict(os.environ, APP_JS=str(REPO / "ui" / "app.js"), SCENARIO=json.dumps(scenario))
    result = subprocess.run(
        [NODE, "-e", DELAYED],
        env=env, capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise AssertionError("app.js harness failed: " + result.stderr)
    return json.loads(result.stdout)


def _race_routes(decision_response):
    """Case A (RUN / 7) with a delayed decision; case B ('B') ready to open."""
    row_b = queue_row(run_id="B", dispute_id="DISP-B")
    case_b = case_file()
    case_b["run_id"] = "B"
    routes = base_routes([queue_row(), row_b])
    routes["/api/review/RUN%20%2F%207/case"] = [ok({"case_file": case_file(), "human_decision": None})]
    routes["/api/review/B/case"] = [ok({"case_file": case_b, "human_decision": None})]
    routes["/api/review/RUN%20%2F%207/decision"] = [dict(decision_response, delay=60)]
    return routes


_FILL_A = [{"className": "queue-open", "op": "click"},
           {"id": "decision-change", "op": "check"},
           {"id": "decision-reviewer", "op": "set", "value": "Ann"},
           {"id": "decision-reason", "op": "set", "value": "r"},
           {"id": "decision-action", "op": "set", "value": "refund"},
           {"id": "decision-amount", "op": "set", "value": "45"},
           {"id": "decision-form", "op": "submit"},
           {"id": "decision-confirm-send", "op": "click"}]
_OPEN_B = [{"className": "queue-open", "op": "click", "index": 1}, {"op": "wait", "ms": 150}]


class DecisionResponseDoesNotLandOnAnotherCase(unittest.TestCase):
    """N1. A reply that arrives after the operator opened another case must not
    touch that case's decision UI. Pre-fix: the success branch replaces B's form
    with A's 'Decision recorded' card, and the error branch throws a TypeError."""

    def test_late_success_leaves_the_new_case_form_intact(self):
        out = drive_delayed(_race_routes(ok({"party_view": {"message": "A's party message"}})), _FILL_A + _OPEN_B)
        self.assertEqual("B", out["ids"]["loaded-file"]["text"])
        rendered = [c for c in out["ids"]["decision-content"]["children"] if c["id"] == "decision-form"]
        self.assertTrue(rendered, "the second case's decision form must survive")
        self.assertEqual([], out["classes"]["decision-result"],
                         "case A's recorded-decision card must not render on case B")

    def test_late_error_does_not_throw_and_is_not_shown_on_the_new_case(self):
        out = drive_delayed(_race_routes(bad(409, {"error": "this case already has a human decision"})), _FILL_A + _OPEN_B)
        self.assertEqual([], out["unhandled"], "the late error must not throw")
        self.assertEqual("B", out["ids"]["loaded-file"]["text"])
        self.assertNotEqual("this case already has a human decision", out["ids"]["decision-error"]["text"],
                            "case A's refusal text must not appear on case B")
        rendered = [c for c in out["ids"]["decision-content"]["children"] if c["id"] == "decision-form"]
        self.assertTrue(rendered, "the second case's decision form must survive")


# ------------------------------------------------------- N2 / S1 (server)
def _deep(prefix="[", depth=200000):
    return prefix * depth + "]" * depth


class ServerEdges(unittest.TestCase):
    """N2. Deeply nested JSON is unparseable-without-crashing: it must be a 404,
    never a 500. S1. A `payloads` directory that is a symlink out of the run must
    not be followed."""

    def setUp(self):
        self.s = Server()
        self.addCleanup(self.s.close)

    def _get(self, path):
        status, _headers, raw = self.s.raw("GET", path)
        try:
            body = json.loads(raw)
        except Exception:
            body = raw.decode(errors="replace")
        return status, body

    def test_deep_payload_is_unknown_payload_not_a_500(self):
        run = self.s.file("T-RD0109", 55.16)["run_id"]
        (self.s.run_dir(run) / "payloads" / "0201-deep.json").write_text(_deep(), encoding="utf-8")
        status, body = self._get("/api/review/%s/payloads/0201-deep.json" % run)
        self.assertEqual(404, status, body)
        self.assertEqual({"error": "unknown payload"}, body)

    def test_deep_case_file_is_unknown_run_not_a_500(self):
        deep = self.s.out / "deep-case"
        deep.mkdir()
        (deep / "case_file.json").write_text(_deep("{", 200000).replace("{", '{"a":'), encoding="utf-8")
        status, body = self._get("/api/review/deep-case/case")
        self.assertEqual(404, status, body)
        self.assertEqual({"error": "unknown run"}, body)

    def test_symlinked_payloads_directory_is_not_followed(self):
        run = self.s.file("T-RD0109", 55.16)["run_id"]
        outside = Path(tempfile.mkdtemp(dir=os.environ.get("TMPDIR", "/tmp")))
        (outside / "0301-secret.json").write_text('{"secret": "outside-run"}', encoding="utf-8")
        target = self.s.run_dir(run) / "payloads"
        for child in target.iterdir():
            child.unlink()
        target.rmdir()
        os.symlink(outside, target)
        status, body = self._get("/api/review/%s/payloads/0301-secret.json" % run)
        self.assertEqual(404, status, body)
        self.assertEqual({"error": "unknown payload"}, body)
        # a normal payload in the same run still serves, so the guard is not blanket
        payloads = self.s.run_dir(run) / "payloads"
        payloads.unlink()
        payloads.mkdir()
        (payloads / "0302-good.json").write_text('{"ok": 1}', encoding="utf-8")
        self.assertEqual((200, {"ok": 1}), self._get("/api/review/%s/payloads/0302-good.json" % run))


# ------------------------------------------------------------ N3 / N6 (JS)
class ConfirmationLinesAndSendGuard(unittest.TestCase):
    """N3. An approve of a `no action` proposal must read `Amount: no action` and
    must not fire the fare warning. N6. An unparseable change amount must not leave
    Send as a silent dead end."""

    def _opened(self, row, fare=112.56):
        routes = base_routes([row])
        routes["/api/review/RUN%20%2F%207/case"] = [ok({"case_file": case_file(fare=fare), "human_decision": None})]
        return routes

    def test_approve_of_a_no_action_proposal_reads_no_action_without_warning(self):
        row = queue_row(proposed={"action": "no action", "amount_sgd": 12.5}, amount_sgd=12.5)
        out = drive(self._opened(row, fare=10.0),
                    [{"className": "queue-open", "op": "click"},
                     {"id": "decision-approve", "op": "check"},
                     {"id": "decision-form", "op": "submit"}])
        text = out["ids"]["decision-confirm"]["text"]
        self.assertIn("Amount: no action", text)
        self.assertNotIn("no action of SGD", text)
        self.assertEqual([], out["classes"]["confirm-warning"], "a no-action approve is not an amount over the fare")

    def test_approve_of_a_zero_no_action_proposal_reads_no_action(self):
        row = queue_row(proposed={"action": "no action", "amount_sgd": 0.0}, amount_sgd=0.0)
        out = drive(self._opened(row),
                    [{"className": "queue-open", "op": "click"},
                     {"id": "decision-approve", "op": "check"},
                     {"id": "decision-form", "op": "submit"}])
        self.assertIn("Amount: no action", out["ids"]["decision-confirm"]["text"])
        self.assertNotIn("no action of SGD 0.00", out["ids"]["decision-confirm"]["text"])

    def test_empty_amount_does_not_leave_send_as_a_silent_dead_end(self):
        out = drive(self._opened(queue_row()),
                    [{"className": "queue-open", "op": "click"},
                     {"id": "decision-change", "op": "check"},
                     {"id": "decision-action", "op": "set", "value": "refund"},
                     {"id": "decision-amount", "op": "set", "value": ""},
                     {"id": "decision-form", "op": "submit"},
                     {"id": "decision-confirm-send", "op": "click"}])
        posts = [r for r in out["requests"] if r["method"] == "POST"]
        self.assertEqual([], posts)
        self.assertTrue(out["ids"]["decision-confirm-send"]["disabled"] or out["ids"]["decision-error"]["text"],
                        "Send must be disabled or explain why it did nothing")


# ------------------------------------------------------------------ N5 (doc)
class ArchitectureEndpointTable(unittest.TestCase):
    """N5. The endpoint table must list the two paths the paragraph above names."""

    def test_table_lists_the_two_review_read_paths(self):
        doc = (REPO / "docs" / "architecture.md").read_text(encoding="utf-8")
        table = doc.split("| Endpoint | Purpose |", 1)[1].split("\n\n", 1)[0]
        self.assertIn("/api/review/<run_id>/case", table)
        self.assertIn("/api/review/<run_id>/payloads/<name>", table)


if __name__ == "__main__":
    unittest.main()
