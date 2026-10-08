/* W35 lane P, real browser: the step 3 summary and the pending "Send my dispute" state, on
 * both filing pages, phone to desktop, inside the one-screen frame.
 *
 * Run (parent-owned, like the W30/W34 scripts):
 *   PUPPETEER_MODULE=... BROWSER_EXECUTABLE=... node tests/browser/w35_P_filing.cjs BASE_URL OUTPUT_JSON
 * BASE_URL is a mock server on the tree under test (python3 -m app.server --port N).
 *
 * Every request off the loopback origin is aborted (no web fonts, deterministic fallback
 * font). POST /api/disputes is HELD by this script and answered when the script decides,
 * so the pending state is a scheduled state, not a race; the app adds no delay. The held
 * answers are explicit fixtures, not live rulings.
 */
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path');
const puppeteer = require(process.env.PUPPETEER_MODULE || 'puppeteer');
const [base, output] = process.argv.slice(2);
fs.mkdirSync(path.dirname(output), {recursive: true});

const SUMMARY_LABEL = 'You are disputing';
const SUBMIT = 'Send my dispute', SENDING = 'Sending\u2026';
const STATUS = 'Sending your dispute. This can take a little while, so please keep this page open.';
const REFUSAL = 'Fixture refusal: please try again.';
const VIEW = {run_id: 'w35-fixture', dispute_id: 'PF-W35FIXTURE', status: 'under_review',
  message: 'Your case is still under review.', questions: []};
// 519/520/521 straddle the bar's own short-screen line (max-height: 520px), where the
// summary steps aside with it: hidden at 519 and 520, shown at 521.
const SIZES = [[360, 740], [390, 844], [600, 900], [1280, 844], [1200, 600], [740, 360],
  [320, 740], [360, 521], [360, 520], [360, 519], [800, 320]];
const report = {passed: false, views: [], errors: []};

(async () => {
  const browser = await puppeteer.launch({headless: true, executablePath: process.env.BROWSER_EXECUTABLE, args: ['--no-sandbox']});
  try {
    for (const file of ['index.html', 'driver-filing.html']) for (const [width, height] of SIZES) {
      for (const motion of (width === 390 ? ['normal', 'reduce'] : ['normal'])) {
        const view = {file, width, height, motion, checks: []};
        report.views.push(view);
        const page = await browser.newPage();
        page.on('pageerror', e => report.errors.push(`${file} ${width}x${height}: ${e.message}`));
        await page.setViewport({width, height});
        if (motion === 'reduce') await page.emulateMediaFeatures([{name: 'prefers-reduced-motion', value: 'reduce'}]);
        const held = [];
        let posts = 0;
        await page.setRequestInterception(true);
        page.on('request', r => {
          const u = new URL(r.url());
          if (u.hostname !== '127.0.0.1') return r.abort();
          if (u.pathname === '/api/disputes' && r.method() === 'POST') { posts += 1; held.push(r); return; }
          return r.continue();
        });
        await page.goto(base + '/party/' + file, {waitUntil: 'networkidle0'});
        const vector = () => page.evaluate(() => ['step-category', 'step-trip', 'step-details', 'outcome']
          .map(id => !document.getElementById(id).hidden));
        const expectVector = async (want, after) => {
          const got = await vector();
          view.checks.push({after, vector: got});
          assert.deepEqual(got, want, 'visible steps after ' + after);
        };
        const pickCategory = async i => {
          await page.evaluate(i => document.querySelectorAll('#category-options .option-card')[i].click(), i);
          return page.evaluate(i => document.querySelectorAll('#category-options .option-card')[i].innerText.trim(), i);
        };
        const pickTrip = async i => {
          await page.evaluate(i => document.querySelectorAll('#trip-options .trip-card')[i].click(), i);
          return page.evaluate(i => [...document.querySelectorAll('#trip-options .trip-card')[i].children]
            .map(c => ({tag: c.tagName, cls: c.className, text: c.textContent.trim()})), i);
        };
        const cont = async id => { await page.evaluate(id => document.getElementById(id).click(), id); };

        // One-screen frame, summary content and geometry on step 3.
        async function checkDetails(stage, category, trip) {
          assert.equal(await page.$eval('#step-details', e => !!e.querySelector('.filing-summary') && !!e.querySelector('#summary-category') && !!e.querySelector('#summary-trip')),
            true, 'step 3 has the read-only summary markup');
          const g = await page.evaluate(() => {
            const rect = e => { const r = e.getBoundingClientRect(); return {top: r.top, bottom: r.bottom, left: r.left, right: r.right, height: r.height}; };
            const step = document.getElementById('step-details');
            const summary = step.querySelector('.filing-summary');
            const hit = e => { const r = e.getBoundingClientRect(), h = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2); return !!h && (h === e || e.contains(h)); };
            const focusable = summary.querySelectorAll('a[href],button,input,textarea,select,[tabindex],[contenteditable]');
            return {vh: innerHeight, scrollY, overflow: document.documentElement.scrollWidth - innerWidth,
              first: step.firstElementChild === summary,
              display: getComputedStyle(summary).display, summary: rect(summary),
              summaryFull: summary.scrollHeight, summaryClient: summary.clientHeight,
              label: (summary.querySelector('.filing-summary-label') || {}).textContent,
              category: document.getElementById('summary-category').textContent.trim(),
              trip: [...document.getElementById('summary-trip').children].map(c => ({tag: c.tagName, cls: c.className, text: c.textContent.trim()})),
              tabIndex: summary.tabIndex, focusable: focusable.length, role: summary.getAttribute('role'),
              h2: rect(step.querySelector('h2')), region: rect(step.querySelector('.filing-fields')),
              status: rect(document.getElementById('details-status')), bar: rect(step.querySelector('.step-actions')),
              buttons: [...step.querySelectorAll('.step-actions button')].map(b => ({id: b.id, ...rect(b), hit: hit(b)}))};
          });
          view.checks.push({stage, ...g});
          assert.equal(g.first, true, 'the summary opens step 3');
          assert.equal(g.label, SUMMARY_LABEL);
          assert.equal(g.category, category, 'category reads as its step 1 card');
          assert.deepEqual(g.trip, trip, 'trip reads as its step 2 card');
          assert.equal(g.tabIndex, -1, 'summary is not focusable');
          assert.equal(g.focusable, 0, 'nothing inside the summary is a control');
          assert.equal(g.role, null);
          assert.equal(g.scrollY, 0, 'the page itself never scrolls');
          assert.ok(g.overflow <= 0, 'no horizontal overflow');
          for (const b of g.buttons) {
            assert.ok(b.top >= 0 && b.bottom <= g.vh + 1, `${b.id} on screen at ${stage}`);
            assert.equal(b.hit, true, `${b.id} centre is clickable at ${stage}`);
          }
          assert.ok(g.h2.bottom <= g.region.top + 1, 'heading above the fields');
          assert.ok(g.region.bottom <= g.bar.top + 1, 'fields above the actions');
          assert.ok(g.region.height > 20, 'a usable strip of fields');
          if (g.vh <= 520) {
            assert.equal(g.display, 'none', 'on a very short screen the summary steps aside with the bar');
          } else {
            assert.notEqual(g.display, 'none', 'summary shown');
            assert.ok(g.summary.bottom <= g.h2.top + 1, 'summary above "Tell us more"');
            assert.ok(g.summary.top >= 0, 'summary on screen');
            // From 360px wide and 600px tall the summary shows whole; narrower or shorter it
            // gives up height to the fields (it scrolls inside itself) before Send moves.
            if (g.vh >= 600 && width >= 360) assert.ok(g.summaryFull <= g.summaryClient + 1, 'summary at its natural height on an ordinary screen');
          }
          // Tab through the whole step: focus never lands inside the summary. Where a short
          // pane clips it, the browser makes the clipped box itself a keyboard scroller
          // (Chromium's focusable scrollers), which is the only stop allowed there.
          await page.evaluate(() => document.activeElement && document.activeElement.blur());
          const landed = [];
          for (let i = 0; i < 25; i += 1) {
            await page.keyboard.press('Tab');
            landed.push(await page.evaluate(() => {
              const a = document.activeElement, s = a.closest('.filing-summary');
              return s ? (a === s ? 'box' : 'inside') : null;
            }));
          }
          view.checks.push({stage: stage + '-tab', landed: landed.filter(Boolean)});
          assert.ok(!landed.includes('inside'), 'keyboard focus never lands on anything inside the summary');
          if (g.summaryFull <= g.summaryClient + 1) assert.ok(!landed.includes('box'), 'an unclipped summary is not a tab stop');
          await page.evaluate(() => document.activeElement && document.activeElement.blur());
          return g;
        }

        await expectVector([true, false, false, false], 'load');
        const cat0 = await pickCategory(0);
        await expectVector([true, false, false, false], 'category card');
        await cont('category-next');
        await page.waitForSelector('#trip-options .trip-card');
        await expectVector([false, true, false, false], 'Continue');
        const trip0 = await pickTrip(0);
        await expectVector([false, true, false, false], 'trip card');
        await cont('trip-next');
        await expectVector([false, false, true, false], 'Continue to step 3');
        await checkDetails('first', cat0, trip0);

        await cont('details-back');
        await page.waitForSelector('#trip-options .trip-card');
        await expectVector([false, true, false, false], 'Back');
        const trip1 = await pickTrip(1);
        assert.notDeepEqual(trip1, trip0, 'fixture: two different trips');
        await expectVector([false, true, false, false], 'other trip card');
        await cont('trip-next');
        await expectVector([false, false, true, false], 'Continue after a trip change');
        await checkDetails('trip-changed', cat0, trip1);

        await cont('details-back');
        await page.waitForSelector('#trip-options .trip-card');
        await cont('trip-back');
        await expectVector([true, false, false, false], 'Back to step 1');
        const cat1 = await pickCategory(1);
        assert.notEqual(cat1, cat0);
        await cont('category-next');
        await page.waitForSelector('#trip-options .trip-card');
        const trip2 = await pickTrip(0);
        await cont('trip-next');
        await expectVector([false, false, true, false], 'Continue after a category change');
        await checkDetails('category-changed', cat1, trip2);

        // The pending state, held open by this script.
        await page.$eval('#description', e => { e.value = 'W35 pending-state fixture'; });
        const state = () => page.evaluate(() => {
          const rect = e => { const r = e.getBoundingClientRect(); return {top: r.top, bottom: r.bottom, left: r.left, right: r.right, width: r.width, height: r.height}; };
          const submit = document.getElementById('details-submit'), back = document.getElementById('details-back');
          const spinner = document.getElementById('details-spinner'), status = document.getElementById('details-status');
          const error = document.getElementById('details-error');
          return {regionBottom: document.querySelector('#step-details .filing-fields').getBoundingClientRect().bottom,
            submit: {text: submit.textContent, disabled: submit.disabled, ...rect(submit)},
            back: {disabled: back.disabled, ...rect(back)},
            spinner: {display: getComputedStyle(spinner).display, animation: getComputedStyle(spinner).animationName,
              ariaHidden: spinner.getAttribute('aria-hidden'), ...rect(spinner)},
            status: {text: status.textContent, role: status.getAttribute('role'), live: status.getAttribute('aria-live'), ...rect(status)},
            actionsTop: document.querySelector('#step-details .step-actions').getBoundingClientRect().top,
            error: error.hidden ? null : error.textContent, vh: innerHeight, scrollY,
            outcome: !document.getElementById('outcome').hidden};
        });
        const waitText = async text => page.waitForFunction(t => document.getElementById('details-submit').textContent === t, {timeout: 10000}, text);

        await page.click('#details-submit');
        await waitText(SENDING);
        let s = await state();
        view.checks.push({stage: 'sending', ...s});
        assert.equal(s.submit.disabled, true, 'Send is disabled while sending');
        assert.equal(s.back.disabled, true, 'Back is disabled while sending');
        assert.equal(s.status.text, STATUS);
        assert.equal(s.status.role, 'status');
        assert.equal(s.status.live, 'polite');
        assert.ok(s.status.height > 0 && s.status.top >= 0 && s.status.bottom <= s.actionsTop + 1, 'status line shown above the actions');
        assert.ok(s.status.top >= s.regionBottom + 4, 'a clear gap between the fields and the status line');
        assert.notEqual(s.spinner.display, 'none', 'spinner shown');
        assert.equal(s.spinner.ariaHidden, 'true');
        assert.ok(s.spinner.width > 0 && s.spinner.width <= 24, 'a small spinner');
        assert.ok(s.spinner.right <= s.submit.left + 1 && s.submit.left - s.spinner.right <= 16, 'spinner directly beside Send');
        assert.ok(s.spinner.top >= s.submit.top - 1 && s.spinner.bottom <= s.submit.bottom + 1, 'spinner on the button row');
        assert.equal(s.spinner.animation, motion === 'reduce' ? 'none' : 'sending-spin', 'spinner motion follows the user setting');
        for (const b of [s.submit, s.back]) assert.ok(b.top >= 0 && b.bottom <= s.vh + 1, 'actions stay on screen while sending');
        assert.equal(s.scrollY, 0);
        await page.evaluate(() => document.getElementById('details-submit').click());
        await page.focus('#claim-amount');
        await page.keyboard.press('Enter');
        await new Promise(r => setTimeout(r, 150));
        assert.equal(posts, 1, 'a pending send cannot be queued twice');
        assert.equal(held.length, 1);

        held.shift().respond({status: 500, contentType: 'application/json', body: JSON.stringify({error: REFUSAL})});
        await waitText(SUBMIT);
        s = await state();
        view.checks.push({stage: 'refused', ...s});
        assert.equal(s.submit.disabled, false);
        assert.equal(s.back.disabled, false);
        assert.equal(s.spinner.display, 'none');
        assert.equal(s.status.text, '');
        assert.equal(s.error, REFUSAL, 'the existing error is shown');
        await expectVector([false, false, true, false], 'a refused send');

        await page.click('#details-submit');
        await waitText(SENDING);
        assert.equal(posts, 2);
        held.shift().respond({status: 200, contentType: 'application/json', body: JSON.stringify(VIEW)});
        await page.waitForSelector('#outcome:not([hidden])');
        assert.equal(await page.$eval('#outcome-title', e => e.textContent), 'Your case is still under review');
        assert.equal(await page.$eval('#form-steps', e => e.hidden), true);
        await expectVector([false, false, true, true], 'success');
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
    console.log(JSON.stringify({passed: report.passed, views: report.views.length,
      checks: report.views.reduce((n, v) => n + v.checks.length, 0), error: report.error}));
  }
})().catch(e => { console.error(e); process.exitCode = 1; });
