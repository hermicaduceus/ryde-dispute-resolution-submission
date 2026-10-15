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

import json
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
        self.assertEqual(5, len(self.hrefs))
        self.assertEqual(expected, self.hrefs[0])

    def test_the_final_step_keeps_the_full_account_list(self):
        self.assertEqual(5, len(self.hrefs))
        self.assertEqual("/party/status.html?snapshot=after", self.hrefs[4])


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
        # The matched list must be the list that renders (a `disputes = disputes` no-op
        # mutation passes the other source pins; this literal is what it breaks).
        self.assertIn("disputes = matched;", body)

    def test_falls_open_when_nothing_matches(self):
        body = _load_account_body()
        self.assertIn("matched.length > 0", body)


class MissingNsDisputeIdRefusal(unittest.TestCase):
    """The exporter refuses a snapshot whose NS case file has no usable dispute id.

    gpt-6.1-sol review of f7ec85a (2026-10-15, MINOR): the refusal shipped unpinned —
    removing its guard left 90 relevant tests green. Each shape here must exit 2 with
    exactly this refusal and leave nothing in --out; a dispute_id that is missing,
    empty or not a string is all the refusal exists to catch.
    """

    REFUSAL = "the T-NS0202 run has no dispute_id in its case file"

    def _refuse(self, change):
        fx = w27.copy_fixture()
        for label in w27.LABELS:
            path = Path(fx[label]) / fx["ns_run"] / "case_file.json"
            case = json.loads(path.read_text(encoding="utf-8"))
            change(case)
            path.write_text(json.dumps(case, indent=2) + "\n", encoding="utf-8")
        out = w27.scratch_dir() / "site"
        code, stdout, stderr = w27.run_cli(w27.export_args(fx, out, allow_mock=True))
        return code, stderr, out

    def _assert_refused(self, code, stderr, out):
        self.assertEqual(2, code)
        self.assertEqual([w27.REFUSAL_PREFIX + self.REFUSAL], w27.refusal_lines(stderr))
        self.assertTrue(w27.is_empty_or_absent(out), "the refusal must leave nothing in --out")

    def test_a_missing_dispute_id_is_refused(self):
        self._assert_refused(*self._refuse(lambda case: case.pop("dispute_id")))

    def test_an_empty_dispute_id_is_refused(self):
        self._assert_refused(*self._refuse(lambda case: case.update(dispute_id="")))

    def test_a_non_string_dispute_id_is_refused(self):
        self._assert_refused(*self._refuse(lambda case: case.update(dispute_id=1)))
        self._assert_refused(*self._refuse(lambda case: case.update(dispute_id=["PF-1"])))


if __name__ == "__main__":
    unittest.main()