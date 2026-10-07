/* W24 fix round (lane B): the console deep link builds the same decision form as a queue click.
 * Written RED-first by the planner's RED-test preparer against BASE 1ae5a84. Driven by
 * tests/test_w24_fix_round.py (RealBrowserDeepLinkApprove), which starts the real server on an
 * ephemeral port with one filed RD-0109-style run (claim SGD 55.16, withheld, queued with a proposal
 * and can_approve true) and passes:
 *   argv: <base url> <report json path>
 *   env:  PUPPETEER_MODULE, BROWSER_EXECUTABLE, W24FIX_EXPECT ({run, note})
 * It never decides or writes: it only opens pages and reads the DOM.
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const puppeteer = require(process.env.PUPPETEER_MODULE || 'puppeteer');
const [base, output] = process.argv.slice(2);
const X = JSON.parse(process.env.W24FIX_EXPECT);
const report = {passed: false, cases: [], errors: []};
const frames = page => page.evaluate(() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r))));

async function settled(page, run) {
  // The case is open, its decision form exists, and the queue row for the run is the current one.
  await page.waitForFunction(id => {
    const row = document.querySelector('.queue-row[data-run-id="' + id + '"] .queue-open');
    return document.getElementById('decision-approve') !== null
      && document.getElementById('loaded-file').textContent === id
      && row !== null && row.getAttribute('aria-current') === 'true';
  }, {timeout: 10000}, run);
  await new Promise(r => setTimeout(r, 400));
  await frames(page);
  return page.evaluate(id => ({
    approveDisabled: document.getElementById('decision-approve').disabled,
    notes: Array.from(document.querySelectorAll('#decision-content .decision-note')).map(n => n.textContent),
    decisionHidden: document.getElementById('decision-section').hidden,
    decisionHtml: document.getElementById('decision-content').innerHTML,
    current: Array.from(document.querySelectorAll('.queue-open[aria-current="true"]')).map(b => b.textContent),
    rowText: document.querySelector('.queue-row[data-run-id="' + id + '"] .queue-open').textContent,
    overflow: document.documentElement.scrollWidth - window.innerWidth,
  }), run);
}

(async () => {
  const browser = await puppeteer.launch({headless: true, executablePath: process.env.BROWSER_EXECUTABLE,
    args: ['--no-sandbox']});
  try {
    for (const [width, height] of [[1280, 900], [390, 844]]) {
      // The deep link.
      const deepPage = await browser.newPage();
      deepPage.on('pageerror', e => report.errors.push(String(e)));
      await deepPage.setViewport({width, height});
      await deepPage.goto(base + '/?run=' + encodeURIComponent(X.run), {waitUntil: 'domcontentloaded'});
      const deep = await settled(deepPage, X.run);
      await deepPage.close();
      // The same run opened by a queue click.
      const clickPage = await browser.newPage();
      clickPage.on('pageerror', e => report.errors.push(String(e)));
      await clickPage.setViewport({width, height});
      await clickPage.goto(base + '/', {waitUntil: 'domcontentloaded'});
      const button = '.queue-row[data-run-id="' + X.run + '"] .queue-open';
      await clickPage.waitForSelector(button);
      await clickPage.$eval(button, b => b.scrollIntoView({block: 'center'}));
      await clickPage.click(button);
      const click = await settled(clickPage, X.run);
      await clickPage.close();
      report.cases.push({width, deep: {approveDisabled: deep.approveDisabled, notes: deep.notes},
        click: {approveDisabled: click.approveDisabled, notes: click.notes}});

      assert.equal(click.approveDisabled, false, 'fixture: a queue click enables Approve at ' + width);
      assert.equal(deep.decisionHidden, false, 'the deep link shows the decision form at ' + width);
      assert.equal(deep.approveDisabled, false, 'the deep link leaves Approve disabled at ' + width);
      assert.deepEqual(deep.notes, [], 'the deep link shows "' + X.note + '" at ' + width);
      assert.equal(deep.decisionHtml, click.decisionHtml, 'deep-link and queue-click decision forms differ at ' + width);
      assert.deepEqual(deep.current, ['Currently open'], 'exactly one current row at ' + width);
      assert.equal(deep.rowText, click.rowText);
      assert.ok(deep.overflow <= 1, 'the page overflows by ' + deep.overflow + 'px at ' + width);
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
