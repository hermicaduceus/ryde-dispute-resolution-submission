"""Five-step replay walkthrough and the banner back link (the operator ruling 2026-10-15).

the operator confirmed the walkthrough: (1) the no-show case decided alone; (2) NEW — the rider's
view while the detour case waits for a human, landing directly on the BEFORE snapshot
so the judge never flips the banner by hand; (3) the console before the decision; (4)
the console after the human approval; (5) the rider's final view. And every copied page
gains a one-click "Back to the steps" link, because the sol review of the export
(NOTE 5) found no copied-page navigation returns to the landing.

Seams: tools/replay/index.html gains a fifth step and {{RD_DISPUTE_ID}};
tools/export_replay.py builds the waiting step's text from the recorded BEFORE
dispute body (refusing when that body is missing) and fills the new placeholder;
tools/replay/replay-shim.js inserts the back link into the banner it already builds
on every page (replay-only code — zero app bytes). The real-browser pin is
tests/browser/replay_walkthrough.cjs (390px and 1280px).
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from tests import w27_replay_support as w27

REPO = w27.REPO
SHIM = REPO / "tools" / "replay" / "replay-shim.js"
TEMPLATE = REPO / "tools" / "replay" / "index.html"

#: The waiting step's text for the mock fixture (its before dispute body is under_review).
WAITING_STEP = "While a human reviews: the rider's case is still under review"
STEP_5 = "What the rider sees"

_EXPORT: dict = {}


def _export():
    if "out" not in _EXPORT:
        fx = w27.fixture()
        out = w27.scratch_dir() / "site"
        code, stdout, stderr = w27.run_cli(w27.export_args(fx, out, allow_mock=True))
        _EXPORT.update(out=out, code=code, stdout=stdout, stderr=stderr, fx=fx)
    return _EXPORT


def _landing(out) -> list:
    import html
    raw = (Path(out) / "replay" / "index.html").read_text(encoding="utf-8")
    block = re.search(r"<ol>(.*?)</ol>", raw, re.S)
    if block is None:
        raise AssertionError("the landing page has no ordered step list")
    return [(href, html.unescape(text)) for href, text in
            re.findall(r'href="([^"]+)">([^<]+)', block.group(1))]


class FiveStepWalkthrough(unittest.TestCase):
    """The landing walks decide -> wait -> held -> approved -> final view, in that order."""

    def setUp(self):
        export = _export()
        self.assertEqual(0, export["code"], export["stderr"])
        self.fx = export["fx"]
        self.steps = _landing(export["out"])

    def test_five_steps_in_walkthrough_order(self):
        expected = [
            ("/party/status.html?snapshot=after&dispute=%s" % self.fx["ns_dispute"], 1),
            ("/party/status.html?snapshot=before&dispute=%s" % self.fx["rd_dispute"], 2),
            ("/index.html?snapshot=before&run=%s" % self.fx["rd_run"], 3),
            ("/index.html?snapshot=after&run=%s" % self.fx["rd_run"], 4),
            ("/party/status.html?snapshot=after", 5),
        ]
        self.assertEqual(5, len(self.steps), "the landing must list five steps")
        for (href, _text), (expected_href, position) in zip(self.steps, expected):
            self.assertEqual(expected_href, href, "step %d's destination" % position)

    def test_the_waiting_step_states_what_the_rider_waits_for(self):
        self.assertEqual(5, len(self.steps))
        self.assertEqual(WAITING_STEP, self.steps[1][1])

    def test_the_final_step_is_what_the_rider_sees(self):
        self.assertEqual(5, len(self.steps))
        self.assertEqual(STEP_5, self.steps[4][1])


class WaitingStepBuilder(unittest.TestCase):
    """The waiting text is generated from the recorded BEFORE dispute body."""

    def test_the_builder_reads_the_before_dispute_body(self):
        source = (REPO / "tools" / "export_replay.py").read_text(encoding="utf-8")
        code = w27.strip_js_comments(source)
        self.assertIn('def _step_waiting(', code)
        self.assertIn('"GET /api/disputes/%s" % rd_dispute_id', code)
        # The under_review branch is the walkthrough's premise; other statuses fall back.
        waiting = re.search(r"def _step_waiting\(.*?\n(?=def |\Z)", code, re.S)
        self.assertIsNotNone(waiting, "_step_waiting not found in export_replay.py")
        self.assertIn('"under_review"', waiting.group(0))


class BannerBackLink(unittest.TestCase):
    """Every copied page's banner carries a one-click link back to the steps."""

    def test_the_shim_inserts_a_back_link_into_the_banner(self):
        code = w27.strip_js_comments(SHIM.read_text(encoding="utf-8"))
        body = _function_body(code, "insertBanner")
        self.assertIn('id", "replay-back"', body)
        self.assertIn('href", "/replay/"', body)
        self.assertIn("Back to the steps", body)


def _function_body(code: str, name: str) -> str:
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
    raise AssertionError("%s body not found in %s" % (name, SHIM))


if __name__ == "__main__":
    unittest.main()