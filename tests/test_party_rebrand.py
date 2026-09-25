"""Session nine acceptance target: W10 token pass — the Ryde visual rebrand of ui/party/.

RED until the CodeBuddy build lane ships docs/session-nine-brief.md.

Rulings behind it (2026-09-25, the operator):
  * Token pass only: color, typography, shape. No layout restructure, no copy change,
    no behaviour change. party.js must stay byte-identical (pinned by SHA below).
  * Full-layout restyle is a named conditional follow-up after W3 (not this session).
Design tokens are Ryde's real brand system, cross-checked from the private design
reference (research/ryde-design/, planning repo — never ships here).
"""
from __future__ import annotations

import hashlib
import re
import unittest
from pathlib import Path

from tests.test_party_surface import FORBIDDEN_PARTY_WORDS

REPO = Path(__file__).resolve().parent.parent
PARTY_UI = REPO / "ui" / "party"
# sha256 of ui/party/party.js at build head 29ba78e — the behaviour freeze pin.
PARTY_JS_SHA = "7f8cfc8508f1ac9a8e899d446ea353f5de0c34ccacbee71e3d443ea4176edc88"

RYDE_TOKENS = ["#e93864", "#31373e", "#f7dde3", "#fff0f3", "#1eb848"]
OLD_PLAIN_TOKENS = ["#0f6b5f", "#f6f8fa", "#1d2733", "#5c6b7a", "#d8dfe6"]
REQUIRED_IDS = ["form-steps", "step-category", "step-trip", "step-details", "outcome",
                "category-options", "trip-options", "question-list", "description",
                "claim-amount", "details-form", "outcome-questions", "question-boxes"]


class RebrandTokensTest(unittest.TestCase):
    def setUp(self):
        self.css = (PARTY_UI / "party.css").read_text(encoding="utf-8").lower()
        self.html = (PARTY_UI / "index.html").read_text(encoding="utf-8")

    def test_ryde_tokens_present_in_css(self):
        for token in RYDE_TOKENS:
            self.assertIn(token, self.css, f"missing Ryde token {token}")

    def test_old_plain_theme_gone(self):
        for token in OLD_PLAIN_TOKENS:
            self.assertNotIn(token, self.css, f"stale plain-theme token {token} still present")

    def test_poppins_in_font_stack_with_fallback(self):
        self.assertRegex(self.css, r"font-family:[^;]*poppins")
        self.assertRegex(self.css, r"font-family:[^;]*sans-serif")

    def test_index_links_poppins_webfont(self):
        self.assertIn("fonts.googleapis.com", self.html)

    def test_pill_buttons(self):
        # at least one button rule carries a pill radius (>= 28px)
        button_blocks = re.findall(r"button[^{]*\{[^}]*\}", self.css, re.S)
        button_radii = [
            float(r)
            for block in button_blocks
            for r in re.findall(r"border-radius:\s*([\d.]+)px", block)
        ]
        self.assertTrue(
            button_radii and any(r >= 28 for r in button_radii),
            f"no pill radius (>=28px) on any button rule; found {button_radii}",
        )

    def test_step_card_radius_in_range(self):
        radii = [float(m) for m in re.findall(r"border-radius:\s*([\d.]+)px", self.css)]
        self.assertTrue(
            any(12 <= r <= 20 for r in radii),
            f"no card radius in 12-20px; found {radii}",
        )

    def test_party_js_unchanged(self):
        digest = hashlib.sha256((PARTY_UI / "party.js").read_bytes()).hexdigest()
        self.assertEqual(
            PARTY_JS_SHA, digest,
            "party.js must stay byte-identical in the token pass",
        )

    def test_no_new_dom_structure(self):
        for id_ in REQUIRED_IDS:
            self.assertIn(f'id="{id_}"', self.html, f"missing required id {id_}")

    def test_forbidden_words_absent(self):
        text = self.html + self.css
        match = FORBIDDEN_PARTY_WORDS.search(text)
        self.assertIsNone(
            match,
            f"system vocabulary leaked into party page: {match.group(0) if match else ''}",
        )


if __name__ == "__main__":
    unittest.main()