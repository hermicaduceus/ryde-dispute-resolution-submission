/* W34 pages in a real browser: the start page, the switch bar on the five pages, and the
 * one-screen filing frame with the bar above it.
 *
 * Run (parent-owned; the W30 scripts in this folder run alongside it):
 *   PUPPETEER_MODULE=... BROWSER_EXECUTABLE=... node tests/browser/w34_pages.cjs BASE_URL OUTPUT_JSON
 * BASE_URL is a mock server on this tree (python3 -m app.server --llm mock --port N).
 *
 * The filing-frame geometry is pinned against the pre-W34 layout: the bar may take height
 * above the frame, never width from it, and the frame must still end at the bottom of the
 * screen. On a very short screen the bar steps aside while the form is open.
 */
const fs = require('node:fs'), path = require('node:path');
const puppeteer = require(process.env.PUPPETEER_MODULE || 'puppeteer');
const [base, output] = process.argv.slice(2);
fs.mkdirSync(path.dirname(output), {recursive: true});
const report = {passed: false, checks: [], errors: []};
const ok = (name, pass, detail) => report.checks.push({name, pass: !!pass, detail});

const BAR_PAGES = [
  ['console', '/', 'Operator console'],
  ['party', '/party/', 'File a dispute'],
  ['driver-filing', '/party/driver-filing.html', 'File a dispute'],
  ['status', '/party/status.html', 'File a dispute'],
  ['driver', '/party/driver.html', 'File a dispute'],
];
// Pre-W34 filing-shell geometry, measured on e13cbe5: full width on a phone, a centred
// 720 px column on a desktop.
const FRAME_SIZES = [[320, 740], [390, 844], [460, 800], [1200, 600], [1280, 844], [360, 480], [800, 320]];
const expectedShell = width => width >= 760 ? {width: 720, left: (width - 720) / 2} : {width, left: 0};

(async () => {
  const browser = await puppeteer.launch({headless: true, executablePath: process.env.BROWSER_EXECUTABLE, args: ['--no-sandbox']});
  const open = async (url, width, height) => {
    const page = await browser.newPage();
    page.on('pageerror', e => report.errors.push(`${width}x${height} ${url}: ${e.message}`));
    page.on('response', r => { if (r.status() >= 400 && !r.url().endsWith('/favicon.ico')) report.errors.push(`${r.status()} ${r.url()}`); });
    await page.setViewport({width, height});
    await page.goto(base + url, {waitUntil: 'networkidle0'});
    return page;
  };
  try {
    for (const width of [390, 1280]) {
      // Start page: two cards, stacked on a phone, side by side on a desktop, above the fold.
      const page = await open('/start/', width, 844);
      const cards = await page.evaluate(() => [...document.querySelectorAll('a')].map(a => {
        const r = a.getBoundingClientRect(); return {href: a.getAttribute('href'), x: r.x, y: r.y, w: r.width, h: r.height};
      }));
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
      ok(`${width} start: two links`, cards.length === 2, cards.map(c => c.href));
      ok(`${width} start: no horizontal overflow`, overflow <= 0, overflow);
      if (cards.length === 2) {
        const [a, b] = cards;
        ok(`${width} start: ${width < 600 ? 'stacked' : 'side by side'}`,
           width < 600 ? b.y >= a.y + a.h - 1 : Math.abs(a.y - b.y) < 2 && b.x >= a.x + a.w - 1, {a, b});
        ok(`${width} start: both cards above the fold`, a.y + a.h <= 844 && b.y + b.h <= 844, [a.y + a.h, b.y + b.h]);
        ok(`${width} start: card tap targets at least 44 px`, a.h >= 44 && b.h >= 44, [a.h, b.h]);
      }
      for (const [href, want] of [['../party/', '/party/'], ['../', '/']]) {
        await page.goto(base + '/start/', {waitUntil: 'networkidle0'});
        await Promise.all([page.waitForNavigation({waitUntil: 'networkidle0'}), page.click(`a[href="${href}"]`)]);
        ok(`${width} start -> ${want}`, new URL(page.url()).pathname === want, page.url());
        await Promise.all([page.waitForNavigation({waitUntil: 'networkidle0'}), page.click('nav.switch-bar a:first-child')]);
        ok(`${width} bar Start from ${want}`, new URL(page.url()).pathname === '/start/', page.url());
      }
      await page.close();

      // The bar on every page: first in the body, three visible links, one current, not pinned.
      for (const [name, url, current] of BAR_PAGES) {
        const p = await open(url, width, 844);
        const bar = await p.evaluate(() => {
          const nav = document.querySelector('nav.switch-bar');
          if (!nav) return null;
          const links = [...nav.querySelectorAll('a')].map(a => {
            const r = a.getBoundingClientRect();
            return {text: a.textContent.trim(), current: a.getAttribute('aria-current'), h: r.height, shown: r.width > 0 && r.right <= innerWidth};
          });
          return {first: document.body.firstElementChild === nav, position: getComputedStyle(nav).position, links,
                  overflow: document.documentElement.scrollWidth - innerWidth};
        });
        ok(`${width} ${name}: bar present`, bar);
        if (!bar) { await p.close(); continue; }
        ok(`${width} ${name}: bar first in body`, bar.first);
        ok(`${width} ${name}: bar not pinned`, !['sticky', 'fixed'].includes(bar.position), bar.position);
        ok(`${width} ${name}: three visible links`, bar.links.length === 3 && bar.links.every(l => l.shown), bar.links);
        ok(`${width} ${name}: current link`, bar.links.filter(l => l.current).map(l => l.text).join() === current, bar.links);
        ok(`${width} ${name}: link tap height at least 36 px`, bar.links.every(l => l.h >= 36), bar.links.map(l => l.h));
        ok(`${width} ${name}: no horizontal overflow`, bar.overflow <= 0, bar.overflow);
        await p.close();
      }
    }

    // The filing frame with the bar above it, both filing pages, phone to desktop.
    for (const file of ['index.html', 'driver-filing.html']) for (const [width, height] of FRAME_SIZES) {
      const p = await open('/party/' + file, width, height);
      const g = await p.evaluate(() => {
        const shell = document.querySelector('.filing-shell').getBoundingClientRect();
        const nav = document.querySelector('nav.switch-bar');
        const bar = nav.getBoundingClientRect();
        const step = [...document.querySelectorAll('#form-steps > .step')].find(s => !s.hidden);
        const buttons = [...step.querySelectorAll('.step-actions button')].map(b => b.getBoundingClientRect().bottom);
        const fine = document.querySelector('.filing-fine-print');
        return {shell: {width: shell.width, left: shell.left, top: shell.top, bottom: shell.bottom},
                barShown: getComputedStyle(nav).display !== 'none' && bar.height > 0, barBottom: bar.bottom,
                buttons, fineBottom: fine ? fine.getBoundingClientRect().bottom : null, vh: innerHeight, scrollY};
      });
      const want = expectedShell(width), tag = `${width}x${height} ${file}`;
      ok(`${tag}: frame keeps its width`, Math.abs(g.shell.width - want.width) <= 1 && Math.abs(g.shell.left - want.left) <= 1,
         {got: g.shell, want});
      ok(`${tag}: frame ends at the bottom of the screen`, Math.abs(g.shell.bottom - g.vh) <= 1, {bottom: g.shell.bottom, vh: g.vh});
      ok(`${tag}: actions and fine print on screen`, g.buttons.every(b => b <= g.vh + 1) && g.fineBottom !== null && g.fineBottom <= g.vh + 1,
         {buttons: g.buttons, fine: g.fineBottom, vh: g.vh});
      ok(`${tag}: page does not scroll`, g.scrollY === 0, g.scrollY);
      if (height <= 520) ok(`${tag}: bar steps aside on a short screen`, !g.barShown, g.barShown);
      else ok(`${tag}: bar shown above the frame`, g.barShown && g.shell.top >= g.barBottom - 1, {bar: g.barBottom, shellTop: g.shell.top});
      await p.close();
    }

    // The receipt (form hidden) and every non-filing page keep the bar on a short screen.
    for (const url of ['/', '/party/status.html', '/party/driver.html', '/start/']) {
      const p = await open(url, 800, 320);
      const shown = await p.evaluate(() => { const n = document.querySelector('nav.switch-bar'); return !n || getComputedStyle(n).display !== 'none'; });
      ok(`800x320 ${url}: bar not hidden off the filing form`, shown);
      await p.close();
    }
  } catch (e) {
    report.errors.push(String(e && e.stack || e));
  } finally {
    await browser.close();
  }
  report.passed = report.checks.length > 0 && report.checks.every(c => c.pass) && report.errors.length === 0;
  fs.writeFileSync(output, JSON.stringify(report, null, 2));
  const failed = report.checks.filter(c => !c.pass);
  console.log(JSON.stringify({passed: report.passed, checks: report.checks.length, failed: failed.length, errors: report.errors.length}));
  for (const f of failed) console.log('FAIL', f.name, JSON.stringify(f.detail));
  for (const e of report.errors) console.log('ERROR', e);
  process.exit(report.passed ? 0 : 1);
})();
