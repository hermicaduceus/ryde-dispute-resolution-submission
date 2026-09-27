"""Session eleven acceptance target: one step per screen (swap-in-place navigation).

RED until the CodeBuddy build lane ships docs/session-eleven-brief.md.

Operator ruling (the operator, 2026-09-27): minimize scrolling on the party page. Today the forward
transitions only SHOW the next section and leave the previous one on the page, so the form
grows downward and the rider scrolls. The fix: every transition, forward AND back, swaps the
visible section, and the page scrolls to the top on each forward swap. Each step is then a
dedicated page under the fixed header; the existing in-page Back buttons remain the only
navigation (no URL routing, no reloads).

What these tests pin (source-level, scoped to the handler body so a decoy call elsewhere in
the file cannot satisfy them — the false-green lesson from the session-nine review):
  * category Continue hides step-category, shows step-trip, scrolls to top
  * trip Continue hides step-trip, shows step-details, scrolls to top
  * trip Back shows step-category, hides step-trip
  * details Back hides step-details, shows step-trip
  * the category card click (R3 reset) keeps hiding both downstream steps

The rendered behaviour is then verified in a real browser by the planner lane.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PARTY_JS = REPO / "ui" / "party" / "party.js"


def _load() -> str:
    source = PARTY_JS.read_text(encoding="utf-8")
    assert source, "could not read ui/party/party.js"
    return source


def _handler_body(js: str, element_id: str, event: str = "click") -> str:
    """Return the balanced body of the addEventListener call for one element.

    Scoped extraction: the assertions below run against THIS body only, so a
    hide()/show() call belonging to a different handler cannot satisfy them.
    """
    pattern = (
        r'getElementById\("%s"\)\s*\.\s*addEventListener\(\s*"%s"\s*,\s*'
        r"function\s*\([^)]*\)\s*\{" % (re.escape(element_id), re.escape(event))
    )
    match = re.search(pattern, js)
    assert match, f"no {event} handler found for #{element_id}"
    depth = 1
    i = match.end()
    while depth > 0 and i < len(js):
        ch = js[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        i += 1
    body = js[match.end():i - 1]
    assert body, f"empty handler body for #{element_id}"
    return body


class ForwardTransitionsSwap(unittest.TestCase):
    """Forward must REPLACE the visible step, not append to it."""

    def test_category_continue_hides_the_category_step(self):
        body = _handler_body(_load(), "category-next")
        self.assertIn("hide(stepCategory)", body,
                      "category Continue must hide step-category (swap, not append)")
        self.assertIn("show(stepTrip)", body)

    def test_category_continue_scrolls_to_top(self):
        body = _handler_body(_load(), "category-next")
        self.assertRegex(body, r"scrollTo\s*\(\s*0\s*,\s*0\s*\)",
                         "the swap must land at the top of the new step's page")

    def test_trip_continue_hides_the_trip_step(self):
        body = _handler_body(_load(), "trip-next")
        self.assertIn("hide(stepTrip)", body,
                      "trip Continue must hide step-trip (swap, not append)")
        self.assertIn("show(stepDetails)", body)

    def test_trip_continue_scrolls_to_top(self):
        body = _handler_body(_load(), "trip-next")
        self.assertRegex(body, r"scrollTo\s*\(\s*0\s*,\s*0\s*\)")


class BackTransitionsStillSwap(unittest.TestCase):
    """Back already swapped; pin it so the redesign cannot regress it."""

    def test_trip_back_shows_only_the_category_step(self):
        body = _handler_body(_load(), "trip-back")
        self.assertIn("show(stepCategory)", body)
        self.assertIn("hide(stepTrip)", body)

    def test_details_back_shows_only_the_trip_step(self):
        body = _handler_body(_load(), "details-back")
        self.assertIn("hide(stepDetails)", body)
        self.assertIn("show(stepTrip)", body)


class CategoryClickKeepsTheReset(unittest.TestCase):
    """R3 page side: picking a new category still collapses downstream state."""

    def test_category_card_click_hides_both_downstream_steps(self):
        js = _load()
        bodies = re.findall(
            r'card\.addEventListener\(\s*"click"\s*,\s*function\s*\(\)\s*\{', js)
        self.assertTrue(bodies, "no category card click handler found")
        # The category-card handler is the one that clears the trip list (R3).
        for m in re.finditer(
            r'card\.addEventListener\(\s*"click"\s*,\s*function\s*\(\)\s*\{', js
        ):
            start = m.end()
            depth = 1
            i = start
            while depth > 0 and i < len(js):
                ch = js[i]
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                i += 1
            body = js[start:i - 1]
            if "tripOptions.removeChild" in body:
                self.assertIn("hide(stepTrip)", body)
                self.assertIn("hide(stepDetails)", body)
                return
        self.fail("could not identify the category card handler (R3 reset)")


class StepsRemainSeparateSections(unittest.TestCase):
    """The swap works because each step is its own section; keep that shape."""

    def test_every_step_is_its_own_section(self):
        html = (REPO / "ui" / "party" / "index.html").read_text(encoding="utf-8")
        for sid in ("step-category", "step-trip", "step-details"):
            with self.subTest(step=sid):
                self.assertRegex(
                    html, r'<section[^>]*id="%s"' % sid,
                    f"{sid} must remain its own <section> for the swap to work")


if __name__ == "__main__":
    unittest.main()