"""W23 B1 acceptance target: the party pages (nothing-more button, status page, driver page).

RED until the build lane ships the party-page half of contract W23 B1 section 4.

Testing rule for page code: behaviour is not reachable from Python, so each pin is scoped to the
code that must carry it, with JS comments stripped first (a comment can never satisfy a rule).
The party.js button is also DRIVEN in node against a fake DOM (the session-sixteen harness
pattern), so the click is proven to fill the box, not merely present in the source.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import unittest

from tests.w23_support import PARTY_UI, Server, html_text, js_function_body, strip_js_comments

NOTHING = "I have nothing more to add"
STATUS_SENTENCE = "This is a demo account. It shows every dispute filed on this demo."
DRIVER_SENTENCE = "This is a demo driver account. It shows the outcome of disputes about your trips."
NEW_FILES = ("status.html", "status.js", "driver.html", "driver.js")
SINKS = ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write")


def _read(name):
    path = PARTY_UI / name
    if not path.is_file():
        raise AssertionError("ui/party/%s does not exist" % name)
    return path.read_text(encoding="utf-8")


def _uses(code, names):
    """A regex alternation matching any of the names (literals verbatim, identifiers whole-word)."""
    return "(?:%s)" % "|".join(re.escape(n) if n[0] in "\"'" else r"\b%s\b" % re.escape(n) for n in names)


def _labels_a_button_and_fills_a_box(test, code, value):
    """The value must label a button (helper call or textContent) AND be written into a box."""
    alt = _uses(code, _literal_or_constant(code, value))
    test.assertRegex(code, r"""(?:element|createElement)\(\s*["']button["'][^;]*%s|\.textContent\s*=\s*%s""" % (alt, alt),
                     "a button must be labelled %r" % value)
    test.assertRegex(code, r"\.value\s*=\s*%s" % alt, "the button must write %r into the answer box" % value)


def _literal_or_constant(code, value):
    """Names that carry `value` in this code: the literal itself, plus any var/let/const
    initialised to it."""
    names = [json.dumps(value), "'%s'" % value]
    for match in re.finditer(r"\b(?:var|let|const)\s+([A-Za-z_$][\w$]*)\s*=\s*([\"'])%s\2" % re.escape(value), code):
        names.append(match.group(1))
    return names


class NothingMoreToAdd(unittest.TestCase):
    def test_the_label_is_the_eval_string(self):
        from app.eval import NOTHING_MORE_TO_ADD

        self.assertEqual(NOTHING, NOTHING_MORE_TO_ADD)

    def test_the_question_box_builder_creates_the_button(self):
        source = _read("party.js")
        body = js_function_body(source, "buildAnswerBoxes")
        self.assertRegex(body, r"""(?:element|createElement)\(\s*["']button["']""")
        names = _literal_or_constant(strip_js_comments(source), NOTHING)
        alt = _uses(body, names)
        self.assertRegex(body, r"""(?:element|createElement)\(\s*["']button["'][^;]*%s|\.textContent\s*=\s*%s""" % (alt, alt))
        self.assertRegex(body, r"\.value\s*=\s*%s" % alt, "the button must write the string into the box")


_HARNESS = r"""
const fs = require("fs"); const vm = require("vm");
function node(tag) {
  const n = { tagName: String(tag).toUpperCase(), children: [], hidden: false, disabled: false, parentNode: null,
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
  n.getAttribute = k => (k in n._attrs ? n._attrs[k] : (k === "for" && n.htmlFor ? n.htmlFor : null));
  n.appendChild = c => { n.children.push(c); c.parentNode = n; return c; };
  n.removeChild = c => { n.children = n.children.filter(x => x !== c); return c; };
  Object.defineProperty(n, "firstChild", { get: () => n.children[0] || null });
  n.addEventListener = (e, h) => { (n._l[e] = n._l[e] || []).push(h); };
  n.fire = e => (n._l[e] || []).forEach(h => h({ preventDefault() {}, target: n }));
  n.click = () => n.fire("click");
  n.all = () => { const out = []; (function walk(x) { x.children.forEach(c => { out.push(c); walk(c); }); })(n); return out; };
  n.querySelectorAll = sel => {
    const parts = sel.match(/^([a-z]+)?((?:\.[\w-]+)*)((?:\[[\w-]+(?:="[^"]*")?\])*)$/i);
    if (!parts) throw new Error("unsupported selector " + sel);
    const tag = parts[1], classes = (parts[2] || "").split(".").filter(Boolean);
    const attrs = [...(parts[3] || "").matchAll(/\[([\w-]+)(?:="([^"]*)")?\]/g)];
    return n.all().filter(c => (!tag || c.tagName === tag.toUpperCase()) && classes.every(k => c.classList.contains(k))
      && attrs.every(a => a[2] === undefined ? c.getAttribute(a[1]) !== null : c.getAttribute(a[1]) === a[2]));
  };
  n.querySelector = sel => n.querySelectorAll(sel)[0] || null;
  return n;
}
const ids = {};
const doc = { getElementById: id => ids[id] || (ids[id] = node("div")), createElement: t => node(t) };
const posted = [];
const NEEDS = { run_id: "RUN-1", dispute_id: "PF-1", status: "needs_info", message: "m",
  questions: ["First question?", "Second question?"] };
const fetch = (url, opts) => {
  if (url.indexOf("/api/trips") === 0) return Promise.resolve({ ok: true, json: () => Promise.resolve(
    { trips: [{ trip_id: "TRIP-X", label: "A trip", date: "2026-09-01", kind_label: "Ride", fare_sgd: 10, charge_label: "fare" }] }) });
  posted.push({ url: url, body: JSON.parse(opts.body) });
  if (url === "/api/disputes") return Promise.resolve({ ok: true, json: () => Promise.resolve(NEEDS) });
  return new Promise(() => {});
};
const tick = () => new Promise(r => setTimeout(r, 0));
(async () => {
  vm.runInNewContext(fs.readFileSync(process.env.PARTY_JS, "utf8"),
    { document: doc, window: { scrollTo() {} }, fetch, Promise, setTimeout, encodeURIComponent, JSON, Array, Number, isFinite, String });
  ids["category-options"].children.find(c => c.textContent === "My trip went the wrong way").click();
  ids["category-next"].click(); await tick(); await tick();
  ids["trip-options"].children[0].click(); ids["trip-next"].click();
  doc.getElementById("description").value = "The driver took a long detour.";
  doc.getElementById("claim-amount").value = "";
  doc.getElementById("details-form").fire("submit"); await tick(); await tick(); await tick();
  const boxes = ids["question-boxes"];
  const buttons = boxes.querySelectorAll("button").filter(b => b.textContent === process.env.NOTHING);
  const areas = boxes.querySelectorAll("textarea");
  const before = areas.map(a => a.value);
  if (buttons.length > 1) buttons[1].click();
  const afterOne = areas.map(a => a.value);
  if (areas.length) areas[0].value = "My own words";
  ids["answers-submit"].click(); await tick();
  const answer = posted.find(p => p.url.indexOf("/answers") >= 0);
  process.stdout.write(JSON.stringify({ buttons: buttons.length, types: buttons.map(b => b.type), areas: areas.length,
    before, afterOne, answer: answer ? answer.body : null, url: answer ? answer.url : null }));
})().catch(e => { process.stderr.write(String(e.stack || e)); process.exit(1); });
"""


class NothingMoreButtonBehaviour(unittest.TestCase):
    def _drive(self):
        node = shutil.which("node")
        if not node:
            raise AssertionError("Node is required for the party-page behavioural pins")
        env = dict(os.environ, PARTY_JS=str(PARTY_UI / "party.js"), NOTHING=NOTHING)
        result = subprocess.run([node, "-e", _HARNESS], env=env, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            raise AssertionError("party.js harness failed: " + result.stderr)
        return json.loads(result.stdout)

    def test_each_question_box_gets_a_button_that_fills_only_its_box(self):
        out = self._drive()
        self.assertEqual(2, out["areas"])
        self.assertEqual(2, out["buttons"], "one button per round-two question")
        self.assertEqual(["button", "button"], out["types"], "never a submit button inside the form")
        self.assertEqual(["", ""], out["before"])
        self.assertEqual(["", NOTHING], out["afterOne"])
        self.assertEqual("/api/disputes/RUN-1/answers", out["url"])
        self.assertEqual(["My own words", NOTHING], [a["answer"] for a in out["answer"]["answers"]])


class StatusPage(unittest.TestCase):
    def test_status_html_carries_the_demo_account(self):
        html = _read("status.html")
        text = html_text(html)
        self.assertIn("Demo account", text)
        self.assertIn(STATUS_SENTENCE, text)
        self.assertRegex(html, r"""<script[^>]+src=["'](?:\./)?status\.js["']""")

    def test_status_js_uses_the_three_endpoints_and_the_button(self):
        code = strip_js_comments(_read("status.js"))
        self.assertIn("/api/demo/rider", code)
        self.assertRegex(code, r"""["']/api/disputes/["']""")
        self.assertIn("/answers", code)
        _labels_a_button_and_fills_a_box(self, code, NOTHING)
        self.assertRegex(code, r"""(?:element|createElement)\(\s*["']textarea["']""")

    def test_the_form_page_links_to_the_status_page(self):
        html = _read("index.html")
        header = re.search(r"<header[\s\S]*?</header>", html)
        outcome = re.search(r"<section[^>]*id=\"outcome\"[\s\S]*?</section>", html)
        self.assertIsNotNone(header)
        self.assertIsNotNone(outcome)
        link = r"""<a\s[^>]*href=["'](?:\./|/party/)?status\.html["']"""
        self.assertRegex(header.group(0), link)
        self.assertRegex(outcome.group(0), link)


class DriverPage(unittest.TestCase):
    def test_driver_html_is_read_only_and_labelled(self):
        html = _read("driver.html")
        text = html_text(html)
        self.assertIn("Demo account", text)
        self.assertIn(DRIVER_SENTENCE, text)
        self.assertRegex(html, r"""<script[^>]+src=["'](?:\./)?driver\.js["']""")
        for tag in ("<form", "<textarea", "<input"):
            self.assertNotIn(tag, html.lower())

    def test_driver_js_never_answers(self):
        code = strip_js_comments(_read("driver.js"))
        self.assertIn("/api/demo/driver", code)
        for banned in ("/answers", "textarea", "POST", "form", NOTHING):
            with self.subTest(banned=banned):
                self.assertNotIn(banned, code)


class NewPagesAreServed(unittest.TestCase):
    def test_both_pages_are_served(self):
        server = Server()
        try:
            for path in ("/party/status.html", "/party/driver.html", "/party/status.js", "/party/driver.js"):
                status, headers, raw = server.raw("GET", path)
                with self.subTest(path=path):
                    self.assertEqual(200, status)
                    self.assertTrue(raw)
        finally:
            server.close()


class NewPagesSpeakPlainly(unittest.TestCase):
    """The plain-vocabulary and textContent-only rules, extended to the new files by name."""

    def test_no_injection_sinks(self):
        for name in ("party.js", "status.js", "driver.js"):
            text = _read(name)
            for sink in SINKS:
                with self.subTest(file=name, sink=sink):
                    self.assertNotIn(sink, text)

    def test_no_internal_vocabulary(self):
        from app.schemas import PARTY_UNSAFE_PATTERN, PARTY_UNSAFE_RULE_ID_PATTERN

        for name in NEW_FILES:
            text = _read(name)
            if name.endswith(".html"):
                shown = html_text(text)
            else:
                pairs = re.findall(r"\"([^\"\\]*)\"|'([^'\\]*)'", strip_js_comments(text))
                shown = " ".join(a or b for a, b in pairs)
            with self.subTest(file=name):
                self.assertIsNone(PARTY_UNSAFE_PATTERN.search(shown), PARTY_UNSAFE_PATTERN.findall(shown))
                self.assertIsNone(PARTY_UNSAFE_RULE_ID_PATTERN.search(shown))


if __name__ == "__main__":
    unittest.main()
