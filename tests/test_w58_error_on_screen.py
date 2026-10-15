"""W58: a message shown under "Send my dispute" is scrolled on screen.

Found on the hosted live site (2026-10-15): the filing-limit refusal appeared below the Send
button, outside the visible area at phone and desktop width, so the party saw nothing happen. The
same function, ui/party/party.js showError(), shows the form's own client-side errors too. A
freeze exception approved one line: after the node is revealed, scroll it into view with
block "nearest" (no jump when it is already visible).

  * ShowErrorBringsTheMessageIntoView pins the line inside showError's own body, comments
    stripped, after the node is revealed.
  * RealBrowserErrorOnScreen (needs PUPPETEER_MODULE and BROWSER_EXECUTABLE) runs
    tests/browser/w58_error_on_screen.cjs against the real server: rider and driver filing pages,
    390px and 1280px, a client-side error and an intercepted 429 server refusal. The message must
    be hit-testable on screen. Without the line every case fails.

Run: env -u PYTHONPATH python3 -B -m unittest tests.test_w58_error_on_screen -v
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.w23_b2_support import NODE
from tests.w23_support import Server

REPO = Path(__file__).resolve().parent.parent
PARTY_JS = REPO / "ui" / "party" / "party.js"
BROWSER_DIR = REPO / "tests" / "browser"


def _strip_js(js):
    js = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
    return re.sub(r"(?m)^\s*//.*$", "", js)


def _function_body(js, name):
    m = re.search(r"function\s+%s\s*\([^)]*\)\s*\{" % re.escape(name), js)
    assert m, "no function " + name
    depth, i = 1, m.end()
    while depth and i < len(js):
        depth += (js[i] == "{") - (js[i] == "}")
        i += 1
    return js[m.end():i - 1]


class ShowErrorBringsTheMessageIntoView(unittest.TestCase):
    def setUp(self):
        js = _strip_js(PARTY_JS.read_text())
        self.assertEqual(1, len(re.findall(r"function\s+showError\s*\(", js)), "exactly one showError")
        self.body = [line.strip() for line in _function_body(js, "showError").splitlines() if line.strip()]

    def test_the_revealed_node_is_scrolled_into_view_nearest(self):
        self.assertEqual([
            "var node = document.getElementById(id);",
            "node.textContent = message;",
            "node.hidden = false;",
            'node.scrollIntoView({ block: "nearest" });',
        ], self.body)

    def test_clear_error_does_not_scroll(self):
        js = _strip_js(PARTY_JS.read_text())
        self.assertNotIn("scrollIntoView", _function_body(js, "clearError"))


def _browser_env():
    return os.environ.get("PUPPETEER_MODULE") and os.environ.get("BROWSER_EXECUTABLE")


@unittest.skipUnless(_browser_env(), "PUPPETEER_MODULE and BROWSER_EXECUTABLE are not set")
class RealBrowserErrorOnScreen(unittest.TestCase):
    """tests/browser/w58_error_on_screen.cjs against the real server."""

    @classmethod
    def setUpClass(cls):
        cls.server = Server()
        cls.report_dir = Path(tempfile.mkdtemp(prefix="w58-browser-"))
        cls.report = cls.report_dir / "report.json"
        cls.result = subprocess.run([NODE, str(BROWSER_DIR / "w58_error_on_screen.cjs"),
                                     cls.server.base, str(cls.report)],
                                    capture_output=True, text=True, timeout=300)
        cls.data = json.loads(cls.report.read_text()) if cls.report.is_file() else {}

    @classmethod
    def tearDownClass(cls):
        cls.server.close()
        shutil.rmtree(cls.report_dir, True)

    def test_the_script_passed(self):
        self.assertEqual(0, self.result.returncode, self.result.stderr[-2000:] + self.result.stdout[-1000:])
        self.assertTrue(self.data.get("passed"), self.data)

    def test_every_page_width_and_scenario_was_measured(self):
        measured = sorted((c["role"], c["width"], c["scenario"]) for c in self.data.get("cases", []))
        expected = sorted((r, w, s) for r in ("rider", "driver") for w in (390, 1280) for s in ("empty", "server"))
        self.assertEqual(expected, measured, self.data)


if __name__ == "__main__":
    unittest.main()
