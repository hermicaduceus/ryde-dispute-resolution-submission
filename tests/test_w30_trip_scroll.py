"""W30 acceptance target: the trip step is a viewport-fit card with its own scroll region.

the operator rulings (2026-10-06), trip step only, rider (ui/party/index.html) AND driver
(ui/party/driver-filing.html) pages, which share ui/party/party.css and ui/party/party.js:

  1. The trip list scrolls inside its own region. Continue/Back stay in normal flow
     directly under it, never over an option (the W15 no-overlap ruling holds).
  2. Updated the operator ruling: the card fills the visible viewport, with Back/Continue at its
     bottom on entry AND after resize. No two-trip floor or page-scroll fallback.
  3. Entering the trip step scrolls the WHOLE card on screen, buttons included, on both
     pages. The rider page used to jump to the page top, which hides the buttons.
  4. the operator's final visual pass removes the bottom fade. The partial next card and scrollbar
     are sufficient cues; the trip region must have no gradient at any scroll position.
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
                self.assertNotEqual("fixed", s.get("position"), "trip card no longer covers the shared header")
                self.assertNotIn("100dvh", s.get("height", ""), "shared frame owns viewport sizing")
                self.assertNotIn("max(", s.get("max-height", ""), "no short-screen page-scroll floor")

    def test_the_vh_fallback_precedes_the_dvh_height(self):
        props = [(p, v) for p, v in _decls(self.css, ".filing-shell:has(#form-steps:not([hidden]))") if p == "height"]
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
                self.assertEqual("start", s.get("align-content"), "few cards do not stretch to fill the list")
                self.assertEqual("max-content", s.get("grid-auto-rows"), "trip cards keep their natural height")

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

    def test_the_trip_region_has_no_bottom_fade(self):
        for width in (320, 390, 1200):
            with self.subTest(width=width):
                s = cascade(self.css, {LIST}, width)
                self.assertIn(s.get("background", "none"), ("none", "transparent"))
                self.assertIn(s.get("background-image", "none"), ("none",))

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

    def test_only_the_ruled_viewport_selectors_are_excluded_from_preservation(self):
        from tests.test_w15_feedback import W30_SELECTORS
        self.assertEqual({STEP, LIST, "#step-category", "#step-trip",
                          "#step-trip > h2", "#step-trip > .hint", "#step-trip > .error",
                          "#step-trip > .step-actions"}, set(W30_SELECTORS),
                         "the W15 preservation exclusion list IS the pin: exactly these selectors")
        present = {s for _, group, _ in rules(self.css) for s in group}
        for selector in W30_SELECTORS:
            self.assertIn(selector, present, "an exclusion for a rule that does not exist is a hole")

    def test_the_removed_fade_has_no_colour_ledger_entry(self):
        ledger = json.loads((REPO / "tests/fixtures/colour_ledger.json").read_text())["ui/party/party.css"]
        self.assertEqual([], [row for row in ledger if row[0] == LIST],
                         "the removed trip-list fade is no longer an approved colour declaration")

    def test_the_console_and_every_other_page_stylesheet_are_untouched(self):
        console = (REPO / "ui" / "styles.css").read_text()
        for token in ("#step-trip", "#trip-options"):
            self.assertNotIn(token, console)

    def test_trip_heading_error_and_buttons_do_not_shrink_with_the_list(self):
        for selector in ("#step-trip > h2", "#step-trip > .hint", "#step-trip > .error",
                         "#step-trip > .step-actions"):
            self.assertEqual("0 0 auto", cascade(self.css, {selector}, 390).get("flex"), selector)

    def test_page_scroll_is_locked_only_while_the_trip_step_is_visible(self):
        self.assertEqual("hidden", cascade(self.css, {"body:has(.filing-shell #form-steps:not([hidden]))"}, 390).get("overflow"))


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
    def test_helper_keeps_its_hidden_step_guard_as_defence_in_depth(self):
        # Request ownership now stops late callbacks before the helper is called.
        # Keep the helper's explicit contract too, without allowing a sibling or
        # comment to satisfy it. This is a source rule, not extra runtime coverage.
        js = _strip_js((PARTY / "party.js").read_text())
        m = re.search(r'function\s+landTripCard\s*\(\s*\)\s*\{', js)
        self.assertIsNotNone(m)
        assert m is not None
        depth, i = 1, m.end()
        while depth and i < len(js):
            depth += (js[i] == "{") - (js[i] == "}")
            i += 1
        body = js[m.end():i - 1]
        self.assertRegex(body, r'if\s*\(\s*stepTrip\.hidden\s*\)\s*\{\s*return\s*;\s*\}')

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
