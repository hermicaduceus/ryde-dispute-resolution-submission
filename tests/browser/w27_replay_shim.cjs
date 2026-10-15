/* W27 replay shim driver. Node only, no browser, no installs, no network.
 *
 *   node tests/browser/w27_replay_shim.cjs SITE_DIR SCENARIOS_JSON
 *
 * Loads SITE_DIR/replay/replay-shim.js into a fresh vm context per page, the way a page's
 * <head> runs it: document.body is null while the shim runs, then the body is attached and
 * DOMContentLoaded and load fire. The context's original fetch is a stand-in network that
 * serves SITE_DIR files and records every request that reaches it; an /api/ request that
 * reaches it answers 599. Pages inside one scenario share one sessionStorage, as in-site
 * navigation does. The shim may use createElement, createTextNode, setAttribute, id,
 * appendChild, insertBefore, prepend, textContent and document/window addEventListener;
 * innerHTML is not modelled and throws.
 *
 * Prints one JSON report; the Python wrapper (tests/test_w27_replay_shim.py) asserts on it.
 * Exit code is non-zero only when the driver itself breaks.
 */
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const [site, scenariosPath] = process.argv.slice(2);
const ORIGIN = 'http://replay.test';
const scenarios = JSON.parse(fs.readFileSync(scenariosPath, 'utf8'));
let currentErrors = null;
process.on('unhandledRejection', (e) => { if (currentErrors) currentErrors.push('unhandled: ' + String(e && e.stack || e)); });

class Node {
  constructor(doc, type, tag, data) {
    this.ownerDocument = doc; this.nodeType = type; this.tagName = tag ? tag.toUpperCase() : undefined;
    this.nodeName = type === 3 ? '#text' : this.tagName; this.data = data || ''; this.childNodes = [];
    this.parentNode = null; this.attributes = {}; this.style = {}; this.listeners = {};
    const node = this;
    this.classList = {
      add(...c) { const s = new Set((node.className || '').split(/\s+/).filter(Boolean)); c.forEach((x) => s.add(x)); node.className = [...s].join(' '); },
      remove(...c) { node.className = (node.className || '').split(/\s+/).filter((x) => x && !c.includes(x)).join(' '); },
      contains(c) { return (node.className || '').split(/\s+/).includes(c); },
    };
  }
  get firstChild() { return this.childNodes[0] || null; }
  get lastChild() { return this.childNodes[this.childNodes.length - 1] || null; }
  get children() { return this.childNodes.filter((n) => n.nodeType === 1); }
  get firstElementChild() { return this.children[0] || null; }
  get nextSibling() { if (!this.parentNode) return null; const s = this.parentNode.childNodes; return s[s.indexOf(this) + 1] || null; }
  get nodeValue() { return this.nodeType === 3 ? this.data : null; }
  _wrap(n) { return typeof n === 'string' ? this.ownerDocument.createTextNode(n) : n; }
  _detach(c) { if (c.parentNode) c.parentNode.removeChild(c); }
  appendChild(c) { this._detach(c); this.childNodes.push(c); c.parentNode = this; return c; }
  insertBefore(c, ref) {
    if (ref === null || ref === undefined) return this.appendChild(c);
    this._detach(c); const i = this.childNodes.indexOf(ref);
    if (i < 0) throw new Error('insertBefore: reference is not a child');
    this.childNodes.splice(i, 0, c); c.parentNode = this; return c;
  }
  removeChild(c) { const i = this.childNodes.indexOf(c); if (i < 0) throw new Error('removeChild: not a child'); this.childNodes.splice(i, 1); c.parentNode = null; return c; }
  prepend(...nodes) { const first = this.firstChild; nodes.map((n) => this._wrap(n)).forEach((n) => this.insertBefore(n, first)); }
  append(...nodes) { nodes.map((n) => this._wrap(n)).forEach((n) => this.appendChild(n)); }
  setAttribute(k, v) { this.attributes[String(k).toLowerCase()] = String(v); }
  getAttribute(k) { const key = String(k).toLowerCase(); return Object.prototype.hasOwnProperty.call(this.attributes, key) ? this.attributes[key] : null; }
  hasAttribute(k) { return this.getAttribute(k) !== null; }
  removeAttribute(k) { delete this.attributes[String(k).toLowerCase()]; }
  get id() { return this.getAttribute('id') || ''; } set id(v) { this.setAttribute('id', v); }
  get className() { return this.getAttribute('class') || ''; } set className(v) { this.setAttribute('class', v); }
  get href() { return this.getAttribute('href') || ''; } set href(v) { this.setAttribute('href', v); }
  get role() { return this.getAttribute('role'); } set role(v) { this.setAttribute('role', v); }
  get textContent() { return this.nodeType === 3 ? this.data : this.childNodes.map((n) => n.textContent).join(''); }
  set textContent(v) { if (this.nodeType === 3) { this.data = String(v); return; } this.childNodes.forEach((n) => { n.parentNode = null; }); this.childNodes = []; if (String(v)) this.appendChild(this.ownerDocument.createTextNode(String(v))); }
  get innerText() { return this.textContent; } set innerText(v) { this.textContent = v; }
  get innerHTML() { throw new Error('innerHTML is not modelled by the W27 driver'); }
  set innerHTML(v) { throw new Error('innerHTML is not modelled by the W27 driver'); }
  insertAdjacentHTML() { throw new Error('insertAdjacentHTML is not modelled by the W27 driver'); }
  addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); }
  removeEventListener(type, fn) { this.listeners[type] = (this.listeners[type] || []).filter((f) => f !== fn); }
  _all() { const out = []; const walk = (n) => { n.childNodes.forEach((c) => { if (c.nodeType === 1) { out.push(c); walk(c); } }); }; walk(this); return out; }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
  querySelectorAll(sel) {
    const s = String(sel).trim();
    if (/^#[\w-]+$/.test(s)) return this._all().filter((n) => n.id === s.slice(1));
    if (/^[a-zA-Z]+$/.test(s)) return this._all().filter((n) => n.tagName === s.toUpperCase());
    throw new Error('selector not modelled by the W27 driver: ' + s);
  }
}

function makeDocument() {
  const doc = { readyState: 'loading', listeners: {} };
  doc.createElement = (tag) => new Node(doc, 1, String(tag));
  doc.createTextNode = (text) => new Node(doc, 3, null, String(text));
  doc.documentElement = new Node(doc, 1, 'html');
  doc.head = new Node(doc, 1, 'head');
  doc.documentElement.appendChild(doc.head);
  doc.body = null;
  doc.getElementById = (id) => doc.documentElement._all().find((n) => n.id === id) || null;
  doc.querySelector = (s) => doc.documentElement.querySelector(s);
  doc.querySelectorAll = (s) => doc.documentElement.querySelectorAll(s);
  doc.addEventListener = (type, fn) => { (doc.listeners[type] = doc.listeners[type] || []).push(fn); };
  doc.removeEventListener = (type, fn) => { doc.listeners[type] = (doc.listeners[type] || []).filter((f) => f !== fn); };
  return doc;
}

function contentType(file) {
  return { '.json': 'application/json', '.js': 'text/javascript', '.html': 'text/html', '.css': 'text/css' }[path.extname(file)] || 'application/octet-stream';
}

function makeNetwork(log, base) {
  return function network(input, init) {
    const url = typeof input === 'string' ? input : (input && input.url) || String(input);
    const method = String((init && init.method) || (input && typeof input === 'object' && input.method) || 'GET').toUpperCase();
    const u = new URL(url, base);
    log.push({ method, url: u.pathname + u.search });
    if (u.origin !== ORIGIN) return Promise.resolve(new Response('', { status: 599 }));
    if (u.pathname.startsWith('/api/')) {
      return Promise.resolve(new Response(JSON.stringify({ error: 'reached the network' }), { status: 599 }));
    }
    let rel = decodeURIComponent(u.pathname);
    if (rel.endsWith('/')) rel += 'index.html';
    const file = path.join(site, rel);
    if (method === 'GET' && file.startsWith(path.resolve(site)) && fs.existsSync(file) && fs.statSync(file).isFile()) {
      return Promise.resolve(new Response(fs.readFileSync(file), { status: 200, headers: { 'Content-Type': contentType(file) } }));
    }
    return Promise.resolve(new Response('', { status: 404 }));
  };
}

function withTimeout(promise, ms, what) {
  let timer;
  return Promise.race([promise, new Promise((_, reject) => { timer = setTimeout(() => reject(new Error('timeout: ' + what)), ms); })])
    .finally(() => clearTimeout(timer));
}

function bannerReport(doc) {
  const all = doc.documentElement._all().filter((n) => n.id === 'replay-banner');
  const body = doc.body;
  const report = { count: all.length, isFirstChild: false, tag: null, role: null, textBefore: null, textAfter: null, link: null };
  if (!all.length) return report;
  const banner = all[0];
  report.isFirstChild = Boolean(body && body.firstChild === banner);
  report.tag = banner.tagName; report.role = banner.getAttribute('role');
  const links = banner._all().filter((n) => n.id === 'replay-switch');
  report.switchCount = doc.documentElement._all().filter((n) => n.id === 'replay-switch').length;
  if (links.length) {
    const link = links[0];
    let top = link; while (top.parentNode && top.parentNode !== banner) top = top.parentNode;
    const index = banner.childNodes.indexOf(top);
    const firstAnchor = banner.childNodes.findIndex((n) => n.tagName === 'A');
    report.textBefore = banner.childNodes.slice(0, firstAnchor === -1 ? index : firstAnchor)
      .map((n) => n.textContent).join('');
    report.textAfter = banner.childNodes.slice(index + 1).map((n) => n.textContent).join('');
    report.link = { tag: link.tagName, text: link.textContent, href: link.getAttribute('href') };
  } else {
    report.textBefore = banner.textContent;
  }
  const backs = banner._all().filter((n) => n.id === 'replay-back');
  report.back = backs.length ? { tag: backs[0].tagName, text: backs[0].textContent,
                                 href: backs[0].getAttribute('href') } : null;
  return report;
}

async function runPage(page, storage, shimSource) {
  const errors = []; currentErrors = errors;
  const network = [];
  const href = new URL(page.url, ORIGIN).href;
  const loc = new URL(href);
  const doc = makeDocument();
  const winListeners = {};
  const location = {
    href, origin: loc.origin, protocol: loc.protocol, host: loc.host, hostname: loc.hostname, port: loc.port,
    pathname: loc.pathname, search: loc.search, hash: loc.hash, toString() { return href; },
    assign() {}, replace() {}, reload() {},
  };
  const sandbox = {
    document: doc, location, sessionStorage: storage, fetch: makeNetwork(network, href),
    Response, Headers, Request, URL, URLSearchParams, Promise, JSON, Object, Array, String, Number, Boolean,
    Math, Date, RegExp, Error, TypeError, isFinite, isNaN, parseInt, parseFloat,
    encodeURIComponent, decodeURIComponent, encodeURI, decodeURI, setTimeout, clearTimeout,
    console: { log() {}, warn() {}, error() {}, info() {} },
    history: { replaceState() {}, pushState() {} }, navigator: { userAgent: 'w27-driver' },
    addEventListener(type, fn) { (winListeners[type] = winListeners[type] || []).push(fn); },
    removeEventListener() {},
  };
  sandbox.window = sandbox; sandbox.self = sandbox;
  const ctx = vm.createContext(sandbox);
  try {
    if (shimSource === null) throw new Error('replay/replay-shim.js is missing from the site');
    vm.runInContext(shimSource, ctx, { filename: 'replay-shim.js' });
  } catch (e) { errors.push('shim: ' + String(e && e.stack || e)); }
  const body = new Node(doc, 1, 'body');
  const header = new Node(doc, 1, 'header'); header.id = 'page-header';
  body.appendChild(header);
  doc.documentElement.appendChild(body); doc.body = body; doc.readyState = 'interactive';
  const fire = (list) => (list || []).forEach((fn) => { try { fn.call(doc, { type: 'event' }); } catch (e) { errors.push('listener: ' + String(e && e.stack || e)); } });
  fire(doc.listeners.DOMContentLoaded); fire(winListeners.DOMContentLoaded);
  doc.readyState = 'complete'; fire(winListeners.load);
  await new Promise((r) => setImmediate(r));
  const responses = [];
  for (const call of page.calls || []) {
    const entry = { input: call.input, status: null, body: null, error: null };
    try {
      const pageFetch = vm.runInContext('fetch', ctx);
      const args = call.init === undefined ? [call.input] : [call.input, call.init];
      const response = await withTimeout(Promise.resolve(pageFetch.apply(sandbox, args)), 5000, call.input);
      entry.status = response.status;
      entry.body = await withTimeout(response.text(), 5000, 'body of ' + call.input);
    } catch (e) { entry.error = String(e && e.stack || e); }
    responses.push(entry);
  }
  await new Promise((r) => setImmediate(r));
  currentErrors = null;
  return { url: page.url, errors, banner: bannerReport(doc), responses, network };
}

function makeStorage() {
  const map = new Map();
  return {
    getItem(k) { return map.has(String(k)) ? map.get(String(k)) : null; },
    setItem(k, v) { map.set(String(k), String(v)); },
    removeItem(k) { map.delete(String(k)); },
    clear() { map.clear(); },
    key(i) { return [...map.keys()][i] || null; },
    get length() { return map.size; },
  };
}

(async () => {
  let shimSource = null;
  try { shimSource = fs.readFileSync(path.join(site, 'replay', 'replay-shim.js'), 'utf8'); } catch (e) { shimSource = null; }
  const report = { scenarios: {} };
  for (const scenario of scenarios) {
    const storage = makeStorage();
    const pages = [];
    for (const page of scenario.pages) pages.push(await runPage(page, storage, shimSource));
    report.scenarios[scenario.name] = pages;
  }
  process.stdout.write(JSON.stringify(report));
})().catch((e) => { process.stderr.write(String(e && e.stack || e)); process.exit(1); });
