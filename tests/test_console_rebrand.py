"""Session thirteen acceptance target: W18 console token pass + W17 selected-choice outline.

RED until the CodeBuddy build lane ships docs/session-thirteen-brief.md.

W18 (the operator ruling 2026-09-27): the operator console wears the Ryde theme as a TOKEN PASS
(colour, type, shape only) on a NEUTRAL canvas. The status colours keep their meaning:
green = delivered, amber = withheld / human-only, red = error, blue = informational
routing (human review, needs info). Ryde pink is chrome only, so a withheld ruling never
blurs into the brand colour.

W17 (the operator ruling 2026-09-27): on the party form the selected Yes/No button keeps the pink
outline; before this it only appeared on hover.

Written to the project's standing rule: pin the RULE, not the string. Every assertion
targets a named selector's declaration blocks with comments stripped, so a decoy rule
or a comment cannot satisfy it.
"""
from __future__ import annotations

import hashlib
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
UI = REPO / "ui"

APP_JS_SHA = "abde2b1516912330a508d1c786c256db65bac4e3d51019b73b4c3442090dedfa"

CONSOLE_IDS = {
    "loader-title", "case-picker", "run-folder-picker", "load-status", "payload-status",
    "case-workspace", "case-summary", "summary-title", "loaded-file", "metadata-list",
    "grievance-section", "grievance-title", "grievance-content", "evidence-section",
    "evidence-title", "evidence-content", "prompts-section", "prompts-title", "prompts-content",
    "claims-section", "claims-title", "claims-content",
    "policy-content", "resolution-section", "resolution-title", "resolution-content",
    "events-section", "events-title", "events-content",
    "queue-panel", "queue-title", "queue-refresh", "queue-status", "queue-content",
    "overrides-panel", "overrides-title", "overrides-status", "overrides-content",
    "decision-section", "decision-title", "decision-content",
}

# New :root values. Brand values from the private design reference; derived values are
# our own picks for WCAG AA contrast on the neutral canvas.
ROOT_TOKENS = [
    ("--ink", "#31373e"),          # brand ink (was #182334)
    ("--muted", "#5a6470"),        # derived, same as party page
    ("--faint", "#646c77"),        # derived, AA 4.84 on canvas (old #8b96a8 was 2.74)
    ("--line", "#e5e0dc"),         # derived warm grey, same as party page
    ("--panel", "#ffffff"),
    ("--canvas", "#f5f4f3"),       # derived NEUTRAL warm grey, deliberately not pink
    ("--accent", "#e93864"),       # brand pink: rules, borders, fills
    ("--accent-text", "#c8284f"),  # derived pink for small TEXT, AA 4.94 on canvas
    ("--accent-wash", "#fff0f3"),  # brand pink tint
]
# Status tokens keep their exact values: the colours carry meaning, not brand.
STATUS_TOKENS = [
    ("--blue", "#2a638c"), ("--blue-wash", "#edf5fa"),
    ("--amber", "#9b5c18"), ("--amber-wash", "#fff6e8"),
    ("--red", "#a33f3f"), ("--red-wash", "#fff0ef"),
    ("--green", "#2e6b51"), ("--green-wash", "#edf7f0"),
]
# Old chrome values that must be gone from the whole stylesheet.
OLD_CHROME = ["#213b5a", "#657085", "#8b96a8", "#d7dee8", "#f3f5f8"]

# Console chrome: every one of these rules used the blue as decoration. Each must now
# take the Ryde accent and drop the blue family entirely.
CHROME_SELECTORS = [
    ".loader-panel", ".header-note", ".section-index", ".grievance-marker",
    "#load-status[data-state=\"loading\"]",
]
# Blue's own hover/border tints, which would betray a half-done swap.
BLUE_FAMILY = ["var(--blue)", "var(--blue-wash)", "#b9d3e3", "#dceef7", "#c9deeb"]

# Status rules that must keep their meaning colour (and must NOT take the accent).
STATUS_SELECTORS = [
    (".outcome-ruled", "var(--green)"), (".outcome-ruled-badge", "var(--green)"),
    (".outcome-withheld", "var(--amber)"), (".outcome-withheld-badge", "var(--amber)"),
    (".human-only-region", "var(--amber)"), (".party-facing-region", "var(--amber)"),
    (".outcome-human-review", "var(--blue)"), (".outcome-needs-info", "var(--blue)"),
    (".routing-explanation", "var(--blue)"), (".citation-unresolved", "var(--red)"),
    # W18 round two: the delivered message is green only on the ruled card, the
    # withheld message stays amber, and the two remaining genuine amber cases hold.
    (".outcome-ruled .party-message", "var(--green)"),
    (".outcome-ruled .party-message-label", "var(--green)"),
    (".party-facing-region .party-message", "var(--amber)"),
    (".event-internal", "var(--amber)"), (".citation-null", "var(--amber)"),
]

# W18 round two (the operator ruling 2026-09-27): colour is reserved for status. These surfaces
# carry no status meaning, so they must be neutral: no brand accent, no status token,
# and no chromatic hard-coded colour. Found by a live colour audit of all four outcomes.
NEUTRAL_SELECTORS = [
    ".claim-card", ".claim-card-header", ".claim-text",               # both advocates, the quote
    ".info-row.highlight dd", ".request-grid .info-row.highlight dd",  # money amounts
    ".resolution-metrics .info-row.highlight dd",
    ".evidence-field.has-null", ".field-value.is-null",                # missing data
    ".evidence-note", ".note-label",
    ".deliberate-empty", ".deliberate-empty h3", ".deliberate-empty p",  # expected absence
    ".policy-item",                                                    # policy rule list
    ".party-message", ".party-message-label",                          # base message box
    # W18 round three (the operator ruling 2026-09-27): brand pink in dense, repeated UI reads as
    # error red (#c8284f vs --red #a33f3f). The agent-traffic log and the citation chips
    # go neutral; only the withheld event row (amber) and the null/unresolved chips
    # (amber/red) keep a colour, so they are the only things that stand out.
    ".event-seq", ".event-actor", ".event-row summary::before",
    ".citation", ".citation:hover",
]
# The driver advocate must not be styled apart from the rider: these rules may be
# deleted, but if present they may not set any colour, background or border.
DRIVER_OVERRIDES = [".claim-driver", ".claim-driver .claim-card-header"]
STATUS_TOKEN_RE = re.compile(r"var\(--(accent|amber|green|blue|red)[\w-]*\)")


def _strip_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _blocks(css: str, selector: str) -> list[str]:
    """Every declaration block whose selector list contains `selector` as a whole
    selector. Raises when none exists, so a renamed rule reads as missing."""
    found = []
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        selectors = [" ".join(s.split()) for s in m.group(1).split(",")]
        if selector in selectors:
            found.append(m.group(2))
    if not found:
        raise AssertionError(f"no CSS rule found for selector {selector!r}")
    return found


def _root(css: str) -> dict[str, str]:
    block = _blocks(css, ":root")[0]
    return {k: v.strip() for k, v in re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", block)}


def _luminance(hex_value: str) -> float:
    h = hex_value.lstrip("#")
    channels = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _contrast(a: str, b: str) -> float:
    la, lb = _luminance(a), _luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def _chromatic_hexes(body: str) -> list[str]:
    """Hard-coded hex colours with a visible hue (channel spread > 8). Pure greys, whites
    and near-greys pass; tinted washes like #dcefe3, #fff6e8 or #e7c58f do not. The
    threshold is low on purpose: a light wash has a small spread but still reads as a
    colour (a 24 threshold let #dcefe3 through in the round-two mutation battery)."""
    found = []
    for h in re.findall(r"#([0-9a-f]{6}|[0-9a-f]{3})\b", body):
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        ch = [int(h[i:i + 2], 16) for i in (0, 2, 4)]
        if max(ch) - min(ch) > 8:
            found.append("#" + h)
    return found


class ConsoleTokensTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.css = _strip_comments((UI / "styles.css").read_text(encoding="utf-8")).lower()
        cls.html = (UI / "index.html").read_text(encoding="utf-8")
        cls.root = _root(cls.css)

    def test_root_carries_the_ryde_tokens(self):
        for var, value in ROOT_TOKENS:
            self.assertEqual(value, self.root.get(var), f":root must set {var}: {value}")

    def test_status_tokens_keep_their_values(self):
        for var, value in STATUS_TOKENS:
            self.assertEqual(value, self.root.get(var), f"status token {var} must stay {value}")

    def test_canvas_is_neutral_not_pink(self):
        canvas = self.root.get("--canvas", "")
        self.assertNotEqual("#f7dde3", canvas, "the console canvas is neutral by the operator's ruling")
        body = " ".join(_blocks(self.css, "body"))
        self.assertIn("var(--canvas)", body, "body must paint the neutral canvas")

    def test_navy_token_retired(self):
        self.assertNotIn("--navy", self.css, "--navy is replaced by --ink everywhere")

    def test_old_chrome_values_gone(self):
        for value in OLD_CHROME:
            self.assertNotIn(value, self.css, f"stale console chrome value {value} still present")

    def test_text_tokens_meet_aa(self):
        """Every text colour must reach 4.5:1 on each surface it sits on."""
        surfaces = [self.root["--canvas"], self.root["--panel"]]
        for var in ["--ink", "--muted", "--faint", "--accent-text"]:
            for surface in surfaces:
                ratio = _contrast(self.root[var], surface)
                self.assertGreaterEqual(ratio, 4.5, f"{var} on {surface} is {ratio:.2f}:1")
        ratio = _contrast(self.root["--accent-text"], self.root["--accent-wash"])
        self.assertGreaterEqual(ratio, 4.5, f"--accent-text on --accent-wash is {ratio:.2f}:1")

    # -- typography -------------------------------------------------------------

    def test_font_stack_is_poppins_with_fallback(self):
        stacks = re.findall(r"font-family:\s*([^;]+);", " ".join(_blocks(self.css, ":root")))
        self.assertTrue(stacks, ":root must declare the base font-family")
        self.assertTrue(stacks[0].strip().startswith("poppins"),
                        f"Poppins must lead the base stack, got {stacks[0]!r}")
        self.assertIn("sans-serif", stacks[0], "a generic fallback must remain")

    def test_index_links_poppins_webfont(self):
        html = re.sub(r"<!--.*?-->", "", self.html, flags=re.S)
        links = re.findall(r"<link[^>]*>", html)
        self.assertTrue(any("fonts.googleapis.com" in l and "family=poppins" in l.lower()
                            for l in links),
                        "a real Poppins stylesheet link must exist (comments do not count)")

    # -- chrome takes the accent, status keeps its meaning ----------------------

    def test_chrome_rules_take_the_accent(self):
        for selector in CHROME_SELECTORS:
            body = " ".join(_blocks(self.css, selector))
            self.assertIn("var(--accent", body, f"{selector} must use the Ryde accent")
            for blue in BLUE_FAMILY:
                self.assertNotIn(blue, body, f"{selector} still carries {blue}")

    def test_status_rules_keep_their_colour(self):
        for selector, colour in STATUS_SELECTORS:
            body = " ".join(_blocks(self.css, selector))
            self.assertIn(colour, body, f"{selector} must keep {colour}")
            self.assertNotIn("var(--accent", body,
                             f"{selector} is a status colour and must not take the brand accent")

    # -- round two: colour only where it carries status --------------------------

    def test_non_status_surfaces_are_neutral(self):
        for selector in NEUTRAL_SELECTORS:
            body = " ".join(_blocks(self.css, selector))
            token = STATUS_TOKEN_RE.search(body)
            self.assertIsNone(token, f"{selector} carries no status and must not use {token and token.group(0)}")
            chroma = _chromatic_hexes(body)
            self.assertEqual([], chroma, f"{selector} hard-codes a chromatic colour {chroma}")

    def test_driver_advocate_is_not_styled_apart(self):
        for selector in DRIVER_OVERRIDES:
            try:
                body = " ".join(_blocks(self.css, selector))
            except AssertionError:
                continue  # deleted outright is fine
            self.assertNotRegex(body, r"(color|background|border)[\w-]*\s*:",
                                f"{selector} must not colour the driver's side differently")

    def test_policy_citations_are_not_green(self):
        """Green means delivered; a policy chip is not a delivery."""
        for selector in [".citation-policy", ".citation-policy:hover"]:
            try:
                body = " ".join(_blocks(self.css, selector))
            except AssertionError:
                continue  # deleted outright is fine (session sixteen removed the empty rules)
            self.assertIsNone(re.search(r"var\(--green[\w-]*\)", body), f"{selector} must not be green")
            self.assertEqual([], [h for h in _chromatic_hexes(body)], f"{selector} hard-codes a chromatic colour")

    def test_focus_ring_is_the_accent(self):
        body = " ".join(_blocks(self.css, "button:focus-visible"))
        self.assertIn("var(--accent)", body, "the focus ring must use the Ryde accent")
        self.assertNotIn("42, 99, 140", body, "the old blue focus ring must be gone")

    def test_headings_use_ink(self):
        for selector in ["h1", "h2", "h3"]:
            body = " ".join(_blocks(self.css, selector))
            self.assertIn("var(--ink)", body, f"{selector} must be set in --ink")

    # -- shape --------------------------------------------------------------------

    def test_section_cards_are_rounded(self):
        body = " ".join(_blocks(self.css, ".story-section"))
        m = re.search(r"border-radius:\s*([\d.]+)px", body)
        self.assertIsNotNone(m, ".story-section must declare border-radius")
        self.assertTrue(12.0 <= float(m.group(1)) <= 20.0,
                        f".story-section radius must be 12-20px, got {m.group(1)}px")

    def test_citations_are_pills(self):
        body = " ".join(_blocks(self.css, ".citation"))
        m = re.search(r"border-radius:\s*([\d.]+)px", body)
        self.assertIsNotNone(m, ".citation must declare border-radius")
        self.assertGreaterEqual(float(m.group(1)), 12.0, f".citation must be a pill, got {m.group(1)}px")

    # -- freezes --------------------------------------------------------------------

    def test_app_js_unchanged(self):
        digest = hashlib.sha256((UI / "app.js").read_bytes()).hexdigest()
        self.assertEqual(APP_JS_SHA, digest, "app.js must stay byte-identical in the token pass")

    def test_console_ids_unchanged(self):
        ids_now = set(re.findall(r'id="([^"]+)"', self.html))
        self.assertEqual(CONSOLE_IDS, ids_now, "no id may be added, renamed or removed")


class PartyChoiceOutlineTest(unittest.TestCase):
    """W17: selection, not the pointer, carries the pink outline."""

    @classmethod
    def setUpClass(cls):
        cls.css = _strip_comments((UI / "party" / "party.css").read_text(encoding="utf-8")).lower()

    def test_selected_choice_carries_the_accent_border(self):
        body = " ".join(_blocks(self.css, ".choice-button.selected"))
        self.assertRegex(body, r"border-color:\s*var\(--accent\)",
                         "the selected Yes/No button must keep the pink outline")

    def test_hover_rule_still_exists(self):
        body = " ".join(_blocks(self.css, ".choice-button:hover"))
        self.assertIn("var(--accent)", body, "hover feedback stays")


if __name__ == "__main__":
    unittest.main()
