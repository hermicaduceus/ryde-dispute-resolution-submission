/* Real-browser W30 contract: the trip step is a viewport-fit card with its own scroll region.
 * Requires Puppeteer and a live mock server (python3 -m app.server style; no app writes).
 *   PUPPETEER_MODULE=/path/to/puppeteer BROWSER_EXECUTABLE=/path/to/browser \
 *     node tests/browser/w30_trip_scroll.cjs BASE_URL OUTPUT_JSON
 * Battery hooks: W30_CSS_OVERRIDE / W30_JS_OVERRIDE serve a mutated party.css / party.js.
 *
 * Tall views (height >= 600) must fit the whole card on screen with a breathing gap, buttons
 * included. Short views (height < 600) may fall back to page scroll but keep the card's top in
 * view, keep a floor of two trip cards in the list, and reach the buttons by page scroll.
 * Every view: one visible step at each stage, no horizontal overflow, a list that scrolls
 * internally, an action bar that follows the cards, no clipped hover/selected card, a fade
 * that shows only while more trips are below (read from real pixels), and a keyboard order
 * of last card -> Back -> Continue.
 */
const assert = require('node:assert/strict');
const fs = require('fs');
const path = require('path');
const puppeteer = require(process.env.PUPPETEER_MODULE || 'puppeteer');
const base = process.argv[2] || 'http://127.0.0.1:55817';
const output = process.argv[3];
if (!output) throw new Error('OUTPUT_JSON is required');
fs.mkdirSync(path.dirname(output), { recursive: true });
const viewports = [[360, 740], [390, 844], [600, 900], [1200, 600], [1200, 700], [1200, 900],
  [1200, 500], [360, 480], [800, 320]];
const report = { views: [], errors: [], passed: false };
const GAP = 16;

(async () => {
  const browser = await puppeteer.launch({ headless: true,
    ...(process.env.BROWSER_EXECUTABLE ? { executablePath: process.env.BROWSER_EXECUTABLE } : {}),
    args: ['--no-sandbox'] });
  try {
    for (const file of ['index.html', 'driver-filing.html']) {
      for (const [width, height] of viewports) {
        const tall = height >= 600;
        const page = await browser.newPage();
        const view = { file, width, height, tall, stages: [] };
        report.views.push(view);
        page.on('pageerror', e => report.errors.push(String(e)));
        await page.setViewport({ width, height });
        if (process.env.W30_CSS_OVERRIDE || process.env.W30_JS_OVERRIDE) {
          await page.setRequestInterception(true);
          page.on('request', r => {
            if (process.env.W30_CSS_OVERRIDE && r.url().endsWith('/party/party.css')) {
              return r.respond({ status: 200, contentType: 'text/css', body: fs.readFileSync(process.env.W30_CSS_OVERRIDE, 'utf8') });
            }
            if (process.env.W30_JS_OVERRIDE && r.url().endsWith('/party/party.js')) {
              return r.respond({ status: 200, contentType: 'application/javascript', body: fs.readFileSync(process.env.W30_JS_OVERRIDE, 'utf8') });
            }
            return r.continue();
          });
        }
        await page.goto(base + '/party/' + file, { waitUntil: 'networkidle0' });
        await page.evaluate(() => document.fonts.ready);
        const visible = () => page.evaluate(() =>
          [...document.querySelectorAll('#form-steps > .step')].filter(e => !e.hidden).map(e => e.id));
        const settle = () => new Promise(r => setTimeout(r, 250));

        // Step 1 -> 2 on the second category (the route/no-show lists differ in height).
        await page.click('#category-options .option-card:nth-child(1)');
        await page.click('#category-next');
        await page.waitForSelector('#trip-options .trip-card');
        await settle();
        assert.deepEqual(await visible(), ['step-trip'], 'only the trip step is visible');

        const geo = () => page.evaluate(() => {
          const rect = e => { const r = e.getBoundingClientRect(); return { top: r.top, bottom: r.bottom, left: r.left, right: r.right, height: r.height }; };
          const card = document.getElementById('step-trip');
          const list = document.getElementById('trip-options');
          const bar = card.querySelector('.step-actions');
          const cards = [...list.querySelectorAll('.trip-card')];
          const hit = el => { const r = el.getBoundingClientRect(); const h = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2); return !!h && (h === el || el.contains(h)); };
          const cs = getComputedStyle(list);
          return { vh: innerHeight, vw: innerWidth, scrollY: scrollY, card: rect(card), list: rect(list), bar: rect(bar),
            back: rect(document.getElementById('trip-back')), next: rect(document.getElementById('trip-next')),
            backHit: hit(document.getElementById('trip-back')), nextHit: document.getElementById('trip-next').disabled ? null : hit(document.getElementById('trip-next')),
            scrollable: list.scrollHeight > list.clientHeight + 1, listClient: list.clientHeight,
            hScroll: list.scrollWidth > list.clientWidth + 1, pageOverflow: document.documentElement.scrollWidth - innerWidth,
            tallestCard: Math.max(...cards.map(c => c.getBoundingClientRect().height)), count: cards.length,
            visibleCardsHit: cards.filter(c => { const r = c.getBoundingClientRect(), l = list.getBoundingClientRect(); return r.top >= l.top && r.bottom <= l.bottom && r.top >= 0 && r.bottom <= innerHeight; }).every(c => hit(c)),
            overscroll: cs.overscrollBehaviorY, overflowY: cs.overflowY, bgImage: cs.backgroundImage, bgAttach: cs.backgroundAttachment };
        });
        const g = await geo();
        view.stages.push({ stage: 'trip-entered', ...g });
        assert.ok(g.pageOverflow <= 0, 'no horizontal page overflow');
        assert.ok(g.card.top >= 0, 'the card heading is on screen');
        assert.equal(g.scrollable, true, 'the list scrolls inside its own region');
        assert.equal(g.hScroll, false, 'no horizontal scroll inside the region');
        assert.equal(g.overflowY, 'auto');
        assert.equal(g.overscroll, 'contain');
        assert.ok(g.list.bottom <= g.bar.top + 0.5, 'the bar follows the list');
        assert.equal(g.visibleCardsHit, true, 'every fully visible trip is the element at its own centre');
        assert.ok(g.card.bottom >= g.bar.bottom - 0.5, 'the bar stays inside the card');
        assert.ok(g.listClient >= 2 * g.tallestCard - 1, 'the list keeps a floor of two trip cards');
        if (tall) {
          assert.ok(g.card.top >= GAP - 1, 'breathing room above the card: ' + g.card.top);
          assert.ok(g.card.bottom <= g.vh - GAP + 1, 'breathing room below the card: ' + g.card.bottom + ' of ' + g.vh);
          assert.ok(g.next.bottom <= g.vh && g.back.bottom <= g.vh, 'Continue/Back are on screen on entry');
          assert.equal(g.backHit, true, 'Back is the element at its own centre');
        } else {
          // Floor mode: page scroll reaches the buttons.
          await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
          await settle();
          const low = await geo();
          assert.ok(low.next.bottom <= low.vh && low.back.bottom <= low.vh, 'page scroll reaches Continue/Back');
          assert.equal(low.backHit, true);
          await page.evaluate(() => document.getElementById('step-trip').scrollIntoView({ block: 'start' }));
          await settle();
        }

        // Scroll the region itself; the page must not move, the last card must end inside it.
        const before = await page.evaluate(() => scrollY);
        await page.evaluate(() => { const l = document.getElementById('trip-options'); l.scrollTop = l.scrollHeight; });
        await settle();
        const end = await page.evaluate(() => {
          const l = document.getElementById('trip-options'); const last = l.lastElementChild.getBoundingClientRect(); const lr = l.getBoundingClientRect();
          return { lastInside: last.bottom <= lr.bottom + 0.5, scrollY: scrollY };
        });
        assert.equal(end.lastInside, true, 'the last trip can be scrolled fully into the region');
        assert.equal(end.scrollY, before, 'scrolling the list does not scroll the page');
        view.stages.push({ stage: 'list-scrolled-to-end', ...end });

        // Fade: real pixels in the region's left gutter (no card paints there), just above its
        // bottom edge. At the top of the list the fade tints it; at the end it is the card white.
        async function gutterPixel() {
          // A screenshot clip is in DOCUMENT coordinates, so add the page scroll offset.
          const place = () => page.evaluate(() => { const r = document.getElementById('trip-options').getBoundingClientRect(); return { x: r.left + 4 + scrollX, y: r.bottom - 4 + scrollY, vy: r.bottom - 4 }; });
          let spot = await place();
          if (spot.vy < 0 || spot.vy >= (await page.evaluate(() => innerHeight))) {
            // Floor mode: the list's bottom edge is below the fold; page scroll brings it up.
            await page.evaluate(() => document.querySelector('#step-trip .step-actions').scrollIntoView({ block: 'end' }));
            await settle();
            spot = await place();
          }
          assert.ok(spot.vy >= 0 && spot.vy < (await page.evaluate(() => innerHeight)), 'list bottom edge is reachable');
          const b64 = await page.screenshot({ clip: { x: Math.max(0, Math.floor(spot.x)), y: Math.floor(spot.y), width: 1, height: 1 }, encoding: 'base64' });
          return page.evaluate(async b64 => { const img = new Image(); img.src = 'data:image/png;base64,' + b64; await img.decode();
            const c = document.createElement('canvas'); c.width = 1; c.height = 1; const x = c.getContext('2d'); x.drawImage(img, 0, 0); return [...x.getImageData(0, 0, 1, 1).data].slice(0, 3); }, b64);
        }
        const atEnd = await gutterPixel();
        await page.evaluate(() => { document.getElementById('trip-options').scrollTop = 0; });
        await settle();
        const atTop = await gutterPixel();
        view.stages.push({ stage: 'fade-pixels', atTop, atEnd });
        {
          assert.ok(atEnd.every(c => c >= 253), 'no fade once the list is scrolled to its end: ' + atEnd);
          assert.ok(atTop.some(c => c < 245), 'a fade shows at the bottom edge while more trips are below: ' + atTop);
        }

        // Hover lift and selected border stay inside the region.
        await page.hover('#trip-options .trip-card:nth-child(1)');
        await settle();
        const lift = await page.evaluate(() => {
          const l = document.getElementById('trip-options').getBoundingClientRect(); const c = document.querySelector('#trip-options .trip-card').getBoundingClientRect();
          return { topGap: c.top - l.top, leftGap: c.left - l.left, rightGap: l.right - c.right };
        });
        assert.ok(lift.topGap >= 4 && lift.leftGap >= 4 && lift.rightGap >= 4, 'a lifted card is not clipped by the region: ' + JSON.stringify(lift));
        await page.click('#trip-options .trip-card:nth-child(1)');
        assert.equal(await page.$$eval('#trip-options .selected', e => e.length), 1, 'exactly one selected trip');
        assert.equal(await page.$eval('#trip-next', e => e.disabled), false);

        // Keyboard: last card -> Back -> Continue; focusing a hidden card scrolls the region to it.
        await page.evaluate(() => document.querySelector('#trip-options .trip-card:last-child').focus());
        const focused = await page.evaluate(() => { const l = document.getElementById('trip-options').getBoundingClientRect(); const c = document.activeElement.getBoundingClientRect();
          return { inside: c.top >= l.top - 0.5 && c.bottom <= l.bottom + 0.5 }; });
        assert.equal(focused.inside, true, 'a keyboard-focused trip is scrolled into the region');
        await page.keyboard.press('Tab');
        assert.equal(await page.evaluate(() => document.activeElement.id), 'trip-back', 'Tab from the last trip reaches Back');
        await page.keyboard.press('Tab');
        assert.equal(await page.evaluate(() => document.activeElement.id), 'trip-next', 'then Continue');

        // Forward, Back, forward again: one visible step each time, the trip card lands again.
        await page.evaluate(() => document.getElementById('trip-next').scrollIntoView({ block: 'center' }));
        await page.click('#trip-next');
        await page.waitForSelector('#step-details:not([hidden])');
        assert.deepEqual(await visible(), ['step-details']);
        await page.click('#details-back');
        await page.waitForSelector('#trip-options .trip-card');
        await settle();
        assert.deepEqual(await visible(), ['step-trip']);
        const again = await geo();
        view.stages.push({ stage: 'trip-after-details-back', ...again });
        assert.ok(again.card.top >= 0, 'the card lands again after Back from details');
        if (tall) {
          assert.ok(again.card.bottom <= again.vh - GAP + 1 && again.next.bottom <= again.vh, 'buttons on screen again');
        }

        // Back to the category step: it is on screen with its Continue.
        await page.evaluate(() => document.getElementById('trip-back').scrollIntoView({ block: 'center' }));
        await page.click('#trip-back');
        await settle();
        assert.deepEqual(await visible(), ['step-category']);
        const cat = await page.evaluate(() => { const c = document.getElementById('step-category').getBoundingClientRect(); const n = document.getElementById('category-next').getBoundingClientRect(); return { top: c.top, nextBottom: n.bottom, vh: innerHeight }; });
        view.stages.push({ stage: 'category-after-back', ...cat });
        assert.ok(cat.top >= 0, 'the category card is not cut off at the top after Back');
        if (tall) assert.ok(cat.nextBottom <= cat.vh, 'category Continue is on screen after Back');

        if (width === 390 && file === 'driver-filing.html') {
          await page.click('#category-options .option-card:nth-child(1)');
          await page.click('#category-next');
          await page.waitForSelector('#trip-options .trip-card');
          await settle();
          await page.screenshot({ path: path.join(path.dirname(output), 'w30-driver-390.png') });
        }
        await page.close();
      }
    }
    assert.deepEqual(report.errors, []);
    report.passed = true;
  } catch (e) { report.error = String(e); process.exitCode = 1; }
  finally {
    await browser.close();
    fs.mkdirSync(path.dirname(output), { recursive: true });
    fs.writeFileSync(output, JSON.stringify(report, null, 2) + '\n');
    console.log(JSON.stringify({ passed: report.passed, views: report.views.length,
      stages: report.views.reduce((n, v) => n + v.stages.length, 0), error: report.error, output }));
  }
})().catch(e => { console.error(e); process.exitCode = 1; });
