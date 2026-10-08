"""Sibling pin for F1, adopted into the W24 fix contract by the parent (2026-10-07).

Sibling of F1 found while checking the class: handleFile's own file.text() read has no
generation guard. A slow local-file read that settles AFTER a newer selection (a queue open, or a
second file pick) still renders, so the page shows the older selection; after a queue open it
renders the local file's content under state.openRun of the QUEUE run, so the decision form for
that run is shown beside a different case's content.
"""
from __future__ import annotations

import json
import os
import subprocess
import unittest

import tests.test_w24_fix_round as F

T = F.T

# Parent addition: a local file whose read itself rejects (after an optional delay), so the
# catch-path guard is pinned on its own. A parse failure never reaches it: the success-path
# guard returns before parsing.
_OLD = 'return a.textDelay?new Promise(r=>setTimeout(()=>r(t),a.textDelay)):Promise.resolve(t)}'
assert F.H.count(_OLD) == 1, "fix-round driver changed; re-aim the read-rejection hook"
H2 = F.H.replace(_OLD, 'if(a.textReject)return new Promise((r,j)=>setTimeout(()=>j(new Error("read failed")),'
                       'a.textDelay||0));' + _OLD)


def drive_rejecting(routes, actions):
    scenario = {"routes": routes, "actions": list(actions), "search": "", "noFetch": False}
    env = dict(os.environ, APP_JS=str(F.UI / "app.js"), SCENARIO=json.dumps(scenario), MISSING="[]")
    result = subprocess.run([F.NODE, "-e", H2], env=env, capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise AssertionError("app.js read-rejection driver failed: " + result.stderr)
    return json.loads(result.stdout)


class LocalFileReadGuard(unittest.TestCase):
    def test_a_slow_local_read_never_replaces_a_newer_queue_open(self):
        out = F.drive(T.routes_for("A"), [F.wait(20), F.pick(body=T.case_for("LOCAL-1"), text_delay=200),
                                          F.wait(30), F.OPEN, F.wait(400)])
        self.assertEqual("A", F.node(out, "loaded-file")["text"], "the older local read replaced case A")
        self.assertEqual("Loaded A.", F.node(out, "load-status")["text"])
        self.assertIn("SYS-a-", F.panel(out)["text"])
        self.assertEqual(["Currently open"], F.row_buttons(out))

    def test_a_slow_local_read_never_replaces_a_newer_local_pick(self):
        out = F.drive(T.routes_for("A"), [F.pick("slow.json", body=T.case_for("SLOW"), text_delay=200),
                                          F.pick("fast.json", body=T.case_for("FAST")), F.wait(400)])
        self.assertEqual("fast/case_file.json", F.node(out, "loaded-file")["text"], "the older pick replaced the newer one")
        self.assertEqual("Loaded fast/case_file.json.", F.node(out, "load-status")["text"])

    def test_a_slow_failing_local_read_never_clears_a_newer_queue_open(self):
        # Parent addition: the read itself rejects after a newer queue open; only the catch-path
        # guard stops it from clearing case A.
        pick = dict(F.pick("broken.json", body=T.case_for("BROKEN"), text_delay=200), textReject=True)
        out = drive_rejecting(T.routes_for("A"), [F.wait(20), pick, F.wait(30), F.OPEN, F.wait(400)])
        self.assertEqual("A", F.node(out, "loaded-file")["text"], "the older failed read cleared case A")
        self.assertEqual("Loaded A.", F.node(out, "load-status")["text"])
        self.assertIn("SYS-a-", F.panel(out)["text"])

    def test_a_failing_local_read_with_nothing_newer_still_reports_the_error(self):
        # Control: the guard must not swallow a read failure that is still current.
        pick = dict(F.pick("broken.json", body=T.case_for("BROKEN")), textReject=True)
        out = drive_rejecting(T.routes_for("A"), [F.wait(20), pick, F.wait(100)])
        self.assertEqual("read failed", F.node(out, "load-status")["text"])


if __name__ == "__main__":
    unittest.main()
