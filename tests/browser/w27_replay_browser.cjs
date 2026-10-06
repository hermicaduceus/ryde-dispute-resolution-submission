/* W27 parent real-browser gate. Existing Puppeteer conventions, no installs, no network.
 * Serve an exported site on loopback first (any static server; the parent uses
 * `/usr/bin/python3 -m http.server --bind 127.0.0.1 <port 18800-18899> -d <out>`), then:
 *   PUPPETEER_MODULE=... BROWSER_EXECUTABLE=... node tests/browser/w27_replay_browser.cjs BASE_URL RD_RUN_ID RECORDED_ON OUTPUT_JSON
 * Every request off the loopback origin is aborted; an /api/ request that reaches the static
 * server is a failure (the shim must answer it in the page). 390px and 1280px.
 */
const assert = require('node:assert/strict'), fs = require('node:fs');
const puppeteer = require(process.env.PUPPETEER_MODULE || 'puppeteer');
const [base, rd, recordedOn, output] = process.argv.slice(2);
const report = { passed: false, pages: [], errors: [] };
const sentence = (s) => 'Replay of saved runs recorded on ' + recordedOn + ', ' + s + ' the human decision. Forms work as a guided walk-through; nothing you submit is processed.';
(async () => {
  const browser = await puppeteer.launch({ headless: true, executablePath: process.env.BROWSER_EXECUTABLE, args: ['--no-sandbox'] });
  try {
    for (const width of [390, 1280]) {
      const page = await browser.newPage();
      const apiHits = [], pageErrors = [];
      page.on('pageerror', (e) => pageErrors.push(String(e)));
      await page.setViewport({ width, height: 844 });
      await page.setRequestInterception(true);
      page.on('request', (r) => {
        const u = new URL(r.url());
        if (u.origin !== new URL(base).origin) return r.abort();
        if (u.pathname.startsWith('/api/')) apiHits.push(r.method() + ' ' + u.pathname + u.search);
        return r.continue();
      });
      // Landing page: four steps, follow each link.
      await page.goto(base + '/replay/index.html', { waitUntil: 'networkidle0' });
      const steps = await page.$$eval('ol li a', (as) => as.map((a) => ({ text: a.textContent.trim(), href: a.getAttribute('href') })));
      assert.equal(steps.length, 4);
      const visits = [];
      for (const step of steps) {
        await page.goto(base + step.href, { waitUntil: 'networkidle0' });
        await new Promise((r) => setTimeout(r, 300));
        const state = await page.evaluate(() => {
          const banner = document.getElementById('replay-banner');
          return {
            path: location.pathname + location.search,
            bannerFirst: Boolean(banner && document.body.firstElementChild === banner),
            bannerText: banner ? Array.from(banner.childNodes).filter((n) => n.id !== 'replay-switch').map((n) => n.textContent).join('').trim() : null,
            switchText: banner && banner.querySelector('#replay-switch') ? banner.querySelector('#replay-switch').textContent.trim() : null,
            overflow: document.scrollingElement.scrollWidth > window.innerWidth,
            text: document.body.innerText,
          };
        });
        const snapshot = step.href.includes('snapshot=before') ? 'before' : 'after';
        assert.ok(state.bannerFirst, 'banner first on ' + step.href);
        assert.equal(state.bannerText, 'TEST REPLAY (mock model). ' + sentence(snapshot));
        assert.equal(state.switchText, snapshot === 'before' ? 'Show after the decision' : 'Show before the decision');
        assert.equal(state.overflow, false, 'horizontal overflow on ' + step.href + ' at ' + width);
        visits.push({ step: step.text, path: state.path, textSample: state.text.slice(0, 400) });
      }
      // Console before the decision: the held RD-0109 run is in the queue; a decision POST is refused.
      await page.goto(base + '/index.html?snapshot=before&run=' + rd, { waitUntil: 'networkidle0' });
      const posted = await page.evaluate((run) => fetch('/api/review/' + run + '/decision', { method: 'POST', body: '{}' })
        .then((r) => r.json().then((b) => ({ status: r.status, body: b }))), rd);
      assert.equal(posted.status, 403);
      assert.equal(posted.body.error, "This is a replay. In the recorded run, the reviewer chose: approve, SGD 55.16. Use 'Show after the decision' in the banner to see the result.");
      // In-site navigation keeps the snapshot.
      await page.goto(base + '/party/status.html', { waitUntil: 'networkidle0' });
      const kept = await page.$eval('#replay-banner', (b) => b.textContent);
      assert.ok(kept.includes('before the human decision'), 'snapshot not kept across navigation');
      assert.deepEqual(apiHits, [], 'API requests reached the static server');
      assert.deepEqual(pageErrors, []);
      report.pages.push({ width, visits });
      await page.close();
    }
    report.passed = true;
  } catch (e) {
    report.errors.push(String(e && e.stack || e));
    throw e;
  } finally {
    await browser.close();
    fs.writeFileSync(output, JSON.stringify(report, null, 2));
  }
})().catch((e) => { console.error(e); process.exit(1); });
