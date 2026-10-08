/* W35 lane C: Recent runs in the static replay. Written RED-first against HEAD 57758ce.
 * Driven by tests/test_w35_C.py (RealBrowserReplay), which exports the W27 mock fixture with
 * tools/export_replay.py --allow-mock, serves the site statically on loopback and passes:
 *   argv: <base url> <report json path>
 *   env:  PUPPETEER_MODULE, BROWSER_EXECUTABLE, W35C_REPLAY_EXPECT ({runs: [run ids]})
 * In both snapshots, at 390 and 1280 wide, the console's Recent runs lists the snapshot's own
 * runs and every listed run opens from the recording. An /api/ request that reaches the static
 * server is a failure (the replay shim answers them in the page). Read-only.
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const puppeteer = require(process.env.PUPPETEER_MODULE || 'puppeteer');
const [base, output] = process.argv.slice(2);
const X = JSON.parse(process.env.W35C_REPLAY_EXPECT);
const report = {passed: false, cases: [], errors: []};

(async () => {
  const browser = await puppeteer.launch({headless: true, executablePath: process.env.BROWSER_EXECUTABLE, args: ['--no-sandbox']});
  try {
    for (const [width, height] of [[390, 844], [1280, 844]]) {
      for (const snapshot of ['before', 'after']) {
        const page = await browser.newPage();
        page.on('pageerror', e => report.errors.push(String(e)));
        const apiHits = [];
        page.on('request', r => { const u = new URL(r.url()); if (u.pathname.startsWith('/api/')) apiHits.push(u.pathname); });
        await page.setViewport({width, height});
        await page.goto(base + '/index.html?snapshot=' + snapshot, {waitUntil: 'networkidle0'});
        await page.waitForFunction(n => document.querySelectorAll('#runs-content .run-row').length === n, {timeout: 10000}, X.runs.length);
        const listed = await page.$$eval('#runs-content .run-row', rows => rows.map(r => r.dataset.runId));
        assert.deepEqual(listed.slice().sort(), X.runs.slice().sort());
        for (const id of listed) {
          await page.click('.run-row[data-run-id="' + id + '"] .run-open');
          await page.waitForFunction(id => document.getElementById('loaded-file').textContent === id
            && document.getElementById('case-workspace').hidden === false, {timeout: 10000}, id);
          const state = await page.evaluate(id => ({
            current: Array.from(document.querySelectorAll('#queue-content [aria-current], #runs-content [aria-current]')).map(b => b.closest('li').dataset.runId),
            rowStatus: document.querySelector('.run-row[data-run-id="' + id + '"] .run-open-status').textContent,
            overflow: document.documentElement.scrollWidth - window.innerWidth,
          }), id);
          assert.deepEqual(state.current, [id], 'exactly one marker, on the opened run');
          assert.equal(state.rowStatus, '', 'the run opened from the recording');
          assert.ok(state.overflow <= 1, 'the replay console overflows by ' + state.overflow + 'px at ' + width);
        }
        assert.deepEqual(apiHits, [], 'API requests reached the static server');
        report.cases.push({width, snapshot, listed});
        await page.close();
      }
    }
    assert.deepEqual(report.errors, []);
    report.passed = true;
  } catch (e) {
    report.error = String(e && e.stack || e);
    process.exitCode = 1;
  } finally {
    await browser.close();
    fs.writeFileSync(output, JSON.stringify(report, null, 2));
    console.log(JSON.stringify({passed: report.passed, cases: report.cases.length, error: report.error}));
  }
})().catch(e => { console.error(e); process.exitCode = 1; });
