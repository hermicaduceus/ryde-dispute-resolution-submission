/* W30 viewport-bottom contract: loading, empty and current error, both filing roles.
 * Intercepted responses are deterministic test fixtures. No dispute submissions.
 * node tests/browser/w30_viewport_states.cjs BASE OUTPUT; same Puppeteer env as w30_trip_scroll.
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const puppeteer = require(process.env.PUPPETEER_MODULE || 'puppeteer');
const [base, output] = process.argv.slice(2);
const report = { passed: false, cases: [], errors: [] };
(async () => {
  const browser = await puppeteer.launch({ headless: true, executablePath: process.env.BROWSER_EXECUTABLE, args: ['--no-sandbox'] });
  try {
    for (const file of ['index.html', 'driver-filing.html']) {
      for (const mode of ['empty', 'error']) {
        for (const [width, height] of [[390, 844], [800, 320], [360, 480]]) {
          const page = await browser.newPage();
          page.on('pageerror', e => report.errors.push(String(e)));
          await page.setViewport({ width, height });
          await page.setRequestInterception(true);
          let held;
          page.on('request', r => {
            if(process.env.W30_TREE_OVERRIDE && r.url().includes('/party/')) {
              const name=require('node:path').basename(new URL(r.url()).pathname);
              if(name===file||name==='party.css')return r.respond({status:200,contentType:name.endsWith('.css')?'text/css':'text/html',body:fs.readFileSync(require('node:path').join(process.env.W30_TREE_OVERRIDE,'ui','party',name),'utf8')});
            }
            if (r.url().includes('/api/trips')) { held = r; return; }
            if (process.env.W30_CSS_OVERRIDE && r.url().endsWith('/party/party.css')) {
              return r.respond({ status: 200, contentType: 'text/css', body: fs.readFileSync(process.env.W30_CSS_OVERRIDE, 'utf8') });
            }
            return r.continue();
          });
          await page.goto(base + '/party/' + file, { waitUntil: 'domcontentloaded' });
          await page.evaluate(() => document.fonts.ready);
          await page.click('#category-options .option-card:first-child');
          await page.click('#category-next');
          const checks = [];
          async function check(stage) {
            const g = await page.evaluate(() => {
              const rect = id => { const r = document.getElementById(id).getBoundingClientRect(); return { top: r.top, bottom: r.bottom, height: r.height }; };
              const back = document.getElementById('trip-back'); const r = back.getBoundingClientRect();
              const footer = document.querySelector('.filing-fine-print').getBoundingClientRect();
              return { vh: innerHeight, footerHeight: footer.height, card: rect('step-trip'), back: rect('trip-back'), next: rect('trip-next'),
                error: rect('trip-error'), errorHidden: document.getElementById('trip-error').hidden,
                disabled: document.getElementById('trip-next').disabled,
                overflow: getComputedStyle(document.body).overflow,
                hit: document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2) === back };
            });
            report.lastProbe={file,mode,width,height,stage,...g};
            assert.ok(g.card.top >= 0 && g.card.bottom <= g.vh, 'card fits without page scrolling');
            assert.ok(g.back.top >= 0 && g.back.bottom <= g.vh && g.next.top >= 0 && g.next.bottom <= g.vh, 'both buttons visible');
            assert.ok(g.vh - g.next.bottom <= g.footerHeight + 55, 'buttons above bottom fine print');
            assert.equal(g.hit, true); assert.equal(g.disabled, true); assert.equal(g.overflow, 'hidden');
            if (!g.errorHidden) assert.ok(g.error.top >= 0 && g.error.bottom <= g.vh, 'current error on screen');
            checks.push({ stage, ...g });
          }
          await page.waitForSelector('#trip-options .loading');
          await check('loading');
          assert.ok(held, 'request intercepted');
          await held.respond({ status: mode === 'error' ? 500 : 200, contentType: 'application/json',
            body: JSON.stringify(mode === 'error' ? { error: 'Could not load trips. Please try again.' } : { trips: [] }) });
          await page.waitForFunction(() => !document.querySelector('#trip-options .loading'));
          await check(mode);
          for (const h of [320, 700, height]) {
            await page.setViewport({ width, height: h });
            await check(mode + '-resized-' + h);
          }
          await page.click('#trip-back');
          assert.equal(await page.$eval('body', e => getComputedStyle(e).overflow), 'hidden', 'category step keeps the shared viewport frame');
          assert.equal(await page.$eval('#step-trip', e => e.hidden), true);
          report.cases.push({ file, mode, width, height, checks });
          await page.close();
        }
      }
    }
    assert.deepEqual(report.errors, []); report.passed = true;
  } catch (e) { report.error = String(e.stack || e); process.exitCode = 1; }
  finally { await browser.close(); fs.writeFileSync(output, JSON.stringify(report, null, 2));
    console.log(JSON.stringify({ passed: report.passed, cases: report.cases.length, checks: report.cases.reduce((n, c) => n + c.checks.length, 0), error: report.error })); }
})().catch(e => { console.error(e); process.exitCode = 1; });
