"""Session sixteen acceptance target: fixes from the glm-5.3 review of sessions twelve and thirteen.

RED until the CodeBuddy build lane ships docs/session-sixteen-brief.md.

Reviewed 2026-09-29 by glm-5.3 (two parallel lanes); every finding below was reproduced
by the operator before it was accepted:

  S12-1 (MAJOR) On the party form, switching a Yes/No answer after typing an elaboration
        submitted the first answer's text under the second answer: "No - <text typed for
        Yes>". Reproduced in headless Brave against the live server. The old tests only
        grepped the handler source, so they could never see it. Pinned here by DRIVING the
        real ui/party/party.js in node (the session-six harness pattern), not by source.
  S12-3 The elaboration box had no accessible name (placeholder only).
  S12-4 The selected button's non-colour cues (3px border, weight 600) were unpinned.
  S13-6 Party-page buttons had no :focus-visible rule, so keyboard focus showed the
        browser's blue ring.
  S13-5 The console's :target pulse still flashed the retired navy blue.
  S13-7 Two empty .citation-policy rules were dead CSS a test "protected".
  S13-9 Font weights 580/650/750/800 are not loaded (Poppins 400/600/700 only).
  S13-1/2/3 (test weakness, MAJOR) Colour pins named selectors, so an appended rule, an
        unlisted status rule or an accent-token swap changed rendered colour with the suite
        green (15 of 22 mutations survived). Closed by the colour ledger below: every
        colour declaration in both stylesheets, in source order with duplicates kept, must
        match tests/fixtures/colour_ledger.json exactly. A deliberate colour change is
        re-baselined with `python3 tools/colour_ledger.py --write`.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from tools import colour_ledger  # noqa: E402

PARTY_JS = REPO / "ui" / "party" / "party.js"
PARTY_CSS = REPO / "ui" / "party" / "party.css"
CONSOLE_CSS = REPO / "ui" / "styles.css"


def _css(path: Path) -> str:
    return re.sub(r"/\*.*?\*/", "", path.read_text(encoding="utf-8"), flags=re.S).lower()


def _rules(css: str):
    """(selector list, declarations) for every rule, in order, duplicates kept."""
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        selectors = [" ".join(s.split()) for s in m.group(1).split(",")]
        decls = [(k.strip(), " ".join(v.split())) for k, v in re.findall(r"([\w-]+)\s*:\s*([^;]+);?", m.group(2))]
        yield selectors, decls


def _last(css: str, selector: str, prop: str):
    """The value the cascade ends on for `prop` across every rule naming `selector`
    (same specificity, so the last declaration wins)."""
    value = None
    for selectors, decls in _rules(css):
        if selector in selectors:
            for k, v in decls:
                if k == prop:
                    value = v
    return value


# --------------------------------------------------------------- party.js driver

_HARNESS = r"""
const fs = require("fs"); const vm = require("vm");
function node(tag) {
  const n = { tagName: String(tag).toUpperCase(), children: [], hidden: false, disabled: false,
    type: "", value: "", rows: 0, placeholder: "", htmlFor: "", _attrs: {}, _cls: [], _l: {} };
  let own = "";
  Object.defineProperty(n, "textContent", { get: () => own + n.children.map(c => c.textContent).join(""),
    set: v => { own = v == null ? "" : String(v); n.children = []; } });
  Object.defineProperty(n, "className", { get: () => n._cls.join(" "),
    set: v => { n._cls = String(v).split(/\s+/).filter(Boolean); } });
  Object.defineProperty(n, "id", { get: () => n._attrs.id || "", set: v => { n._attrs.id = String(v); } });
  Object.defineProperty(n, "role", { get: () => n._attrs.role || null, set: v => { n._attrs.role = String(v); } });
  n.classList = { add: c => { if (!n._cls.includes(c)) n._cls.push(c); },
    remove: c => { n._cls = n._cls.filter(x => x !== c); }, contains: c => n._cls.includes(c) };
  n.dataset = new Proxy({}, {
    set: (t, k, v) => { n._attrs["data-" + k.replace(/[A-Z]/g, c => "-" + c.toLowerCase())] = String(v); return true; },
    get: (t, k) => n._attrs["data-" + String(k).replace(/[A-Z]/g, c => "-" + c.toLowerCase())] });
  n.setAttribute = (k, v) => { n._attrs[k] = String(v); };
  n.getAttribute = k => (k in n._attrs ? n._attrs[k] : null);
  n.appendChild = c => { n.children.push(c); return c; };
  n.removeChild = c => { n.children = n.children.filter(x => x !== c); return c; };
  Object.defineProperty(n, "firstChild", { get: () => n.children[0] || null });
  n.addEventListener = (e, h) => { (n._l[e] = n._l[e] || []).push(h); };
  n.fire = e => (n._l[e] || []).forEach(h => h({ preventDefault() {}, target: n }));
  n.click = () => n.fire("click");
  n.querySelectorAll = sel => {
    const parts = sel.match(/^([a-z]+)?((?:\.[\w-]+)*)((?:\[[\w-]+(?:="[^"]*")?\])*)$/i);
    if (!parts) throw new Error("unsupported selector " + sel);
    const tag = parts[1], classes = (parts[2] || "").split(".").filter(Boolean);
    const attrs = [...(parts[3] || "").matchAll(/\[([\w-]+)(?:="([^"]*)")?\]/g)];
    const out = [];
    (function walk(x) { x.children.forEach(c => {
      if ((!tag || c.tagName === tag.toUpperCase()) && classes.every(k => c.classList.contains(k))
          && attrs.every(a => a[2] === undefined ? c.getAttribute(a[1]) !== null : c.getAttribute(a[1]) === a[2])) out.push(c);
      walk(c); }); })(n);
    return out;
  };
  n.querySelector = sel => n.querySelectorAll(sel)[0] || null;
  n.scrollIntoView = () => {};
  return n;
}
const ids = {};
const doc = { getElementById: id => ids[id] || (ids[id] = node("div")), createElement: t => node(t) };
const posted = [];
const fetch = (url, opts) => {
  if (url.indexOf("/api/trips") === 0) return Promise.resolve({ ok: true, json: () => Promise.resolve(
    { trips: [{ trip_id: "TRIP-X", label: "A trip", date: "2026-09-01", kind_label: "Ride", fare_sgd: 10, charge_label: "fare" }] }) });
  posted.push(JSON.parse(opts.body));
  return new Promise(() => {});
};
const tick = () => new Promise(r => setTimeout(r, 0));
(async () => {
  vm.runInNewContext(fs.readFileSync(process.env.PARTY_JS, "utf8"),
    { document: doc, window: { scrollTo() {} }, fetch, Promise, setTimeout, encodeURIComponent, JSON, Array, Number, isFinite, String });
  const category = ids["category-options"].children.find(c => c.textContent === "My trip went the wrong way");
  category.click(); ids["category-next"].click(); await tick(); await tick();
  ids["trip-options"].children[0].click(); ids["trip-next"].click();
  const list = ids["question-list"];
  const steps = JSON.parse(process.env.STEPS);
  for (const [op, key, arg] of steps) {
    if (op === "click") list.querySelector('.choice-button[data-question-key="' + key + '"][data-choice="' + arg + '"]').click();
    if (op === "type") list.querySelector('textarea[data-elaborate-for="' + key + '"]').value = arg;
  }
  const boxes = {};
  list.querySelectorAll("textarea[data-elaborate-for]").forEach(b => {
    boxes[b.getAttribute("data-elaborate-for")] = { ariaLabel: b.getAttribute("aria-label"),
      labelledBy: b.getAttribute("aria-labelledby"), id: b.id, hidden: b.hidden };
  });
  const labels = {};
  list.querySelectorAll("label").forEach(l => { labels[l.id] = l.textContent; });
  doc.getElementById("description").value = "The driver took a long detour.";
  doc.getElementById("claim-amount").value = "";
  doc.getElementById("details-form").fire("submit"); await tick();
  process.stdout.write(JSON.stringify({ answers: posted.length ? posted[0].answers : null, boxes, labels }));
})().catch(e => { process.stderr.write(String(e.stack || e)); process.exit(1); });
"""


def _drive(steps):
    node = shutil.which("node")
    if not node:
        raise AssertionError("Node is required for the party-form behavioural pins")
    env = dict(os.environ, PARTY_JS=str(PARTY_JS), STEPS=json.dumps(steps))
    result = subprocess.run([node, "-e", _HARNESS], env=env, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise AssertionError("party.js harness failed: " + result.stderr)
    return json.loads(result.stdout)


class S12ChoiceSwitchBehaviour(unittest.TestCase):
    """S12-1: the elaboration belongs to the answer it was typed for."""

    def test_harness_sanity_untouched_questions_submit_blank(self):
        out = _drive([])
        self.assertEqual({"expected_route": "", "was_route_agreed": "", "asked_driver_to_stop": "",
                          "safety_concern": ""}, out["answers"])

    def test_elaboration_typed_for_one_answer_is_kept_with_it(self):
        out = _drive([["click", "safety_concern", "Yes"], ["type", "safety_concern", "He was shouting"]])
        self.assertEqual("Yes - He was shouting", out["answers"]["safety_concern"])

    def test_switching_the_answer_drops_the_old_elaboration(self):
        out = _drive([["click", "safety_concern", "Yes"], ["type", "safety_concern", "He was shouting"],
                      ["click", "safety_concern", "No"]])
        self.assertEqual("No", out["answers"]["safety_concern"],
                         "text typed for Yes must never be submitted as the reason for No")

    def test_switching_back_does_not_resurrect_the_text(self):
        out = _drive([["click", "was_route_agreed", "No"], ["type", "was_route_agreed", "Never asked"],
                      ["click", "was_route_agreed", "Yes"], ["click", "was_route_agreed", "No"]])
        self.assertEqual("No", out["answers"]["was_route_agreed"])

    def test_text_typed_after_the_switch_is_kept(self):
        out = _drive([["click", "safety_concern", "Yes"], ["type", "safety_concern", "old"],
                      ["click", "safety_concern", "No"], ["type", "safety_concern", "I felt fine"]])
        self.assertEqual("No - I felt fine", out["answers"]["safety_concern"])

    def test_clicking_the_selected_answer_again_keeps_the_text(self):
        out = _drive([["click", "asked_driver_to_stop", "Yes"], ["type", "asked_driver_to_stop", "At the ATM"],
                      ["click", "asked_driver_to_stop", "Yes"]])
        self.assertEqual("Yes - At the ATM", out["answers"]["asked_driver_to_stop"],
                         "re-clicking the chosen answer is not a switch and must not wipe the text")

    def test_a_switch_on_one_question_leaves_the_others_alone(self):
        out = _drive([["click", "was_route_agreed", "Yes"], ["type", "was_route_agreed", "We agreed"],
                      ["click", "safety_concern", "Yes"], ["type", "safety_concern", "x"],
                      ["click", "safety_concern", "No"]])
        self.assertEqual("Yes - We agreed", out["answers"]["was_route_agreed"])
        self.assertEqual("No", out["answers"]["safety_concern"])


class S12ElaborationBoxName(unittest.TestCase):
    """S12-3: the box a Yes/No answer reveals has a programmatic name naming its question."""

    def test_every_elaboration_box_is_named_after_its_question(self):
        out = _drive([])
        self.assertEqual({"was_route_agreed", "asked_driver_to_stop", "safety_concern"}, set(out["boxes"]))
        for key, box in out["boxes"].items():
            with self.subTest(key=key):
                question = out["labels"]["label-" + key]
                self.assertTrue(question)
                name = box["ariaLabel"] or ""
                self.assertIn(question, name, "the box's accessible name must carry the question text")
                self.assertIn("tell us more", name.lower())


class S12SelectedStateCues(unittest.TestCase):
    """S12-4: selection is visible without colour, and a later rule may not undo it."""

    def test_selected_button_keeps_a_thicker_border_and_heavier_weight(self):
        css = _css(PARTY_CSS)
        self.assertEqual("3px", _last(css, ".choice-button.selected", "border-width"))
        self.assertEqual("600", _last(css, ".choice-button.selected", "font-weight"))
        self.assertEqual("var(--accent)", _last(css, ".choice-button.selected", "border-color"))


class S13PartyKeyboardFocus(unittest.TestCase):
    """S13-6: keyboard focus on party-page buttons is the brand ring, not the UA blue."""

    def test_party_buttons_have_an_accent_focus_ring(self):
        css = _css(PARTY_CSS)
        outline = _last(css, "button:focus-visible", "outline")
        self.assertIsNotNone(outline, "party.css needs a button:focus-visible rule")
        self.assertRegex(outline, r"^\d+px solid var\(--accent\)$")


class S13ConsoleLeftovers(unittest.TestCase):
    def test_target_pulse_carries_no_hue(self):
        css = _css(CONSOLE_CSS)
        m = re.search(r"@keyframes\s+target-pulse\s*\{((?:[^{}]*\{[^{}]*\})*)\s*\}", css)
        self.assertIsNotNone(m, "the :target pulse keyframes must still exist")
        body = m.group(1)
        self.assertNotIn("42, 99, 140", body, "the retired navy must be gone from the pulse")
        self.assertIsNone(re.search(r"var\(--(accent|amber|green|blue|red)[\w-]*\)", body),
                          "a jump highlight is not a status and must not use a status or brand token")
        for rgb in re.findall(r"rgba?\(([^)]*)\)", body):
            ch = [float(x) for x in re.split(r"[ ,/]+", rgb.strip())[:3]]
            self.assertLessEqual(max(ch) - min(ch), 8, "the pulse must be a neutral tint, got rgb(%s)" % rgb)

    def test_no_empty_rules_in_either_stylesheet(self):
        for path in (CONSOLE_CSS, PARTY_CSS):
            empty = [m.group(1).strip() for m in re.finditer(r"([^{}]+)\{\s*\}", _css(path))]
            self.assertEqual([], empty, "%s has empty rules" % path.name)

    def test_console_font_weights_are_ones_the_page_loads(self):
        weights = set(re.findall(r"font-weight:\s*([^;]+);", _css(CONSOLE_CSS)))
        self.assertLessEqual(weights, {"400", "600", "700"},
                             "index.html loads Poppins 400/600/700 only; got %s" % sorted(weights))


class ColourLedger(unittest.TestCase):
    """S13-1/2/3: every colour declaration is accounted for, not just the named ones."""

    def test_the_ledger_covers_the_stylesheets(self):
        data = colour_ledger.build()
        self.assertGreater(len(data["ui/styles.css"]), 150)
        self.assertGreater(len(data["ui/party/party.css"]), 30)
        self.assertIn([".event-internal .event-type, .event-internal .event-payload-ref", "color", "var(--amber)"],
                      data["ui/styles.css"], "the parser must see the withheld event row's amber")

    def test_colour_declarations_match_the_approved_ledger(self):
        approved = json.loads((REPO / "tests" / "fixtures" / "colour_ledger.json").read_text(encoding="utf-8"))
        current = colour_ledger.build()
        for sheet in colour_ledger.SHEETS:
            with self.subTest(sheet=sheet):
                self.assertEqual(approved[sheet], current[sheet],
                                 "a colour declaration changed, moved or appeared in %s; if the operator "
                                 "approved it, re-baseline with `python3 tools/colour_ledger.py --write`" % sheet)


if __name__ == "__main__":
    unittest.main()
