"""Step-1 targeting: the landing page's first link must open the no-show case it names.

the operator comment round (2026-10-15, on /party/status.html?snapshot=after): landing step 1 says
"A no-show case the AI decided alone" but opens the rider's account page, where the
route-deviation decision (SGD 55.16) renders first, so a judge reads the wrong case before
finding the 6.61 card. Two seams fix it, both named by this round:

- ui/party/status.js renders ONE dispute when a ?dispute=<id> query param matches a
  dispute on the demo account, and falls open to the full list when the param is absent
  or matches nothing (a mistyped param must not blank the page). No new party text: the
  filtered card uses the existing renderer and headings.
- tools/export_replay.py fills {{NS_DISPUTE_ID}} from the NS run's case file, and
  tools/replay/index.html targets it on step 1 ONLY. Step 4 ("What the rider sees") keeps
  the full list: its subject is the detour rider, whose card renders first there.

The real-browser pin is tests/browser/step1_dispute_target.cjs (parent gate, 390px and
1280px). The source pin below keeps the guard always-on, scoped to the loadAccount body
with comments stripped, per the standing source-pin rules.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from tests import w27_replay_support as w27

REPO = w27.REPO
STATUS_JS = REPO / "ui" / "party" / "status.js"

_EXPORT: dict = {}


def _export():
    if "out" not in _EXPORT:
        fx = w27.fixture()
        out = w27.scratch_dir() / "site"
        code, stdout, stderr = w27.run_cli(w27.export_args(fx, out, allow_mock=True))
        _EXPORT.update(out=out, code=code, stdout=stdout, stderr=stderr, fx=fx)
    return _EXPORT


def _function_body(code: str, name: str) -> str:
    """One function's body, brace-matched, from comment-stripped source. No dict folding."""
    start = code.index("function %s" % name)
    opening = code.index("{", start)
    depth = 0
    for index in range(opening, len(code)):
        if code[index] == "{":
            depth += 1
        elif code[index] == "}":
            depth -= 1
            if depth == 0:
                return code[opening:index + 1]
    raise AssertionError("%s body not found in ui/party/status.js" % name)


def _load_account_body() -> str:
    """The loadAccount function body, comment-stripped, brace-matched. No dict folding."""
    return _function_body(_stripped(), "loadAccount")


def _stripped() -> str:
    return w27.strip_js_comments(STATUS_JS.read_text(encoding="utf-8"))


def _landing_hrefs(landing_html: str) -> list:
    block = re.search(r"<ol>(.*?)</ol>", landing_html, re.S)
    if block is None:
        raise AssertionError("the landing page has no ordered step list")
    return re.findall(r'href="([^"]+)"', block.group(1))


class LandingTargetsTheNoShowCase(unittest.TestCase):
    """The exported landing page's step 1 must carry the NS dispute id; step 4 must not."""

    def setUp(self):
        export = _export()
        self.assertEqual(0, export["code"], export["stderr"])
        self.fx = export["fx"]
        self.hrefs = _landing_hrefs(
            (export["out"] / "replay" / "index.html").read_text(encoding="utf-8"))

    def test_step_one_targets_the_no_show_dispute(self):
        expected = "/party/status.html?snapshot=after&dispute=%s" % self.fx["ns_dispute"]
        self.assertEqual(expected, self.hrefs[0])

    def test_step_four_keeps_the_full_account_list(self):
        self.assertEqual("/party/status.html?snapshot=after", self.hrefs[3])


class StatusPageDisputeParam(unittest.TestCase):
    """The status page renders one case when ?dispute= matches; falls open otherwise."""

    def test_reads_the_dispute_query_param(self):
        stripped = _stripped()
        self.assertIn("function focusedDispute", stripped)
        helper = _function_body(stripped, "focusedDispute")
        self.assertIn('new URLSearchParams(window.location.search).get("dispute")', helper)
        self.assertIn("focusedDispute()", _load_account_body())

    def test_filters_by_dispute_id_only_on_matching_entries(self):
        body = _load_account_body()
        self.assertIn("entry.dispute_id === focused", body)

    def test_falls_open_when_nothing_matches(self):
        body = _load_account_body()
        self.assertIn("matched.length > 0", body)


if __name__ == "__main__":
    unittest.main()