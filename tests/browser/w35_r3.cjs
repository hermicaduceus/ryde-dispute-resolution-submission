/* W35 fix round R3: the operator console in a real browser. Written RED-first against 680ce9b.
 * Driven by tests/test_w35_r3.py (RealBrowserR3) against the real server on the mock model, which holds a
 * withheld route-deviation run (queued, env W35R3_QUEUED) and a ruled no-show run. Passes:
 *   argv: <base url> <report json path>
 *   env:  PUPPETEER_MODULE, BROWSER_EXECUTABLE, W35R3_QUEUED
 * Only the response ORDER is scripted (request interception on 127.0.0.1); every case body comes from the
 * real server. Each scenario records its own error in report.scenarios (null = passed). 390x844 and 1280x844.
 *   reused-current-<list>-<stale>   open A; reopen A (held: the stale open); Refresh; reopen A from the
 *                                   replacement, already-current row (held: the newer open); release the
 *                                   stale one (success or HTTP 500): the newer open stays "Opening…" and
 *                                   disabled, its row stays the one current; release the newer: settled.
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const puppeteer = require(process.env.PUPPETEER_MODULE || 'puppeteer');
const [base, output] = process.argv.slice(2);
const A = process.env.W35R3_QUEUED;
const report = {passed: false, scenarios: {}, pageErrors: []};
const sleep = ms => new Promise(r => setTimeout(r, ms));
const get = p => new Promise((resolve, reject) => http.get(base + p, r => {
  let raw = ''; r.on('data', c => raw += c); r.on('end', () => resolve(JSON.parse(raw)));
}).on('error', reject));
const json = body => ({status: 200, contentType: 'application/json', body: JSON.stringify(body)});

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

async function scenario(name, fn) {
  try { await fn(); report.scenarios[name] = null; } catch (e) { report.scenarios[name] = String(e && e.message || e); }
}

(async () => {
  assert.ok(A, 'W35R3_QUEUED names the queued run');
  const queue = (await get('/api/review/queue')).cases;
  const runs = (await get('/api/review/runs')).runs;
  assert.ok(queue.some(c => c.run_id === A) && runs.some(r => r.run_id === A), 'fixture: A is listed and queued');
  const caseA = await get('/api/review/' + A + '/case');
  const browser = await puppeteer.launch({headless: true, executablePath: process.env.BROWSER_EXECUTABLE, args: ['--no-sandbox']});
  try {
    for (const [width, height] of [[390, 844], [1280, 844]]) {
      for (const list of ['runs', 'queue']) {
        for (const stale of ['success', 'http500']) {
          await scenario('reused-current-' + list + '-' + stale + '@' + width, async () => {
            const sel = {list, button: '#' + list + '-content [data-run-id="' + A + '"] .' + (list === 'runs' ? 'run' : 'queue') + '-open'};
            const held = [];
            let n = 0;
            const rules = {['/api/review/' + A + '/case']: req => { const index = n++; if (index === 0) return req.continue(); held[index] = req; }};
            const {page, log} = await openPage(browser, width, height, rules);
            const state = () => page.evaluate(sel => {
              const b = document.querySelector(sel.button);
              const marked = Array.from(document.querySelectorAll('[aria-current="true"]'));
              return {text: b.textContent, disabled: b.disabled, current: marked.length,
                      mine: marked.length === 1 && marked[0] === b, open: b.closest('li').classList.contains('is-open'),
                      loaded: document.getElementById('loaded-file').textContent};
            }, sel);
            try {
              await page.goto(base, {waitUntil: 'networkidle0'});
              await until(page, s => !!document.querySelector(s), sel.button, 'the list');
              await page.click(sel.button);
              await until(page, a => document.getElementById('loaded-file').textContent === a, A, 'the first open');
              await page.click(sel.button);                                   // the open Refresh will drop
              while (!held[1]) await sleep(10);
              await page.click('#queue-refresh');
              await until(page, sel => document.getElementById(sel.list + '-content').getAttribute('aria-busy') === 'false'
                && !!document.querySelector(sel.button) && !document.querySelector(sel.button).disabled, sel, 'the replacement row');
              const settled = await state();
              assert.equal(settled.text, 'Currently open', 'the replacement row is the current one');
              await page.click(sel.button);                                   // the newer open
              while (!held[2]) await sleep(10);
              const pending = await state();
              assert.deepEqual([pending.text, pending.disabled], ['Opening…', true], 'the newer open is pending');
              await held[1].respond(stale === 'success' ? json(caseA) : {status: 500, contentType: 'application/json', body: '{}'});
              await sleep(250);
              const afterStale = await state();
              assert.deepEqual([afterStale.text, afterStale.disabled], ['Opening…', true],
                'the stale ' + stale + ' settled the newer open\'s button');
              assert.equal(afterStale.current, 1, 'exactly one row is current');
              assert.equal(afterStale.mine, true, 'the current mark stays on the pending row');
              assert.equal(afterStale.open, true);
              assert.equal(afterStale.loaded, A);
              await held[2].respond(json(caseA));
              await until(page, s => { const b = document.querySelector(s); return b.textContent === 'Currently open' && !b.disabled; },
                sel.button, 'the newer open to settle');
              const landed = await state();
              assert.equal(landed.loaded, A);
              assert.equal(landed.mine, true);
              assert.equal(log.filter(p => p === '/api/review/' + A + '/case').length, 3);
            } finally { await page.close(); }
          });
        }
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
