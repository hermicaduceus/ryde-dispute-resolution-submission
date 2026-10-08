/* W35 lane P, real browser: the status page keeps its header and the "Look up a reference
 * number" box in place while only "My disputes" scrolls, on a screen at least 654px tall;
 * below that the page scrolls normally.
 *
 * Run (parent-owned):
 *   PUPPETEER_MODULE=... BROWSER_EXECUTABLE=... node tests/browser/w35_P_status.cjs BASE_URL OUTPUT_JSON
 * BASE_URL is a mock server on the tree under test. Off-loopback requests are aborted. The
 * account list and the two lookups are answered by this script with explicit fixtures, so
 * the list is long enough to scroll on every screen.
 */
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path');
const puppeteer = require(process.env.PUPPETEER_MODULE || 'puppeteer');
const [base, output] = process.argv.slice(2);
fs.mkdirSync(path.dirname(output), {recursive: true});

const THRESHOLD = 654;
const DISPUTES = Array.from({length: 8}, (_, i) => ({run_id: 'w35-run-' + i, dispute_id: 'PF-W35LIST' + i,
  status: 'decided', message: 'Fixture decision ' + i + ': no action. This sentence is long enough to wrap on a phone, as real messages do.', questions: []}));
const TALL = {run_id: 'w35-tall', dispute_id: 'PF-W35TALL', status: 'needs_info',
  message: 'We need a little more information about this trip.',
  questions: ['Fixture question one?', 'Fixture question two?', 'Fixture question three?', 'Fixture question four?',
    'Fixture question five?', 'Fixture question six?']};
const SHORT = {run_id: 'w35-short', dispute_id: 'PF-W35SHORT', status: 'under_review', message: 'Under review.', questions: []};
// Threshold-1/threshold/threshold+1 on the 320px phone whose bar wraps to two rows (the
// width that sets the threshold) and on a desktop, the required phone and desktop sizes,
// a 390x700 phone (framed), and short desktop/landscape panes (page scroll).
const SIZES = [[320, 653], [320, 654], [320, 655], [1280, 653], [1280, 654], [1280, 655],
  [360, 740], [320, 740], [390, 844], [600, 900], [1280, 844], [1200, 600], [740, 360], [390, 700]];
const report = {passed: false, views: [], errors: []};

(async () => {
  const browser = await puppeteer.launch({headless: true, executablePath: process.env.BROWSER_EXECUTABLE, args: ['--no-sandbox']});
  const open = async (width, height, hash = '') => {
    const page = await browser.newPage();
    page.on('pageerror', e => report.errors.push(`${width}x${height}: ${e.message}`));
    await page.setViewport({width, height});
    await page.setRequestInterception(true);
    page.on('request', r => {
      const u = new URL(r.url());
      if (u.hostname !== '127.0.0.1') return r.abort();
      const json = body => r.respond({status: 200, contentType: 'application/json', body: JSON.stringify(body)});
      if (u.pathname === '/api/demo/rider') return json({account: {kind: 'rider', label: 'Demo account'}, disputes: DISPUTES});
      if (u.pathname === '/api/disputes/PF-W35TALL') return json(TALL);
      if (u.pathname === '/api/disputes/PF-W35SHORT') return json(SHORT);
      return r.continue();
    });
    await page.goto(base + '/party/status.html' + hash, {waitUntil: 'networkidle0'});
    await page.waitForFunction(n => document.querySelectorAll('#account-list > .step').length === n, {}, DISPUTES.length);
    assert.equal(await page.evaluate(() => !!document.querySelector('.status-shell') && !!document.querySelector('.status-lookup') && !!document.querySelector('.status-list')),
      true, 'status page has its shell, fixed lookup box and internal-list region');
    return page;
  };
  const geometry = page => page.evaluate(() => {
    const rect = e => { const r = e.getBoundingClientRect(); return {top: r.top, bottom: r.bottom, left: r.left, right: r.right, height: r.height}; };
    const list = document.getElementById('account-list'), result = document.getElementById('lookup-result');
    const cards = list.querySelectorAll(':scope > .step');
    return {vh: innerHeight, scrollY, docHeight: document.documentElement.scrollHeight,
      overflow: document.documentElement.scrollWidth - innerWidth,
      bodyOverflow: getComputedStyle(document.body).overflow,
      bar: rect(document.querySelector('nav.switch-bar')), barShown: getComputedStyle(document.querySelector('nav.switch-bar')).display !== 'none',
      header: rect(document.querySelector('.party-header')), lookup: rect(document.querySelector('.status-lookup')),
      input: rect(document.getElementById('reference-input')), check: rect(document.getElementById('reference-check')),
      section: rect(document.querySelector('.status-list')), list: rect(list),
      listClient: list.clientHeight, listFull: list.scrollHeight, listTop: list.scrollTop,
      lastCard: rect(cards[cards.length - 1]),
      result: rect(result), resultClient: result.clientHeight, resultFull: result.scrollHeight};
  });
  try {
    for (const [width, height] of SIZES) {
      const framed = height >= THRESHOLD;
      const view = {width, height, framed, checks: []};
      report.views.push(view);
      const page = await open(width, height);
      await page.evaluate(() => document.fonts.ready);
      let g = await geometry(page);
      view.checks.push({stage: 'load', ...g});
      assert.ok(g.overflow <= 0, 'no horizontal overflow');
      assert.equal(g.barShown, true, 'the bar stays on the status page');
      if (framed) {
        assert.equal(g.bodyOverflow, 'hidden', 'the page itself does not scroll');
        for (const part of ['header', 'lookup', 'section']) {
          assert.ok(g[part].top >= g.bar.bottom - 1 && g[part].bottom <= g.vh + 1, part + ' on screen under the bar');
        }
        assert.ok(g.header.bottom <= g.lookup.top + 1 && g.lookup.bottom <= g.section.top + 1, 'header, lookup box, list in order');
        assert.ok(g.listClient >= 60, 'the list keeps a usable region');
        assert.ok(g.listFull > g.listClient + 1, 'fixture: the list overflows its region');
        // Scroll the list three ways; the lookup box and header never move.
        const before = {header: g.header, lookup: g.lookup};
        await page.evaluate(() => { const l = document.getElementById('account-list'); l.scrollTop = l.scrollHeight; });
        g = await geometry(page);
        view.checks.push({stage: 'list-end', ...g});
        assert.ok(g.listTop > 0, 'the LIST scrolled, not the page');
        assert.ok(g.lastCard.bottom <= g.list.bottom + 1, 'the last dispute is reachable');
        assert.deepEqual({header: g.header, lookup: g.lookup}, before, 'scrolling the list never moves the lookup box');
        assert.equal(g.scrollY, 0);
        await page.evaluate(() => { document.getElementById('account-list').scrollTop = 0; });
        await page.mouse.move(width / 2, (g.list.top + g.list.bottom) / 2);
        await page.mouse.wheel({deltaY: 300});
        await page.waitForFunction(() => document.getElementById('account-list').scrollTop > 0, {timeout: 5000});
        g = await geometry(page);
        view.checks.push({stage: 'wheel', ...g});
        assert.deepEqual({header: g.header, lookup: g.lookup}, before, 'a wheel over the list moves only the list');
        assert.equal(g.scrollY, 0);
        await page.evaluate(() => { document.getElementById('account-list').scrollTop = 0; });
        await page.focus('#reference-check');
        await page.keyboard.press('Tab');
        assert.equal(await page.evaluate(() => document.activeElement.id), 'account-list', 'Tab from Check status reaches the list region');
        await page.keyboard.press('End');
        await page.waitForFunction(() => document.getElementById('account-list').scrollTop > 0, {timeout: 5000});
        g = await geometry(page);
        view.checks.push({stage: 'keyboard', ...g});
        assert.deepEqual({header: g.header, lookup: g.lookup}, before, 'keyboard scrolling moves only the list');
        assert.equal(g.scrollY, 0);
        await page.evaluate(() => { document.getElementById('account-list').scrollTop = 0; document.activeElement.blur(); });
      } else {
        assert.notEqual(g.bodyOverflow, 'hidden', 'a short screen scrolls the page');
        assert.ok(g.listFull <= g.listClient + 1, 'the list is not its own scroller on a short screen');
        assert.ok(g.docHeight > g.vh, 'fixture: the page is taller than the screen');
        await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
        g = await geometry(page);
        view.checks.push({stage: 'page-end', ...g});
        assert.ok(g.scrollY > 0, 'the page scrolls');
        assert.ok(g.lastCard.bottom <= g.vh + 1, 'the last dispute is reachable');
        await page.evaluate(() => window.scrollTo(0, 0));
      }
      // A short lookup result shows whole; a tall one scrolls inside the lookup box.
      for (const [ref, tall] of [['PF-W35SHORT', false], ['PF-W35TALL', true]]) {
        await page.$eval('#reference-input', (e, v) => { e.value = v; }, ref);
        await page.click('#reference-check');
        await page.waitForFunction(r => document.querySelector('#lookup-result .reference') &&
          document.querySelector('#lookup-result .reference').textContent.includes(r), {}, ref);
        await page.evaluate(() => window.scrollTo(0, 0));
        g = await geometry(page);
        view.checks.push({stage: 'lookup-' + ref, ...g});
        const scrolls = g.resultFull > g.resultClient + 1;
        if (!framed) {
          assert.equal(scrolls, false, 'on a short screen the result shows whole in the page');
        } else {
          // The result takes the room above the list; it scrolls only once the list is at
          // its 8rem floor, and never pushes anything off the screen.
          if (scrolls) assert.ok(g.section.height <= 128 + 1, 'the list gives up its room before the result scrolls');
          assert.ok(g.result.bottom <= g.section.top + 1, 'the result ends above the list');
          assert.ok(g.section.bottom <= g.vh + 1 && g.section.height >= 128 - 1, 'the list keeps at least 8rem');
          assert.ok(g.input.top >= 0 && g.check.bottom <= g.result.top + 1, 'the lookup controls stay on screen above the result');
          assert.equal(g.scrollY, 0);
        }
        if (tall && framed) {
          assert.equal(scrolls, true, 'fixture: the tall result is taller than the room');
          assert.ok(g.input.top >= 0 && g.check.bottom <= g.vh + 1, 'the lookup controls stay on screen');
          assert.ok(g.section.bottom <= g.vh + 1 && g.listClient >= 60, 'the list keeps its region below');
          assert.equal(g.scrollY, 0);
          // The last answer box is reachable by keyboard inside the result.
          await page.evaluate(() => { const t = [...document.querySelectorAll('#lookup-result textarea')].pop(); t.focus(); });
          const inside = await page.evaluate(() => {
            const t = document.activeElement.getBoundingClientRect(), r = document.getElementById('lookup-result').getBoundingClientRect();
            return t.top >= r.top - 1 && t.bottom <= r.bottom + 1;
          });
          assert.equal(inside, true, 'focus brings the last answer box into the result window');
          assert.equal(await page.evaluate(() => scrollY), 0);
        }
      }
      if (width === 390 || width === 1280) {
        const shot = path.join(path.dirname(output), `status-${width}x${height}.png`);
        await page.screenshot({path: shot});
      }
      await page.close();
    }
    // Arriving from the driver page's "Look up your reference number" link.
    const page = await open(390, 844, '#reference-input');
    const arrived = await geometry(page);
    report.views.push({width: 390, height: 844, hash: true, checks: [arrived]});
    assert.equal(arrived.scrollY, 0, 'the anchor does not scroll the page');
    assert.ok(arrived.input.top >= 0 && arrived.input.bottom <= arrived.vh, 'the reference input is on screen');
    await page.close();
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
