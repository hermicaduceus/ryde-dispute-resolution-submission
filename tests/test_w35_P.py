"""W35 lane P: the party pages' UI/UX round (the operator findings P1-P4 plus the contrast fix).

P1  Status page: on a screen at least 654px tall the page header and the "Look up a reference
    number" box stay put and only the "My disputes" list scrolls, inside its own region. Below
    654px the page scrolls normally (measured: below 654px a 320px phone's list would sit on its
    8rem floor, and from 651px the header clips). A lookup result takes the room above the list (the list
    keeps 8rem, the header 4.5rem) and only then scrolls, inside the lookup box.
    The geometry is a real-browser contract: tests/browser/w35_P_status.cjs.
P2+P3  Step 3 opens with a read-only summary ("You are disputing"): the step 1 category label and
    the step 2 trip card, rendered by the same code as the card. It updates whenever the party
    goes Back and changes either. It never pushes Send/Back below the fold
    (tests/browser/w35_P_filing.cjs).
P4  "Send my dispute" owns a pending state: disabled + "Sending…", Back disabled, a spinner
    (aria-hidden, still under reduced motion), and a fixed polite status line. A failure
    restores both buttons, clears the line and shows the existing error. No artificial delay.
Contrast  --accent-strong #CC2852 for small pink text and white-on-pink fills; #E93864 stays for
    borders, outlines and decoration. Measured in the browser: tests/browser/w35_P_contrast.cjs.

The behaviour tests run party.js in a small fake DOM built from the REAL page markup (both
filing pages), so a missing element or a wrong order in the HTML fails here and not only in a
browser. Each fetch the page makes is answered by the test, so the pending state is held open
deterministically: nothing in the app is delayed.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import unittest
from html.parser import HTMLParser
from pathlib import Path

from tests.test_w15_feedback import cascade, rules, stripped

REPO = Path(__file__).resolve().parent.parent
PARTY = REPO / "ui" / "party"
FILING_PAGES = ("index.html", "driver-filing.html")

SUMMARY_LABEL = "You are disputing"
SUBMIT_LABEL = "Send my dispute"
SENDING_LABEL = "Sending\u2026"
SENDING_STATUS = "Sending your dispute. This can take a little while, so please keep this page open."
RIDER_CATEGORIES = ["My trip went the wrong way", "I was charged for a trip that did not happen",
                    "Property damage or a mess left behind", "A safety incident", "Something else"]
DRIVER_CATEGORIES = ["A question about the route I took", "A no-show or waiting fee",
                     "A cleaning fee or damage report", "A safety incident", "Something else"]

# Two trips per category, with every field the card renders; the second has no fare, so the
# charge suffix is absent (the card's own rule).
TRIPS = {
    "route_deviation": [
        {"trip_id": "T-RD9001", "label": "Dhoby Ghaut to Hougang Avenue 5", "date": "2026-09-14",
         "kind_label": "Route complaint", "fare_sgd": 18.63, "charge_label": "fare"},
        {"trip_id": "T-RD9002", "label": "Dhoby Ghaut to Buangkok East Drive", "date": "2026-09-15",
         "kind_label": "Route complaint", "fare_sgd": None, "charge_label": None},
    ],
    "no_show_charge": [
        {"trip_id": "T-NS9001", "label": "Orchard Boulevard to Novena Square", "date": "2026-09-14",
         "kind_label": "No-show charge", "fare_sgd": 6.61, "charge_label": "cancellation fee"},
        {"trip_id": "T-NS9002", "label": "Tanjong Pagar to Bugis", "date": "2026-09-16",
         "kind_label": "No-show charge", "fare_sgd": 5, "charge_label": "cancellation fee"},
    ],
}
TRIP_TEXT = {
    "T-RD9001": ["Dhoby Ghaut to Hougang Avenue 5", "2026-09-14 · Route complaint",
                 "Trip T-RD9001 · SGD 18.63 fare"],
    "T-RD9002": ["Dhoby Ghaut to Buangkok East Drive", "2026-09-15 · Route complaint", "Trip T-RD9002"],
    "T-NS9001": ["Orchard Boulevard to Novena Square", "2026-09-14 · No-show charge",
                 "Trip T-NS9001 · SGD 6.61 cancellation fee"],
    "T-NS9002": ["Tanjong Pagar to Bugis", "2026-09-16 · No-show charge",
                 "Trip T-NS9002 · SGD 5.00 cancellation fee"],
}


# ------------------------------------------------------------------ markup -> fake DOM


class _Tree(HTMLParser):
    """The page body as a JSON tree: {tag, attrs, children} and text nodes {text}."""

    VOID = {"meta", "link", "input", "br", "hr", "img"}

    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.root = {"tag": "#root", "attrs": {}, "children": []}
        self.stack = [self.root]
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        node = {"tag": tag, "attrs": {k: ("" if v is None else v) for k, v in attrs}, "children": []}
        self.stack[-1]["children"].append(node)
        if tag not in self.VOID:
            self.stack.append(node)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i]["tag"] == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        if data.strip():
            self.stack[-1]["children"].append({"text": data})


def page_tree(page):
    return _Tree((PARTY / page).read_text(encoding="utf-8")).root


HARNESS = r"""
const fs = require("fs"); const vm = require("vm");
const ids = {};
function textNode(t) {
  return { tagName: "#TEXT", children: [], get textContent() { return t; }, classList: { contains: () => false } };
}
function node(tag) {
  const n = { tagName: String(tag).toUpperCase(), children: [], hidden: false, disabled: false,
    type: "", value: "", rows: 0, placeholder: "", _attrs: {}, _cls: [], _l: {}, parentNode: null };
  Object.defineProperty(n, "textContent", { get: () => n.children.map(c => c.textContent).join(""),
    set: v => { n.children = []; const s = v == null ? "" : String(v); if (s) n.children.push(textNode(s)); } });
  Object.defineProperty(n, "className", { get: () => n._cls.join(" "),
    set: v => { n._cls = String(v).split(/\s+/).filter(Boolean); } });
  Object.defineProperty(n, "id", { get: () => n._attrs.id || "", set: v => { n._attrs.id = String(v); ids[String(v)] = n; } });
  Object.defineProperty(n, "role", { get: () => n._attrs.role || null, set: v => { n._attrs.role = String(v); } });
  Object.defineProperty(n, "htmlFor", { get: () => n._attrs.for || "", set: v => { n._attrs.for = String(v); } });
  Object.defineProperty(n, "firstChild", { get: () => n.children[0] || null });
  n.classList = { add: c => { if (!n._cls.includes(c)) n._cls.push(c); },
    remove: c => { n._cls = n._cls.filter(x => x !== c); }, contains: c => n._cls.includes(c) };
  n.dataset = new Proxy({}, {
    set: (t, k, v) => { n._attrs["data-" + k.replace(/[A-Z]/g, c => "-" + c.toLowerCase())] = String(v); return true; },
    get: (t, k) => n._attrs["data-" + String(k).replace(/[A-Z]/g, c => "-" + c.toLowerCase())] });
  n.setAttribute = (k, v) => { if (k === "id") n.id = v; else if (k === "class") n.className = v; else n._attrs[k] = String(v); };
  n.getAttribute = k => (k === "class" ? (n._cls.length ? n.className : null) : (k in n._attrs ? n._attrs[k] : null));
  n.appendChild = c => { if (c.parentNode) c.parentNode.removeChild(c); c.parentNode = n; n.children.push(c); return c; };
  n.removeChild = c => { n.children = n.children.filter(x => x !== c); c.parentNode = null; return c; };
  n.addEventListener = (e, h) => { (n._l[e] = n._l[e] || []).push(h); };
  n.fire = e => (n._l[e] || []).forEach(h => h({ preventDefault() {}, target: n }));
  n.click = () => { if (!n.disabled) n.fire("click"); };
  n.querySelectorAll = sel => {
    const parts = sel.match(/^([a-z0-9]+)?((?:\.[\w-]+)*)((?:\[[\w-]+(?:="[^"]*")?\])*)$/i);
    if (!parts) throw new Error("unsupported selector " + sel);
    const tag = parts[1], classes = (parts[2] || "").split(".").filter(Boolean);
    const attrs = [...(parts[3] || "").matchAll(/\[([\w-]+)(?:="([^"]*)")?\]/g)];
    const out = [];
    (function walk(x) { x.children.forEach(c => { if (c.tagName === "#TEXT") return;
      if ((!tag || c.tagName === tag.toUpperCase()) && classes.every(k => c.classList.contains(k))
          && attrs.every(a => a[2] === undefined ? c.getAttribute(a[1]) !== null : c.getAttribute(a[1]) === a[2])) out.push(c);
      walk(c); }); })(n);
    return out;
  };
  n.querySelector = sel => n.querySelectorAll(sel)[0] || null;
  n.scrollIntoView = () => {};
  return n;
}
function build(spec) {
  if (spec.text !== undefined) return textNode(spec.text);
  const n = node(spec.tag);
  for (const [k, v] of Object.entries(spec.attrs)) {
    if (k === "hidden") n.hidden = true;
    else if (k === "disabled") n.disabled = true;
    else n.setAttribute(k, v);
  }
  if (n.tagName === "BUTTON") n.type = spec.attrs.type || "submit";
  spec.children.forEach(c => n.appendChild(build(c)));
  return n;
}
const opts = JSON.parse(process.env.W35P);
const root = build(opts.tree);
const doc = { getElementById: id => ids[id] || null, createElement: t => node(t) };
const byId = id => ids[id];
const calls = []; const pending = [];
const tick = () => new Promise(r => setTimeout(r, 0));
const fetch = (url, o) => {
  calls.push({ url, method: o.method, body: o.body ? JSON.parse(o.body) : null });
  if (o.method === "GET") {
    const category = decodeURIComponent(url.split("category=")[1] || "");
    return Promise.resolve({ ok: true, json: () => Promise.resolve({ trips: opts.trips[category] || [] }) });
  }
  return new Promise((resolve, reject) => pending.push({ resolve, reject }));
};
// Missing elements read as null, so a page without the W35 markup fails the assertions
// instead of crashing the driver.
function own(n) { return n ? n.textContent.replace(/\s+/g, " ").trim() : null; }
const prop = (id, key) => (byId(id) ? byId(id)[key] : null);
function lines(n) {
  if (!n) return null;
  return n.children.filter(c => c.tagName !== "#TEXT").map(c => ({ tag: c.tagName, cls: c.className, text: own(c) }));
}
function vector() { return ["step-category", "step-trip", "step-details", "outcome"].map(id => !byId(id).hidden); }
function snapshot(label) {
  const summary = byId("step-details").children.find(c => c.tagName !== "#TEXT" && c.classList.contains("filing-summary"));
  const selectedTrip = byId("trip-options").children.find(c => c.classList.contains("selected"));
  const selectedCategory = byId("category-options").children.find(c => c.classList.contains("selected"));
  return {
    label, vector: vector(),
    summaryLabel: summary ? own(summary.querySelector(".filing-summary-label")) : null,
    category: own(byId("summary-category")),
    trip: lines(byId("summary-trip")),
    selectedCategory: selectedCategory ? own(selectedCategory) : null,
    selectedTrip: selectedTrip ? lines(selectedTrip) : null,
    submit: { text: own(byId("details-submit")), disabled: byId("details-submit").disabled },
    back: { disabled: byId("details-back").disabled },
    spinnerHidden: prop("details-spinner", "hidden"),
    status: prop("details-status", "textContent"),
    error: byId("details-error").hidden ? null : own(byId("details-error")),
    posts: calls.filter(c => c.method === "POST").length,
    outcomeTitle: own(byId("outcome-title")),
    formHidden: byId("form-steps").hidden
  };
}
(async () => {
  vm.runInNewContext(fs.readFileSync(process.env.PARTY_JS, "utf8"),
    { document: doc, window: { scrollTo() {} }, fetch, Promise, setTimeout, encodeURIComponent, JSON, Array, Number, isFinite, String, Object });
  const out = [];
  for (const op of opts.ops) {
    const [kind, a, b] = op;
    if (kind === "category") byId("category-options").children[a].click();
    else if (kind === "trip") byId("trip-options").children[a].click();
    else if (kind === "click") byId(a).click();
    else if (kind === "value") byId(a).value = b;
    else if (kind === "submit") byId("details-form").fire("submit");
    else if (kind === "resolve") pending.shift().resolve({ ok: true, json: () => Promise.resolve(a) });
    else if (kind === "refuse") pending.shift().resolve({ ok: false, json: () => Promise.resolve({ error: a }) });
    else if (kind === "drop") pending.shift().reject(new Error(a));
    await tick(); await tick(); await tick();
    if (kind === "snap") out.push(snapshot(a));
  }
  process.stdout.write(JSON.stringify({ snaps: out, calls }));
})().catch(e => { process.stderr.write(String(e && e.stack || e)); process.exit(1); });
"""


def drive(page, ops, party_js=None):
    node_bin = shutil.which("node")
    if not node_bin:
        raise AssertionError("Node is required for the W35 page driver")
    tree = page_tree(page)
    env = dict(os.environ, PARTY_JS=str(party_js or PARTY / "party.js"),
               W35P=json.dumps({"tree": tree, "trips": TRIPS, "ops": ops}))
    result = subprocess.run([node_bin, "-e", HARNESS], env=env, text=True, capture_output=True, timeout=30)
    if result.returncode:
        raise AssertionError("driven page failed: " + result.stderr[-2000:])
    data = json.loads(result.stdout)
    return {s["label"]: s for s in data["snaps"]}, data["calls"]


def trip_lines(trip_id):
    texts = TRIP_TEXT[trip_id]
    return [{"tag": "STRONG", "cls": "", "text": texts[0]},
            {"tag": "SPAN", "cls": "trip-meta", "text": texts[1]},
            {"tag": "SPAN", "cls": "trip-meta", "text": texts[2]}]


def to_details(category, trip):
    return [["category", category], ["click", "category-next"], ["trip", trip], ["click", "trip-next"]]


# ------------------------------------------------------------------ helpers over markup


def find_all(node, pred, out=None):
    out = [] if out is None else out
    for child in node.get("children", []):
        if "tag" in child:
            if pred(child):
                out.append(child)
            find_all(child, pred, out)
    return out


def by_id(tree, ident):
    found = find_all(tree, lambda n: n["attrs"].get("id") == ident)
    assert len(found) == 1, "exactly one #%s, found %d" % (ident, len(found))
    return found[0]


def classes(n):
    return n["attrs"].get("class", "").split()


def text_of(n):
    return " ".join(" ".join(c["text"] if "text" in c else text_of(c) for c in n["children"]).split())


def elements(n):
    return [c for c in n["children"] if "tag" in c]


# ================================================================== P2 + P3: step 3 summary


class StepThreeSummaryMarkup(unittest.TestCase):
    """The summary sits first in step 3, above the heading, and is not a control."""

    def test_summary_is_first_in_step_three_above_the_heading_on_both_pages(self):
        for page in FILING_PAGES:
            with self.subTest(page=page):
                step = by_id(page_tree(page), "step-details")
                kids = elements(step)
                self.assertEqual("div", kids[0]["tag"])
                self.assertEqual(["filing-summary"], classes(kids[0]))
                self.assertEqual("h2", kids[1]["tag"], "the summary comes directly before 'Tell us more'")
                self.assertEqual("3 Tell us more", text_of(kids[1]))
                summary = kids[0]
                self.assertEqual(["p", "p", "div"], [k["tag"] for k in elements(summary)])
                label, category, trip = elements(summary)
                self.assertEqual(["filing-summary-label"], classes(label))
                self.assertEqual(SUMMARY_LABEL, text_of(label))
                self.assertEqual("summary-category", category["attrs"].get("id"))
                self.assertEqual("summary-trip", trip["attrs"].get("id"))

    def test_summary_carries_nothing_interactive(self):
        interactive = {"button", "a", "input", "textarea", "select", "label"}
        for page in FILING_PAGES:
            with self.subTest(page=page):
                summary = elements(by_id(page_tree(page), "step-details"))[0]
                for n in [summary] + find_all(summary, lambda n: True):
                    self.assertNotIn(n["tag"], interactive)
                    for attr in ("tabindex", "onclick", "contenteditable", "role", "href"):
                        self.assertNotIn(attr, n["attrs"], "%s on a read-only summary" % attr)


class StepThreeSummaryBehaviour(unittest.TestCase):
    """party.js on the real markup: the summary repeats the step 1 card and the step 2 card."""

    def _flow(self, page, names):
        ops = to_details(0, 0) + [["snap", "first"],
               ["click", "details-back"], ["snap", "back-at-trip"],
               ["trip", 1], ["snap", "other-trip-picked"], ["click", "trip-next"], ["snap", "second"],
               ["click", "details-back"], ["click", "trip-back"], ["snap", "back-at-category"],
               ["category", 1], ["snap", "other-category-picked"], ["click", "category-next"],
               ["snap", "trip-list"], ["trip", 1], ["click", "trip-next"], ["snap", "third"],
               ["click", "details-back"], ["trip", 0], ["click", "trip-next"], ["snap", "fourth"]]
        snaps, _ = drive(page, ops)
        return snaps

    def test_summary_shows_the_chosen_category_and_trip_and_follows_every_change(self):
        for page, names in (("index.html", RIDER_CATEGORIES), ("driver-filing.html", DRIVER_CATEGORIES)):
            with self.subTest(page=page):
                s = self._flow(page, names)
                expected = [("first", 0, "T-RD9001"), ("second", 0, "T-RD9002"),
                            ("third", 1, "T-NS9002"), ("fourth", 1, "T-NS9001")]
                for label, category, trip in expected:
                    with self.subTest(snapshot=label):
                        snap = s[label]
                        self.assertEqual([False, False, True, False], snap["vector"])
                        self.assertEqual(SUMMARY_LABEL, snap["summaryLabel"])
                        self.assertEqual(names[category], snap["category"])
                        self.assertEqual(snap["selectedCategory"], snap["category"],
                                         "the category reads exactly as its step 1 card")
                        self.assertEqual(trip_lines(trip), snap["trip"])
                        self.assertEqual(snap["selectedTrip"], snap["trip"],
                                         "the trip reads exactly as its step 2 card, line for line")

    def test_each_interaction_shows_exactly_one_step(self):
        for page in FILING_PAGES:
            with self.subTest(page=page):
                s = self._flow(page, None)
                self.assertEqual([False, True, False, False], s["back-at-trip"]["vector"])
                self.assertEqual([False, True, False, False], s["other-trip-picked"]["vector"],
                                 "picking a trip card moves nothing")
                self.assertEqual([True, False, False, False], s["back-at-category"]["vector"])
                self.assertEqual([True, False, False, False], s["other-category-picked"]["vector"])
                self.assertEqual([False, True, False, False], s["trip-list"]["vector"])

    def test_step_two_cards_are_unchanged_by_the_shared_rendering(self):
        snaps, _ = drive("index.html", to_details(0, 0) + [["click", "details-back"], ["snap", "list"]])
        self.assertEqual(trip_lines("T-RD9001"), snaps["list"]["selectedTrip"])


# ================================================================== P4: pending state


VIEW = {"run_id": "run-w35", "dispute_id": "PF-W35FIXTURE", "status": "under_review",
        "message": "Your case is still under review.", "questions": []}


class SendPendingState(unittest.TestCase):
    """The request is held open by the test; nothing in the app is delayed."""

    def _pending_flow(self, page):
        ops = to_details(0, 0) + [
            ["value", "description", "The driver went a long way round."], ["snap", "ready"],
            ["submit"], ["snap", "sending"],
            ["submit"], ["click", "details-submit"], ["snap", "sending-again"],
            ["refuse", "Fixture refusal: please try again."], ["snap", "refused"],
            ["submit"], ["snap", "sending-second"],
            ["drop", "Failed to fetch"], ["snap", "dropped"],
            ["submit"], ["snap", "sending-third"],
            ["resolve", VIEW], ["snap", "done"]]
        return drive(page, ops)

    def test_send_shows_the_pending_state_then_restores_on_failure(self):
        for page in FILING_PAGES:
            with self.subTest(page=page):
                s, calls = self._pending_flow(page)
                ready = s["ready"]
                self.assertEqual({"text": SUBMIT_LABEL, "disabled": False}, ready["submit"])
                self.assertEqual({"disabled": False}, ready["back"])
                self.assertTrue(ready["spinnerHidden"])
                self.assertEqual("", ready["status"])
                for label in ("sending", "sending-again", "sending-second", "sending-third"):
                    with self.subTest(state=label):
                        snap = s[label]
                        self.assertEqual({"text": SENDING_LABEL, "disabled": True}, snap["submit"])
                        self.assertEqual({"disabled": True}, snap["back"], "Back is disabled while sending")
                        self.assertFalse(snap["spinnerHidden"], "the spinner shows while sending")
                        self.assertEqual(SENDING_STATUS, snap["status"])
                        self.assertIsNone(snap["error"])
                        self.assertEqual([False, False, True, False], snap["vector"])
                for label, message in (("refused", "Fixture refusal: please try again."),
                                       ("dropped", "Failed to fetch")):
                    with self.subTest(state=label):
                        snap = s[label]
                        self.assertEqual({"text": SUBMIT_LABEL, "disabled": False}, snap["submit"])
                        self.assertEqual({"disabled": False}, snap["back"])
                        self.assertTrue(snap["spinnerHidden"])
                        self.assertEqual("", snap["status"], "the status line is cleared")
                        self.assertEqual(message, snap["error"], "the existing error is shown")
                        self.assertEqual([False, False, True, False], snap["vector"])

    def test_a_second_send_while_pending_posts_nothing(self):
        for page in FILING_PAGES:
            with self.subTest(page=page):
                s, calls = self._pending_flow(page)
                self.assertEqual(1, s["sending"]["posts"])
                self.assertEqual(1, s["sending-again"]["posts"], "a pending send cannot be queued twice")
                self.assertEqual(2, s["sending-second"]["posts"])
                self.assertEqual(3, s["sending-third"]["posts"])
                self.assertEqual(3, len([c for c in calls if c["method"] == "POST"]))

    def test_success_renders_the_outcome_as_before(self):
        for page in FILING_PAGES:
            with self.subTest(page=page):
                s, _ = self._pending_flow(page)
                done = s["done"]
                self.assertTrue(done["formHidden"])
                self.assertEqual([False, False, True, True], done["vector"])
                self.assertEqual("Your case is still under review", done["outcomeTitle"])

    def test_a_refused_form_never_enters_the_pending_state(self):
        cases = [("empty description", [["value", "description", "  "]], "Please tell us what happened before sending."),
                 ("amount out of range", [["value", "description", "x"], ["value", "claim-amount", "900"]],
                  "The amount must be between 0 and 500 SGD.")]
        for page in FILING_PAGES:
            for name, setup, message in cases:
                with self.subTest(page=page, case=name):
                    s, calls = drive(page, to_details(0, 0) + setup + [["submit"], ["snap", "after"]])
                    after = s["after"]
                    self.assertEqual(message, after["error"])
                    self.assertEqual({"text": SUBMIT_LABEL, "disabled": False}, after["submit"])
                    self.assertEqual({"disabled": False}, after["back"])
                    self.assertTrue(after["spinnerHidden"])
                    self.assertEqual("", after["status"])
                    self.assertEqual(0, after["posts"])


class SendPendingMarkup(unittest.TestCase):

    def test_status_line_is_a_polite_live_region_between_fields_and_actions(self):
        for page in FILING_PAGES:
            with self.subTest(page=page):
                form = by_id(page_tree(page), "details-form")
                kids = elements(form)
                names = [k["attrs"].get("id") or " ".join(classes(k)) for k in kids]
                self.assertEqual(["filing-fields", "details-status", "step-actions"], names)
                status = kids[1]
                self.assertEqual("p", status["tag"])
                self.assertEqual("status", status["attrs"].get("role"))
                self.assertEqual("polite", status["attrs"].get("aria-live"))
                self.assertIn("sending-status", classes(status))
                self.assertEqual("", text_of(status), "empty until a send starts")

    def test_spinner_sits_beside_send_hidden_from_assistive_tech(self):
        for page in FILING_PAGES:
            with self.subTest(page=page):
                form = elements(by_id(page_tree(page), "details-form"))
                actions = [k for k in form if "step-actions" in classes(k)]
                self.assertEqual(1, len(actions))
                kids = elements(actions[0])
                self.assertEqual(["details-back", "details-spinner", "details-submit"],
                                 [k["attrs"].get("id") for k in kids])
                spinner = kids[1]
                self.assertEqual("span", spinner["tag"])
                self.assertEqual(["sending-spinner"], classes(spinner))
                self.assertEqual("true", spinner["attrs"].get("aria-hidden"))
                self.assertIn("hidden", spinner["attrs"])
                self.assertEqual("", text_of(spinner))
                self.assertEqual(SUBMIT_LABEL, text_of(kids[2]))


# ================================================================== CSS: spinner, summary, frame


def party_css():
    return stripped((PARTY / "party.css").read_text(encoding="utf-8"))


def bar_css():
    return stripped((REPO / "ui" / "switch-bar.css").read_text(encoding="utf-8"))


def start_css():
    return stripped((REPO / "ui" / "start" / "start.css").read_text(encoding="utf-8"))


def declarations(css, context, selector):
    out = []
    for ctx, group, decls in rules(css):
        if ctx == context and selector in group:
            out.extend(decls)
    return out


REDUCE = ("@media (prefers-reduced-motion: reduce)",)
FRAME = ".filing-shell:has(#form-steps:not([hidden]))"


class SpinnerAndSummaryStyle(unittest.TestCase):

    def test_spinner_spins_hides_with_its_attribute_and_stops_under_reduced_motion(self):
        css = party_css()
        for width in (360, 1200):
            moving = cascade(css, {".sending-spinner"}, width)
            self.assertEqual("inline-block", moving.get("display"))
            self.assertEqual("sending-spin 0.8s linear infinite", moving.get("animation"))
            self.assertEqual("50%", moving.get("border-radius"))
            still = cascade(css, {".sending-spinner"}, width, reduced_motion=True)
            self.assertEqual("none", still.get("animation"))
            self.assertEqual("none", cascade(css, {".sending-spinner", ".sending-spinner[hidden]"}, width).get("display"))
        self.assertEqual([("animation", "none")], declarations(css, REDUCE, ".sending-spinner"))
        keyframes = [d for ctx, group, d in rules(css) if group == ("@keyframes sending-spin",)]
        self.assertEqual([(("__opaque__", "to { transform: rotate(360deg); }"),)], keyframes)

    def test_summary_keeps_its_height_in_the_frame_and_yields_only_past_ten_rem(self):
        css = party_css()
        framed = cascade(css, {".filing-summary", FRAME + " .filing-summary"})
        self.assertEqual("0 0 auto", framed.get("flex"))
        self.assertEqual("calc(100% - 10rem)", framed.get("max-height"))
        self.assertEqual("auto", framed.get("overflow-y"))
        self.assertEqual("var(--tint)", framed.get("background-color"))
        self.assertEqual("display: block", "display: " + cascade(css, {".filing-summary-trip strong"}).get("display"))

    def test_status_line_takes_no_room_until_it_has_text(self):
        css = party_css()
        self.assertEqual("1rem 0 0", cascade(css, {".sending-status"}).get("margin"))
        self.assertEqual("0", cascade(css, {".sending-status", ".sending-status:empty"}).get("margin"))
        self.assertEqual("0 0 auto", cascade(css, {".sending-status"}).get("flex"))

    def test_summary_steps_aside_with_the_bar_on_a_very_short_screen(self):
        short = ("@media (max-height: 520px)",)
        self.assertEqual([("display", "none")], declarations(bar_css(), short, ".filing-shell .filing-summary"))
        self.assertEqual([("display", "none")],
                         declarations(bar_css(), short, "body:has(.filing-shell #form-steps:not([hidden])) > .switch-bar"))


# ================================================================== P1: the status page frame


TALL = ("@media (min-height: 654px)",)
STATUS_FRAME = {
    "body:has(> .status-shell)": [("display", "flex"), ("flex-direction", "column"), ("height", "100vh"),
                                  ("height", "100dvh"), ("overflow", "hidden")],
    "body:has(> .status-shell) > .switch-bar": [("flex", "none")],
    ".status-shell": [("flex", "1 1 auto"), ("min-height", "0"), ("width", "100%"), ("display", "flex"),
                      ("flex-direction", "column"), ("gap", "0.5rem"), ("padding", "0.5rem 1.25rem"),
                      ("overflow-y", "auto")],
    ".status-shell > .party-header": [("flex", "0 1 auto"), ("min-height", "4.5rem"), ("overflow-y", "auto")],
    ".status-shell > .party-header h1": [("font-size", "1.25rem"), ("line-height", "1.2"), ("margin", "0.25rem 0")],
    ".status-shell > .party-header .eyebrow": [("font-size", "0.65rem"), ("padding", "0.1rem 0.5rem")],
    ".status-shell > .party-header .demo-note": [("margin", "0.25rem 0"), ("padding", "0.2rem 0.6rem"),
                                                 ("font-size", "0.75rem")],
    ".status-shell > .party-header .intro": [("font-size", "0.85rem"), ("margin", "0")],
    ".status-shell > .party-header > p:last-child": [("margin", "0.375rem 0 0")],
    ".status-shell > .status-lookup": [("margin", "0"), ("padding", "0.75rem"), ("flex", "none")],
    ".status-shell > .status-list": [("margin", "0"), ("padding", "0.75rem"), ("flex", "1 1 0"),
                                     ("min-height", "8rem"), ("display", "flex"), ("flex-direction", "column")],
    ".status-shell .step h2": [("margin-bottom", "0.5rem")],
    ".status-shell > .status-lookup .field": [("margin-bottom", "0.5rem")],
    ".status-shell > .status-lookup .step-actions": [("margin-top", "0.5rem"), ("padding-top", "0.5rem")],
    ".status-shell > #lookup-result:empty": [("display", "none")],
    ".status-shell > #lookup-result": [("flex", "0 1 auto"), ("min-height", "5rem"),
                                       ("overflow-y", "auto"), ("overscroll-behavior", "contain")],
    ".status-shell > #lookup-result > .step": [("margin", "0"), ("padding", "0.75rem")],
    ".status-shell > .status-list > h2": [("flex", "0 0 auto")],
    ".status-shell > .status-list > #account-list": [("flex", "1 1 auto"), ("min-height", "0"),
                                                     ("overflow-y", "auto"), ("overscroll-behavior", "contain"),
                                                     ("padding", "0.75rem"), ("margin", "-0.75rem")],
}


class StatusPageFrame(unittest.TestCase):

    def test_status_markup_names_the_shell_the_lookup_box_and_the_list_region(self):
        tree = _Tree((PARTY / "status.html").read_text(encoding="utf-8")).root
        main = find_all(tree, lambda n: n["tag"] == "main")
        self.assertEqual(1, len(main))
        self.assertEqual(["party-shell", "status-shell"], classes(main[0]))
        sections = [k for k in elements(main[0]) if k["tag"] == "section"]
        self.assertEqual([["step", "status-lookup"], ["step", "status-list"]], [classes(s) for s in sections])
        self.assertEqual("Look up a reference number", text_of(elements(sections[0])[0]))
        # W35 round 2: the result block is the shell's own child, between the lookup box and the
        # list (tests/test_w35_r2_S.py pins the order), so the lookup box never holds it.
        self.assertFalse(find_all(sections[0], lambda n: n["attrs"].get("id") == "lookup-result"))
        self.assertEqual(1, len([k for k in elements(main[0]) if k["attrs"].get("id") == "lookup-result"]))
        self.assertEqual("My disputes", text_of(elements(sections[1])[0]))
        region = by_id(tree, "account-list")
        self.assertEqual(sections[1], next(s for s in sections if region in elements(s)))
        self.assertEqual({"id": "account-list", "tabindex": "0", "role": "region", "aria-label": "My disputes"},
                         region["attrs"], "the list is a keyboard-scrollable, named region")

    def test_the_frame_rules_are_exactly_these_and_only_on_a_tall_screen(self):
        found = {}
        for ctx, group, decls in rules(bar_css()):
            for selector in group:
                if any(selector.startswith(p) for p in ("body:has(> .status-shell)", ".status-shell")):
                    self.assertEqual(TALL, ctx, "%s applies only at min-height 654px" % selector)
                    found.setdefault(selector, []).extend(decls)
        self.assertEqual(STATUS_FRAME, found)
        self.assertNotIn("status-shell", party_css(), "party.css carries no status-frame rule (height queries live in the bar sheet)")

    def test_no_fade_overlay_on_either_region(self):
        for ctx, group, decls in rules(bar_css()):
            if any("status" in s for s in group):
                for prop, value in decls:
                    self.assertNotIn("gradient", value)
                    self.assertNotIn(prop, ("mask", "mask-image", "-webkit-mask-image"))


# ================================================================== contrast


def _lum(hex_colour):
    hex_colour = hex_colour.lstrip("#")
    rgb = [int(hex_colour[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a, b):
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


class ContrastTokens(unittest.TestCase):

    def test_token_values_and_the_ratios_they_buy(self):
        for css in (party_css(), start_css()):
            root = dict(declarations(css, (), ":root"))
            self.assertEqual("#cc2852", root.get("--accent-strong"))
            self.assertEqual("#e93864", root.get("--accent"), "the brand pink stays for borders and decoration")
        self.assertGreaterEqual(contrast("#ffffff", "#cc2852"), 4.5)
        self.assertGreaterEqual(contrast("#cc2852", "#fff0f3"), 4.5)
        self.assertGreaterEqual(contrast("#cc2852", "#ffffff"), 4.5)
        self.assertLess(contrast("#ffffff", "#e93864"), 4.5, "why the change: 4.03:1")

    def test_white_text_sits_on_the_strong_pink(self):
        css = party_css()
        for selectors in ({"button", "button.primary"}, {"button", "button.primary", "button:not(:disabled):hover"}):
            style = cascade(css, selectors)
            self.assertEqual("var(--accent-strong)", style.get("background-color"))
            self.assertEqual("var(--accent-strong)", style.get("border-color"))
            self.assertEqual("var(--accent-ink)", style.get("color"))
        number = cascade(css, {".step-number"})
        self.assertEqual("var(--accent-strong)", number.get("background-color"))
        self.assertEqual("var(--accent-ink)", number.get("color"))
        # The bar sheet carries height queries the shared cascade reader refuses, so read the
        # rule itself; it is the only rule that paints the pill.
        pill = dict(declarations(bar_css(), (), ".switch-bar a[aria-current]"))
        self.assertEqual("#cc2852", pill.get("background"))
        self.assertEqual("#ffffff", pill.get("color"))

    def test_small_pink_text_uses_the_strong_pink_and_borders_keep_the_brand_pink(self):
        css = party_css()
        eyebrow = cascade(css, {".party-header .eyebrow"})
        self.assertEqual("var(--accent-strong)", eyebrow.get("color"))
        self.assertEqual("var(--accent)", eyebrow.get("border-color"))
        start = start_css()
        self.assertEqual("var(--accent-strong)", cascade(start, {".start-header .eyebrow"}).get("color"))
        self.assertEqual("var(--accent)", cascade(start, {".start-header .eyebrow"}).get("border-color"))
        self.assertEqual("var(--accent-strong)", cascade(start, {".start-card .card-title"}).get("color"))
        self.assertEqual("var(--accent)", cascade(start, {".start-card:hover"}).get("border-color"))
        self.assertEqual("var(--accent)", cascade(css, {".option-card", ".option-card.selected"}).get("border-color"))

    def test_no_rule_sets_text_in_the_brand_pink_or_white_on_it(self):
        for name, css in (("party.css", party_css()), ("start.css", start_css()), ("switch-bar.css", bar_css())):
            for ctx, group, decls in rules(css):
                props = dict(decls)
                with self.subTest(sheet=name, rule=group):
                    self.assertNotIn(props.get("color"), ("var(--accent)", "#e93864"))
                    if props.get("color") in ("var(--accent-ink)", "#ffffff", "#fff", "white"):
                        self.assertNotIn(props.get("background", props.get("background-color")),
                                         ("var(--accent)", "#e93864"))


# ================================================================== preservation


# The exact W35 edits per sheet: (context, selector, property, value). Everything else in the
# three stylesheets must equal BASE 57758ce, rule for rule (W35_KEPT below). The exception list
# IS the pin: an extra or missing W35 declaration fails here, and so does any other change.
W35_PARTY = [
    ((), ":root", "--accent-strong", "#cc2852"),
    ((), ".party-header .eyebrow", "color", "var(--accent-strong)"),
    ((), ".step-number", "background", "var(--accent-strong)"),
    ((), "button.primary", "background", "var(--accent-strong)"),
    ((), "button.primary", "border-color", "var(--accent-strong)"),
    ((), ".filing-summary", "overflow-y", "auto"),
    ((), ".filing-summary", "margin", "0 0 0.5rem"),
    ((), ".filing-summary", "padding", "0.4rem 0.75rem"),
    ((), ".filing-summary", "font-size", "0.9rem"),
    ((), ".filing-summary", "line-height", "1.35"),
    ((), ".filing-summary", "background", "var(--tint)"),
    ((), ".filing-summary", "border", "1px solid var(--line)"),
    ((), ".filing-summary", "border-radius", "14px"),
    ((), ".filing-summary p", "margin", "0"),
    ((), ".filing-summary-label", "font-size", "0.75rem"),
    ((), ".filing-summary-label", "font-weight", "600"),
    ((), ".filing-summary-label", "color", "var(--muted)"),
    ((), ".filing-summary-category", "font-weight", "600"),
    ((), ".filing-summary-trip strong", "display", "block"),
    ((), FRAME + " .filing-summary", "flex", "0 0 auto"),
    ((), FRAME + " .filing-summary", "max-height", "calc(100% - 10rem)"),
    ((), ".sending-status", "flex", "0 0 auto"),
    ((), ".sending-status", "margin", "1rem 0 0"),
    ((), ".sending-status:empty", "margin", "0"),
    ((), ".sending-spinner", "display", "inline-block"),
    ((), ".sending-spinner", "flex", "0 0 auto"),
    ((), ".sending-spinner", "align-self", "center"),
    ((), ".sending-spinner", "width", "1.25rem"),
    ((), ".sending-spinner", "height", "1.25rem"),
    ((), ".sending-spinner", "border", "3px solid var(--line)"),
    ((), ".sending-spinner", "border-top-color", "var(--accent)"),
    ((), ".sending-spinner", "border-radius", "50%"),
    ((), ".sending-spinner", "animation", "sending-spin 0.8s linear infinite"),
    ((), ".sending-spinner[hidden]", "display", "none"),
    ((), "@keyframes sending-spin", "__opaque__", "to { transform: rotate(360deg); }"),
    (REDUCE, ".sending-spinner", "animation", "none"),
]
W35_BAR = [((), ".switch-bar a[aria-current]", "background", "#cc2852"),
           (("@media (max-height: 520px)",), ".filing-shell .filing-summary", "display", "none")] + [
    (TALL, selector, prop, value) for selector, decls in STATUS_FRAME.items() for prop, value in decls]
W35_START = [((), ":root", "--accent-strong", "#cc2852"),
             ((), ".start-header .eyebrow", "color", "var(--accent-strong)"),
             ((), ".start-card .card-title", "color", "var(--accent-strong)")]
# The declarations W35 replaced (BASE values), so the kept digest is computed the same way on
# both sides.
W35_REPLACED = {
    "party": {((), ".party-header .eyebrow", "color"), ((), ".step-number", "background"),
              ((), "button.primary", "background"), ((), "button.primary", "border-color")},
    "bar": {((), ".switch-bar a[aria-current]", "background")},
    "start": {((), ".start-header .eyebrow", "color"), ((), ".start-card .card-title", "color")},
}
# sha256 of every OTHER declaration, in order, at BASE 57758ce (see kept_digest).
W35_KEPT = {
    "party": "ae38fe84f84873ed4558bd265852d7af4718c8deafe3b18950549696003bf9b3",
    "bar": "14b0b64d76cfdf88d9eb1b2d56dd7ca60c51c496fee2cc3132e64a1fd007618c",
    "start": "e577b5152f62a9bca2ca86556648cad3d8abf499e5737c794cd18ab072e894ee",
}
SHEETS = {"party": lambda: party_css(), "bar": lambda: bar_css(), "start": lambda: start_css()}
ADDED = {"party": W35_PARTY, "bar": W35_BAR, "start": W35_START}


def flat(css):
    return [(ctx, selector, prop, value) for ctx, group, decls in rules(css)
            for selector in group for prop, value in decls]


def kept_digest(sheet, css):
    added = {row for row in ADDED[sheet]}
    replaced = W35_REPLACED[sheet]
    kept = [row for row in flat(css) if row not in added and row[:3] not in replaced]
    return hashlib.sha256(json.dumps(kept, separators=(",", ":")).encode()).hexdigest()


class W35Preservation(unittest.TestCase):

    def test_every_w35_declaration_is_present_exactly_once(self):
        for sheet, rows in ADDED.items():
            with self.subTest(sheet=sheet):
                have = flat(SHEETS[sheet]())
                for row in rows:
                    self.assertEqual(1, have.count(row), row)
                self.assertEqual(len(rows), len(set(rows)), "the exception list has no duplicates")

    def test_nothing_else_in_the_three_sheets_moved(self):
        for sheet in SHEETS:
            with self.subTest(sheet=sheet):
                self.assertEqual(W35_KEPT[sheet], kept_digest(sheet, SHEETS[sheet]()))

    def test_the_replaced_declarations_are_gone(self):
        for sheet, keys in W35_REPLACED.items():
            have = flat(SHEETS[sheet]())
            for key in keys:
                with self.subTest(sheet=sheet, rule=key):
                    values = [row[3] for row in have if row[:3] == key]
                    self.assertEqual(1, len(values), key)
                    self.assertIn("strong" if sheet != "bar" else "#cc2852", values[0])


if __name__ == "__main__":
    unittest.main()
