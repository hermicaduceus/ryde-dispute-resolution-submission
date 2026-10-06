/* W24 console prompt panel: the real-browser contract, written RED-first by the planner's
 * RED-test preparer. Driven by tests/test_w24_prompt_panel.py (RealBrowserPromptPanel), which
 * starts the real server on an ephemeral port with real mock runs and passes:
 *   argv: <base url> <report json path>
 *   env:  PUPPETEER_MODULE, BROWSER_EXECUTABLE, W24_EXPECT (run ids, stored fingerprints, strings)
 * It never files, decides or writes; the only interference is holding or failing the
 * /prompts requests it names, each released explicitly.
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const puppeteer = require(process.env.PUPPETEER_MODULE || 'puppeteer');
const [base, output] = process.argv.slice(2);
const X = JSON.parse(process.env.W24_EXPECT);
const report = {passed: false, cases: [], errors: []};
const frames = page => page.evaluate(() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r))));
const badge = fp => 'Matches what was sent (fingerprint ' + fp.slice(0, 8) + ')';

async function panel(page) {
  return page.evaluate(() => {
    const root = document.getElementById('prompts-content');
    if (!root) return null;
    return {
      text: root.textContent,
      articles: Array.from(root.querySelectorAll('article')).map(a => ({
        heading: (a.querySelector('h1,h2,h3,h4,h5,h6') || {}).textContent || null,
        text: a.textContent,
        details: a.querySelectorAll('details').length,
        summary: (a.querySelector('details > summary') || {}).textContent || null,
        pre: (a.querySelector('details pre') || {}).textContent || null,
        dl: a.querySelectorAll('dl').length,
      })),
    };
  });
}

(async () => {
  const browser = await puppeteer.launch({headless: true, executablePath: process.env.BROWSER_EXECUTABLE,
    args: ['--no-sandbox']});
  try {
    // 1. Deep link to a ruled run, desktop then narrow: three articles, exact badges, order.
    for (const [width, height] of [[1280, 900], [390, 844]]) {
      const page = await browser.newPage();
      page.on('pageerror', e => report.errors.push(String(e)));
      await page.setViewport({width, height});
      await page.goto(base + '/?run=' + encodeURIComponent(X.ruled), {waitUntil: 'domcontentloaded'});
      await page.waitForFunction(() => document.querySelectorAll('#prompts-content article').length === 3,
        {timeout: 10000});
      const p = await panel(page);
      assert.deepEqual(p.articles.map(a => a.heading), X.labels);
      p.articles.forEach((a, i) => {
        assert.ok(a.text.includes(badge(X.fingerprints.ruled[i])), 'badge for ' + X.labels[i]);
        assert.ok(a.dl >= 1, 'summary is a <dl>');
        assert.equal(a.details, 1);
        assert.equal(a.summary, X.summary);
      });
      assert.ok(p.articles[0].pre.startsWith('You are the Rider Advocate'), 'full text starts with the system prompt');
      assert.ok(p.articles[0].pre.includes('\n\nDISPUTE\n'), 'system and user prompt joined by a blank line');
      const order = await page.evaluate(() => Array.from(document.querySelectorAll('#case-workspace > section'))
        .map(s => s.id));
      assert.deepEqual(order.slice(2, 5), ['evidence-section', 'prompts-section', 'claims-section']);
      // Open every full text and require no horizontal page overflow (narrow viewport included).
      await page.evaluate(() => document.querySelectorAll('#prompts-content details').forEach(d => { d.open = true; }));
      await frames(page);
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      assert.ok(overflow <= 1, 'open full text overflows the page by ' + overflow + 'px at ' + width);
      // Each full text stays inside its card: it wraps, or it scrolls inside itself.
      const pres = await page.evaluate(() => Array.from(document.querySelectorAll('#prompts-content article')).map(a => {
        const pre = a.querySelector('details pre');
        const s = getComputedStyle(pre);
        return {inside: pre.getBoundingClientRect().right <= a.getBoundingClientRect().right + 1,
          fits: pre.scrollWidth <= pre.clientWidth + 1, scrolls: ['auto', 'scroll'].includes(s.overflowX)};
      }));
      pres.forEach((p, i) => {
        assert.ok(p.inside, X.labels[i] + ' full text runs outside its card at ' + width);
        assert.ok(p.fits || p.scrolls, X.labels[i] + ' full text is cut off at ' + width);
      });
      report.cases.push({deepLink: X.ruled, width, overflow, pres});
      await page.close();
    }

    // 2. Stale responses: open case A from the queue, hold its /prompts, open case B, then release
    //    A as a late success and as a late failure. B's panel must survive both.
    for (const stale of ['success', 'failure']) {
      const page = await browser.newPage();
      page.on('pageerror', e => report.errors.push(String(e)));
      await page.setViewport({width: 1280, height: 900});
      await page.setRequestInterception(true);
      const held = [];
      page.on('request', r => (r.url().endsWith('/api/review/' + encodeURIComponent(X.a) + '/prompts')
        ? held.push(r) : r.continue()));
      await page.goto(base + '/', {waitUntil: 'domcontentloaded'});
      const open = id => page.click('.queue-row[data-run-id="' + id + '"] .queue-open');
      await page.waitForSelector('.queue-row[data-run-id="' + X.a + '"] .queue-open');
      await page.waitForSelector('.queue-row[data-run-id="' + X.b + '"] .queue-open');
      await open(X.a);
      const start = Date.now();
      while (!held.length) { assert.ok(Date.now() - start < 5000, 'A prompts not requested'); await new Promise(r => setTimeout(r, 10)); }
      await open(X.b);
      await page.waitForFunction(fp => document.getElementById('prompts-content').textContent.includes(fp),
        {timeout: 10000}, badge(X.fingerprints.withheld[0]));
      const before = await panel(page);
      if (stale === 'success') await held[0].continue();
      else await held[0].respond({status: 500, contentType: 'application/json', body: '{"error":"late"}'});
      await new Promise(r => setTimeout(r, 300));
      await frames(page);
      const after = await panel(page);
      assert.deepEqual(after, before, 'a late ' + stale + ' for case A changed case B\'s panel');
      assert.ok(!after.text.includes(badge(X.fingerprints.filed[0])), 'case A badge rendered');
      assert.ok(!after.text.includes(X.badgeFailure), 'case A failure rendered');
      report.cases.push({stale, articles: after.articles.length});
      await page.close();
    }

    // 3. An invalid deep link says so and renders nothing.
    {
      const page = await browser.newPage();
      page.on('pageerror', e => report.errors.push(String(e)));
      await page.goto(base + '/?run=..%2Fetc', {waitUntil: 'load'});
      await new Promise(r => setTimeout(r, 300));
      await frames(page);
      assert.equal(await page.$eval('#load-status', e => e.textContent), X.unknown);
      assert.equal(await page.$eval('#case-workspace', e => e.hidden), true);
      report.cases.push({invalidDeepLink: true});
      await page.close();
    }

    // 4. The server is gone for the prompts request: the one fixed sentence.
    {
      const page = await browser.newPage();
      page.on('pageerror', e => report.errors.push(String(e)));
      await page.setRequestInterception(true);
      page.on('request', r => (r.url().endsWith('/prompts') ? r.abort('connectionrefused') : r.continue()));
      await page.goto(base + '/?run=' + encodeURIComponent(X.ruled), {waitUntil: 'domcontentloaded'});
      await page.waitForFunction(() => document.getElementById('case-workspace').hidden === false
        && document.getElementById('prompts-content').textContent.length > 0, {timeout: 10000});
      await new Promise(r => setTimeout(r, 200));
      assert.equal(await page.$eval('#prompts-content', e => e.textContent), X.badgeFailure);
      report.cases.push({serverGone: true});
      await page.close();
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
