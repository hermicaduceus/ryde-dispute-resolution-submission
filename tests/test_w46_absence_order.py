"""W46: where the rider no-show form puts the structured absence question.

the operator (2026-10-13, test round): "Did the driver fail to show up at the pickup point?" is a question
about the incident, so it belongs with the other intake questions. The amount box is the closing
request before Send and stays last. Before W46 the question was appended to the end of the form
container, which put it BELOW the amount box.

The contract, in document order inside #details-form on the rider no-show page:

    #description  ->  #question-list  ->  the absence Yes/No  ->  #claim-amount

  * the absence field sits OUTSIDE #question-list (the pinned three-row list keeps exactly its rows,
    tests/test_w43_must_ns6_web_filing.py);
  * there is exactly one absence field after any Back/Continue re-render, a trip switch, or a
    category switch away and back (a stale copy is removed, never left beside the new one);
  * no other page or category gains the field (route filings and the driver page have none).

The always-on tests drive the real ui/party/party.js in Node over a tree built from the REAL page
markup (the W35 lane P harness), with `insertBefore` and `nextSibling` added for this file only, so
the shared harness the other pins depend on is untouched. RealBrowserAbsenceOrder
(needs PUPPETEER_MODULE and BROWSER_EXECUTABLE) runs tests/browser/w46_absence_order.cjs against the
real server and measures the rendered layout at phone and desktop width.

Run: env -u PYTHONPATH python3 -B -m unittest tests.test_w46_absence_order -v
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests import test_w35_P as P
from tests.w23_b2_support import NODE
from tests.w23_support import Server

REPO = Path(__file__).resolve().parent.parent
BROWSER_DIR = REPO / "tests" / "browser"

IN_ORDER = ["description", "question-list", "absence-yes", "claim-amount"]
NO_ABSENCE = ["description", "question-list", "claim-amount"]

# --- the harness: the W35 P harness with insertBefore/nextSibling, and an order-reading tail ---

_REMOVE_CHILD = "  n.removeChild = c =>"
_INSERT_BEFORE = (
    '  Object.defineProperty(n, "nextSibling", { get: () => { const p = n.parentNode;'
    " if (!p) return null; return p.children[p.children.indexOf(n) + 1] || null; } });\n"
    "  n.insertBefore = (c, ref) => { if (c.parentNode) c.parentNode.removeChild(c); c.parentNode = n;"
    " const i = ref ? n.children.indexOf(ref) : -1;"
    " if (i < 0) n.children.push(c); else n.children.splice(i, 0, c); return c; };\n"
)
_SPLIT = "(async () => {"

_TAIL = r"""
(async () => {
  vm.runInNewContext(fs.readFileSync(process.env.PARTY_JS, "utf8"),
    { document: doc, window: { scrollTo() {} }, fetch, Promise, setTimeout, encodeURIComponent, JSON, Array, Number, isFinite, String, Object });
  const ABSENCE = "rider_claims_driver_absent";
  function order() {
    const out = [];
    (function walk(x, inList) {
      if (x.tagName === "#TEXT") return;
      const id = x.getAttribute("id");
      if (id === "description" || id === "question-list" || id === "claim-amount") out.push(id);
      if (x.getAttribute("data-question-key") === ABSENCE && x.getAttribute("data-choice") === "Yes") {
        out.push(inList ? "absence-yes-in-list" : "absence-yes");
      }
      x.children.forEach(c => walk(c, inList || id === "question-list"));
    })(byId("details-form"), false);
    return out;
  }
  const snaps = [];
  for (const op of opts.ops) {
    const [kind, a] = op;
    if (kind === "category") byId("category-options").children[a].click();
    else if (kind === "trip") byId("trip-options").children[a].click();
    else if (kind === "click") byId(a).click();
    await tick(); await tick(); await tick();
    if (kind === "snap") snaps.push({ label: a, order: order() });
  }
  process.stdout.write(JSON.stringify({ snaps }));
})().catch(e => { process.stderr.write(String(e && e.stack || e)); process.exit(1); });
"""


def _harness():
    head = P.HARNESS.split(_SPLIT)[0]
    if head.count(_REMOVE_CHILD) != 1:
        raise AssertionError("the W35 harness no longer has the removeChild line this file extends")
    return head.replace(_REMOVE_CHILD, _INSERT_BEFORE + _REMOVE_CHILD) + _TAIL


def drive(page, ops):
    """{label: document-order token list} for each ["snap", label] in ops."""
    node = shutil.which("node")
    if not node:
        raise AssertionError("Node is required for the W46 page driver")
    env = dict(os.environ, PARTY_JS=str(P.PARTY / "party.js"),
               W35P=json.dumps({"tree": P.page_tree(page), "trips": P.TRIPS, "ops": ops}))
    result = subprocess.run([node, "-e", _harness()], env=env, text=True, capture_output=True, timeout=30)
    if result.returncode:
        raise AssertionError("driven page failed: " + result.stderr[-2000:])
    return {s["label"]: s["order"] for s in json.loads(result.stdout)["snaps"]}


RIDER_ROUTE, RIDER_NO_SHOW = 0, 1


class TheAbsenceQuestionSitsWithTheOtherQuestions(unittest.TestCase):
    def test_it_comes_after_the_intake_questions_and_before_the_amount(self):
        got = drive("index.html", P.to_details(RIDER_NO_SHOW, 0) + [["snap", "first"]])
        self.assertEqual(IN_ORDER, got["first"], got["first"])

    def test_it_stays_outside_the_pinned_question_list(self):
        got = drive("index.html", P.to_details(RIDER_NO_SHOW, 0) + [["snap", "first"]])
        self.assertNotIn("absence-yes-in-list", got["first"], got["first"])

    def test_the_order_survives_a_trip_switch_with_no_second_copy(self):
        ops = (P.to_details(RIDER_NO_SHOW, 0) + [["snap", "first"], ["click", "details-back"],
               ["trip", 1], ["click", "trip-next"], ["snap", "switched"]])
        got = drive("index.html", ops)
        self.assertEqual(IN_ORDER, got["first"], got["first"])
        self.assertEqual(IN_ORDER, got["switched"], got["switched"])

    def test_a_category_switch_away_and_back_rebuilds_it_in_place(self):
        ops = (P.to_details(RIDER_ROUTE, 0) + [["snap", "route"], ["click", "details-back"],
               ["click", "trip-back"], ["category", RIDER_NO_SHOW], ["click", "category-next"],
               ["trip", 0], ["click", "trip-next"], ["snap", "no-show"]])
        got = drive("index.html", ops)
        self.assertEqual(NO_ABSENCE, got["route"], got["route"])
        self.assertEqual(IN_ORDER, got["no-show"], got["no-show"])

    def test_no_other_filing_gains_the_question(self):
        rider_route = drive("index.html", P.to_details(RIDER_ROUTE, 0) + [["snap", "s"]])["s"]
        driver_no_show = drive("driver-filing.html", P.to_details(RIDER_NO_SHOW, 0) + [["snap", "s"]])["s"]
        self.assertEqual(NO_ABSENCE, rider_route, rider_route)
        self.assertEqual(NO_ABSENCE, driver_no_show, driver_no_show)


def _browser_env():
    return os.environ.get("PUPPETEER_MODULE") and os.environ.get("BROWSER_EXECUTABLE")


@unittest.skipUnless(_browser_env(), "PUPPETEER_MODULE and BROWSER_EXECUTABLE are not set")
class RealBrowserAbsenceOrder(unittest.TestCase):
    """tests/browser/w46_absence_order.cjs against the real server, at 390px and 1280px."""

    @classmethod
    def setUpClass(cls):
        cls.server = Server()
        cls.report_dir = Path(tempfile.mkdtemp(prefix="w46-browser-"))
        cls.report = cls.report_dir / "report.json"
        cls.result = subprocess.run([NODE, str(BROWSER_DIR / "w46_absence_order.cjs"),
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

    def test_both_widths_were_measured(self):
        self.assertEqual([390, 1280], [c["width"] for c in self.data.get("cases", [])], self.data)


if __name__ == "__main__":
    unittest.main()
