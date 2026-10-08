/* W35 lane P, real browser: WCAG AA text contrast measured from COMPUTED colours on the five
 * party/start pages, in the states a party actually sees, at a phone and a desktop width.
 *
 * Run (parent-owned):
 *   PUPPETEER_MODULE=... BROWSER_EXECUTABLE=... node tests/browser/w35_P_contrast.cjs BASE_URL OUTPUT_JSON
 * Off-loopback requests are aborted. Lists, lookups and the dispute POST are answered with
 * explicit fixtures.
 *
 * Every element with its own visible text is measured: its colour against the background
 * actually painted behind it (ancestor backgrounds composited, opacity applied), and each
 * input placeholder. Small text needs 4.5:1, large text (24px, or 18.66px at weight 700+)
 * 3:1. Text inside a DISABLED control is reported but exempt (WCAG 1.4.3 "inactive user
 * interface component"). The full table goes to OUTPUT_JSON.
 */
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path');
const puppeteer = require(process.env.PUPPETEER_MODULE || 'puppeteer');
const [base, output] = process.argv.slice(2);
fs.mkdirSync(path.dirname(output), {recursive: true});

const DISPUTES = [
  {run_id: 'c1', dispute_id: 'PF-W35C1', status: 'decided', message: 'Fixture decision: no action.', questions: []},
  {run_id: 'c2', dispute_id: 'PF-W35C2', status: 'needs_info', message: 'We need a little more information.', questions: ['Fixture question?']},
];
const LOOKUP = {run_id: 'c3', dispute_id: 'PF-W35C3', status: 'under_review', message: 'Under review.', questions: []};
const REFUSAL = 'Fixture refusal: please try again.';
const report = {passed: false, states: [], failures: [], errors: []};

const MEASURE = () => {
  const parse = c => { const m = c.match(/rgba?\(([^)]+)\)/); if (!m) return [0, 0, 0, 0];
    const p = m[1].split(/[ ,/]+/).filter(Boolean).map(Number); return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1]; };
  const over = (top, bottom) => { const a = top[3]; return [0, 1, 2].map(i => top[i] * a + bottom[i] * (1 - a)).concat(1); };
  const lum = c => { const l = c.slice(0, 3).map(v => { v /= 255; return v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); });
    return 0.2126 * l[0] + 0.7152 * l[1] + 0.0722 * l[2]; };
  const ratio = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
  const hex = c => '#' + c.slice(0, 3).map(v => Math.round(v).toString(16).padStart(2, '0')).join('');
  // The colour painted behind el: walk to the root, then composite downwards.
  const backdrop = el => {
    const chain = [];
    for (let n = el; n; n = n.parentElement) chain.push(n);
    let bg = [255, 255, 255, 1];
    for (const n of chain.reverse()) {
      const s = getComputedStyle(n), c = parse(s.backgroundColor), o = Number(s.opacity);
      bg = over([c[0], c[1], c[2], c[3] * o], bg);
    }
    return bg;
  };
  const opacity = el => { let o = 1; for (let n = el; n; n = n.parentElement) o *= Number(getComputedStyle(n).opacity); return o; };
  const visible = el => { const r = el.getBoundingClientRect(), s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility === 'visible' && !el.closest('[hidden]') && !el.closest('[aria-hidden="true"]'); };
  const rows = [];
  const record = (el, fgRaw, what) => {
    const s = getComputedStyle(el), size = parseFloat(s.fontSize), weight = Number(s.fontWeight);
    const bg = backdrop(el.parentElement || el);
    const own = parse(s.backgroundColor);
    const behind = over([own[0], own[1], own[2], own[3] * Number(s.opacity)], bg);
    const fg = over([fgRaw[0], fgRaw[1], fgRaw[2], fgRaw[3] * opacity(el)], behind);
    const large = size >= 24 || (size >= 18.66 && weight >= 700);
    const disabled = !!el.closest('button:disabled, input:disabled, textarea:disabled');
    rows.push({what, text: (what === 'placeholder' ? el.placeholder : el.textContent).trim().replace(/\s+/g, ' ').slice(0, 60),
      tag: el.tagName.toLowerCase(), cls: el.className && typeof el.className === 'string' ? el.className : '', id: el.id,
      fg: hex(fg), bg: hex(behind), size, weight, large, disabled, ratio: Math.round(ratio(fg, behind) * 100) / 100,
      need: large ? 3 : 4.5});
  };
  for (const el of document.querySelectorAll('body *')) {
    if (!visible(el)) continue;
    const ownText = [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim());
    if (ownText) record(el, parse(getComputedStyle(el).color), 'text');
    if ((el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') && el.placeholder && !el.value) {
      record(el, parse(getComputedStyle(el, '::placeholder').color), 'placeholder');
    }
  }
  return rows;
};

(async () => {
  const browser = await puppeteer.launch({headless: true, executablePath: process.env.BROWSER_EXECUTABLE, args: ['--no-sandbox']});
  const open = async (url, width) => {
    const page = await browser.newPage();
    page.on('pageerror', e => report.errors.push(`${width} ${url}: ${e.message}`));
    await page.setViewport({width, height: 844});
    await page.setRequestInterception(true);
    page.on('request', r => {
      const u = new URL(r.url());
      if (u.hostname !== '127.0.0.1') return r.abort();
      const json = (body, status = 200) => r.respond({status, contentType: 'application/json', body: JSON.stringify(body)});
      if (u.pathname === '/api/demo/rider' || u.pathname === '/api/demo/driver') return json({account: {}, disputes: DISPUTES});
      if (u.pathname === '/api/disputes/PF-W35C3') return json(LOOKUP);
      if (u.pathname === '/api/disputes' && r.method() === 'POST') {
        return page.__refuse ? json({error: REFUSAL}, 500) : (page.__hold ? undefined : json(LOOKUP));
      }
      return r.continue();
    });
    await page.goto(base + url, {waitUntil: 'networkidle0'});
    await page.mouse.move(0, 0);
    return page;
  };
  const measure = async (page, name, width) => {
    await page.mouse.move(0, 0);
    await new Promise(r => setTimeout(r, 250));
    const rows = await page.evaluate(MEASURE);
    report.states.push({name, width, rows});
    for (const row of rows) if (!row.disabled && row.ratio < row.need) report.failures.push({name, width, ...row});
    return rows;
  };
  const find = (rows, pred, label) => { const r = rows.find(pred); assert.ok(r, 'measured: ' + label); return r; };
  // Named spots: recorded (not thrown), so one run lists every low pair at once.
  const spot = (state, width, row, label) => {
    report.spots = report.spots || [];
    report.spots.push({state, width, label, ratio: row.ratio, fg: row.fg, bg: row.bg});
    if (row.ratio < 4.5) report.failures.push({name: state, width, spot: label, ...row});
  };
  try {
    for (const width of [390, 1280]) {
      let p = await open('/start/', width);
      let rows = await measure(p, 'start', width);
      spot('start eyebrow', width, find(rows, r => r.cls === 'eyebrow', 'start eyebrow'), 'start eyebrow');
      spot('start card title', width, find(rows, r => r.cls === 'card-title', 'start card title'), 'start card title');
      await p.close();

      for (const file of ['index.html', 'driver-filing.html']) {
        p = await open('/party/' + file, width);
        rows = await measure(p, file + ' step 1', width);
        spot('eyebrow on tint', width, find(rows, r => r.cls === 'eyebrow', 'eyebrow on tint'), 'eyebrow on tint');
        spot('bar pill', width, find(rows, r => r.text === 'File a dispute' && r.tag === 'a', 'bar pill'), 'bar pill');
        spot('step number', width, find(rows, r => r.cls === 'step-number', 'step number'), 'step number');
        await p.click('#category-options .option-card');
        rows = await measure(p, file + ' step 1 chosen', width);
        spot('enabled Continue', width, find(rows, r => r.id === 'category-next' && !r.disabled, 'enabled Continue'), 'enabled Continue');
        await p.click('#category-next');
        await p.waitForSelector('#trip-options .trip-card');
        await p.evaluate(() => document.querySelector('#trip-options .trip-card').click());
        await measure(p, file + ' step 2 chosen', width);
        await p.click('#trip-next');
        rows = await measure(p, file + ' step 3', width);
        spot('summary label', width, find(rows, r => r.cls === 'filing-summary-label', 'summary label'), 'summary label');
        spot('Send', width, find(rows, r => r.id === 'details-submit', 'Send'), 'Send');
        await p.$eval('#description', e => { e.value = 'Contrast fixture'; });
        p.__hold = true;
        await p.click('#details-submit');
        await p.waitForFunction(() => document.getElementById('details-status').textContent !== '');
        rows = await measure(p, file + ' step 3 sending', width);
        spot('status line', width, find(rows, r => r.id === 'details-status', 'status line'), 'status line');
        await p.close();
        p = await open('/party/' + file, width);
        p.__refuse = true;
        await p.click('#category-options .option-card');
        await p.click('#category-next');
        await p.waitForSelector('#trip-options .trip-card');
        await p.evaluate(() => document.querySelector('#trip-options .trip-card').click());
        await p.click('#trip-next');
        await p.$eval('#description', e => { e.value = 'Contrast fixture'; });
        await p.click('#details-submit');
        await p.waitForSelector('#details-error:not([hidden])');
        rows = await measure(p, file + ' step 3 refused', width);
        spot('error', width, find(rows, r => r.id === 'details-error', 'error'), 'error');
        p.__refuse = false;
        await p.click('#details-submit');
        await p.waitForSelector('#outcome:not([hidden])');
        await measure(p, file + ' outcome', width);
        await p.close();
      }

      p = await open('/party/status.html', width);
      await p.click('#reference-check');
      await p.waitForSelector('#reference-error:not([hidden])');
      await measure(p, 'status empty lookup', width);
      await p.$eval('#reference-input', e => { e.value = 'PF-W35C3'; });
      await p.click('#reference-check');
      await p.waitForSelector('#lookup-result .step');
      await measure(p, 'status with result', width);
      await p.close();
      p = await open('/party/driver.html', width);
      await measure(p, 'driver account', width);
      await p.close();
    }
    report.passed = report.failures.length === 0 && report.errors.length === 0;
  } catch (e) {
    report.error = String(e && e.stack || e);
  } finally {
    await browser.close();
    // The distinct colour pairs, for the report.
    const pairs = {};
    for (const s of report.states) for (const r of s.rows) {
      const key = [r.fg, r.bg, r.large ? 'large' : 'small', r.disabled ? 'disabled' : 'enabled'].join(' ');
      pairs[key] = pairs[key] || {fg: r.fg, bg: r.bg, large: r.large, disabled: r.disabled, ratio: r.ratio, need: r.need, examples: []};
      if (pairs[key].examples.length < 3) pairs[key].examples.push(`${s.name}@${s.width}: ${r.text}`);
    }
    report.pairs = Object.values(pairs).sort((a, b) => a.ratio - b.ratio);
    if (report.error) report.passed = false;
    fs.writeFileSync(output, JSON.stringify(report, null, 2));
    console.log(JSON.stringify({passed: report.passed, states: report.states.length, pairs: report.pairs.length,
      failures: report.failures.length, error: report.error}));
    for (const f of report.failures.slice(0, 20)) console.log('LOW', f.ratio, f.fg, 'on', f.bg, f.name + '@' + f.width, JSON.stringify(f.text));
    process.exitCode = report.passed ? 0 : 1;
  }
})().catch(e => { console.error(e); process.exitCode = 1; });
