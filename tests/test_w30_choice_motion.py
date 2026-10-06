"""Final visual pass: Yes/No shares card hover motion, not card shape or selection."""
from pathlib import Path
import unittest
from tests.test_w15_feedback import CHOICE_MOTION, cascade, rules, stripped

REPO = Path(__file__).resolve().parent.parent
REDUCE = ('@media (prefers-reduced-motion: reduce)',)
EXPECTED = {
    ((), '.choice-button'): [('transition', 'transform 0.15s ease, box-shadow 0.15s ease, border-color 0.15s ease')],
    ((), '.choice-button:hover'): [('transform', 'translatey(-2px)'), ('box-shadow', 'var(--float-shadow)')],
    (REDUCE, '.choice-button'): [('transition', 'none')],
    (REDUCE, '.choice-button:hover'): [('transform', 'none')],
}

class ChoiceMotion(unittest.TestCase):
    def setUp(self):
        self.css = stripped((REPO / 'ui/party/party.css').read_text())

    def test_exact_motion_exceptions_exist_without_duplicates(self):
        self.assertEqual({k: {p for p, _ in v} for k, v in EXPECTED.items()}, CHOICE_MOTION)
        found = {k: [] for k in EXPECTED}
        for context, selectors, decls in rules(self.css):
            for selector in selectors:
                key = (context, selector)
                if key in found:
                    found[key].extend((p, v) for p, v in decls if p in CHOICE_MOTION[key])
        self.assertEqual(EXPECTED, found)

    def test_hover_lift_and_transition_match_existing_option_cards(self):
        for width in (320, 390, 1200):
            choice = cascade(self.css, {'.choice-button', '.choice-button:hover'}, width)
            option = cascade(self.css, {'.option-card', '.option-card:hover'}, width)
            for prop in ('transition', 'transform', 'box-shadow'):
                self.assertEqual(option[prop], choice.get(prop), prop)

    def test_reduced_motion_disables_only_choice_movement_and_transition(self):
        for width in (320, 390, 1200):
            choice = cascade(self.css, {'.choice-button', '.choice-button:hover'}, width, reduced_motion=True)
            self.assertEqual('none', choice.get('transition'))
            self.assertEqual('none', choice.get('transform'))
            self.assertEqual('var(--float-shadow)', choice.get('box-shadow'))

    def test_choice_selection_and_shape_remain_unchanged(self):
        base = cascade(self.css, {'button', '.choice-button'})
        selected = cascade(self.css, {'button', '.choice-button', '.choice-button.selected'})
        self.assertEqual('29px', base.get('border-radius'))
        self.assertEqual('0.7rem 1.5rem', base.get('padding'))
        self.assertEqual('var(--card)', base.get('background-color'))
        self.assertEqual('var(--ink)', base.get('color'))
        self.assertEqual('3px', selected.get('border-width'))
        self.assertEqual('var(--accent)', selected.get('border-color'))
        self.assertEqual('600', selected.get('font-weight'))
