"""Session nine acceptance target: W10 token pass — the Ryde visual rebrand of ui/party/.

RED until the CodeBuddy build lane ships docs/build-briefs/session-nine-brief.md; then hardened in
the review-fix round after the a second-model review found the original tests were
false-green (whole-file greps satisfied by decoy rules and comments).

Round-two rulings (2026-09-25, the operator):
  * --muted darkened #6B7480 -> #5A6470 (AA on the pastel canvas: 4.70, on white 6.01).
  * Tests pin the RULE, not the string: each assertion targets a specific selector's
    declaration block, so a decoy rule or a comment cannot satisfy it.
  * Old-token ban extended to the sixth plain-theme value #a03024 (old --error).

Design tokens are Ryde's real brand system, cross-checked from the private design
reference (research/ryde-design/, planning repo — never ships here).
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from tests.test_party_surface import FORBIDDEN_PARTY_WORDS

REPO = Path(__file__).resolve().parent.parent
PARTY_UI = REPO / "ui" / "party"
# W35 (2026-10-08): PARTY_JS_SHA released. W35 changes party.js (step 3 summary, pending
# send); tests/test_w35_P.py pins the new behaviour instead.

ROOT_TOKENS = [("--ink", "#31373e"), ("--muted", "#5a6470"), ("--line", "#e5e0dc"),
               ("--paper", "#f7dde3"), ("--accent", "#e93864"), ("--error", "#c0392b"),
               ("--ok", "#1eb848")]
OLD_PLAIN_TOKENS = ["#0f6b5f", "#f6f8fa", "#1d2733", "#5c6b7a", "#d8dfe6", "#a03024"]
REQUIRED_IDS = ["form-steps", "step-category", "category-options", "category-error",
                "category-next", "step-trip", "trip-options", "trip-error", "trip-back",
                "trip-next", "step-details", "details-form", "question-list", "description",
                "claim-amount", "details-error", "details-back", "details-submit",
                "outcome", "outcome-title", "outcome-reference", "outcome-message",
                "outcome-questions", "question-boxes", "answers-error", "answers-submit",
                "outcome-status"]
# W35 releases only these four additions from the old no-new-id freeze. Their presence,
# exact structure and behaviour are required by tests/test_w35_P.py, not this older test.
W35_ALLOWED_IDS = {"summary-category", "summary-trip", "details-status", "details-spinner"}


def _strip_comments(css: str) -> str:
    """Remove /* ... */ comments so a token named in a comment cannot pass a check."""
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _block(css: str, selector: str) -> str:
    """Return the declaration block of the rule whose selector list contains
    `selector` as a whole selector (not a substring). Raises if not found, so a
    renamed rule reads as a missing rule instead of a silent pass."""
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        selectors = [s.strip() for s in m.group(1).split(",")]
        if selector in selectors:
            return m.group(2)
    raise AssertionError(f"no CSS rule found for selector {selector!r}")


class RebrandTokensTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.css = _strip_comments((PARTY_UI / "party.css").read_text(encoding="utf-8")).lower()
        cls.html = (PARTY_UI / "index.html").read_text(encoding="utf-8")

    # -- token values, pinned to the :root block itself ----------------------

    def test_root_block_carries_the_ryde_tokens(self):
        root = _block(self.css, ":root")
        for var, value in ROOT_TOKENS:
            self.assertIn(f"{var}: {value}", root, f":root must set {var}: {value}")

    def test_muted_meets_aa_on_pastel_canvas(self):
        # #5A6470 on #F7DDE3 = 4.70:1. Pin the exact value so a future lightening
        # of --muted (the review's AA finding) goes red instead of silently passing.
        root = _block(self.css, ":root")
        self.assertRegex(root, r"--muted:\s*#5a6470\b")

    def test_old_plain_theme_gone(self):
        for token in OLD_PLAIN_TOKENS:
            self.assertNotIn(token, self.css, f"stale plain-theme token {token} still present")

    def test_old_selected_ring_gone(self):
        self.assertNotIn("rgba(15, 107, 95", self.css)

    # -- typography, pinned to the body rule ----------------------------------

    def test_body_font_stack_is_poppins_with_fallback(self):
        body = _block(self.css, "body")
        m = re.search(r"font-family:\s*([^;]+);", body)
        self.assertIsNotNone(m, "body must declare font-family")
        stack = m.group(1)
        self.assertTrue(stack.strip().lower().startswith("poppins"),
                        f"Poppins must lead the stack, got: {stack!r}")
        self.assertIn("sans-serif", stack, "fallback generic must remain in the stack")

    def test_index_links_poppins_webfont(self):
        links = re.findall(r"<link[^>]*>", self.html)
        self.assertTrue(any("fonts.googleapis.com" in l and "family=poppins" in l.lower()
                            for l in links),
                        "a real Poppins stylesheet link must exist (comments do not count)")

    # -- shape, pinned to the named rules -------------------------------------

    def test_button_rule_is_pill(self):
        btn = _block(self.css, "button")
        m = re.search(r"border-radius:\s*([\d.]+)px", btn)
        self.assertIsNotNone(m, "button rule must declare border-radius")
        self.assertGreaterEqual(float(m.group(1)), 28.0,
                                f"button must be a pill (>=28px), got {m.group(1)}px")

    def test_step_rule_card_radius(self):
        step = _block(self.css, ".step")
        m = re.search(r"border-radius:\s*([\d.]+)px", step)
        self.assertIsNotNone(m, ".step rule must declare border-radius")
        self.assertTrue(12.0 <= float(m.group(1)) <= 20.0,
                        f".step card radius must be 12-20px, got {m.group(1)}px")

    def test_option_card_and_input_radius(self):
        # W15 layout pass (the operator, 2026-10-05): option cards sit at the top of the app
        # reference's 12-16px card range (16px); inputs stay at 14px.
        for sel, want in [(".option-card", "16.0"), ("input[type=\"number\"]", "14.0")]:
            block = _block(self.css, sel)
            m = re.search(r"border-radius:\s*([\d.]+)px", block)
            self.assertIsNotNone(m, f"{sel} must declare border-radius")
            self.assertEqual(float(m.group(1)), float(want),
                            f"{sel} radius must be {want}px, got {m.group(1)}px")

    def test_selected_ring_uses_tint(self):
        # W15: the selected card now fills with the tint token (the app's selected
        # ride-row treatment) instead of a ring shadow; the literal lives in :root.
        sel = _block(self.css, ".option-card.selected")
        self.assertIn("background: var(--tint)", sel,
                      ".option-card.selected must fill with var(--tint)")
        root = _block(self.css, ":root")
        self.assertRegex(root, r"--tint:\s*#fff0f3\b",
                         ":root must define --tint as the #FFF0F3 tint")

    # -- freezes ----------------------------------------------------------------

    def test_dom_ids_unchanged(self):
        """Every id present at build head 29ba78e must still exist, and no NEW id
        may appear except the four W35 additions (required by test_w35_P)."""
        ids_now = set(re.findall(r'id="([^"]+)"', self.html))
        missing = set(REQUIRED_IDS) - ids_now
        self.assertEqual(set(), missing, f"required ids removed: {missing}")
        extra = ids_now - set(REQUIRED_IDS) - W35_ALLOWED_IDS
        self.assertEqual(set(), extra, f"new ids appeared: {extra}")

    def test_forbidden_words_absent(self):
        text = self.html + self.css
        match = FORBIDDEN_PARTY_WORDS.search(text)
        self.assertIsNone(match, f"system vocabulary leaked: {match.group(0) if match else ''}")


if __name__ == "__main__":
    unittest.main()