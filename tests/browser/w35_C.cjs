/* W35 lane C: the operator console's real-browser contract (one run-folder picker, Recent runs,
 * readable prompt full text, contrast). Written RED-first against HEAD 57758ce.
 * Driven by tests/test_w35_C.py (RealBrowserConsole), which starts the real server on an
 * ephemeral port with three real mock runs (RD-0109 held and queued, NS-0202 ruled, RD-0109 held
 * with a human decision recorded) and passes:
 *   argv: <base url> <report json path>
 *   env:  PUPPETEER_MODULE, BROWSER_EXECUTABLE, W35C_EXPECT ({out, queued, ruled, decided, hint,
 *         label, noCase, severalRuns, caseFailed, runsUnavailable}), optional W35C_SHOTS (a folder
 *         for screenshots)
 * It never files or decides. Its only interference is holding or failing the /case requests it
 * names, each released explicitly, failing /api/review/runs once at the end, and picking run
 * folders from the server's own output folder.
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const puppeteer = require(process.env.PUPPETEER_MODULE || 'puppeteer');
const [base, output] = process.argv.slice(2);
const X = JSON.parse(process.env.W35C_EXPECT);
const SHOTS = process.env.W35C_SHOTS || '';
const report = {passed: false, cases: [], errors: []};
const VIEWPORTS = [[360, 740], [390, 844], [600, 900], [740, 360], [1200, 600], [1280, 844]];
const sleep = ms => new Promise(r => setTimeout(r, ms));
const frames = page => page.evaluate(() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r))));

function filesUnder(dir) {
  let n = 0;
  for (const entry of fs.readdirSync(dir, {withFileTypes: true})) {
    n += entry.isDirectory() ? filesUnder(path.join(dir, entry.name)) : 1;
  }
  return n;
}

// Every visible text element on the page (the demo switch bar excluded: lane P owns it), with the
// contrast of its computed colour on the first opaque background behind it.
function census() {
  const parse = c => { const m = c.match(/rgba?\(([^)]+)\)/); if (!m) return null; const p = m[1].split(',').map(Number); return {r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1}; };
  const lum = c => { const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }; return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b); };
  const bgOf = el => { const layers = []; for (let n = el; n && n.nodeType === 1; n = n.parentElement) { const c = parse(getComputedStyle(n).backgroundColor); if (c && c.a > 0) { layers.push(c); if (c.a >= 1) break; } } let out = {r: 255, g: 255, b: 255}; for (let i = layers.length - 1; i >= 0; i--) { const c = layers[i]; out = {r: c.r * c.a + out.r * (1 - c.a), g: c.g * c.a + out.g * (1 - c.a), b: c.b * c.a + out.b * (1 - c.a)}; } return out; };
  const hex = c => '#' + [c.r, c.g, c.b].map(v => Math.round(v).toString(16).padStart(2, '0')).join('');
  const low = [];
  let checked = 0;
  document.querySelectorAll('body *').forEach(el => {
    if (el.closest('.switch-bar')) return;
    const own = Array.from(el.childNodes).filter(n => n.nodeType === 3 && n.textContent.trim()).map(n => n.textContent.trim()).join(' ');
    if (!own) return;
    const s = getComputedStyle(el); const r = el.getBoundingClientRect();
    if (s.visibility === 'hidden' || s.display === 'none' || r.width === 0 || r.height === 0) return;
    if (el.closest('details:not([open])') && !el.closest('summary')) return;
    const fg = parse(s.color); const bg = bgOf(el);
    const fgm = {r: fg.r * fg.a + bg.r * (1 - fg.a), g: fg.g * fg.a + bg.g * (1 - fg.a), b: fg.b * fg.a + bg.b * (1 - fg.a)};
    const l1 = lum(fgm), l2 = lum(bg); const ratio = (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
    const size = parseFloat(s.fontSize), weight = parseInt(s.fontWeight, 10);
    const need = size >= 24 || (size >= 18.66 && weight >= 700) ? 3 : 4.5;
    checked += 1;
    if (ratio < need) low.push({el: (el.id ? '#' + el.id : el.tagName.toLowerCase() + '.' + String(el.className).split(/\s+/).join('.')), text: own.slice(0, 40), fg: hex(fgm), bg: hex(bg), ratio: Math.round(ratio * 100) / 100});
  });
  return {checked, low};
}

async function newPage(browser, width, height) {
  const page = await browser.newPage();
  page.on('pageerror', e => report.errors.push(String(e)));
  await page.setViewport({width, height});
  return page;
}

async function loaded(page, id) {
  await page.waitForFunction(id => document.getElementById('loaded-file').textContent === id
    && document.getElementById('case-workspace').hidden === false, {timeout: 10000}, id);
}

async function markers(page) {
  return page.evaluate(() => Array.from(document.querySelectorAll('#queue-content [aria-current], #runs-content [aria-current]'))
    .map(b => ({row: b.closest('li') ? b.closest('li').dataset.runId : null, list: b.className, value: b.getAttribute('aria-current'), text: b.textContent})));
}

async function runButton(page, id) {
  return page.$eval('.run-row[data-run-id="' + id + '"] .run-open', b => ({text: b.textContent, disabled: b.disabled}));
}

async function shot(page, name, selector) {
  if (!SHOTS) return;
  fs.mkdirSync(SHOTS, {recursive: true});
  if (selector) await page.$eval(selector, el => el.scrollIntoView({block: 'start', behavior: 'instant'}));
  await frames(page);
  await sleep(150);
  await page.screenshot({path: path.join(SHOTS, name)});
}

(async () => {
  const browser = await puppeteer.launch({headless: true, executablePath: process.env.BROWSER_EXECUTABLE, args: ['--no-sandbox']});
  try {
    // 1. Every viewport: panel order, the picker's words, the runs rows reflow without overflow.
    const modes = [];
    for (const [width, height] of VIEWPORTS) {
      const page = await newPage(browser, width, height);
      await page.goto(base + '/', {waitUntil: 'networkidle0'});
      await page.waitForFunction(() => document.querySelectorAll('#runs-content .run-row').length === 3, {timeout: 10000});
      const state = await page.evaluate(() => {
        const ids = ['queue-panel', 'overrides-panel', 'runs-panel'];
        const loader = document.querySelector('.loader-panel');
        const tops = ids.map(id => document.getElementById(id).getBoundingClientRect().top).concat([loader.getBoundingClientRect().top]);
        const inputs = Array.from(document.querySelectorAll('input[type="file"]')).map(i => ({id: i.id, dir: i.webkitdirectory, multiple: i.multiple, accept: i.getAttribute('accept')}));
        const label = document.querySelector('label[for="run-folder-picker"]');
        const rows = Array.from(document.querySelectorAll('#runs-content .run-row')).map(row => {
          const r = row.getBoundingClientRect();
          const items = Array.from(row.children).filter(c => getComputedStyle(c).display !== 'none').map(c => c.getBoundingClientRect());
          const sorted = items.slice().sort((a, b) => a.top - b.top);
          const lines = [];
          sorted.forEach(it => { const last = lines[lines.length - 1]; if (last && it.top < last.bottom - 1) { last.n += 1; last.bottom = Math.max(last.bottom, it.bottom); } else lines.push({n: 1, bottom: it.bottom}); });
          const button = row.querySelector('.run-open').getBoundingClientRect();
          return {lines: lines.map(l => l.n), inside: items.every(it => it.left >= r.left - 1 && it.right <= r.right + 1),
            buttonInside: button.left >= r.left - 1 && button.right <= r.right + 1, buttonHeight: button.height};
        });
        return {tops, inputs, label: label ? label.textContent : null, hint: document.getElementById('run-folder-hint').textContent,
          overflow: document.documentElement.scrollWidth - window.innerWidth, rows,
          status: document.getElementById('runs-status').textContent};
      });
      assert.ok(state.tops[0] < state.tops[1] && state.tops[1] < state.tops[2] && state.tops[2] < state.tops[3],
        'queue, overrides, Recent runs, loader in that order at ' + width);
      assert.deepEqual(state.inputs, [{id: 'run-folder-picker', dir: true, multiple: true, accept: null}]);
      assert.equal(state.label, X.label);
      assert.equal(state.hint, X.hint);
      assert.equal(state.status, '3 runs, newest first.');
      assert.ok(state.overflow <= 1, 'page overflows by ' + state.overflow + 'px at ' + width);
      state.rows.forEach((row, i) => {
        assert.ok(row.inside, 'run row ' + i + ' spills out of its row at ' + width);
        assert.ok(row.buttonInside, 'run row ' + i + ' Open button is cropped at ' + width);
        assert.ok(row.buttonHeight >= 44, 'run row ' + i + ' Open button is ' + row.buttonHeight + 'px tall at ' + width);
      });
      const c = await page.evaluate(census);
      assert.deepEqual(c.low, [], 'text under AA at ' + width + ': ' + JSON.stringify(c.low));
      modes.push({width, lines: state.rows[0].lines});
      if (width === 390 || width === 1280) await shot(page, width + 'x' + height + '-runs-and-loader.png', '#runs-panel');
      await page.close();
    }
    // Progressive wrapping, not a snap: one line when wide, stacked when narrow, and at least one
    // width in between where a line holds two or more fields and the row still wraps.
    const at = w => modes.find(m => m.width === w).lines;
    assert.equal(at(1280).length, 1, 'a run row is one line at 1280: ' + JSON.stringify(at(1280)));
    assert.ok(at(360).length >= 3, 'a run row stacks at 360: ' + JSON.stringify(at(360)));
    assert.ok(modes.some(m => m.lines.length > 1 && m.lines.some(n => n >= 2)), 'no intermediate wrap: ' + JSON.stringify(modes));
    report.cases.push({modes});

    // 2. The lifecycle of an open from Recent runs, plus the prompt panel and payloads from the server.
    {
      const page = await newPage(browser, 1280, 844);
      await page.setRequestInterception(true);
      const hold = new Set(); const held = []; const failOnce = new Set(); const seen = []; let runsFail = false;
      page.on('request', r => {
        const u = new URL(r.url()); seen.push(u.pathname);
        if (runsFail && u.pathname === '/api/review/runs') { r.respond({status: 500, contentType: 'application/json', body: '{"error":"x"}'}); return; }
        const m = u.pathname.match(/^\/api\/review\/([^/]+)\/case$/);
        if (m && failOnce.has(m[1])) { failOnce.delete(m[1]); r.respond({status: 500, contentType: 'application/json', body: '{"error":"x"}'}); return; }
        if (m && hold.has(m[1])) { held.push(r); return; }
        r.continue();
      });
      await page.goto(base + '/', {waitUntil: 'domcontentloaded'});
      await page.waitForSelector('.run-row[data-run-id="' + X.ruled + '"] .run-open');
      // pending: distinct label and disabled, on the clicked button only
      hold.add(X.ruled);
      await page.click('.run-row[data-run-id="' + X.ruled + '"] .run-open');
      while (!held.length) await sleep(10);
      assert.deepEqual(await runButton(page, X.ruled), {text: 'Opening…', disabled: true});
      assert.deepEqual(await runButton(page, X.decided), {text: 'Open case', disabled: false});
      hold.delete(X.ruled); held.shift().continue();
      await loaded(page, X.ruled);
      // the scroll is smooth unless reduced motion is asked for: wait for it to land
      await page.waitForFunction(() => { const t = document.getElementById('case-summary').getBoundingClientRect().top;
        return t >= -2 && t < 40; }, {timeout: 5000}).catch(() => {});
      const arrival = await page.evaluate(() => ({focus: document.activeElement && document.activeElement.id,
        top: document.getElementById('case-summary').getBoundingClientRect().top, vh: window.innerHeight}));
      assert.equal(arrival.focus, 'case-summary', 'focus moves to the opened case');
      assert.ok(arrival.top >= -2 && arrival.top < arrival.vh, 'the opened case is in view: ' + JSON.stringify(arrival));
      assert.deepEqual(await markers(page), [{row: X.ruled, list: 'run-open', value: 'true', text: 'Currently open'}]);
      // the prompt panel works from the server; the full text reads on the dark code panel
      await page.waitForFunction(() => document.querySelectorAll('#prompts-content article').length === 3, {timeout: 10000});
      await page.evaluate(() => document.querySelectorAll('#prompts-content details').forEach(d => { d.open = true; }));
      await frames(page);
      const pres = await page.evaluate(() => Array.from(document.querySelectorAll('#prompts-content details > pre')).map(p => {
        const s = getComputedStyle(p);
        return {bg: s.backgroundColor, color: s.color, border: s.borderTopColor + ' ' + s.borderTopStyle + ' ' + s.borderTopWidth, padding: s.paddingTop};
      }));
      assert.equal(pres.length, 3);
      pres.forEach(p => assert.deepEqual(p, {bg: 'rgb(24, 35, 52)', color: 'rgb(231, 238, 247)', border: 'rgb(47, 69, 95) solid 1px', padding: '12px'}));
      // event payloads look exactly as before: the dark panel is the container, the pre is bare
      await page.evaluate(() => { const d = document.querySelector('#events-content details.event-row'); d.open = true; });
      await page.waitForSelector('#events-content .event-payload pre.payload-json', {timeout: 10000});
      const payload = await page.evaluate(() => {
        const panel = document.querySelector('#events-content .event-payload'); const pre = panel.querySelector('pre');
        const a = getComputedStyle(panel), b = getComputedStyle(pre);
        return {panel: [a.backgroundColor, a.borderTopColor, a.color, a.paddingTop], pre: [b.backgroundColor, b.borderTopStyle, b.paddingTop, b.marginTop, b.color]};
      });
      assert.deepEqual(payload, {panel: ['rgb(24, 35, 52)', 'rgb(47, 69, 95)', 'rgb(231, 238, 247)', '12px'],
        pre: ['rgba(0, 0, 0, 0)', 'none', '0px', '0px', 'rgb(231, 238, 247)']});
      assert.ok(seen.some(p => p.startsWith('/api/review/' + X.ruled + '/payloads/')), 'the payload came from the server');
      const c = await page.evaluate(census);
      assert.deepEqual(c.low, [], 'text under AA with a run open: ' + JSON.stringify(c.low));
      await shot(page, '1280x844-prompt-full-text.png', '#prompts-content details');
      // row-local failure, retry
      failOnce.add(X.decided);
      await page.click('.run-row[data-run-id="' + X.decided + '"] .run-open');
      await page.waitForFunction(id => document.querySelector('.run-row[data-run-id="' + id + '"] .run-open-status').textContent.length > 0, {timeout: 10000}, X.decided);
      const failed = await page.evaluate(id => { const row = document.querySelector('.run-row[data-run-id="' + id + '"]'); const st = row.querySelector('.run-open-status');
        return {status: st.textContent, role: st.getAttribute('role'), visible: st.getBoundingClientRect().height > 0, button: row.querySelector('.run-open').textContent,
          disabled: row.querySelector('.run-open').disabled, others: Array.from(document.querySelectorAll('.run-open-status')).filter(s => s !== st).map(s => s.textContent)}; }, X.decided);
      assert.deepEqual(failed, {status: X.caseFailed, role: 'status', visible: true, button: 'Open case', disabled: false, others: ['', '']});
      const cf = await page.evaluate(census);
      assert.deepEqual(cf.low, [], 'text under AA with a row-local failure: ' + JSON.stringify(cf.low));
      assert.deepEqual(await markers(page), [{row: X.ruled, list: 'run-open', value: 'true', text: 'Currently open'}]);
      await page.click('.run-row[data-run-id="' + X.decided + '"] .run-open');
      await loaded(page, X.decided);
      assert.deepEqual(await markers(page), [{row: X.decided, list: 'run-open', value: 'true', text: 'Currently open'}]);
      // a run shown in both lists is marked only where it was opened
      await page.click('.queue-row[data-run-id="' + X.queued + '"] .queue-open');
      await loaded(page, X.queued);
      assert.deepEqual(await markers(page), [{row: X.queued, list: 'queue-open', value: 'true', text: 'Currently open'}]);
      await page.click('.run-row[data-run-id="' + X.queued + '"] .run-open');
      await page.waitForFunction(id => { const b = document.querySelector('.run-row[data-run-id="' + id + '"] .run-open'); return b.getAttribute('aria-current') === 'true'; }, {timeout: 10000}, X.queued);
      assert.deepEqual(await markers(page), [{row: X.queued, list: 'run-open', value: 'true', text: 'Currently open'}]);
      assert.equal(await page.$eval('#decision-approve', e => e.disabled), false, 'the queue entry gives the runs open its proposal');
      // a slow earlier open never replaces a later one
      hold.add(X.ruled);
      await page.click('.run-row[data-run-id="' + X.ruled + '"] .run-open');
      while (!held.length) await sleep(10);
      await page.click('.run-row[data-run-id="' + X.decided + '"] .run-open');
      await loaded(page, X.decided);
      hold.delete(X.ruled); held.shift().continue();
      await sleep(400);
      assert.equal(await page.$eval('#loaded-file', e => e.textContent), X.decided);
      assert.deepEqual(await markers(page), [{row: X.decided, list: 'run-open', value: 'true', text: 'Currently open'}]);
      assert.deepEqual(await runButton(page, X.ruled), {text: 'Open case', disabled: false});
      // Refresh invalidates a pending open
      hold.add(X.ruled);
      await page.click('.run-row[data-run-id="' + X.ruled + '"] .run-open');
      while (!held.length) await sleep(10);
      await page.click('#queue-refresh');
      await page.waitForFunction(id => { const b = document.querySelector('.run-row[data-run-id="' + id + '"] .run-open'); return b && b.textContent === 'Open case' && !b.disabled; }, {timeout: 10000}, X.ruled);
      hold.delete(X.ruled); held.shift().continue();
      await sleep(400);
      assert.equal(await page.$eval('#loaded-file', e => e.textContent), X.decided, 'the invalidated open rendered');
      // Recent runs unavailable: the status line says so, and reads at AA
      runsFail = true;
      await page.click('#queue-refresh');
      await page.waitForFunction(t => document.getElementById('runs-status').textContent === t, {timeout: 10000}, X.runsUnavailable);
      assert.equal(await page.$$eval('#runs-content .run-row', rows => rows.length), 0);
      const cu = await page.evaluate(census);
      assert.deepEqual(cu.low, [], 'text under AA with Recent runs unavailable: ' + JSON.stringify(cu.low));
      report.cases.push({lifecycle: true});
      await page.close();
    }

    // 3. The one picker: a run folder loads and attaches; wrong folders say so.
    for (const [width, height] of [[1280, 844], [390, 844]]) {
      const page = await newPage(browser, width, height);
      const seen = [];
      page.on('request', r => seen.push(new URL(r.url()).pathname));
      await page.goto(base + '/', {waitUntil: 'networkidle0'});
      const input = await page.$('#run-folder-picker');
      const runDir = path.join(X.out, X.ruled);
      await input.uploadFile(runDir);
      await page.waitForFunction(() => document.getElementById('load-status').dataset.state === 'success', {timeout: 10000});
      const st = await page.evaluate(() => ({load: document.getElementById('load-status').textContent, file: document.getElementById('loaded-file').textContent,
        payload: document.getElementById('payload-status').textContent, hidden: document.getElementById('case-workspace').hidden}));
      assert.deepEqual(st, {load: 'Loaded ' + X.ruled + '/case_file.json.', file: X.ruled + '/case_file.json',
        payload: 'Attached ' + filesUnder(runDir) + ' run file(s); event payloads can be opened.', hidden: false});
      await page.evaluate(() => { const d = document.querySelector('#events-content details.event-row'); d.open = true; });
      await page.waitForSelector('#events-content .event-payload pre.payload-json', {timeout: 10000});
      const ref = await page.$eval('#events-content .event-payload .payload-path', e => e.textContent);
      const shown = await page.$eval('#events-content .event-payload pre.payload-json', e => e.textContent);
      assert.equal(shown, JSON.stringify(JSON.parse(fs.readFileSync(path.join(runDir, ref), 'utf8')), null, 2));
      assert.ok(!seen.some(p => p.includes('/payloads/') || p.endsWith('/case')), 'a local folder asked the server: ' + seen.join(' '));
      if (width === 1280) {
        await page.waitForFunction(() => document.querySelectorAll('#prompts-content article').length === 3, {timeout: 10000});
        await page.evaluate(() => document.querySelectorAll('details').forEach(d => { d.open = true; }));
        await sleep(300);
        const c = await page.evaluate(census);
        assert.deepEqual(c.low, [], 'text under AA with a local folder open: ' + JSON.stringify(c.low));
      }
      await shot(page, width + 'x' + height + '-folder-loaded.png', '.loader-panel');
      if (width === 390) {
        await page.evaluate(() => document.querySelectorAll('#prompts-content details').forEach(d => { d.open = true; }));
        await shot(page, '390x844-prompt-full-text.png', '#prompts-content details');
      }
      await input.uploadFile(path.join(runDir, 'payloads'));
      await page.waitForFunction(t => document.getElementById('load-status').textContent === t, {timeout: 10000}, X.noCase);
      assert.equal(await page.$eval('#case-workspace', e => e.hidden), true);
      assert.equal(await page.$eval('#load-status', e => e.dataset.state), 'error');
      await input.uploadFile(X.out);
      await page.waitForFunction(t => document.getElementById('load-status').textContent === t, {timeout: 10000}, X.severalRuns);
      assert.equal(await page.$eval('#payload-status', e => e.textContent), 'Payload files are not attached.');
      const c = await page.evaluate(census);
      assert.deepEqual(c.low, [], 'text under AA after a wrong folder: ' + JSON.stringify(c.low));
      await shot(page, width + 'x' + height + '-wrong-folder.png', '.loader-panel');
      report.cases.push({picker: width});
      await page.close();
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
