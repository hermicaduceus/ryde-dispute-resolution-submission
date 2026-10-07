"""W15 acceptance target: full-layout restyle of the party pages.

RED until the CodeBuddy build lane ships docs/build-briefs/w15-brief.md. The layout
values are the Ryde design reference's real ones (private reference,
research/ryde-design/ in the planning repo — never ships here):
  * generous canvas and page rhythm (720px shell, 2.25rem h1)
  * white floating cards on the pastel canvas (20px radius, soft shadow
    0 8px 24px rgba(0,0,0,0.08) — the app lane's floating-card shadow)
  * the eyebrow reads as a pill chip (tint fill, accent border, 9999px)
  * selected option = the app's selected ride-row treatment: #FFF0F3
    fill + 2px accent border, not a ring
  * normal-flow step actions, following the operator's reviewed W15 repair ruling:
    in-card (white bg, top border, card's bottom radius), never covering options
  * primary CTA weight 600, larger pill padding
  * inputs 14px radius with a #FFF0F3 focus halo

Rules pinned like the W10 rebrand tests: every assertion targets one
selector's own declaration block with comments stripped, so a decoy rule
or a comment cannot satisfy a check.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PARTY_UI = REPO / "ui" / "party"
PAGES = ["index.html", "driver-filing.html", "status.html", "driver.html"]


def _strip_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _block(css: str, selector: str) -> str:
    """Declaration block of the rule whose selector list contains `selector`
    as a whole selector. Raises when absent so a renamed rule reads as a
    missing rule, never a silent pass."""
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        selectors = [s.strip() for s in m.group(1).split(",")]
        if selector in selectors:
            return m.group(2)
    raise AssertionError(f"no CSS rule found for selector {selector!r}")


def _decl(block: str, prop: str) -> str:
    m = re.search(rf"{prop}\s*:\s*([^;]+);", block)
    if m is None:
        raise AssertionError(f"declaration {prop} not found in block: {block!r}")
    return " ".join(m.group(1).split())


class W15LayoutTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.css = _strip_comments((PARTY_UI / "party.css").read_text(encoding="utf-8")).lower()
        cls.raw_css = (PARTY_UI / "party.css").read_text(encoding="utf-8")

    # -- canvas and page rhythm -----------------------------------------------

    def test_party_shell_is_the_w15_canvas(self):
        shell = _block(self.css, ".party-shell")
        self.assertEqual("720px", _decl(shell, "max-width"),
                         "the shell widens to 720px in the layout pass")
        self.assertRegex(_decl(shell, "padding"), r"2\.5rem\s+1\.25rem\s+5rem",
                         "page rhythm: 2.5rem top, 5rem bottom padding")

    def test_h1_is_the_display_size(self):
        h1 = _block(self.css, ".party-header h1")
        self.assertEqual("2.25rem", _decl(h1, "font-size"),
                         "h1 grows to 2.25rem in the layout pass")

    # -- the eyebrow reads as a pill chip --------------------------------------

    def test_eyebrow_is_a_pill_chip(self):
        eb = _block(self.css, ".party-header .eyebrow")
        self.assertEqual("9999px", _decl(eb, "border-radius"),
                         "the eyebrow must be a pill chip")
        self.assertIn("var(--tint)", _decl(eb, "background"),
                      "chip fill is the tint token")
        self.assertIn("var(--accent)", _decl(eb, "border"),
                      "chip border is the accent token")
        self.assertIn("var(--accent)", _decl(eb, "color"),
                      "chip text is the accent token")

    # -- floating cards on the pastel canvas -----------------------------------

    def test_step_is_a_floating_card(self):
        step = _block(self.css, ".step")
        self.assertEqual("20px", _decl(step, "border-radius"),
                         ".step radius moves to the site's 20px card corner")
        self.assertRegex(_decl(step, "box-shadow"),
                         r"var\(--float-shadow\)",
                         ".step must float via the shadow token")
        self.assertRegex(_decl(step, "padding"), r"1\.5rem",
                         ".step padding grows to 1.5rem")
        self.assertRegex(_decl(step, "margin-bottom"), r"1\.5rem",
                         "section gap grows to 1.5rem")

    def test_float_shadow_token_matches_the_app_lane(self):
        root = _block(self.css, ":root")
        self.assertRegex(
            root,
            r"--float-shadow:\s*0 8px 24px rgba\(0,\s*0,\s*0,\s*0\.08\)",
            ":root must define the app lane's floating-card shadow",
        )

    # -- selected option = the app's selected ride-row -------------------------

    def test_selected_option_fills_with_tint_and_accent_border(self):
        sel = _block(self.css, ".option-card.selected")
        self.assertIn("var(--tint)", _decl(sel, "background"),
                      "selected fill is the tint")
        self.assertRegex(_decl(sel, "border"), r"2px solid var\(--accent\)",
                         "selected border is 2px accent")
        root = _block(self.css, ":root")
        self.assertRegex(root, r"--tint:\s*#fff0f3\b",
                         ":root must define --tint as #FFF0F3")

    # -- hover lift ------------------------------------------------------------

    def test_option_card_hover_lifts(self):
        hov = _block(self.css, ".option-card:hover")
        self.assertRegex(_decl(hov, "transform"), r"translatey\(-2px\)",
                         "hover must lift the card")
        self.assertRegex(_decl(hov, "box-shadow"), r"var\(--float-shadow\)",
                         "hover must add the floating shadow")

    # -- normal-flow step actions (the operator's W15 repair ruling, in-card) -------------

    def test_step_actions_remain_in_normal_flow(self):
        sa = _block(self.css, ".step-actions")
        self.assertEqual("static", _decl(sa, "position"),
                         ".step-actions must not cover form options at any width")
        self.assertNotRegex(sa, r"\bbottom\s*:",
                            "the obsolete sticky bottom offset is removed")
        self.assertIn("var(--card)", _decl(sa, "background"),
                      "action bar keeps the card surface")
        self.assertRegex(_decl(sa, "border-top"), r"1px solid var\(--line\)",
                         "action bar retains its top rule")
        self.assertRegex(_decl(sa, "border-radius"), r"0 0 20px 20px",
                         "action bar retains the card's bottom radius")

    # -- CTA and inputs -----------------------------------------------------------

    def test_primary_cta_weight_and_padding(self):
        btn = _block(self.css, "button")
        self.assertRegex(_decl(btn, "font-weight"), r"600",
                         "buttons read as 600 weight in the layout pass")
        self.assertRegex(_decl(btn, "padding"), r"0\.7rem\s+1\.5rem",
                         "button padding grows to the reference's generous pill")

    def test_input_radius_and_focus_halo(self):
        inp = _block(self.css, 'input[type="number"]')
        self.assertEqual("14px", _decl(inp, "border-radius"),
                         "inputs round at 14px")
        focus = _block(self.css, "input:focus")
        self.assertRegex(_decl(focus, "box-shadow"), r"var\(--tint\)",
                         "focus halo uses the tint token")

    # -- demo note becomes a soft chip -------------------------------------------

    def test_demo_note_is_a_soft_chip(self):
        dn = _block(self.css, ".demo-note")
        self.assertIn("var(--tint)", _decl(dn, "background"),
                      "demo note chip fill is the tint")
        self.assertRegex(_decl(dn, "border-radius"), r"14px",
                         "demo note chip rounds at 14px")

    # -- scope guards --------------------------------------------------------------

    def test_layout_rules_are_scoped_to_party_css_only(self):
        """The layout pass must not touch the operator console's sheet."""
        console = (REPO / "ui" / "styles.css").read_text(encoding="utf-8")
        for token in ["--float-shadow", "position: sticky"]:
            self.assertNotIn(token, console,
                             f"console stylesheet gained a party layout token: {token}")

    def test_all_four_party_pages_use_the_restyled_shell(self):
        for page in PAGES:
            with self.subTest(page=page):
                html = (PARTY_UI / page).read_text(encoding="utf-8")
                self.assertIn("party-shell", html, f"{page} must keep the shell class")
                # Exact link, not a substring: "./party.css.bak" contains "party.css".
                links = re.findall(r'<link[^>]*href="([^"]+)"', html)
                self.assertIn("./party.css", links,
                              f"{page} must link the restyled sheet by its exact href")

    def test_party_js_unchanged_by_the_layout_pass(self):
        import hashlib
        # The two digest freezes (test_party_rebrand, test_w12_demo_notice) pin the
        # bytes; this test pins that the layout pass never edits the file at all by
        # requiring the builder to leave it byte-identical to main.
        digest = hashlib.sha256((PARTY_UI / "party.js").read_bytes()).hexdigest()
        # The expected digest equals main's committed party.js (4683f65).
        self.assertEqual(
            "90d55dbf1730f9991234cc2772cae27051cf4c2f5d43d6fca96e7ce54ef7efc0", digest,
            "party.js must stay byte-identical through the layout pass")


if __name__ == "__main__":
    unittest.main()