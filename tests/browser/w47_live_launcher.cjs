/* W47 A: the live launcher's page contract in a real browser.
 *
 * PARENT-OWNED and UNEXECUTED in this prep. Run it once, serially, on the combined
 * reference after the build, with a resolved browser — do not run it from the prep lane.
 *
 * Run:
 *   PUPPETEER_MODULE=... BROWSER_EXECUTABLE=... \
 *     node tests/browser/w47_live_launcher.cjs BASE_URL OUTPUT_JSON
 *
 * BASE_URL is a running server on this tree. The mock is enough here: this script checks
 * the START PAGE's provider-neutral sentence (one sentence, two links, no mock-only text)
 * and that the live launcher's landing surface, /party/, answers. It does NOT and cannot
 * prove the live provider — that proof is the launcher's own in-process check and a real
 * filing, never a page claim.
 */
const fs = require('node:fs'), path = require('node:path');
const puppeteer = require(process.env.PUPPETEER_MODULE || 'puppeteer');
const [base, output] = process.argv.slice(2);
fs.mkdirSync(path.dirname(output), {recursive: true});
const report = {passed: false, checks: [], errors: []};
const ok = (name, pass, detail) => report.checks.push({name, pass: !!pass, detail});

const INTRO = 'Runs on your computer with sample trips. The standard launcher uses an illustrative mock; the live launcher uses Tencent AI and needs private access keys.';
const OLD_INTRO = 'The AI is a stand-in (mock)';

(async () => {
  const browser = await puppeteer.launch({headless: true, executablePath: process.env.BROWSER_EXECUTABLE, args: ['--no-sandbox']});
  const open = async (url, width, height) => {
    const page = await browser.newPage();
    page.on('pageerror', e => report.errors.push(`${url}: ${e.message}`));
    page.on('response', r => { if (r.status() >= 400 && !r.url().endsWith('/favicon.ico')) report.errors.push(`${r.status()} ${r.url()}`); });
    await page.setViewport({width, height});
    await page.goto(base + url, {waitUntil: 'networkidle0'});
    return page;
  };
  try {
    for (const width of [390, 1280]) {
      const page = await open('/start/', width, 844);
      const intro = await page.evaluate(() => {
        const p = document.querySelector('p.intro');
        return p ? p.textContent.trim().replace(/\s+/g, ' ') : null;
      });
      const links = await page.evaluate(() => [...document.querySelectorAll('a')].map(a => a.getAttribute('href')));
      const bodyText = await page.evaluate(() => document.body.textContent);
      ok(`${width} start: one provider-neutral intro`, intro === INTRO, intro);
      ok(`${width} start: no mock-only sentence`, bodyText.indexOf(OLD_INTRO) === -1, OLD_INTRO);
      ok(`${width} start: two links`, links.length === 2, links);
    }
    // The live launcher lands the operator on /party/; it must answer with the Ryde server.
    const party = await open('/party/', 390, 844);
    ok('party page answers', (await party.evaluate(() => document.title)).length > 0, null);
  } catch (e) {
    report.errors.push(String(e && e.stack || e));
  }
  report.passed = report.errors.length === 0 && report.checks.every(c => c.pass);
  fs.writeFileSync(output, JSON.stringify(report, null, 2));
  await browser.close();
  console.log(JSON.stringify({passed: report.passed, checks: report.checks.length, errors: report.errors.length}));
  process.exit(report.passed ? 0 : 1);
})();
