"""W30 review repair: only the current trip request may render or move the page.

the operator approved landing the current error card as well as successful results. A
superseded success or failure must not alter trips, error, selection, disabled
state or page position, even after Back and reopening the SAME category.
Run: /usr/bin/python3 -m unittest tests.test_w30_trip_requests
"""
import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path
from tests.w16_support import DOM

ROOT = Path(__file__).resolve().parent.parent
END = "  return n;\n}\nconst ids = {};"
assert END in DOM
HARNESS = DOM.replace(END, """  n.scrollIntoView = o => landings.push({
    id: Object.keys(ids).find(k => ids[k] === n), block: o.block });
  return n;
}
const ids = {};
const landings = [];""", 1) + r'''
const opts = JSON.parse(process.env.SCENARIO);
if (opts.role) doc.getElementById('form-steps').setAttribute('data-filed-by', opts.role);
['step-trip','step-details','outcome','trip-error'].forEach(k => doc.getElementById(k).hidden = true);
const requests = [];
function fetch(url, options) {
  return new Promise((resolve, reject) => requests.push({url, resolve, reject}));
}
const tick = () => new Promise(r => setTimeout(r, 0));
function snapshot() {
  const cards = ids['trip-options'].children;
  return {landings: landings.slice(), requests: requests.map(r => r.url),
    texts: cards.map(c => c.textContent), selected: cards.filter(c => c.classList.contains('selected')).map(c => c.textContent),
    nextDisabled: ids['trip-next'].disabled, error: ids['trip-error'].textContent,
    errorVisible: !ids['trip-error'].hidden,
    visible: ['step-category','step-trip','step-details'].filter(k => !ids[k].hidden)};
}
(async () => {
  vm.runInNewContext(fs.readFileSync(process.env.PARTY_JS, 'utf8'), {
    document: doc, window: { scrollTo() {} }, fetch, Promise, setTimeout,
    encodeURIComponent, JSON, Array, Number, isFinite, String });
  const checkpoints = [];
  for (const a of opts.actions) {
    if (a.op === 'category') ids['category-options'].children[a.index || 0].click();
    if (a.op === 'click') ids[a.id].click();
    if (a.op === 'pick') ids['trip-options'].children[0].click();
    if (a.op === 'resolve') requests[a.index].resolve({ok: true, json: () => Promise.resolve({
      trips: Array.from({length: a.count === undefined ? 3 : a.count}, (_, i) => ({
        trip_id: a.tag + '-' + i, label: a.tag + '-' + i, date: '2026', kind_label: 'Ride', fare_sgd: 6.61}))})});
    if (a.op === 'fail') requests[a.index].resolve({ok: false, json: () => Promise.resolve({error: a.message || 'offline'})});
    if (a.op === 'reject') requests[a.index].reject(new Error('network unavailable'));
    await tick(); await tick();
    if (a.op === 'snapshot') checkpoints.push(snapshot());
  }
  process.stdout.write(JSON.stringify({checkpoints, final: snapshot()}));
})().catch(e => { console.error(e.stack); process.exit(1); });
'''


def category(index=0): return {'op': 'category', 'index': index}
def click(id): return {'op': 'click', 'id': id}
def resolve(index, tag='NEW', count=3): return {'op': 'resolve', 'index': index, 'tag': tag, 'count': count}
SNAP = {'op': 'snapshot'}


def drive(actions, role=None):
    node = shutil.which('node')
    assert node is not None, 'Node required'
    env = dict(os.environ, PARTY_JS=str(ROOT / 'ui/party/party.js'),
               SCENARIO=json.dumps({'role': role, 'actions': actions}))
    r = subprocess.run([node, '-e', HARNESS], env=env, text=True, capture_output=True, timeout=15)
    if r.returncode:
        raise AssertionError('request driver failed: ' + r.stderr)
    return json.loads(r.stdout)


class TripRequestLifecycle(unittest.TestCase):
    def test_retry_without_reselecting_category_clears_the_previous_error(self):
        for role in (None, 'driver'):
            with self.subTest(role=role):
                out = drive([category(), click('category-next'), {'op': 'fail', 'index': 0}, SNAP,
                             click('trip-back'), click('category-next'), SNAP, resolve(1), SNAP], role)
                failed, loading, succeeded = out['checkpoints']
                self.assertTrue(failed['errorVisible'])
                self.assertTrue(failed['error'])
                self.assertFalse(loading['errorVisible'])
                self.assertEqual('', loading['error'])
                self.assertFalse(succeeded['errorVisible'])
                self.assertEqual(3, len(succeeded['texts']))

    def test_repeated_continue_activation_supersedes_a_request_without_back_or_category_reset(self):
        # Two queued activations of the same Continue handler must also create two
        # distinct requests, not merely rely on category/Back invalidation.
        for role in (None, 'driver'):
            for stale in (resolve(0, 'OLD'), {'op': 'fail', 'index': 0}):
                with self.subTest(role=role, stale=stale):
                    out = drive([category(), click('category-next'), click('category-next'),
                                 resolve(1), {'op': 'pick'}, SNAP, stale, SNAP], role)
                    before, after = out['checkpoints']
                    self.assertEqual(2, len(before['requests']))
                    self.assertTrue(before['selected'])
                    self.assertEqual(before, after)

    def reenter(self, different=True):
        return [category(), click('category-next'), click('trip-back'),
                category(1 if different else 0), click('category-next')]

    def test_old_success_cannot_overwrite_the_new_list_or_selection_or_land_again(self):
        for role in (None, 'driver'):
            for different in (False, True):
                with self.subTest(role=role, different=different):
                    out = drive(self.reenter(different) + [resolve(1), {'op': 'pick'}, SNAP,
                                resolve(0, 'OLD'), SNAP], role)
                    before, after = out['checkpoints']
                    self.assertEqual(3, len(before['texts']))
                    self.assertTrue(before['selected'])
                    self.assertFalse(before['nextDisabled'])
                    self.assertEqual(before, after, 'old success must change no current UI state')

    def test_old_failure_cannot_clear_the_new_list_or_selection_or_show_an_error(self):
        for role in (None, 'driver'):
            for failure in ('fail', 'reject'):
                with self.subTest(role=role, failure=failure):
                    out = drive(self.reenter() + [resolve(1), {'op': 'pick'}, SNAP,
                                {'op': failure, 'index': 0}, SNAP], role)
                    before, after = out['checkpoints']
                    self.assertTrue(before['selected'])
                    self.assertEqual(before, after, 'old failure must change no current UI state')

    def test_old_response_cannot_settle_the_new_request_while_it_is_loading(self):
        for role in (None, 'driver'):
            for stale in (resolve(0, 'OLD'), {'op': 'fail', 'index': 0}):
                with self.subTest(role=role, stale=stale):
                    out = drive(self.reenter(False) + [SNAP, stale, SNAP, resolve(1), SNAP], role)
                    waiting, unchanged, settled = out['checkpoints']
                    self.assertIn('Loading trips', waiting['texts'][0])
                    self.assertTrue(waiting['nextDisabled'])
                    self.assertEqual(waiting, unchanged, 'new pending request still owns its placeholder')
                    self.assertEqual(3, len(settled['texts']))
                    self.assertEqual(2, len(settled['landings']))

    def test_back_invalidates_a_request_even_before_a_new_request_starts(self):
        for role in (None, 'driver'):
            for stale in (resolve(0, 'OLD'), {'op': 'fail', 'index': 0}):
                with self.subTest(role=role, stale=stale):
                    out = drive([category(), click('category-next'), click('trip-back'), SNAP, stale, SNAP], role)
                    before, after = out['checkpoints']
                    self.assertEqual(['step-category'], before['visible'])
                    self.assertEqual(before, after, 'Back alone invalidates every outcome of the old request')

    def test_category_change_invalidates_a_request_before_the_next_continue(self):
        for stale in (resolve(0, 'OLD'), {'op': 'fail', 'index': 0}):
            with self.subTest(stale=stale):
                out = drive([category(), click('category-next'), category(1), SNAP, stale, SNAP])
                before, after = out['checkpoints']
                self.assertEqual([], before['texts'])
                self.assertEqual(before, after, 'category reset owns its empty trip list')

    def test_current_failure_displays_and_lands_the_error_card_on_both_pages(self):
        for role in (None, 'driver'):
            for failure in ('fail', 'reject'):
                with self.subTest(role=role, failure=failure):
                    out = drive([category(), click('category-next'), {'op': failure, 'index': 0}], role)['final']
                    self.assertEqual([], out['texts'])
                    self.assertTrue(out['errorVisible'])
                    self.assertTrue(out['error'])
                    self.assertTrue(out['nextDisabled'])
                    self.assertEqual(['step-trip'], out['visible'])
                    self.assertEqual([{'id': 'step-trip', 'block': 'start'}], out['landings'])

    def test_empty_stale_success_cannot_erase_a_new_populated_list(self):
        out = drive(self.reenter() + [resolve(1), SNAP, resolve(0, 'OLD', 0), SNAP])
        self.assertEqual(out['checkpoints'][0], out['checkpoints'][1])

    def test_new_current_failure_is_not_hidden_by_the_epoch_guard(self):
        out = drive(self.reenter() + [{'op': 'fail', 'index': 1}, SNAP, resolve(0, 'OLD'), SNAP])
        before, after = out['checkpoints']
        self.assertTrue(before['errorVisible'])
        self.assertEqual('offline', before['error'])
        self.assertEqual(before, after)

    def test_successful_return_after_details_still_lands_a_fresh_request(self):
        out = drive([category(), click('category-next'), resolve(0), {'op': 'pick'},
                     click('trip-next'), click('details-back'), resolve(1, 'RETURN')])['final']
        self.assertEqual(['step-trip'], out['visible'])
        self.assertTrue(out['nextDisabled'])
        self.assertEqual(2, len(out['requests']))
        self.assertEqual(2, len(out['landings']))
        self.assertIn('RETURN', out['texts'][0])


if __name__ == '__main__': unittest.main()
