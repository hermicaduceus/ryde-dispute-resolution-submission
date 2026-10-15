/* Five-step walkthrough parent real-browser gate. Existing Puppeteer conventions, no installs.
 * Serve an exported site on loopback first (any static server; the parent uses
 * `/usr/bin/python3 -m http.server --bind 127.0.0.1 <port 18800-18899> -d <out>`), then:
 *   PUPPETEER_MODULE=... BROWSER_EXECUTABLE=... node tests/browser/replay_walkthrough.cjs \
 *       BASE_URL NS_DISPUTE RD_DISPUTE RD_RUN OUTPUT_JSON
 * Pins the walkthrough round (the operator ruling 2026-10-15) at 390px and 1280px:
 *   1. the landing lists five steps in the order after/waiting/before/after/final;
 *   2. the waiting step opens the BEFORE snapshot with one card, the detour case,
 *      heading "Your case is still under review", and not the no-show case;
 *   3. every visited page's banner carries a "Back to the steps" link to /replay/,
 *      and clicking it returns to the landing;
 *   4. the final step still shows both cards in the after state;
 *   5. no /api/ request reaches the static server and no page errors fire.
 * Every request off the loopback origin is aborted.
 */
const assert = require('node:assert/strict'), fs = require('node:fs');
const puppeteer = require(process.env.PUPPETEER_MODULE || 'puppeteer');
const [base, ns, rd, rdRun, output] = process.argv.slice(2);
const report = { passed: false, widths: [], errors: [] };

(async () => {
  const browser = await puppeteer.launch({ headless: true, executablePath: process.env.BROWSER_EXECUTABLE, args: ['--no-sandbox'] });
  try {
    for (const width of [390, 1280]) {
      const page = await browser.newPage();
      const apiHits = [], pageErrors = [];
      page.on('pageerror', (e) => pageErrors.push(String(e)));
      await page.setRequestInterception(true);
      page.on('request', (req) => {
        const url = new URL(req.url());
        if (url.origin !== new URL(base).origin) return req.abort();
        if (url.pathname.startsWith('/api/')) apiHits.push(url.pathname);
        req.continue();
      });
      await page.setViewport({ width, height: 844 });
      const checks = {};

      await page.goto(base + '/replay/', { waitUntil: 'networkidle0' });
      const steps = await page.$$eval('ol li a', (as) => as.map((a) => a.getAttribute('href')));
      checks.fiveSteps = steps.length === 5;
      checks.stepOrder = steps.length === 5 &&
        steps[0] === '/party/status.html?snapshot=after&dispute=' + ns &&
        steps[1] === '/party/status.html?snapshot=before&dispute=' + rd &&
        steps[2] === '/index.html?snapshot=before&run=' + rdRun &&
        steps[3] === '/index.html?snapshot=after&run=' + rdRun &&
        steps[4] === '/party/status.html?snapshot=after';

      const backOnPage = () => page.evaluate(() => {
        const banner = document.getElementById('replay-banner');
        const back = banner && banner.querySelector('#replay-back');
        return { hasBanner: Boolean(banner), hasBack: Boolean(back),
                 href: back ? back.getAttribute('href') : null,
                 text: back ? back.textContent.trim() : null };
      });

      await page.goto(base + '/party/status.html?snapshot=before&dispute=' + rd, { waitUntil: 'networkidle0' });
      const cards = await page.$$eval('#account-list .step', (cs) => cs.map((c) => c.textContent));
      checks.waitingShowsOneCard = cards.length === 1;
      checks.waitingCardIsTheDetour = cards.length === 1 && cards[0].includes(rd) && !cards[0].includes(ns);
      checks.waitingHeading = cards.length === 1 && cards[0].includes('Your case is still under review');
      const waitingBack = await backOnPage();
      checks.bannerOnWaitingPage = waitingBack.hasBanner;
      checks.backLinkOnWaitingPage = waitingBack.hasBack && waitingBack.href === '/replay/' &&
        waitingBack.text === 'Back to the steps';

      await Promise.all([page.waitForNavigation({ waitUntil: 'networkidle0' }),
        page.evaluate(() => document.getElementById('replay-back').click())]);
      checks.backClickReturnsToLanding = (await page.title()).trim() === 'Ryde dispute resolution: replay';

      await page.goto(base + '/index.html?snapshot=before&run=' + rdRun, { waitUntil: 'networkidle0' });
      checks.backLinkOnConsolePage = (await backOnPage()).hasBack;

      await page.goto(base + '/party/status.html?snapshot=after', { waitUntil: 'networkidle0' });
      checks.finalShowsBothCards = (await page.$$('#account-list .step')).length === 2;
      checks.backLinkOnFinalPage = (await backOnPage()).hasBack;

      checks.noApiReachedTheServer = apiHits.length === 0;
      checks.noPageErrors = pageErrors.length === 0;
      report.widths.push({ width, checks, apiHits, pageErrors });
      await page.close();
    }
    const every = (name) => report.widths.every((w) => w.checks[name] === true);
    for (const name of Object.keys(report.widths[0].checks)) assert.ok(every(name), 'failed: ' + name);
    report.passed = true;
  } catch (error) {
    report.errors.push(String(error));
  } finally {
    await browser.close();
    fs.writeFileSync(output, JSON.stringify(report, null, 2));
    console.log(report.passed ? 'PASS' : 'FAIL');
    process.exit(report.passed ? 0 : 1);
  }
})();