/* Step-1 targeting parent real-browser gate. Existing Puppeteer conventions, no installs.
 * Serve an exported site on loopback first (any static server; the parent uses
 * `/usr/bin/python3 -m http.server --bind 127.0.0.1 <port 18800-18899> -d <out>`), then:
 *   PUPPETEER_MODULE=... BROWSER_EXECUTABLE=... node tests/browser/step1_dispute_target.cjs \
 *       BASE_URL NS_DISPUTE RD_DISPUTE OUTPUT_JSON
 * Pins the comment-round fix at 390px and 1280px:
 *   1. the landing page's first step href carries dispute=<NS_DISPUTE>;
 *   2. that URL shows exactly ONE account card, the NS one, and not the RD one;
 *   3. the plain status URL (no param) still shows both cards;
 *   4. an unknown dispute param falls open to both cards (no blank page);
 *   5. no /api/ request reaches the static server and no page errors fire.
 * Every request off the loopback origin is aborted.
 */
const assert = require('node:assert/strict'), fs = require('node:fs');
const puppeteer = require(process.env.PUPPETEER_MODULE || 'puppeteer');
const [base, ns, rd, output] = process.argv.slice(2);
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
      const hrefs = await page.$$eval('ol li a', (as) => as.map((a) => a.getAttribute('href')));
      checks.landingStepOneTargetsNs = hrefs.length === 5 && hrefs[0].includes('dispute=' + ns);
      checks.landingFinalStepUnchanged = hrefs.length === 5 &&
        hrefs[4] === '/party/status.html?snapshot=after';

      await page.goto(base + '/party/status.html?snapshot=after&dispute=' + ns, { waitUntil: 'networkidle0' });
      const one = await page.$$eval('#account-list .step', (cards) => cards.map((c) => c.textContent));
      checks.stepOneShowsExactlyOneCard = one.length === 1;
      checks.stepOneCardIsTheNoShow = one.length === 1 && one[0].includes(ns) && one[0].includes('SGD 6.61');
      checks.stepOneCardIsNotTheDetour = one.length === 1 && !one[0].includes(rd);

      await page.goto(base + '/party/status.html?snapshot=after', { waitUntil: 'networkidle0' });
      checks.noParamShowsBothCards = (await page.$$('#account-list .step')).length === 2;

      await page.goto(base + '/party/status.html?snapshot=after&dispute=PF-NOPE', { waitUntil: 'networkidle0' });
      checks.unknownParamFallsOpen = (await page.$$('#account-list .step')).length === 2;

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