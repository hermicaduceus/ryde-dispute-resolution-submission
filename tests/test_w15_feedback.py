"""W15 narrow feedback source contracts, not browser geometry proof.

Comments are stripped. Named-selector profiles resolve all matching rules by
!important, specificity and source/declaration order, including margin/padding,
gap, border and background shorthands. Media rules are checked at 360 and 1200px.
Profiles deliberately describe the existing markup, not a general CSS engine.
The new scoped rules use the existing driver form/header selector contract below.
JS and all unrelated CSS declarations are frozen to the reviewed W15 tree. W34 (2026-10-07)
released the HTML pages; their only permitted change is pinned in tests/test_w34_launcher.py.
the operator's review-repair carve-out allows only .step-actions position/bottom to change.
Browser wrap, geometry, actual hover/focus and accessibility remain separate gates.
"""
from __future__ import annotations

import hashlib
import json
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CLAIM = '#form-steps[data-filed-by="driver"] #claim-amount + .hint'
HEADER = '.party-header:has(+ #form-steps[data-filed-by="driver"]) > p:last-child'
NAV = HEADER + ' a'
FROZEN = {
    'ui/party/driver.js': 'fff0dd47777ed9b872fa51deb51171a844f6b827e3c58d4ba90302cf0cbe70ff',
    # W35 (2026-10-08): ui/party/party.js released; tests/test_w35_P.py pins it.
    # Step-1 targeting round (2026-10-15): ui/party/status.js released for the ?dispute=
    # focus param (tests/test_step1_dispute_target.py pins the new behaviour).
    'ui/party/status.js': 'fc62509fb8b4f5a2507a0a05620657016b3dc68859ab6badde9e5683549e4931',
}
# Excludes only the approved .step-actions position/bottom declarations in
# addition to the original feedback rules. Computed from the pre-repair CSS.
PARTY_UNRELATED = '7e8a0a6308c851e0a106794a1363dbae1f2772f349c7cdea18bd64e295d4a1ae'
CONSOLE_UNRELATED = '6d655bbcbbbc0725dccec64095142581c682c0cecdbbe4610f03e1e5e3b8efb4'
# W30 (the operator 2026-10-06): the trip step's viewport-fit card, its scroll region and the
# landing margin. The exclusion list IS the pin (tests/test_w30_trip_scroll.py).
W30_SELECTORS = ('#step-trip:not([hidden])', '#step-trip #trip-options', '#step-category', '#step-trip',
                 '#step-trip > h2', '#step-trip > .hint', '#step-trip > .error',
                 '#step-trip > .step-actions')
# the operator-approved compact shared frame; every new rule pinned in test_w30_filing_frame.
FILING_SELECTORS = ('.filing-shell:has(#form-steps:not([hidden]))', 'body:has(.filing-shell #form-steps:not([hidden]))', '.filing-shell:has(#form-steps:not([hidden])) > .party-header', '.filing-shell:has(#form-steps:not([hidden])) > .party-header h1', '.filing-shell:has(#form-steps:not([hidden])) > .party-header .eyebrow', '.filing-shell:has(#form-steps:not([hidden])) > .party-header .intro', '.filing-shell:has(#form-steps:not([hidden])) > .party-header > .party-nav', '.filing-shell:has(#form-steps:not([hidden])) > #form-steps', '.filing-shell:has(#form-steps:not([hidden])) #form-steps > .step:not([hidden])', '.filing-shell:has(#form-steps:not([hidden])) #details-form', '.filing-shell:has(#form-steps:not([hidden])) .step-actions', '.filing-shell:has(#form-steps:not([hidden])) .step-actions button', '.filing-shell .filing-fields', '.filing-shell .filing-fine-print', '.filing-shell .filing-fine-print p', '.filing-shell:has(#form-steps:not([hidden])) .step h2', '.filing-shell:has(#form-steps:not([hidden])) #step-trip > .hint', '.filing-shell:has(#form-steps:not([hidden])) #step-trip:has(#trip-error:not([hidden])) > .hint', '.filing-shell:has(#form-steps:not([hidden])) #step-trip:has(#trip-error:not([hidden])) #trip-options', '.filing-shell:has(#form-steps:not([hidden])) #step-trip:has(#trip-error:not([hidden])) > .step-actions')
# Final W30 visual follow-up: exclude only the five explicitly pinned motion declarations.
CHOICE_MOTION = {
    ((), '.choice-button'): {'transition'},
    ((), '.choice-button:hover'): {'transform', 'box-shadow'},
    (('@media (prefers-reduced-motion: reduce)',), '.choice-button'): {'transition'},
    (('@media (prefers-reduced-motion: reduce)',), '.choice-button:hover'): {'transform'},
}
RHYTHM = {'.loader-panel', '#queue-panel', '#overrides-panel', '#case-workspace'}
# W35 lane C (one run-folder picker, Recent runs, readable prompt full text): every rule it ADDS
# to ui/styles.css, by selector, top level only. tests/test_w35_C.py pins these rules exactly.
W35_CONSOLE_SELECTORS = frozenset({
    '#runs-panel', '#runs-panel .section-heading > div', '#runs-status', '.runs-list',
    '.runs-list > .run-row', '.run-row > span', '.run-row > .run-category', '.run-row > .run-id',
    '.run-row > .run-outcome', '.run-row > .run-generated', '.run-row > .run-decided',
    '.run-row > .run-open', '.run-row > .run-open:hover', '.runs-list > .run-row.is-open',
    '.run-open-status', '.run-open-status:empty', '.loader-hint',
    '#prompts-content details > .payload-json',
})
RHYTHM_PROPS = {'margin', 'margin-top', 'margin-bottom', 'gap', 'row-gap'}


def stripped(css):
    return re.sub(r'/\*.*?\*/', '', css, flags=re.S).lower()


def rules(css, context=()):
    """Retain declarations and media context; freeze other at-blocks opaquely."""
    pos = 0
    while pos < len(css):
        start = css.find('{', pos)
        if start < 0:
            break
        head = ' '.join(css[pos:start].split())
        depth, end = 1, start + 1
        while end < len(css) and depth:
            depth += (css[end] == '{') - (css[end] == '}')
            end += 1
        assert depth == 0, 'unbalanced CSS block'
        body = css[start + 1:end - 1]
        if head.startswith('@media'):
            yield from rules(body, context + (head,))
        elif not head.startswith('@'):
            # Existing :has argument has no comma. No selector-list functional pseudos.
            selectors = tuple(' '.join(s.strip().split()) for s in head.split(','))
            decls = tuple((p.strip(), ' '.join(v.split()))
                          for p, v in re.findall(r'([\w-]+)\s*:\s*([^;]+);?', body))
            yield context, selectors, decls
        else:
            yield context, (head,), (('__opaque__', ' '.join(body.split())),)
        pos = end


def active(context, width, reduced_motion=False):
    for query in context:
        if query == "@media (prefers-reduced-motion: reduce)":
            if not reduced_motion:
                return False
            continue
        matches = re.findall(r'(max|min)-width:\s*([\d.]+)px', query)
        assert matches, 'unsupported media query in source contract: ' + query
        if any((kind == 'max' and width > float(n)) or
               (kind == 'min' and width < float(n)) for kind, n in matches):
            return False
    return True


def specificity(selector):
    # :has adopts its argument's specificity, it does not add a pseudo-class.
    selector = selector.replace(':has(', '(')
    ids = len(re.findall(r'#[\w-]+', selector))
    classes = len(re.findall(r'\.[\w-]+|\[[^]]+\]|:(?!:)[\w-]+', selector))
    plain = re.sub(r'#[\w-]+|\.[\w-]+|\[[^]]+\]|:[\w-]+', '', selector)
    tags = len(re.findall(r'(?:^|[\s>+~(])([a-z][\w-]*)', plain))
    return ids, classes, tags


def expanded(prop, value):
    important = bool(re.search(r'\s*!important\s*$', value))
    value = re.sub(r'\s*!important\s*$', '', value)
    out = {prop: value}
    if prop in ('margin', 'padding'):
        bits = value.split()
        assert 1 <= len(bits) <= 4, 'unsupported box shorthand: ' + value
        top = bits[0]
        right = bits[1] if len(bits) > 1 else top
        bottom = bits[2] if len(bits) > 2 else top
        left = bits[3] if len(bits) > 3 else right
        out.update({prop + '-' + side: val for side, val in
                    zip(('top', 'right', 'bottom', 'left'), (top, right, bottom, left))})
    if prop == 'gap':
        out['row-gap'] = value.split()[0]
        out['column-gap'] = value.split()[-1]
    if prop == 'background':
        out['background-color'] = value
    if prop == 'border':
        bits = value.split()
        out['border-width'] = bits[0]
        out['border-style'] = bits[1] if len(bits) > 1 else 'none'
        out['border-color'] = ' '.join(bits[2:]) if len(bits) > 2 else 'currentcolor'
    return out, important


def cascade(css, selectors, width=1200, reduced_motion=False):
    """Explicit markup profile, including base ancestors/types and state selectors."""
    winners = {}
    for order, (context, group, decls) in enumerate(rules(css)):
        if not active(context, width, reduced_motion):
            continue
        for selector in group:
            if selector not in selectors:
                continue
            for index, (prop, value) in enumerate(decls):
                values, important = expanded(prop, value)
                rank = (important, specificity(selector), order, index)
                for key, val in values.items():
                    if key not in winners or rank >= winners[key][0]:
                        winners[key] = rank, val
    return {p: v for p, (_, v) in winners.items()}


def px(value):
    assert value is not None, 'required length declaration is absent'
    m = re.fullmatch(r'(-?[\d.]+)(px|rem)?', value)
    assert m is not None, 'unsupported source length: ' + value
    return float(m.group(1)) * (16 if m.group(2) == 'rem' else 1)


def unrelated_digest(css, party):
    kept = []
    for context, selectors, decls in rules(css):
        for selector in selectors:
            if party and selector in {'.party-header > .party-nav', '.party-header > .party-nav a'}:
                continue
            if party and selector in set(W30_SELECTORS) | set(FILING_SELECTORS):
                continue
            if not party and not context and selector in {'.queue-list > .queue-row', '.queue-row > span', '.queue-row > .queue-safety', '.queue-row > .queue-open'}:
                continue
            if party and (selector == CLAIM or selector in
                          (HEADER, NAV, NAV + ':hover', NAV + ':focus', NAV + ':focus-visible',
                           '.party-shell a', '.party-shell a:hover', '.party-shell a:focus-visible')):
                continue
            if not party and selector in {'.queue-row.is-open', '.queue-open-status',
                                          '.queue-open-status:empty', '#case-summary.case-open-highlight'}:
                continue
            if not party and not context and selector in W35_CONSOLE_SELECTORS:
                continue
            filtered = tuple((p, v) for p, v in decls
                             if (not party or p not in CHOICE_MOTION.get((context, selector), set())) and
                             (not party or selector != '.step-actions' or
                                 p not in ('position', 'bottom')) and
                             (party or selector not in RHYTHM or p not in RHYTHM_PROPS))
            if filtered:
                kept.append((context, selector, filtered))
    return hashlib.sha256(json.dumps(kept, separators=(',', ':')).encode()).hexdigest()


def nav_style(css, state='', width=1200):
    states = {NAV + ':focus', 'a:focus'} if state == ':focus-visible' else set()
    return cascade(css, states | {'*', 'a', '.party-header a', '.party-header > p a',
                         '.party-header > p:last-child a', NAV,
                         'a' + state, '.party-header a' + state, NAV + state,
                         '.party-shell a', '.party-shell a' + state}, width)


class W15Feedback(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.party = stripped((REPO / 'ui/party/party.css').read_text())
        cls.console = stripped((REPO / 'ui/styles.css').read_text())

    def test_claim_helper_has_positive_driver_only_clearance(self):
        for width in (360, 1200):
            style = cascade(self.party, {'*', 'p', '.hint', '.field .hint',
                                        '#claim-amount + .hint', CLAIM}, width)
            self.assertGreaterEqual(px(style.get('margin-top')), 8,
                                    'driver claim helper needs at least 0.5rem clearance')
        # Shared heading helpers retain their existing negative heading rhythm.
        self.assertEqual('-0.4rem', cascade(self.party, {'.hint'}).get('margin-top'))

    def test_console_top_level_cards_share_loader_28px_rhythm(self):
        for width in (360, 1200):
            for selector in ('.loader-panel', '#queue-panel', '#overrides-panel', '#case-workspace'):
                with self.subTest(width=width, selector=selector):
                    style = cascade(self.console, {'*', 'section' if selector != '#case-workspace' else 'div',
                                                  '.app-shell > section', selector}, width)
                    self.assertEqual(28, px(style.get('margin-top')),
                                     selector + ' must end at 28px, not a later zero/24px reset')
                    self.assertEqual(0, px(style.get('margin-bottom', '0')))
                    self.assertEqual(0, px(style.get('margin-left', '0')))
                    self.assertEqual(0, px(style.get('margin-right', '0')))

    def test_console_lower_story_sections_have_28px_gap(self):
        for width in (360, 1200):
            workspace = cascade(self.console, {'*', 'div', '#case-workspace'}, width)
            self.assertEqual('grid', workspace.get('display'))
            self.assertEqual(28, px(workspace.get('row-gap')),
                             'all lower story cards share the loader gap')
            # The unchanged story margins are zero; grid gap must not be doubled.
            story = cascade(self.console, {'*', 'section', '.story-section'}, width)
            self.assertEqual(0, px(story.get('margin-top', '0')))
            self.assertEqual(0, px(story.get('margin-bottom', '0')))

    def test_header_navigation_is_quiet_outlined_ink_on_white(self):
        style = nav_style(self.party)
        self.assertIn(style.get('background-color'), ('var(--card)', '#fff', '#ffffff', 'white'))
        self.assertEqual('var(--ink)', style.get('color'))
        self.assertEqual('var(--line)', style.get('border-color'))
        self.assertEqual('solid', style.get('border-style'))
        self.assertGreaterEqual(px(style.get('border-width')), 1)
        self.assertGreaterEqual(px(style.get('border-radius')), 24)
        self.assertEqual('none', style.get('text-decoration'))

    def test_header_navigation_hover_uses_pink_border_and_soft_tint(self):
        style = nav_style(self.party, ':hover')
        self.assertEqual('var(--accent)', style.get('border-color'))
        self.assertEqual('var(--tint)', style.get('background-color'))
        self.assertEqual('var(--ink)', style.get('color'))

    def test_header_navigation_keyboard_focus_uses_pink_border_and_soft_tint(self):
        style = nav_style(self.party, ':focus-visible')
        self.assertEqual('var(--accent)', style.get('border-color'))
        self.assertEqual('var(--tint)', style.get('background-color'))
        self.assertEqual('var(--ink)', style.get('color'))


    def test_header_navigation_can_wrap_with_comfortable_tap_targets(self):
        for width in (360, 1200):
            row = cascade(self.party, {'*', 'p', HEADER}, width)
            self.assertEqual('flex', row.get('display'))
            self.assertEqual('wrap', row.get('flex-wrap'))
            self.assertGreaterEqual(px(row.get('gap')), 8)
            self.assertNotIn(row.get('font-size'), ('0', '0px', '0rem'), 'keep text separators')
            self.assertNotEqual('hidden', row.get('visibility'))
            style = nav_style(self.party, width=width)
            self.assertIn(style.get('display'), ('inline-flex', 'flex', 'inline-block'))
            self.assertEqual('100%', style.get('max-width'))
            self.assertGreaterEqual(px(style.get('min-height')), 44)
            self.assertGreaterEqual(px(style.get('padding-top')), 8)
            self.assertGreaterEqual(px(style.get('padding-left')), 16)
            self.assertNotEqual('nowrap', style.get('white-space'))
            self.assertIn(style.get('overflow-wrap'), ('anywhere', 'break-word'))
            self.assertNotIn(style.get('flex-shrink'), ('0', '0.0'))

    def test_primary_continue_send_hierarchy_stays_filled_pink(self):
        # W35 releases the old exact fill/border token. Keep the filled-pink hierarchy
        # here; test_w35_P requires --accent-strong and pins the measured contrast.
        style = cascade(self.party, {'*', 'button', 'button.primary'})
        self.assertIn(style.get('background-color'), ('var(--accent)', 'var(--accent-strong)'))
        self.assertEqual(style.get('background-color'), style.get('border-color'))
        self.assertEqual('var(--accent-ink)', style.get('color'))

    def test_action_bars_are_normal_flow_at_all_widths(self):
        for width in (320, 360, 390, 600, 601, 768, 1200):
            style = cascade(self.party, {'*', 'div', '.step-actions'}, width)
            self.assertEqual('static', style.get('position'),
                             'action bars cannot obstruct options on mobile or desktop')
            self.assertNotIn('bottom', style, 'remove the obsolete sticky bottom offset')
        for context, selectors, decls in rules(self.party):
            if '.step-actions' in selectors:
                self.assertFalse(context, 'no viewport exception can reintroduce sticky actions')

    def test_party_changes_are_only_approved_feedback_and_action_rules(self):
        self.assertNotRegex(self.party, r'@import\b')
        # W35 (2026-10-08): PARTY_UNRELATED released. W35 edits party.css (contrast token,
        # step 3 summary, pending send); tests/test_w35_P.py W35Preservation now pins every
        # other party.css declaration against BASE 57758ce with an exact exception list.
        allowed = {'margin-top'}
        row_layout = {'display', 'flex-wrap', 'align-items', 'gap', 'row-gap',
                      'column-gap', 'margin', 'margin-top', 'margin-bottom'}
        for _, selectors, decls in rules(self.party):
            if CLAIM in selectors:
                self.assertLessEqual({p for p, _ in decls}, allowed,
                                     'claim correction changes only helper clearance')
            if HEADER in selectors:
                self.assertLessEqual({p for p, _ in decls}, row_layout,
                                     'header row changes layout only, not separator typography')
            if any(s.startswith(HEADER) for s in selectors):
                for prop, value in decls:
                    self.assertNotIn(prop, {'content', 'font', 'position', 'transform'})
                    self.assertNotEqual('hidden', value)

    def test_console_changes_only_top_level_rhythm_not_inner_layouts(self):
        self.assertNotRegex(self.console, r'@import\b')
        self.assertEqual(CONSOLE_UNRELATED, unrelated_digest(self.console, False),
                         'console inner layout, colours and padding stay unchanged')

    def test_all_javascript_bytes_stay_frozen(self):
        actual = {rel: hashlib.sha256((REPO / rel).read_bytes()).hexdigest()
                  for rel in FROZEN}
        self.assertEqual(FROZEN, actual,
                         'preserve every JavaScript byte while W34 adds navigation HTML')

    def test_cascade_reader_handles_existing_shared_reset_and_shorthands(self):
        css = stripped('''/* #overrides-panel { margin-top: 28px; } */
          #queue-panel, #overrides-panel { margin-top: 28px; }
          #overrides-panel { margin: 0; }
          section { margin-top: 99px; }
          #overrides-panel { margin-top: 8px !important; margin-top: 7px; }
          @media (max-width: 760px) { #overrides-panel { margin: 2px !important; } }
        ''')
        self.assertEqual('8px', cascade(css, {'section', '#overrides-panel'}, 1200)['margin-top'])
        self.assertEqual('2px', cascade(css, {'section', '#overrides-panel'}, 360)['margin-top'])
        self.assertGreater(specificity(CLAIM), specificity('.hint'))
        self.assertGreater(specificity(NAV), specificity('.party-header a'))


if __name__ == '__main__':
    unittest.main()
