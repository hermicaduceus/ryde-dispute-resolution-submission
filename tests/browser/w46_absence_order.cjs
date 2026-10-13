/* W46 real-browser gate: the rider no-show form's absence question sits after the intake questions
 * and above the amount box, measured on the rendered page at phone and desktop width.
 * PUPPETEER_MODULE=... BROWSER_EXECUTABLE=... node tests/browser/w46_absence_order.cjs BASE_URL OUTPUT_JSON
 */
const assert = require('node:assert/strict'), fs = require('node:fs');
const puppeteer = require(process.env.PUPPETEER_MODULE || 'puppeteer');
const [base, output] = process.argv.slice(2);
const report = { passed: false, cases: [], errors: [] };
(async () => {
  const browser = await puppeteer.launch({ headless: true, executablePath: process.env.BROWSER_EXECUTABLE, args: ['--no-sandbox'] });
  try {
    for (const width of [390, 1280]) {
      const page = await browser.newPage();
      page.on('pageerror', e => report.errors.push(String(e)));
      await page.setViewport({ width, height: 844 });
      await page.goto(base + '/party/index.html', { waitUntil: 'networkidle0' });
      await page.evaluate(() => document.querySelectorAll('#category-options button')[1].click());
      await page.click('#category-next');
      await page.waitForSelector('#trip-options .trip-card');
      await page.evaluate(() => document.querySelector('#trip-options .trip-card').click());
      await page.click('#trip-next');
      await page.waitForSelector('#claim-amount', { visible: true });
      const m = await page.evaluate(() => {
        const q = document.getElementById('question-list'), amount = document.getElementById('claim-amount');
        const yes = document.querySelectorAll('[data-question-key="rider_claims_driver_absent"][data-choice="Yes"]');
        const field = yes.length === 1 ? yes[0].closest('.field') : null;
        if (!field) return { copies: yes.length };
        const F = Node.DOCUMENT_POSITION_FOLLOWING;
        return {
          copies: yes.length,
          afterList: !!(q.compareDocumentPosition(field) & F),
          beforeAmount: !!(field.compareDocumentPosition(amount) & F),
          outsideList: !q.contains(field),
          listBottom: q.getBoundingClientRect().bottom,
          fieldTop: field.getBoundingClientRect().top,
          fieldHeight: field.getBoundingClientRect().height,
          amountTop: amount.getBoundingClientRect().top,
        };
      });
      assert.equal(m.copies, 1, 'exactly one absence field at ' + width);
      assert.ok(m.afterList, 'after the intake questions at ' + width);
      assert.ok(m.beforeAmount, 'before the amount box at ' + width);
      assert.ok(m.outsideList, 'outside the pinned question list at ' + width);
      assert.ok(m.fieldHeight > 0, 'the field is rendered at ' + width);
      assert.ok(m.listBottom <= m.fieldTop + 1, 'rendered below the last intake question at ' + width);
      assert.ok(m.fieldTop < m.amountTop, 'rendered above the amount box at ' + width);
      report.cases.push({ width, ...m });
      await page.close();
    }
    assert.deepEqual(report.errors, []);
    report.passed = true;
  } finally {
    await browser.close();
    fs.writeFileSync(output, JSON.stringify(report, null, 2));
  }
})().catch(e => { console.error(e && e.stack || e); process.exit(1); });
