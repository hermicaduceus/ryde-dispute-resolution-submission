"""W30 acceptance target: the trip step is a viewport-fit card with its own scroll region.

the operator rulings (2026-10-06), trip step only, rider (ui/party/index.html) AND driver
(ui/party/driver-filing.html) pages, which share ui/party/party.css and ui/party/party.js:

  1. The trip list scrolls inside its own region. Continue/Back stay in normal flow
     directly under it, never over an option (the W15 no-overlap ruling holds).
  2. The whole card (heading, hint, list, buttons) never exceeds the viewport height,
     with a floor of about two trip cards: a very short screen falls back to page scroll.
  3. Entering the trip step scrolls the WHOLE card on screen, buttons included, on both
     pages. The rider page used to jump to the page top, which hides the buttons.
  4. A bottom fade hints that the list scrolls. A next-card peek is not guaranteed, so the
     fade and the scrollable state are pinned, not a peek.
  Hover lift and selected shadow must not clip at the region edge.

HTML is frozen, so the contract uses the ids the pages already carry: #step-trip,
#trip-options, #step-category and the in-card .step-actions bar. Source-level pins only
(comments stripped, rules read by exact selector, handler bodies scoped); real geometry,
hit-testing, the fade pixels and the keyboard order are the browser contract in
tests/browser/w30_trip_scroll.cjs, run by the parent.

Run: /usr/bin/python3 -m unittest tests.test_w30_trip_scroll
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import unittest
from pathlib import Path

from tests.test_w15_feedback import cascade, rules, stripped
from tests.w16_support import DOM

REPO = Path(__file__).resolve().parent.parent
PARTY = REPO / "ui" / "party"
STEP = "#step-trip:not([hidden])"
LIST = "#step-trip #trip-options"
LANDING = {"#step-category", "#step-trip"}


def _decls(css, selector):
    """Every (prop, value) the stylesheet declares for exactly this selector, in order."""
    out = []
    for context, selectors, decls in rules(css):
        if selector in selectors and not context:
            out.extend(decls)
    return out


def _body(js, element_id):
    m = re.search(r'getElementById\("%s"\)\s*\.\s*addEventListener\(\s*"click"\s*,\s*'
                  r"function\s*\([^)]*\)\s*\{" % re.escape(element_id), js)
    assert m, "no click handler for #" + element_id
    depth, i = 1, m.end()
    while depth and i < len(js):
        depth += (js[i] == "{") - (js[i] == "}")
        i += 1
    return js[m.end():i - 1]


def _strip_js(js):
    js = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
    return re.sub(r"(?m)^\s*//.*$", "", js)


class TripRegionCss(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.css = stripped((PARTY / "party.css").read_text())

    def test_the_trip_card_is_a_flex_column_that_cannot_outgrow_the_screen(self):
        for width in (320, 390, 1200):
            with self.subTest(width=width):
                s = cascade(self.css, {STEP}, width)
                self.assertEqual("flex", s.get("display"))
                self.assertEqual("column", s.get("flex-direction"))
                self.assertRegex(s.get("max-height", ""),
                                 r"^max\(calc\(100dvh - [\d.]+rem\), [\d.]+rem\)$",
                                 "viewport-fit height with a rem floor, in dynamic viewport units")

    def test_the_vh_fallback_precedes_the_dvh_height(self):
        props = [(p, v) for p, v in _decls(self.css, STEP) if p == "max-height"]
        self.assertEqual(2, len(props), "one vh fallback, then the dvh declaration")
        self.assertIn("100vh", props[0][1])
        self.assertIn("100dvh", props[1][1])

    def test_the_list_is_its_own_scroll_region_that_may_shrink(self):
        for width in (320, 390, 1200):
            with self.subTest(width=width):
                s = cascade(self.css, {LIST}, width)
                self.assertEqual("auto", s.get("overflow-y"))
                self.assertEqual("1 1 auto", s.get("flex"))
                self.assertIn("min-height", s)
                self.assertEqual(0.0, float(re.sub(r"[a-z%]*$", "", s["min-height"])),
                                 "min-height: 0 lets the list shrink inside the card")
                self.assertEqual("contain", s.get("overscroll-behavior"),
                                 "a flick at the end of the list must not scroll the page")

    def test_the_region_has_room_for_the_hover_lift_and_selected_border(self):
        s = cascade(self.css, {LIST}, 390)
        for side in ("top", "right", "bottom", "left"):
            self.assertRegex(s.get("padding-" + side, ""), r"^[\d.]+rem$", "padding-" + side)
            self.assertGreaterEqual(float(s["padding-" + side][:-3]), 0.5,
                                    "region padding keeps lifted/selected cards unclipped")
        # Negative margin of the same size keeps the cards aligned with the card's content box.
        for side in ("top", "bottom"):
            self.assertEqual("-" + s["padding-" + side], s.get("margin-" + side),
                             "region padding is cancelled by an equal negative margin")

    def test_the_bottom_fade_is_a_scroll_aware_gradient_made_of_tokens(self):
        value = cascade(self.css, {LIST}, 390).get("background", "")
        self.assertGreaterEqual(value.count("linear-gradient("), 2, "a fade and a cover")
        self.assertRegex(value, r"\blocal\b", "a card-coloured cover that scrolls with the content")
        self.assertRegex(value, r"\bscroll\b", "a fade fixed to the region edge")
        self.assertNotRegex(value, r"#[0-9a-f]{3,8}\b|rgba?\(|hsla?\(",
                            "colour tokens only (var(--card), var(--line))")
        self.assertIn("var(--line)", value)
        self.assertIn("var(--card)", value)

    def test_landing_steps_keep_a_margin_so_the_card_never_sits_flush(self):
        s = cascade(self.css, LANDING, 390)
        self.assertEqual(2, len(s.get("scroll-margin", "").split()), s)
        top, side = s["scroll-margin"].split()
        self.assertRegex(top, r"^[\d.]+rem$")
        self.assertGreaterEqual(float(top[:-3]), 1.0)

    def test_the_action_bar_stays_normal_flow_outside_the_scroll_region(self):
        for page in ("index.html", "driver-filing.html"):
            html = (PARTY / page).read_text()
            section = re.search(r'<section class="step" id="step-trip".*?</section>', html, re.S).group(0)
            list_at = section.index('id="trip-options"')
            bar_at = section.index('class="step-actions"')
            self.assertLess(list_at, bar_at, page)
            # The list element is closed before the bar opens, so the bar is a sibling, not a child.
            between = section[list_at:bar_at]
            self.assertIn("</div>", between, page)
        sa = cascade(self.css, {".step-actions"}, 390)
        self.assertEqual("static", sa.get("position"))

    def test_only_the_three_ruled_rules_four_selectors_were_added_to_the_party_sheet(self):
        from tests.test_w15_feedback import W30_SELECTORS
        self.assertEqual({STEP, LIST, "#step-category", "#step-trip"}, set(W30_SELECTORS),
                         "the W15 preservation exclusion list IS the pin: exactly these selectors")
        present = {s for _, group, _ in rules(self.css) for s in group}
        for selector in W30_SELECTORS:
            self.assertIn(selector, present, "an exclusion for a rule that does not exist is a hole")

    def test_the_new_colours_are_tokens_in_the_approved_ledger(self):
        ledger = json.loads((REPO / "tests/fixtures/colour_ledger.json").read_text())["ui/party/party.css"]
        mine = [row for row in ledger if row[0] == LIST]
        self.assertTrue(mine, "the fade's background is approved in the colour ledger")
        for _, prop, value in mine:
            self.assertEqual("background", prop)
            self.assertNotRegex(value, r"#[0-9a-f]{3,8}\b|rgba?\(|hsla?\(")

    def test_the_console_and_every_other_page_stylesheet_are_untouched(self):
        console = (REPO / "ui" / "styles.css").read_text()
        for token in ("#step-trip", "#trip-options"):
            self.assertNotIn(token, console)


# ------------------------------------------------------------------ driven page

# The shared DOM gives every node a no-op scrollIntoView; this driver puts a recorder in AFTER
# it, so the recorder wins. The assert keeps a changed shared DOM from silently recording nothing.
_NODE_END = "  return n;\n}\nconst ids = {};"
assert _NODE_END in DOM, "shared DOM no longer ends its node factory where the W30 driver hooks in"
SCROLL_DRIVER = DOM.replace(
    _NODE_END,
    "  n.scrollIntoView = function (o) { LOG.push(snap('scrollIntoView', Object.keys(ids).find(k => ids[k] === n) || null, o)); };\n"
    "  return n;\n}\nconst LOG = [];\nconst ids = {};", 1) + r'''
function snap(op, id, o) {
  const trips = ids["trip-options"].children;
  return { op, id, block: o && o.block,
    vector: ["step-category", "step-trip", "step-details"].map(s => !ids[s].hidden),
    cards: trips.filter(c => c.classList.contains("trip-card")).length,
    loading: trips.filter(c => c.classList.contains("loading")).length };
}
const opts = JSON.parse(process.env.DRIVE);
if (opts.role) doc.getElementById("form-steps").setAttribute("data-filed-by", opts.role);
["step-trip", "step-details", "outcome", "outcome-questions", "category-error", "trip-error",
 "details-error", "answers-error"].forEach(id => doc.getElementById(id).hidden = true);
const pending = [];
const trips = opts.trips === undefined ? 3 : opts.trips;
const fetch = (url, o) => {
  const body = { trips: Array.from({ length: trips }, (_, i) => ({ trip_id: "T-" + i, label: "Trip " + i,
    date: "2026", kind_label: "Ride", fare_sgd: 6.61, charge_label: "fee" })) };
  const done = () => Promise.resolve({ ok: true, json: () => Promise.resolve(body) });
  if (opts.hold) return new Promise(res => pending.push(() => res(done())));
  return done();
};
const tick = () => new Promise(r => setTimeout(r, 0));
(async () => {
  vm.runInNewContext(fs.readFileSync(process.env.PARTY_JS, "utf8"), { document: doc,
    window: { scrollTo(x, y) { LOG.push(snap("scrollTo", null, null)); LOG[LOG.length - 1].at = [x, y]; } },
    fetch, Promise, setTimeout, encodeURIComponent, JSON, Array, Number, isFinite, String });
  const checkpoints = {};
  for (const step of opts.script) {
    if (step === "category") ids["category-options"].children[0].click();
    if (step === "next") ids["category-next"].click();
    if (step === "release") pending.splice(0).forEach(f => f());
    if (step === "pick") ids["trip-options"].children[0].click();
    if (step === "trip-next") ids["trip-next"].click();
    if (step === "trip-back") ids["trip-back"].click();
    if (step === "details-back") ids["details-back"].click();
    if (step.startsWith("mark:")) checkpoints[step.slice(5)] = LOG.length;
    await tick(); await tick();
  }
  process.stdout.write(JSON.stringify({ log: LOG, checkpoints }));
})().catch(e => { process.stderr.write(String(e.stack || e)); process.exit(1); });
'''


def drive(script, role=None, **options):
    node = shutil.which("node")
    if not node:
        raise AssertionError("Node required")
    env = dict(os.environ, PARTY_JS=str(PARTY / "party.js"),
               DRIVE=json.dumps(dict(role=role, script=script, **options)))
    r = subprocess.run([node, "-e", SCROLL_DRIVER], env=env, text=True, capture_output=True, timeout=20)
    if r.returncode:
        raise AssertionError("driven page failed: " + r.stderr)
    return json.loads(r.stdout)


def into_view(out, element, after=0):
    return [e for e in out["log"][after:] if e["op"] == "scrollIntoView" and e["id"] == element]


class EnteringTheTripStep(unittest.TestCase):
    def test_the_card_is_brought_on_screen_once_the_list_has_rendered(self):
        for role in (None, "driver"):
            with self.subTest(role=role):
                out = drive(["category", "next"], role)
                landed = into_view(out, "step-trip")
                self.assertEqual(1, len(landed), out["log"])
                self.assertEqual("start", landed[0]["block"])
                self.assertEqual([False, True, False], landed[0]["vector"])
                self.assertEqual((3, 0), (landed[0]["cards"], landed[0]["loading"]),
                                 "scrolling to the 'Loading trips' placeholder lands on the wrong height")

    def test_the_page_no_longer_jumps_to_the_top_on_the_way_in(self):
        for role in (None, "driver"):
            with self.subTest(role=role):
                out = drive(["category", "next"], role)
                self.assertEqual([], [e for e in out["log"] if e["op"] == "scrollTo"],
                                 "a jump to the page top hides the buttons on a phone")

    def test_an_empty_list_still_lands_the_card(self):
        out = drive(["category", "next"], trips=0)
        landed = into_view(out, "step-trip")
        self.assertEqual(1, len(landed))
        self.assertEqual([False, True, False], landed[0]["vector"])

    def test_a_slow_response_after_back_must_not_scroll_a_hidden_step(self):
        for role in (None, "driver"):
            with self.subTest(role=role):
                out = drive(["category", "next", "trip-back", "release"], role, hold=True)
                self.assertEqual([], into_view(out, "step-trip"),
                                 "the late response would jump the page while the rider is on step 1")
                back = into_view(out, "step-category")
                self.assertEqual(1, len(back))
                self.assertEqual([True, False, False], back[0]["vector"])


class LeavingAndReturning(unittest.TestCase):
    def test_back_from_the_trip_step_lands_the_category_card(self):
        for role in (None, "driver"):
            with self.subTest(role=role):
                out = drive(["category", "next", "trip-back"], role)
                back = into_view(out, "step-category")
                self.assertEqual(1, len(back), out["log"])
                self.assertEqual("start", back[0]["block"])
                self.assertEqual([True, False, False], back[0]["vector"])

    def test_back_from_details_lands_the_trip_card_again_after_the_list_renders(self):
        for role in (None, "driver"):
            with self.subTest(role=role):
                out = drive(["category", "next", "pick", "trip-next", "mark:details", "details-back"], role)
                again = into_view(out, "step-trip", out["checkpoints"]["details"])
                self.assertEqual(1, len(again), out["log"])
                self.assertEqual([False, True, False], again[0]["vector"])
                self.assertEqual(3, again[0]["cards"])

    def test_continuing_to_details_still_returns_to_the_page_top(self):
        out = drive(["category", "next", "pick", "mark:before", "trip-next"])
        tops = [e for e in out["log"][out["checkpoints"]["before"]:] if e["op"] == "scrollTo"]
        self.assertEqual(1, len(tops))
        self.assertEqual([0, 0], tops[0]["at"])
        self.assertEqual([False, False, True], tops[0]["vector"])
        self.assertEqual([], into_view(out, "step-details"))


class TheOldScrollToTopOnCategoryContinueIsGone(unittest.TestCase):
    def test_category_continue_handler_has_no_scroll_to_top(self):
        body = _strip_js(_body((PARTY / "party.js").read_text(), "category-next"))
        self.assertNotRegex(body, r"scrollTo\s*\(", "superseded by landing the whole trip card (W30)")
        self.assertIn("hide(stepCategory)", body)
        self.assertIn("show(stepTrip)", body)


if __name__ == "__main__":
    unittest.main()
