"""Scoped W31 visual follow-up. Browser geometry is checked separately."""
import unittest
from pathlib import Path
from tests.test_w15_feedback import cascade, stripped
ROOT = Path(__file__).resolve().parent.parent
RIDER_NAV = '.party-header:has(+ #form-steps:not([data-filed-by])) > p:has(> a)'

class ResponsiveFeedback(unittest.TestCase):
    def test_filing_navigation_uses_shared_compact_wrap(self):
        css = stripped((ROOT/'ui/party/party.css').read_text())
        for width in (320,542,1200):
            style = cascade(css, {'.party-header > .party-nav'}, width)
            self.assertEqual('flex', style.get('display'))
            self.assertEqual('wrap', style.get('flex-wrap'))
            self.assertEqual('0.5rem', style.get('gap'))
            self.assertEqual('1rem 0', style.get('margin'))

    def test_filing_navigation_text_is_smaller_but_tap_targets_remain(self):
        css = stripped((ROOT/'ui/party/party.css').read_text())
        s = cascade(css, {'.party-shell a', '.party-header > .party-nav a'}, 320)
        self.assertEqual('0.9rem', s.get('font-size'))
        self.assertEqual('44px', s.get('min-height'))

    def test_both_filing_pages_have_single_navigation_paragraph_with_dots(self):
        import re
        for file, count in (('index.html', 2), ('driver-filing.html', 3)):
            html = (ROOT/'ui/party'/file).read_text()
            groups = re.findall(r'<p class="party-nav">(.*?)</p>', html, re.S)
            self.assertEqual(1, len(groups))
            if groups:
                self.assertEqual(count, groups[0].count('<a '))
                self.assertEqual(count-1, groups[0].count('·'))

    def test_queue_uses_content_driven_wrap_at_every_width(self):
        css = stripped((ROOT/'ui/styles.css').read_text())
        for width in (320,375,542,760,1000,1001,1200):
            style = cascade(css, {'.queue-row', '.queue-list > .queue-row'}, width)
            self.assertEqual('flex', style.get('display'))
            self.assertEqual('wrap', style.get('flex-wrap'))
        field = cascade(css, {'.queue-row > span'}, 542)
        self.assertEqual('1 1 140px', field.get('flex'))

    def test_open_button_and_inline_error_survive_reflow(self):
        css = stripped((ROOT/'ui/styles.css').read_text())
        for width in (320,1200):
            s = cascade(css, {'.queue-open', '.queue-row > .queue-open'}, width)
            self.assertEqual('44px', s.get('min-height'))
            self.assertEqual('0 0 auto', s.get('flex'))
            self.assertEqual('100%', s.get('max-width'))
            status = cascade(css, {'.queue-open-status'}, width)
            self.assertEqual('1 0 100%', status.get('flex'))

if __name__ == '__main__': unittest.main()
