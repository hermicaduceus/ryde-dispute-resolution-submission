"""W31 narrow navigation/queue feedback, with a timed DOM driver.
Real-browser geometry, keyboard focus and reduced motion are verified separately.
"""
import json
import os
import subprocess
import unittest
from pathlib import Path

from tests.w23_b2_support import HARNESS, NODE, base_routes, case_file, ok, queue_row
from tests.test_w15_feedback import cascade, stripped, px

REPO = Path(__file__).resolve().parent.parent

# Extend the existing instrument, not the application. Record transient states,
# real scroll/focus requests and delayed responses so stale completion is testable.
H = HARNESS.replace('n.dataset={};', '''n.focus=()=>{n.focused=true};n.scrollIntoView=()=>{n.scrolled=true};n.dataset={};''')
H = H.replace('if(r.reject)return Promise.reject(new Error("offline"));return Promise.resolve({', 'return new Promise((resolve,reject)=>setTimeout(()=>{if(r.reject){reject(new Error("offline"));return}resolve({')
H = H.replace('json:()=>Promise.resolve(r.body)});};', 'json:()=>Promise.resolve(r.body)});},r.delay||0));};')
H = H.replace('const scenario=JSON.parse', 'const checkpoints=[]; const scenario=JSON.parse')
H = H.replace('dataset:n.dataset,children:', 'dataset:n.dataset,focused:!!n.focused,scrolled:!!n.scrolled,children:')
H = H.replace('for(const a of (scenario.actions||[])){let n;', '''for(const a of (scenario.actions||[])){if(a.op==="wait"){await new Promise(r=>setTimeout(r,a.ms));continue}if(a.op==="snapshot"){checkpoints.push({buttons:byClass("queue-open").map(snap),rows:byClass("queue-row").map(snap)});continue}let n;''')
H = H.replace('window:{},fetch,Promise,setTimeout,', 'window:{matchMedia:()=>({matches:true})},fetch,Promise,setTimeout,clearTimeout,')
H = H.replace('JSON.stringify({ids:', 'JSON.stringify({checkpoints,ids:')


def drive(routes, actions):
    env = dict(os.environ, APP_JS=str(REPO / 'ui/app.js'), SCENARIO=json.dumps({'routes':routes,'actions':actions}))
    r = subprocess.run([NODE,'-e',H],env=env,capture_output=True,text=True,timeout=15)
    if r.returncode:
        raise AssertionError('feedback driver error: '+r.stderr)
    return json.loads(r.stdout)


def scenario(delay=0, reject=False):
    a=queue_row(run_id='A',dispute_id='CASE-A')
    b=queue_row(run_id='B',dispute_id='CASE-B')
    routes=base_routes([a,b])
    ca=case_file(); ca.update(run_id='A',dispute_id='CASE-A')
    cb=case_file(); cb.update(run_id='B',dispute_id='CASE-B')
    routes['/api/review/A/case']=[dict(ok({'case_file':ca}),delay=delay,reject=reject)]
    routes['/api/review/B/case']=[ok({'case_file':cb})]
    return routes


OPEN={'className':'queue-open','op':'click'}
WAIT={'op':'wait','ms':50}


class QueueFeedback(unittest.TestCase):
    def test_stale_same_row_completion_preserves_new_current_label(self):
        for rejected in (False, True):
            with self.subTest(rejected=rejected):
                routes = scenario()
                ca = case_file()
                routes['/api/review/A/case'] = [dict(ok({'case_file': ca}), delay=250, reject=rejected), ok({'case_file': ca})]
                actions = [OPEN, {'id':'run-folder-picker','op':'pick','body':ca}, OPEN, {'op':'wait','ms':400}]
                o = drive(routes, actions)
                button = o['classes']['queue-open'][0]
                self.assertEqual('Currently open', button['text'])
                self.assertEqual('true', button['attrs'].get('aria-current'))

    def test_stale_same_row_failure_preserves_new_loading_state(self):
        routes = scenario()
        ca = case_file()
        routes['/api/review/A/case'] = [dict(ok({'case_file':ca}),delay=200,reject=True), dict(ok({'case_file':ca}),delay=650)]
        o = drive(routes, [OPEN, {'id':'run-folder-picker','op':'pick','body':ca}, OPEN, {'op':'wait','ms':350}, {'op':'snapshot'}, {'op':'wait','ms':500}])
        button = o['checkpoints'][0]['buttons'][0]
        self.assertEqual('Opening…', button['text'])
        self.assertTrue(button['disabled'])
        self.assertEqual('Currently open', o['classes']['queue-open'][0]['text'])

    def test_failed_reopen_keeps_current_label_consistent(self):
        routes = scenario()
        routes['/api/review/A/case'].append({'reject':True})
        o = drive(routes, [OPEN, WAIT, OPEN, WAIT])
        button = o['classes']['queue-open'][0]
        self.assertEqual('Currently open', button['text'])
        self.assertEqual('true', button['attrs'].get('aria-current'))
        self.assertFalse(button['disabled'])
        self.assertIn('The case could not be opened.', o['classes']['queue-row'][0]['text'])

    def test_loading_is_on_clicked_button_only(self):
        o=drive(scenario(delay=150),[OPEN,{'op':'snapshot'},{'op':'wait','ms':180}])
        buttons=o['checkpoints'][0]['buttons']
        self.assertEqual('Opening…',buttons[0]['text'])
        self.assertTrue(buttons[0]['disabled'])
        self.assertEqual('Open case',buttons[1]['text'])
        self.assertFalse(buttons[1]['disabled'])

    def test_success_marks_exactly_one_current_row(self):
        o=drive(scenario(),[OPEN,WAIT])
        buttons=o['classes']['queue-open']
        self.assertEqual('Currently open',buttons[0]['text'])
        self.assertEqual('true',buttons[0]['attrs'].get('aria-current'))
        self.assertEqual('Open case',buttons[1]['text'])
        self.assertFalse(buttons[0]['disabled'])

    def test_success_scrolls_and_focuses_case_heading(self):
        o=drive(scenario(),[OPEN,WAIT]); summary=o['ids'].get('case-summary',{})
        self.assertTrue(summary.get('scrolled'),'successful open must scroll to case summary')
        self.assertTrue(summary.get('focused'),'successful open must transfer keyboard focus')
        self.assertEqual('-1',summary.get('attrs',{}).get('tabindex'))
        self.assertIn('case-open-highlight',summary.get('className',''))

    def test_failure_is_announced_in_clicked_row_and_retryable(self):
        o=drive(scenario(reject=True),[OPEN,WAIT]); row=o['classes']['queue-row'][0]
        self.assertIn('The case could not be opened.',row['text'])
        notes=[c for c in row['children'] if c['attrs'].get('role') in ('status','alert')]
        self.assertTrue(notes,'row needs an accessible inline failure status')
        self.assertFalse(o['classes']['queue-open'][0]['disabled'])
        self.assertEqual('Open case',o['classes']['queue-open'][0]['text'])
        self.assertNotIn('Currently open',row['text'])

    def test_switching_clears_previous_current_row(self):
        o=drive(scenario(),[OPEN,WAIT,dict(OPEN,index=1),WAIT])
        self.assertEqual(['Open case','Currently open'],[b['text'] for b in o['classes']['queue-open']])
        self.assertEqual('B',o['ids']['loaded-file']['text'])

    def test_slow_previous_success_cannot_replace_latest_case(self):
        o=drive(scenario(delay=160),[OPEN,dict(OPEN,index=1),{'op':'wait','ms':200}])
        self.assertEqual('B',o['ids']['loaded-file']['text'])
        self.assertEqual(['Open case','Currently open'],[b['text'] for b in o['classes']['queue-open']])

    def test_slow_previous_failure_cannot_hide_latest_decision(self):
        o=drive(scenario(delay=160,reject=True),[OPEN,dict(OPEN,index=1),{'op':'wait','ms':200}])
        self.assertEqual('B',o['ids']['loaded-file']['text'])
        self.assertFalse(o['ids']['decision-section']['hidden'])
        self.assertNotIn('could not',o['ids']['load-status']['text'])

    def test_refresh_retains_current_case_marker(self):
        o=drive(scenario(),[OPEN,WAIT,{'id':'queue-refresh','op':'click'},WAIT])
        self.assertEqual(['Currently open','Open case'],[b['text'] for b in o['classes']['queue-open']])

    def test_local_file_load_clears_queue_selection(self):
        o=drive(scenario(),[OPEN,WAIT,{'id':'run-folder-picker','op':'pick','body':case_file()},WAIT])
        self.assertNotIn('Currently open',[b['text'] for b in o['classes']['queue-open']])

    def test_local_file_load_invalidates_pending_queue_request(self):
        o=drive(scenario(delay=160),[OPEN,{'id':'run-folder-picker','op':'pick','path':'picked/case_file.json','body':case_file()},{'op':'wait','ms':200}])
        self.assertEqual('picked/case_file.json',o['ids']['loaded-file']['text'])
        self.assertTrue(o['ids']['decision-section']['hidden'])


class PartyNavigation(unittest.TestCase):
    def test_shared_navigation_has_outlined_pill_style(self):
        css=stripped((REPO/'ui/party/party.css').read_text())
        for width in (320,1200):
            s=cascade(css,{'*','a','.party-shell a'},width)
            self.assertEqual('var(--ink)',s.get('color'))
            self.assertEqual('none',s.get('text-decoration'))
            self.assertEqual('solid',s.get('border-style'))
            self.assertEqual('var(--line)',s.get('border-color'))
            self.assertEqual('var(--card)',s.get('background-color'))
            self.assertGreaterEqual(px(s.get('min-height')),44)
            self.assertGreaterEqual(px(s.get('border-radius')),24)
            self.assertEqual('100%',s.get('max-width'))
            self.assertEqual('anywhere',s.get('overflow-wrap'))

    def test_shared_hover_and_keyboard_focus_match_driver_pattern(self):
        css=stripped((REPO/'ui/party/party.css').read_text())
        for state in (':hover',':focus-visible'):
            s=cascade(css,{'*','a','.party-shell a','.party-shell a'+state},320)
            self.assertEqual('var(--accent)',s.get('border-color'))
            self.assertEqual('var(--tint)',s.get('background-color'))
            self.assertEqual('var(--ink)',s.get('color'))
            if state==':focus-visible': self.assertIn('outline',s)


if __name__=='__main__': unittest.main()
