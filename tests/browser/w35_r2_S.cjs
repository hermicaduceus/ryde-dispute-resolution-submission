/* W35 round 2, lane S, real browser: on the party status page no lookup control may ever be
 * covered by "My disputes" or be unreachable, live AND in the exported replay (whose banner
 * sits above the switch bar). Run (parent-owned):
 *
 *   PUPPETEER_MODULE=... BROWSER_EXECUTABLE=... \
 *     node tests/browser/w35_r2_S.cjs live|replay BASE_URL OUTPUT_JSON
 *
 * live   BASE_URL is a mock server on the tree under test.
 * replay BASE_URL is the exported mock replay served statically (tools/export_replay.py).
 * Optional env W35S_THRESHOLD (default 654): the min-height at which the fixed frame starts.
 * Off-loopback requests are aborted. The account list and the lookups are answered by this
 * script with explicit fixtures (live: the API; replay: the recorded data files the shim
 * reads), so the list is always long enough to scroll and one lookup is always tall.
 *
 * Per viewport and per lookup state (initial, empty reference, unknown reference, a long
 * error, a found result, a tall result, the empty error above a result) it checks:
 *  (a) the lookup's own controls (title, input, Check status, the error line, the result box)
 *      sit inside the lookup section and above the list section, no overlap;
 *  (b) the page is never "overflow hidden with a control off-screen": every control can be
 *      brought on screen the way a person can (scrolling an auto/scroll ancestor, the page
 *      only when the body is not overflow hidden) and its centre hit-tests to itself with the
 *      pointer parked away from it (a hover raises the filtered button above its neighbours,
 *      so a hovered check proves nothing);
 *  (c) whenever the page is framed (body overflow hidden) the list scrolls inside its own
 *      region and that never moves the lookup;
 *  (d) no fade: no mask or gradient on the shell, the lookup box or the list.
 * The soft checks collect every violation, so one run shows the whole picture.
 */
const fs = require('node:fs'), path = require('node:path');
const puppeteer = require(process.env.PUPPETEER_MODULE || 'puppeteer');
const [target, base, output] = process.argv.slice(2);
if (!['live', 'replay'].includes(target) || !base || !output) {
  console.error('usage: w35_r2_S.cjs live|replay BASE_URL OUTPUT_JSON'); process.exit(2);
}
fs.mkdirSync(path.dirname(output), {recursive: true});
const THRESHOLD = Number(process.env.W35S_THRESHOLD || 654);
const FIT_HEIGHT = Number(process.env.W35S_FIT || 660);
const REPLAY = target === 'replay';
const PAGE_URL = base + '/party/status.html' + (REPLAY ? '?snapshot=after' : '');

const DISPUTES = Array.from({length: 8}, (_, i) => ({run_id: 'w35-run-' + i, dispute_id: 'PF-W35LIST' + i,
  status: 'decided', message: 'Fixture decision ' + i + ': no action. This sentence is long enough to wrap on a phone, as real messages do.', questions: []}));
const TALL = {run_id: 'w35-tall', dispute_id: 'PF-W35TALL', status: 'needs_info',
  message: 'We need a little more information about this trip.',
  questions: ['Fixture question one?', 'Fixture question two?', 'Fixture question three?', 'Fixture question four?',
    'Fixture question five?', 'Fixture question six?']};
const SHORT = {run_id: 'w35-short', dispute_id: 'PF-W35SHORT', status: 'under_review', message: 'Under review.', questions: []};
const LONG_ERROR = 'We could not find that reference number. Check the number on your confirmation, ' +
  'then try again, or open the list below and pick the dispute from there. Nothing was changed.';
const WIDTHS = [320, 360, 390, 1280];
const HEIGHTS = [600, THRESHOLD - 1, THRESHOLD, THRESHOLD + 1, 700, 740, 844];
const EXTRA = [[740, 360], [1200, 600], [600, 900]];
const SIZES = [];
for (const w of WIDTHS) for (const h of HEIGHTS) SIZES.push([w, h]);
for (const e of EXTRA) SIZES.push(e);
// W35S_SIZES="320x654,390x700" replaces the matrix (used to re-measure the threshold).
if (process.env.W35S_SIZES) { SIZES.length = 0; for (const p of process.env.W35S_SIZES.split(',')) SIZES.push(p.split('x').map(Number)); }

const report = {passed: false, target, threshold: THRESHOLD, views: [], violations: [], errors: []};
const sleep = ms => new Promise(r => setTimeout(r, ms));

// Runs in the page. Returns geometry plus the violations of (a), (b), (d) for the current state.
function auditInPage(label) {
  const out = {label, violations: []};
  const bad = msg => out.violations.push(label + ': ' + msg);
  const $ = s => document.querySelector(s);
  const rect = e => { const r = e.getBoundingClientRect(); return {top: +r.top.toFixed(2), bottom: +r.bottom.toFixed(2), left: +r.left.toFixed(2), right: +r.right.toFixed(2), height: +r.height.toFixed(2)}; };
  const shown = e => e && !e.hidden && getComputedStyle(e).display !== 'none' && e.getBoundingClientRect().height > 0;
  const lookup = $('.status-lookup'), list = $('.status-list'), header = $('.party-header'), shell = $('.status-shell');
  const result = $('#lookup-result'), error = $('#reference-error');
  const framed = getComputedStyle(document.body).overflow === 'hidden';
  const banner = $('#replay-banner');
  const lr = rect(lookup), sr = rect(list), hr = rect(header);
  // (a) containment and order
  const parts = [['title', lookup.querySelector('h2')], ['input', $('#reference-input')], ['check', $('#reference-check')]];
  if (shown(error)) parts.push(['error', error]);
  const resultInside = lookup.contains(result);
  if (shown(result.firstElementChild)) {
    if (resultInside) parts.push(['result', result]);
    else {
      const rr = rect(result);
      if (rr.top < lr.bottom - 0.5) bad(`result top ${rr.top} overlaps the lookup section (bottom ${lr.bottom})`);
      if (rr.bottom > sr.top + 0.5) bad(`result bottom ${rr.bottom} overlaps the list section (top ${sr.top})`);
    }
  }
  for (const [name, el] of parts) {
    const r = rect(el);
    if (r.bottom > sr.top + 0.5) bad(`${name} bottom ${r.bottom} overlaps the list section (top ${sr.top})`);
    if (r.bottom > lr.bottom + 0.5) bad(`${name} bottom ${r.bottom} runs out of the lookup section (bottom ${lr.bottom})`);
    if (r.top < lr.top - 0.5) bad(`${name} top ${r.top} runs above the lookup section (top ${lr.top})`);
  }
  if (framed) {
    // The box is exactly as tall as its controls need: it never grows into free room.
    const rem = parseFloat(getComputedStyle(document.documentElement).fontSize);
    const slack = lr.bottom - rect($('#reference-check')).bottom;
    if (slack > 2 * rem) bad(`the lookup box is ${slack.toFixed(1)}px taller than its controls need (most allowed: ${2 * rem})`);
  }
  if (lr.bottom > sr.top + 0.5) bad(`lookup section bottom ${lr.bottom} overlaps the list section (top ${sr.top})`);
  if (hr.bottom > lr.top + 0.5) bad(`header bottom ${hr.bottom} overlaps the lookup section (top ${lr.top})`);
  const noResult = !result.firstElementChild;
  if (framed && noResult && result.getBoundingClientRect().height > 0) bad(`the empty result block takes ${result.getBoundingClientRect().height}px`);
  if (framed) {
    const de = document.documentElement;
    if (de.scrollHeight > innerHeight + 1) bad(`framed page is taller than the screen (${de.scrollHeight} > ${innerHeight}) with the body overflow hidden`);
  }
  // (d) no fades
  for (const [name, el] of [['shell', shell], ['lookup', lookup], ['list', list], ['region', $('#account-list')], ['result', result]]) {
    const cs = getComputedStyle(el);
    for (const prop of ['maskImage', 'webkitMaskImage']) if (cs[prop] && cs[prop] !== 'none') bad(`${name} has a ${prop}`);
    if (/gradient/.test(cs.backgroundImage)) bad(`${name} has a gradient background`);
    for (const pseudo of ['::before', '::after']) {
      const p = getComputedStyle(el, pseudo);
      if (p.content !== 'none' && p.content !== 'normal' && (/gradient/.test(p.backgroundImage) || p.position === 'absolute')) bad(`${name}${pseudo} is an overlay`);
    }
  }
  out.geometry = {vw: innerWidth, vh: innerHeight, framed, bodyOverflow: getComputedStyle(document.body).overflow,
    bannerHeight: banner ? rect(banner).height : 0, bannerFirst: banner ? document.body.firstElementChild === banner : null,
    bar: rect($('nav.switch-bar')), header: hr, lookup: lr, list: sr, input: rect($('#reference-input')), check: rect($('#reference-check')),
    error: shown(error) ? rect(error) : null, result: shown(result.firstElementChild) ? rect(result) : null,
    resultClient: result.clientHeight, resultFull: result.scrollHeight,
    shellClient: shell.clientHeight, shellFull: shell.scrollHeight, shellOverflowY: getComputedStyle(shell).overflowY,
    docHeight: document.documentElement.scrollHeight, scrollY, scrollWidthOver: document.documentElement.scrollWidth - innerWidth,
    listClient: $('#account-list').clientHeight, listFull: $('#account-list').scrollHeight};
  out.geometry.shellOverflow = shell.scrollHeight - shell.clientHeight;
  if (out.geometry.scrollWidthOver > 0) bad(`horizontal overflow of ${out.geometry.scrollWidthOver}px`);
  return out;
}

// Runs in the page. Brings each selector's element on screen the way a person can, then hit-tests
// its centre. Never calls scrollIntoView (it would scroll overflow:hidden boxes, which no person can).
function reachInPage(selectors, label) {
  const violations = [];
  const clip = v => v === 'hidden' || v === 'clip';
  const scrolls = v => v === 'auto' || v === 'scroll';
  for (const sel of selectors) {
    const el = typeof sel === 'string' ? document.querySelector(sel) : null;
    const name = sel;
    if (!el) { violations.push(`${label}: ${name} not found`); continue; }
    // Innermost to outermost: scroll the scrollable ancestors, then require the clipping ones to show it.
    for (let a = el.parentElement; a && a !== document.body && a !== document.documentElement; a = a.parentElement) {
      const oy = getComputedStyle(a).overflowY, ar = a.getBoundingClientRect();
      if (scrolls(oy) && a.scrollHeight > a.clientHeight) {
        const er = el.getBoundingClientRect();
        if (er.bottom > ar.bottom) a.scrollTop += Math.min(er.bottom - ar.bottom, er.top - ar.top);
        else if (er.top < ar.top) a.scrollTop -= ar.top - er.top;
      } else if (clip(oy)) {
        const er = el.getBoundingClientRect();
        if (er.bottom > ar.bottom + 0.5 || er.top < ar.top - 0.5) violations.push(`${label}: ${name} is cut off by overflow:hidden on ${a.tagName.toLowerCase()}.${a.className}`);
      }
    }
    // The viewport: the body's overflow when it propagates, else the page scrolls.
    const bodyHidden = clip(getComputedStyle(document.body).overflowY) && !clip(getComputedStyle(document.documentElement).overflowY) || clip(getComputedStyle(document.documentElement).overflowY);
    let er = el.getBoundingClientRect();
    if (!bodyHidden) {
      if (er.bottom > innerHeight) scrollBy(0, Math.min(er.bottom - innerHeight, er.top));
      else if (er.top < 0) scrollBy(0, er.top);
      er = el.getBoundingClientRect();
    }
    if (er.top < -0.5 || er.bottom > innerHeight + 0.5) { violations.push(`${label}: ${name} is off screen (${er.top.toFixed(1)}..${er.bottom.toFixed(1)} of ${innerHeight})`); continue; }
    const hit = document.elementFromPoint(er.left + er.width / 2, er.top + er.height / 2);
    if (!(hit === el || el.contains(hit))) {
      violations.push(`${label}: the centre of ${name} hit-tests to ${hit ? hit.tagName.toLowerCase() + (hit.id ? '#' + hit.id : '') + '.' + String(hit.className).slice(0, 40) : 'nothing'}`);
    }
  }
  return violations;
}

(async () => {
  const browser = await puppeteer.launch({headless: true, executablePath: process.env.BROWSER_EXECUTABLE, args: ['--no-sandbox']});
  // Replay: which recorded data files back the list and two lookups.
  let replayFiles = null;
  if (REPLAY) {
    const manifest = await (await fetch(base + '/replay/data/after/manifest.json')).json();
    const ids = Object.keys(manifest).map(k => /^GET \/api\/disputes\/([^/?]+)$/.exec(k)).filter(Boolean).map(m => m[1]);
    if (ids.length < 2 || !manifest['GET /api/demo/rider']) throw new Error('the replay export has no rider list or fewer than two disputes');
    replayFiles = {list: '/replay/data/after/' + manifest['GET /api/demo/rider'], refs: ids.slice(0, 2),
      files: ids.slice(0, 2).map(id => '/replay/data/after/' + manifest['GET /api/disputes/' + id])};
  }
  const REF = REPLAY ? {short: replayFiles.refs[0], tall: replayFiles.refs[1]} : {short: 'PF-W35SHORT', tall: 'PF-W35TALL'};
  const open = async (width, height) => {
    const page = await browser.newPage();
    page.on('pageerror', e => report.errors.push(`${width}x${height}: ${e.message}`));
    await page.setViewport({width, height});
    await page.setRequestInterception(true);
    page.on('request', r => {
      const u = new URL(r.url());
      if (u.hostname !== '127.0.0.1') return r.abort();
      const json = (body, status = 200) => r.respond({status, contentType: 'application/json', body: JSON.stringify(body)});
      if (REPLAY) {
        if (u.pathname === replayFiles.list) return json({account: {kind: 'rider', label: 'Demo account'}, disputes: DISPUTES});
        if (u.pathname === replayFiles.files[0]) return json(SHORT);
        if (u.pathname === replayFiles.files[1]) return json(TALL);
        return r.continue();
      }
      if (u.pathname === '/api/demo/rider') return json({account: {kind: 'rider', label: 'Demo account'}, disputes: DISPUTES});
      if (u.pathname === '/api/disputes/PF-W35TALL') return json(TALL);
      if (u.pathname === '/api/disputes/PF-W35SHORT') return json(SHORT);
      if (u.pathname === '/api/disputes/PF-W35LONGERR') return json({error: LONG_ERROR}, 404);
      return r.continue();
    });
    await page.goto(PAGE_URL, {waitUntil: 'networkidle0'});
    await page.waitForFunction(n => document.querySelectorAll('#account-list > .step').length === n, {}, DISPUTES.length);
    if (REPLAY) await page.waitForSelector('#replay-banner');
    await page.evaluate(() => document.fonts.ready);
    return page;
  };
  const park = async page => { await page.mouse.move(0, 0); await page.evaluate(() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))); };
  const state = async (page, view, label, controls) => {
    await park(page);
    await page.evaluate(() => { scrollTo(0, 0); });
    const audit = await page.evaluate(auditInPage, label);
    const reach = await page.evaluate(reachInPage, controls, label);
    view.states.push({label, geometry: audit.geometry});
    view.violations.push(...audit.violations, ...reach);
    // Room: the result and the header give way before the shell scrolls. Measured with the fix:
    // live 320x654 needs at most 7px of shell scroll (an error line over a result), none from
    // FIT_HEIGHT up; a replay needs none from 844 up (its banner is 48-120px of pinned room).
    const g = audit.geometry;
    if (g.framed) {
      const over = g.shellOverflow;
      const longError = label === 'long-error' || label === 'large-text-error';
      if (!REPLAY && !longError && over > 8) view.violations.push(`${label}: the shell scrolls by ${over}px (most allowed: 8)`);
      if (!REPLAY && !longError && view.height >= FIT_HEIGHT && over > 1) view.violations.push(`${label}: the shell scrolls by ${over}px at height ${view.height} (none from ${FIT_HEIGHT})`);
      if (REPLAY && !longError && view.height >= 844 && over > 1) view.violations.push(`${label}: the replay shell scrolls by ${over}px at height ${view.height} (none from 844)`);
      if (label === 'tall-result' && !(g.resultFull > g.resultClient + 1)) view.violations.push(`${label}: the tall result does not scroll inside its own window (${g.resultFull} in ${g.resultClient})`);
    }
    await page.evaluate(() => {
      scrollTo(0, 0);
      for (const e of document.querySelectorAll('.status-shell, #lookup-result, #account-list')) e.scrollTop = 0;
    });
    return audit.geometry;
  };
  const CONTROLS = ['#reference-input', '#reference-check', '.party-header a'];
  const click = async (page, ref) => {
    await page.$eval('#reference-input', (e, v) => { e.value = v; }, ref);
    await page.mouse.move(0, 0);
    // A person taps the button. When the layout hides it the tap lands elsewhere; the state is
    // then reached by the DOM so the later states can still be audited.
    const hit = await page.evaluate(() => { const b = document.getElementById('reference-check'); b.scrollIntoView({block: 'nearest'}); const r = b.getBoundingClientRect(); const h = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2); return h === b; });
    if (hit) await page.click('#reference-check'); else await page.$eval('#reference-check', e => e.click());
    await page.evaluate(() => new Promise(r => setTimeout(r, 120)));
    await page.$eval('#reference-input', e => e.focus());
    await page.evaluate(() => scrollTo(0, 0));
  };
  try {
    for (const [width, height] of SIZES) {
      const view = {width, height, states: [], violations: []};
      report.views.push(view);
      const page = await open(width, height);
      // Does the page start framed exactly from the threshold? (live and replay alike)
      const probe = await page.evaluate(() => ({overflow: getComputedStyle(document.body).overflow, banner: !!document.getElementById('replay-banner'),
        bannerFirst: !!document.getElementById('replay-banner') && document.body.firstElementChild === document.getElementById('replay-banner')}));
      view.framed = probe.overflow === 'hidden';
      if (REPLAY && !probe.bannerFirst) view.violations.push('fixture: the replay banner is not the first child of body');
      if (!REPLAY && probe.banner) view.violations.push('fixture: the live page has a replay banner');
      if (view.framed !== (height >= THRESHOLD)) view.violations.push(`the ${target} page is ${view.framed ? '' : 'not '}framed at height ${height}; expected framed = ${height >= THRESHOLD} (threshold ${THRESHOLD})`);

      await state(page, view, 'initial', CONTROLS);
      // (c) the list scrolls inside its own region when framed, and the lookup never moves.
      if (view.framed) {
        const before = await page.evaluate(auditInPage, 'b');
        await page.evaluate(() => { const l = document.getElementById('account-list'); l.scrollTop = l.scrollHeight; });
        const after = await page.evaluate(() => { const l = document.getElementById('account-list'), cards = l.querySelectorAll(':scope > .step'), r = e => { const q = e.getBoundingClientRect(); return {top: q.top, bottom: q.bottom}; };
          return {top: l.scrollTop, full: l.scrollHeight, client: l.clientHeight, last: r(cards[cards.length - 1]), region: r(l), lookup: r(document.querySelector('.status-lookup')), scrollY, shell: document.querySelector('.status-shell').scrollTop}; });
        const g = before.geometry;
        if (!(after.top > 0)) view.violations.push(`list-scroll: the list region did not scroll (client ${after.client} full ${after.full})`);
        if (after.client < 60) view.violations.push(`list-scroll: the list region is only ${after.client}px tall`);
        if (after.last.bottom > after.region.bottom + 1) view.violations.push('list-scroll: the last dispute is not reachable inside the list region');
        if (Math.abs(after.lookup.top - g.lookup.top) > 0.5) view.violations.push('list-scroll: scrolling the list moved the lookup box');
        if (after.scrollY !== 0 || after.shell !== 0) view.violations.push('list-scroll: scrolling the list scrolled the page or the shell');
        await page.evaluate(() => { document.getElementById('account-list').scrollTop = 0; });
      }
      // empty reference
      await click(page, '');
      await state(page, view, 'empty-error', CONTROLS.concat('#reference-error'));
      // unknown reference
      await click(page, 'PF-NOSUCH');
      await state(page, view, 'unknown-error', CONTROLS.concat('#reference-error'));
      if (!REPLAY) {
        await click(page, 'PF-W35LONGERR');
        await state(page, view, 'long-error', CONTROLS.concat('#reference-error'));
      }
      // The same empty-reference error with the text 25% larger (a browser text-size setting, or a
      // wider web font than this machine's fallback): rem-based room grows, the viewport does not.
      await page.evaluate(() => { document.documentElement.style.fontSize = '20px'; });
      await click(page, '');
      await state(page, view, 'large-text-error', CONTROLS.concat('#reference-error'));
      await page.evaluate(() => { document.documentElement.style.fontSize = ''; });
      // found
      await click(page, REF.short);
      await page.waitForFunction(r => (document.querySelector('#lookup-result .reference') || {textContent: ''}).textContent.includes(r), {}, 'PF-W35SHORT');
      await state(page, view, 'found', CONTROLS.concat('#lookup-result .reference'));
      // tall
      await click(page, REF.tall);
      await page.waitForFunction(r => (document.querySelector('#lookup-result .reference') || {textContent: ''}).textContent.includes(r), {}, 'PF-W35TALL');
      const tallControls = CONTROLS.concat('#lookup-result .reference', '#lookup-result .question-boxes .field:last-child textarea', '#lookup-result > .step > button.primary');
      const tg = await state(page, view, 'tall-result', tallControls);
      if (view.framed) {
        // the list still scrolls inside its region, and the lookup stays put
        await page.evaluate(() => { const l = document.getElementById('account-list'); l.scrollTop = l.scrollHeight; });
        const after = await page.evaluate(auditInPage, 'tall-list-scrolled');
        const moved = Math.abs(after.geometry.lookup.top - tg.lookup.top) > 0.5 || Math.abs(after.geometry.check.top - tg.check.top) > 0.5;
        if (moved) view.violations.push('tall-list-scroll: scrolling the list moved the lookup box');
        view.violations.push(...after.violations);
        await page.evaluate(() => { document.getElementById('account-list').scrollTop = 0; });
      }
      // the empty-reference error with a result already shown
      await click(page, '');
      await state(page, view, 'empty-error-over-result', CONTROLS.concat('#reference-error'));
      if (width === 320 || width === 390 || width === 1280) {
        await page.screenshot({path: path.join(path.dirname(output), `${target}-${width}x${height}.png`)}).catch(() => {});
      }
      await page.close();
    }
    for (const v of report.views) for (const m of v.violations) report.violations.push(`${v.width}x${v.height}: ${m}`);
    if (report.errors.length) report.violations.push('page errors: ' + report.errors.join('; '));
    report.passed = report.violations.length === 0;
    if (!report.passed) process.exitCode = 1;
  } catch (e) {
    report.error = String(e && e.stack || e);
    process.exitCode = 1;
  } finally {
    await browser.close();
    fs.writeFileSync(output, JSON.stringify(report, null, 2));
    console.log(JSON.stringify({target, passed: report.passed, views: report.views.length, violations: report.violations.length, error: report.error}));
    for (const m of report.violations.slice(0, 40)) console.log('  ' + m);
  }
})().catch(e => { console.error(e); process.exitCode = 1; });
