/* W35 fix round R2, lane K: the operator console in a real browser. Written RED-first against 55204c1.
 * Driven by tests/test_w35_r2_K.py (RealBrowserK) against the real server on the mock model, which holds a
 * withheld route-deviation run (queued) and a ruled no-show run. Passes:
 *   argv: <base url> <report json path>
 *   env:  PUPPETEER_MODULE, BROWSER_EXECUTABLE, W35RK_EXPECT (see the Python side for the keys)
 * Only the response ORDER is scripted (request interception on 127.0.0.1); every body comes from the real server
 * or is a copy of one. Each scenario records its own error in report.scenarios (null = passed), so a failure names
 * the schedule. Scenarios run at 390x844 and 1280x844.
 *   stale-<panel>-<older>-then-<newer>   an older panel response arriving after a newer one changes nothing
 *   refresh-then-open-<list>             Refresh held -> Open disabled + aria-busy -> list lands -> Open works,
 *                                        and its failure is shown on the visible row; retry succeeds
 *   folder-<shape>                       the run-folder picker rejects every incomplete case object
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const os = require('node:os');
const path = require('node:path');
const puppeteer = require(process.env.PUPPETEER_MODULE || 'puppeteer');
const [base, output] = process.argv.slice(2);
const X = JSON.parse(process.env.W35RK_EXPECT);
const report = {passed: false, scenarios: {}, pageErrors: []};
const sleep = ms => new Promise(r => setTimeout(r, ms));
const get = p => new Promise((resolve, reject) => http.get(base + p, r => {
  let raw = ''; r.on('data', c => raw += c); r.on('end', () => resolve(JSON.parse(raw)));
}).on('error', reject));
const json = body => ({status: 200, contentType: 'application/json', body: JSON.stringify(body)});

// A rule answers the nth request of one path: {pass}, {hold} (kept in held[n]), or {status, body}.
function scripted(steps, held, seen) {
  let n = 0;
  return req => {
    const index = n++;
    seen.push(index);
    const step = steps[Math.min(index, steps.length - 1)];
    if (step.hold) { held[index] = req; return; }
    if (step.pass) return req.continue();
    return req.respond({status: step.status || 200, contentType: 'application/json', body: JSON.stringify(step.body === undefined ? {} : step.body)});
  };
}

async function openPage(browser, width, height, rules) {
  const page = await browser.newPage();
  page.on('pageerror', e => report.pageErrors.push(String(e)));
  const log = [];
  await page.setViewport({width, height});
  await page.setRequestInterception(true);
  page.on('request', req => {
    const u = new URL(req.url());
    if (u.hostname !== '127.0.0.1') return req.abort();
    if (u.pathname.startsWith('/api/')) log.push(u.pathname);
    const rule = rules[u.pathname];
    if (rule) return rule(req);
    return req.continue();
  });
  return {page, log};
}

async function until(page, fn, arg, what) {
  try { await page.waitForFunction(fn, {timeout: 8000}, arg); } catch (e) { throw new Error('timed out waiting for ' + what); }
}

const PANEL = {
  runs: {path: '/api/review/runs', state: () => ({
    ids: Array.from(document.querySelectorAll('#runs-content .run-row')).map(r => r.dataset.runId),
    status: document.getElementById('runs-status').textContent, busy: document.getElementById('runs-content').getAttribute('aria-busy')})},
  queue: {path: '/api/review/queue', state: () => ({
    ids: Array.from(document.querySelectorAll('#queue-content .queue-row')).map(r => r.dataset.runId),
    status: document.getElementById('queue-status').textContent, busy: document.getElementById('queue-content').getAttribute('aria-busy')})},
  overrides: {path: '/api/review/overrides', state: () => ({
    ids: [], status: document.getElementById('overrides-status').textContent,
    text: document.getElementById('overrides-content').textContent, busy: document.getElementById('overrides-content').getAttribute('aria-busy')})},
};

async function scenario(name, fn) {
  try { await fn(); report.scenarios[name] = null; } catch (e) { report.scenarios[name] = String(e && e.message || e); }
}

(async () => {
  const runs = (await get('/api/review/runs')).runs;
  const queue = (await get('/api/review/queue')).cases;
  assert.ok(runs.length >= 2 && queue.length >= 1, 'fixture: two runs, one queued');
  const [A, B] = runs;
  const realBodies = {runs: {runs}, queue: {cases: queue}, overrides: await get('/api/review/overrides')};
  const queueB = Object.assign({}, queue[0], {run_id: B.run_id});
  const bodies = {
    runs: {old: {runs: [A]}, fresh: {runs: [B]}, freshIds: [B.run_id], unavailable: X.runsUnavailable},
    queue: {old: {cases: [queue[0]]}, fresh: {cases: [queueB]}, freshIds: [B.run_id], unavailable: X.queueUnavailable},
    overrides: {old: {approved_count: 7, groups: []}, fresh: {approved_count: 2, groups: []}, freshIds: [], unavailable: X.overridesUnavailable},
  };
  const browser = await puppeteer.launch({headless: true, executablePath: process.env.BROWSER_EXECUTABLE, args: ['--no-sandbox']});
  try {
    for (const [width, height] of [[390, 844], [1280, 844]]) {
      // ------------------------------------------------------------ stale panel loads
      for (const panel of ['runs', 'queue', 'overrides']) {
        for (const older of ['success', 'http500']) {
          for (const newer of ['success', 'failure']) {
            await scenario('stale-' + panel + '-' + older + '-then-' + newer + '@' + width, async () => {
              const held = [], seen = [];
              const spec = bodies[panel];
              const newerStep = newer === 'success' ? {body: spec.fresh} : {status: 500};
              const {page} = await openPage(browser, width, height, {[PANEL[panel].path]: scripted([{hold: true}, newerStep], held, seen)});
              try {
                await page.goto(base, {waitUntil: 'domcontentloaded'});
                while (!held[0]) await sleep(10);
                await page.click('#queue-refresh');
                while (seen.length < 2) await sleep(10);
                await sleep(250);
                const before = await page.evaluate(PANEL[panel].state);
                if (newer === 'success') {
                  if (panel === 'overrides') assert.match(before.text, /Approved as proposed: 2/);
                  else assert.deepEqual(before.ids, spec.freshIds, 'the newer load rendered');
                } else {
                  assert.deepEqual(before.ids, []);
                  assert.equal(before.status, spec.unavailable, 'the newer failure is shown');
                }
                assert.equal(before.busy, 'false', 'the newer load cleared aria-busy');
                await held[0].respond(older === 'success' ? json(spec.old) : {status: 500, contentType: 'application/json', body: '{}'});
                await sleep(300);
                const after = await page.evaluate(PANEL[panel].state);
                assert.deepEqual(after, before, 'an older ' + older + ' response changed the ' + panel + ' list');
              } finally { await page.close(); }
            });
          }
        }
      }

      // ------------------------------------------------------------ refresh, then open
      for (const list of ['runs', 'queue']) {
        await scenario('refresh-then-open-' + list + '@' + width, async () => {
          const cfg = list === 'runs'
            ? {panel: 'runs', row: '#runs-content .run-row', open: '#runs-content .run-open', rowStatus: '.run-open-status', id: A.run_id, same: {runs}}
            : {panel: 'queue', row: '#queue-content .queue-row', open: '#queue-content .queue-open', rowStatus: '.queue-open-status', id: queue[0].run_id, same: {cases: queue}};
          // Every list is held on Refresh, so nothing re-renders (and re-marks the buttons) behind the check.
          const heldList = [], seenList = [], heldCase = [], seenCase = [], heldOther = {};
          const rules = {
            ['/api/review/' + cfg.id + '/case']: scripted([{hold: true}, {pass: true}], heldCase, seenCase),
          };
          for (const other of Object.keys(PANEL)) {
            heldOther[other] = [];
            rules[PANEL[other].path] = scripted([{pass: true}, {hold: true}], other === cfg.panel ? heldList : heldOther[other], []);
          }
          const {page, log} = await openPage(browser, width, height, rules);
          try {
            await page.goto(base, {waitUntil: 'networkidle0'});
            await until(page, s => document.querySelectorAll(s).length > 0, cfg.open, 'the list');
            await page.click('#queue-refresh');
            while (!heldList[1] || Object.keys(heldOther).some(k => k !== cfg.panel && !heldOther[k][1])) await sleep(10);
            const during = await page.evaluate(cfg => ({
              disabled: Array.from(document.querySelectorAll(cfg.open)).map(b => b.disabled),
              texts: Array.from(document.querySelectorAll(cfg.open)).map(b => b.textContent),
              busy: document.getElementById(cfg.panel + '-content').getAttribute('aria-busy')}), cfg);
            assert.ok(during.disabled.length >= 1 && during.disabled.every(d => d === true), 'every Open button is disabled while the list loads');
            assert.deepEqual(during.texts, during.texts.map(() => 'Open case'));
            assert.equal(during.busy, 'true', 'the list is aria-busy');
            await page.click(cfg.open);                 // a click on a disabled button starts nothing
            await sleep(150);
            assert.equal(seenCase.length, 0, 'no /case request while the list is loading');
            await heldList[1].respond(json(cfg.same));
            for (const other of Object.keys(heldOther)) if (other !== cfg.panel) await heldOther[other][1].respond(json(realBodies[other]));
            await until(page, cfg => document.getElementById(cfg.panel + '-content').getAttribute('aria-busy') === 'false'
              && Array.from(document.querySelectorAll(cfg.open)).every(b => !b.disabled), cfg, 'the replacement rows');
            await page.click(cfg.open);
            while (!heldCase[0]) await sleep(10);
            const pending = await page.$eval(cfg.open, b => ({text: b.textContent, disabled: b.disabled}));
            assert.deepEqual(pending, {text: 'Opening…', disabled: true}, 'the replacement row shows the pending open');
            await heldCase[0].respond({status: 500, contentType: 'application/json', body: '{}'});
            await until(page, cfg => document.querySelector(cfg.row + ' ' + cfg.rowStatus).textContent !== '', cfg, 'the row-local failure');
            const failed = await page.evaluate(cfg => ({
              row: document.querySelector(cfg.row + ' ' + cfg.rowStatus).textContent,
              button: document.querySelector(cfg.open).textContent, disabled: document.querySelector(cfg.open).disabled,
              global: document.getElementById('load-status').textContent}), cfg);
            assert.equal(failed.row, X.caseFailed, 'the failure is on the visible row');
            assert.equal(failed.global, X.caseFailed);
            assert.equal(failed.button, 'Open case');
            assert.equal(failed.disabled, false, 'retry is possible');
            await page.click(cfg.open);
            await until(page, id => document.getElementById('loaded-file').textContent === id, cfg.id, 'the retry to open the case');
            const retried = await page.$eval(cfg.row + ' ' + cfg.rowStatus, e => e.textContent);
            assert.equal(retried, '', 'the retry cleared the row failure');
            assert.equal(log.filter(p => p === '/api/review/' + cfg.id + '/case').length, 2);
          } finally { await page.close(); }
        });
      }

      // A dropped open (Open, then Refresh) answers late: its reply must not re-enable the rows still loading.
      for (const list of ['runs', 'queue']) {
        await scenario('refresh-then-open-late-reply-' + list + '@' + width, async () => {
          const cfg = list === 'runs'
            ? {panel: 'runs', open: '#runs-content .run-open', id: A.run_id, same: {runs}}
            : {panel: 'queue', open: '#queue-content .queue-open', id: queue[0].run_id, same: {cases: queue}};
          const heldList = [], heldCase = [], heldOther = {};
          const rules = {['/api/review/' + cfg.id + '/case']: scripted([{hold: true}, {pass: true}], heldCase, [])};
          for (const other of Object.keys(PANEL)) {
            heldOther[other] = [];
            rules[PANEL[other].path] = scripted([{pass: true}, {hold: true}], other === cfg.panel ? heldList : heldOther[other], []);
          }
          const {page} = await openPage(browser, width, height, rules);
          try {
            await page.goto(base, {waitUntil: 'networkidle0'});
            await until(page, s => document.querySelectorAll(s).length > 0, cfg.open, 'the list');
            await page.click(cfg.open);
            while (!heldCase[0]) await sleep(10);
            await page.click('#queue-refresh');
            while (!heldList[1] || Object.keys(heldOther).some(k => k !== cfg.panel && !heldOther[k][1])) await sleep(10);
            await heldCase[0].respond(json((await get('/api/review/' + cfg.id + '/case'))));
            await sleep(200);
            const during = await page.evaluate(cfg => ({
              disabled: Array.from(document.querySelectorAll(cfg.open)).map(b => b.disabled),
              busy: document.getElementById(cfg.panel + '-content').getAttribute('aria-busy'),
              loaded: document.getElementById('loaded-file').textContent}), cfg);
            assert.ok(during.disabled.length >= 1 && during.disabled.every(d => d === true), 'the late reply re-enabled an Open button');
            assert.equal(during.busy, 'true');
            assert.equal(during.loaded, '', 'the dropped open did not render');
            await heldList[1].respond(json(cfg.same));
            for (const other of Object.keys(heldOther)) if (other !== cfg.panel) await heldOther[other][1].respond(json(realBodies[other]));
            await until(page, cfg => document.getElementById(cfg.panel + '-content').getAttribute('aria-busy') === 'false'
              && Array.from(document.querySelectorAll(cfg.open)).every(b => !b.disabled), cfg, 'the replacement rows');
          } finally { await page.close(); }
        });
      }

      // ------------------------------------------------------------ the folder picker
      {
        const root = fs.mkdtempSync(path.join(os.tmpdir(), 'w35rk-'));
        const {page, log} = await openPage(browser, width, height, {});
        try {
          await page.goto(base, {waitUntil: 'networkidle0'});
          const input = await page.$('#run-folder-picker');
          const realCase = (await get('/api/review/' + queue[0].run_id + '/case')).case_file;
          const pick = async (dirName, raw) => {
            const dir = path.join(root, dirName);
            fs.mkdirSync(path.join(dir, 'payloads'), {recursive: true});
            fs.writeFileSync(path.join(dir, 'case_file.json'), raw);
            fs.writeFileSync(path.join(dir, 'payloads', '0001-x.json'), '{}');
            const mark = log.length;
            await input.uploadFile(dir);
            await sleep(100);
            await until(page, () => { const s = document.getElementById('load-status'); return s.dataset.state === 'success' || s.dataset.state === 'error'; }, null, 'the folder load to settle');
            await sleep(120);
            const state = await page.evaluate(() => ({
              text: document.getElementById('load-status').textContent, state: document.getElementById('load-status').dataset.state,
              hidden: document.getElementById('case-workspace').hidden, loaded: document.getElementById('loaded-file').textContent,
              payload: document.getElementById('payload-status').textContent, resolution: document.getElementById('resolution-content').textContent}));
            return Object.assign(state, {requests: log.slice(mark)});
          };
          let index = 0;
          for (const [label, raw] of Object.entries(X.shapes)) {
            const name = 'folder-' + label.replace(/\W+/g, '-') + '@' + width;
            await scenario(name, async () => {
              const got = await pick('shape-' + (index++), raw);
              assert.equal(got.text, X.notObject);
              assert.equal(got.state, 'error');
              assert.equal(got.hidden, true, 'no workspace');
              assert.equal(got.loaded, '');
              assert.equal(got.payload, X.notAttached, 'nothing attached');
              assert.deepEqual(got.requests.filter(p => p.endsWith('/prompts')), [], 'no prompts request');
            });
          }
          await scenario('folder-valid-control@' + width, async () => {
            const got = await pick('valid-' + width, JSON.stringify(realCase));
            assert.equal(got.state, 'success');
            assert.equal(got.hidden, false);
            assert.match(got.text, /^Loaded valid-\d+\/case_file\.json\.$/);
            assert.match(got.payload, /^Attached 2 run file\(s\)/);
            assert.ok(got.requests.some(p => p.endsWith('/prompts')), 'a valid case asks for its prompts');
          });
          await scenario('folder-unknown-outcome-control@' + width, async () => {
            const odd = Object.assign({}, realCase, {resolution: {outcome: 'mystery'}});
            const got = await pick('odd-' + width, JSON.stringify(odd));
            assert.equal(got.state, 'success');
            assert.match(got.resolution, /UNKNOWN OUTCOME/);
          });
          await scenario('folder-wrong-after-valid-clears-the-workspace@' + width, async () => {
            const got = await pick('after-' + width, '{}');
            assert.equal(got.state, 'error');
            assert.equal(got.hidden, true);
          });
        } finally { await page.close(); fs.rmSync(root, {recursive: true, force: true}); }
      }
    }
    report.passed = Object.values(report.scenarios).every(v => v === null) && report.pageErrors.length === 0;
  } catch (e) {
    report.error = String(e && e.stack || e);
    process.exitCode = 1;
  } finally {
    await browser.close();
    fs.writeFileSync(output, JSON.stringify(report, null, 2));
    const failed = Object.entries(report.scenarios).filter(([, v]) => v !== null);
    console.log(JSON.stringify({passed: report.passed, scenarios: Object.keys(report.scenarios).length, failed: failed.length, error: report.error}));
    if (!report.passed) process.exitCode = 1;
  }
})().catch(e => { console.error(e); process.exitCode = 1; });
