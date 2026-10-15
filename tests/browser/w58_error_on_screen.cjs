/* W58 real-browser gate: a message shown under "Send my dispute" is brought on screen.
 *
 * party.js showError() reveals an error node below the Send button. On a long details form that
 * node sat below the visible area, so the party saw nothing happen. The fix scrolls the node into
 * view. Measured on the rendered page, rider and driver filing pages, at phone and desktop width:
 *
 *   empty   - Send with no description (the form's own client-side check)
 *   server  - Send with a description; the filing POST is answered 429 with an error body (the
 *             hosted site's limit refusal, reproduced here by intercepting the request)
 *
 * "On screen" is a hit test, not a rectangle check: the point at the message's centre must land on
 * the message itself, so a node clipped by a scroll container or below the viewport fails.
 *
 * PUPPETEER_MODULE=... BROWSER_EXECUTABLE=... node tests/browser/w58_error_on_screen.cjs BASE_URL OUTPUT_JSON
 */
const fs = require('node:fs');
const puppeteer = require(process.env.PUPPETEER_MODULE || 'puppeteer');
const [base, output] = process.argv.slice(2);
const SERVER_MESSAGE = 'W58 gate: refusal from the server.';
const EMPTY_MESSAGE = 'Please tell us what happened before sending.';
const report = { passed: false, cases: [], errors: [] };
(async () => {
  const browser = await puppeteer.launch({ headless: true, executablePath: process.env.BROWSER_EXECUTABLE, args: ['--no-sandbox'] });
  try {
    for (const [file, role, category] of [['index.html', 'rider', 'My trip went the wrong way'],
                                          ['driver-filing.html', 'driver', 'A no-show or waiting fee']]) {
      for (const width of [390, 1280]) {
        for (const scenario of ['empty', 'server']) {
          const page = await browser.newPage();
          page.on('pageerror', e => report.errors.push(`${role} ${width} ${scenario}: ${e}`));
          await page.setViewport({ width, height: width < 600 ? 844 : 900 });
          await page.setRequestInterception(true);
          page.on('request', req => {
            if (scenario === 'server' && req.method() === 'POST' && new URL(req.url()).pathname === '/api/disputes') {
              req.respond({ status: 429, contentType: 'application/json', body: JSON.stringify({ error: SERVER_MESSAGE }) });
            } else {
              req.continue();
            }
          });
          await page.goto(`${base}/party/${file}`, { waitUntil: 'networkidle0' });
          await page.evaluate(c => [...document.querySelectorAll('#category-options .option-card')]
            .find(b => b.innerText.trim().startsWith(c)).click(), category);
          await page.click('#category-next');
          await page.waitForFunction(() => document.querySelectorAll('#trip-options .trip-card').length > 0);
          await page.evaluate(() => document.querySelector('#trip-options .trip-card').click());
          await page.click('#trip-next');
          await page.waitForSelector('#step-details:not([hidden])');
          if (scenario === 'server') await page.type('#description', `W58 gate ${role} ${width}`);
          await page.click('#details-submit');
          await page.waitForFunction(() => { const e = document.getElementById('details-error'); return e && !e.hidden && e.innerText.trim(); }, { timeout: 15000 });
          await new Promise(r => setTimeout(r, 400));  // let any smooth scroll settle before measuring
          const m = await page.evaluate(() => {
            const e = document.getElementById('details-error');
            const r = e.getBoundingClientRect();
            const x = Math.min(Math.max(r.left + r.width / 2, 0), innerWidth - 1);
            const y = r.top + r.height / 2;
            const inViewport = r.height > 0 && r.top >= 0 && r.bottom <= innerHeight;
            const hit = y >= 0 && y < innerHeight ? document.elementFromPoint(x, y) : null;
            return { message: e.innerText.trim(), top: r.top, bottom: r.bottom, viewport: innerHeight,
                     inViewport, hitIsMessage: !!hit && e.contains(hit) };
          });
          const expected = scenario === 'server' ? SERVER_MESSAGE : EMPTY_MESSAGE;
          const ok = m.message === expected && m.inViewport && m.hitIsMessage;
          report.cases.push({ role, width, scenario, ok, ...m });
          await page.close();
        }
      }
    }
    report.passed = report.cases.length === 8 && report.cases.every(c => c.ok) && report.errors.length === 0;
  } finally {
    await browser.close();
    fs.writeFileSync(output, JSON.stringify(report, null, 2));
  }
  if (!report.passed) { console.error(JSON.stringify(report.cases.filter(c => !c.ok))); process.exit(1); }
})().catch(e => { console.error(e && e.stack || e); process.exit(1); });
