"""the operator's compact shared filing frame, 2026-10-06. Browser geometry is a separate gate."""
import re
import unittest
from pathlib import Path
from html.parser import HTMLParser
from tests.test_w15_feedback import stripped, cascade

ROOT = Path(__file__).resolve().parent.parent
FRAME = '.filing-shell:has(#form-steps:not([hidden]))'
BODY = 'body:has(.filing-shell #form-steps:not([hidden]))'
FIELDS = '.filing-shell .filing-fields'
FOOT = '.filing-shell .filing-fine-print'
SELECTORS = (FRAME, BODY, FRAME + ' > .party-header', FRAME + ' > .party-header h1',
             FRAME + ' > .party-header .eyebrow', FRAME + ' > .party-header .intro',
             FRAME + ' > .party-header > .party-nav', FRAME + ' > #form-steps',
             FRAME + ' #form-steps > .step:not([hidden])', FRAME + ' #details-form',
             FRAME + ' .step-actions', FRAME + ' .step-actions button', FIELDS, FOOT, FOOT + ' p',
             FRAME + ' .step h2', FRAME + ' #step-trip > .hint',
             FRAME + ' #step-trip:has(#trip-error:not([hidden])) > .hint',
             FRAME + ' #step-trip:has(#trip-error:not([hidden])) #trip-options',
             FRAME + ' #step-trip:has(#trip-error:not([hidden])) > .step-actions')

class Structure(HTMLParser):
    def __init__(self, text):
        super().__init__(); self.stack=[]; self.nodes=[]; self.feed(text)
    def handle_starttag(self, tag, attrs):
        node={'tag':tag, 'attrs':dict(attrs), 'parents':list(self.stack)}
        self.nodes.append(node)
        if tag not in ('meta','link','input','br','hr','img'): self.stack.append(node)
    def handle_endtag(self, tag):
        for i in range(len(self.stack)-1,-1,-1):
            if self.stack[i]['tag']==tag: self.stack=self.stack[:i]; break

class FilingFrame(unittest.TestCase):
    def test_both_pages_have_the_shared_frame_and_footer_after_the_form(self):
        for page in ('index.html','driver-filing.html'):
            with self.subTest(page=page):
                text=(ROOT/'ui/party'/page).read_text(); nodes=Structure(text).nodes
                main=next(n for n in nodes if n['tag']=='main')
                self.assertIn('filing-shell',main['attrs'].get('class','').split())
                headers=[n for n in nodes if n['tag']=='header']; self.assertEqual(1,len(headers))
                notes=[n for n in nodes if 'demo-note' in n['attrs'].get('class','').split()]
                self.assertEqual(1 if page=='index.html' else 2,len(notes))
                for note in notes:
                    self.assertNotIn(headers[0],note['parents'])
                    self.assertTrue(any('filing-fine-print' in n['attrs'].get('class','').split() for n in note['parents']))
                footer=next((n for n in nodes if 'filing-fine-print' in n['attrs'].get('class','').split()),None)
                self.assertIsNotNone(footer)
                self.assertGreater(nodes.index(footer),nodes.index(next(n for n in nodes if n['attrs'].get('id')=='outcome')))
                self.assertTrue(any(n['tag']=='h1' and headers[0] in n['parents'] for n in nodes))
                self.assertTrue(any('party-nav' in n['attrs'].get('class','').split() and headers[0] in n['parents'] for n in nodes))
                for id in ('category-options','description','question-list','claim-amount'):
                    node=next(n for n in nodes if n['attrs'].get('id')==id)
                    self.assertTrue(any('filing-fields' in p['attrs'].get('class','').split() for p in node['parents']),id)
                for id in ('category-next','details-back','details-submit'):
                    node=next(n for n in nodes if n['attrs'].get('id')==id)
                    self.assertFalse(any('filing-fields' in p['attrs'].get('class','').split() for p in node['parents']),id)
                if page=='driver-filing.html':
                    header=re.search(r'<header.*?</header>',text,re.S).group()
                    outcome=re.search(r'<section class="step outcome".*?</section>',text,re.S).group()
                    self.assertNotIn('Save your reference number.',header)
                    self.assertIn('Save your reference number.',outcome)

    def test_frame_replaces_the_obscuring_viewport_fixed_card(self):
        css=stripped((ROOT/'ui/party/party.css').read_text())
        s=cascade(css,{FRAME}); self.assertEqual('flex',s.get('display'))
        self.assertEqual('column',s.get('flex-direction')); self.assertIn('100dvh',s.get('height',''))
        card=cascade(css,{'#step-trip:not([hidden])'})
        self.assertNotEqual('fixed',card.get('position')); self.assertNotIn('100dvh',card.get('height',''))
        self.assertEqual('hidden',cascade(css,{BODY}).get('overflow'))
        for selector in (FRAME+' > #form-steps',FRAME+' #form-steps > .step:not([hidden])',FRAME+' #details-form',FIELDS):
            s=cascade(css,{selector}); self.assertEqual('0',s.get('min-height'),selector)
        self.assertEqual('auto',cascade(css,{FIELDS}).get('overflow-y'))
        self.assertEqual('0 0 auto',cascade(css,{FRAME+' .step-actions'}).get('flex'))

    def test_demo_footer_is_plain_readable_fine_print(self):
        css=stripped((ROOT/'ui/party/party.css').read_text())
        s=cascade(css,{FOOT}); self.assertEqual('0.75rem',s.get('font-size'))
        self.assertEqual('var(--muted)',s.get('color'))
        self.assertEqual('auto',s.get('overflow-y'))
        p=cascade(css,{'.demo-note',FOOT+' p'})
        self.assertEqual('none',p.get('background')); self.assertEqual('0',p.get('border'))
        self.assertEqual('0',p.get('padding')); self.assertEqual('inherit',p.get('font-size'))

    def test_frame_rules_keep_the_regions_shrinkable_and_the_header_compact(self):
        css=stripped((ROOT/'ui/party/party.css').read_text())
        expected=[(FRAME,'display','flex'),(FRAME,'flex-direction','column'),
                  (FRAME+' > .party-header','overflow-y','auto'),
                  (FRAME+' > .party-header h1','font-size','1.25rem'),
                  (FRAME+' > #form-steps','flex','1 1 auto'),
                  (FRAME+' #form-steps > .step:not([hidden])','display','flex'),
                  (FRAME+' #details-form','flex-direction','column'),
                  (FRAME+' .step-actions button','min-height','44px'),
                  (FIELDS,'flex','1 1 auto'),(FIELDS,'overscroll-behavior','contain'),
                  (FOOT,'flex','0 0 auto'),
                  (FRAME+' #step-trip:has(#trip-error:not([hidden])) > .hint','display','none'),
                  (FRAME+' #step-trip:has(#trip-error:not([hidden])) #trip-options','display','none'),
                  (FRAME+' #step-trip:has(#trip-error:not([hidden])) > .step-actions','margin-top','auto')]
        for selector,prop,value in expected:
            with self.subTest(selector=selector,property=prop):
                self.assertEqual(value,cascade(css,{selector}).get(prop))
        self.assertTrue(cascade(css,{FRAME+' > .party-header'}).get('max-height'))
        self.assertTrue(cascade(css,{FOOT}).get('max-height'))

    def test_preservation_carveout_is_exact_and_has_no_dead_rules(self):
        from tests.test_w15_feedback import FILING_SELECTORS
        self.assertEqual(set(SELECTORS),set(FILING_SELECTORS))
        from tests.test_w15_feedback import rules
        present={s for _,group,_ in rules(stripped((ROOT/'ui/party/party.css').read_text())) for s in group}
        for s in SELECTORS:self.assertIn(s,present)

if __name__=='__main__':unittest.main()
