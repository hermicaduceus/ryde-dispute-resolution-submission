// Renders system-architecture.svg/.png: the diagram from docs/architecture.md, hand-laid-out to fit a slide.
// Run from tools/deployment with puppeteer installed (the Edge path below is Windows): node render-system-architecture.js
// Hand-laid slide version of the system diagram in docs/architecture.md (same nodes and edges).
const fs = require("fs");
const puppeteer = require("puppeteer");

const INK = "#31373E", PINK = "#E93864", PASTEL = "#F7DDE3", GREY = "#5A6470", LINE = "#5A6470";
const W = 2000, H = 880, DY = 40;           // viewBox is shifted so the top lane can sit at y=15
const N = {};
function box(id, cx, cy, w, h, lines, kind) { N[id] = { cx, cy, w, h, lines, kind, shape: "box" }; }
function dia(id, cx, cy, w, h, lines, size) { N[id] = { cx, cy, w, h, lines, kind: "decision", shape: "dia", size }; }
const L = (n) => [N[n].cx - N[n].w / 2, N[n].cy], R = (n) => [N[n].cx + N[n].w / 2, N[n].cy];
const T = (n) => [N[n].cx, N[n].cy - N[n].h / 2], B = (n) => [N[n].cx, N[n].cy + N[n].h / 2];

// ---- nodes (kind: in = grey input, core = ink, key = pink emphasis, out = pastel) ----
box("A", 105, 125, 190, 70, ["Rider and driver", "intake forms"], "in");
box("PACK", 105, 285, 190, 60, ["Dataset pack"], "in");
box("CL", 105, 445, 190, 70, ["Command-line", "runner"], "core");
box("B", 330, 125, 170, 60, ["Server"], "core");
dia("C", 545, 285, 250, 130, ["Category in", "scope?"], 24);
box("POL", 850, 125, 190, 60, ["Policy document"], "in");
box("E", 850, 285, 190, 60, ["Evidence Pack"], "key");
box("RA", 1110, 125, 190, 60, ["Rider Advocate"], "core");
box("DA", 1110, 285, 190, 60, ["Driver Advocate"], "core");
dia("S", 1330, 205, 250, 140, ["Questions for", "the party?"], 22);
box("O4", 850, 560, 170, 60, ["Needs info"], "out");
box("PA", 330, 560, 190, 70, ["Party answers", "follow-ups"], "out");
box("J", 1560, 285, 170, 60, ["Judge"], "key");
dia("G", 1560, 470, 400, 190, ["Gates pass?", "Confidence, cap, measured deviation,", "NS-6, NS-8, RD-5, RD-4"], 20);
box("O1", 1395, 635, 150, 56, ["Ruled"], "core");
box("O2", 1560, 635, 150, 56, ["Withheld"], "core");
box("H", 1100, 745, 190, 60, ["Human review"], "out");
box("LOG", 1850, 470, 170, 60, ["Event log"], "out");
box("K", 1850, 635, 190, 60, ["Operator console"], "out");

// ---- edges: points, label {t:[lines], x, y}, dotted ----
const E = [];
const e = (pts, label, dotted) => E.push({ pts, label, dotted });
e([R("A"), L("B")]);
e([R("PACK"), [222, 285], [222, 140], [L("B")[0], 140]]);
e([B("PACK"), T("CL")]);
e([R("B"), [545, 125], T("C")]);
e([R("CL"), [395, 445], [395, 285], L("C")]);
e([B("C"), [545, 745], L("H")], { t: ["Out of scope"], x: 760, y: 745 });
e([R("C"), L("E")], { t: ["Route deviation", "or no-show"], x: 700, y: 345 });
e([R("POL"), L("RA")]);
e([[R("POL")[0], 135], [L("DA")[0], 270]]);
e([[R("E")[0], 275], [L("RA")[0], 140]]);
e([R("E"), L("DA")]);
e([[R("RA")[0], 135], [1268, 172]]);
e([[R("DA")[0], 275], [1268, 238]]);
e([B("S"), [1330, 560], R("O4")], { t: ["Yes, first round"], x: 1130, y: 560 });
e([L("O4"), R("PA")]);
e([T("PA"), B("B")], { t: ["Fresh run with", "the answers"], x: 262, y: 362 });
e([R("S"), [1520, 205], [1520, 255]], { t: ["No"], x: 1486, y: 195 });
e([T("POL"), [850, 45], [1595, 45], [1595, 255]]);
e([B("J"), T("G")]);
e([[1560, 565], [1560, 590], [1395, 590], T("O1")], { t: ["Yes"], x: 1478, y: 590 });
e([[1560, 565], T("O2")], { t: ["No"], x: 1586, y: 588 });
e([B("O2"), [1560, 815], [1100, 815], B("H")], { t: ["Candidate ruling queued"], x: 1330, y: 815 });
e([[L("J")[0], 300], [1260, 300], [1260, 745], R("H")], { t: ["Model could not", "answer"], x: 1260, y: 520 });
e([T("B"), [330, 15], [1895, 15], [1895, 440]], { t: ["Every step emits an event"], x: 1000, y: 15 }, true);
e([R("J"), [1850, 285], [1850, 440]], null, true);
e([B("LOG"), T("K")], { t: ["Embedded in the", "case file"], x: 1850, y: 552 });

// ---- SVG ----
const fills = { in: [GREY, "#fff"], core: [INK, "#fff"], key: [PINK, "#fff"], out: [PASTEL, INK], decision: [PINK, "#fff"] };
let svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 -${DY} ${W} ${H}" font-family="Arial, Helvetica, sans-serif">
<defs><marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="9" markerHeight="9" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="${LINE}"/></marker></defs>
<rect x="0" y="-${DY}" width="${W}" height="${H}" fill="#fff"/>`;
for (const ed of E) {
  const d = ed.pts.map((p, i) => (i ? "L" : "M") + p[0] + "," + p[1]).join(" ");
  svg += `<path d="${d}" fill="none" stroke="${LINE}" stroke-width="2.5" ${ed.dotted ? 'stroke-dasharray="3 6"' : ""} marker-end="url(#ah)"/>`;
}
for (const id in N) {
  const n = N[id], [fill, tc] = fills[n.kind], x = n.cx - n.w / 2, y = n.cy - n.h / 2;
  if (n.shape === "dia") svg += `<polygon points="${n.cx},${y} ${x + n.w},${n.cy} ${n.cx},${y + n.h} ${x},${n.cy}" fill="${fill}" stroke="${fill}"/>`;
  else svg += `<rect x="${x}" y="${y}" width="${n.w}" height="${n.h}" rx="6" fill="${fill}" stroke="${n.kind === "out" ? PINK : fill}" stroke-width="2"/>`;
  const fs = n.size || 24, lh = fs * 1.25, y0 = n.cy - (n.lines.length - 1) * lh / 2;
  n.lines.forEach((t, i) => { svg += `<text x="${n.cx}" y="${y0 + i * lh}" font-size="${fs}" fill="${tc}" text-anchor="middle" dominant-baseline="central">${t}</text>`; });
}
for (const ed of E) {
  if (!ed.label) continue;
  const { t, x, y } = ed.label, fs = 21, lh = 24, wmax = Math.max(...t.map((s) => s.length)) * 10.6 + 14, h = t.length * lh + 6;
  svg += `<rect x="${x - wmax / 2}" y="${y - h / 2}" width="${wmax}" height="${h}" fill="#fff"/>`;
  t.forEach((s, i) => { svg += `<text x="${x}" y="${y - (t.length - 1) * lh / 2 + i * lh}" font-size="${fs}" fill="${INK}" text-anchor="middle" dominant-baseline="central">${s}</text>`; });
}
svg += "</svg>";
fs.writeFileSync("system-architecture.svg", svg);

(async () => {
  const browser = await puppeteer.launch({ executablePath: "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe", args: ["--no-sandbox"] });
  const page = await browser.newPage();
  await page.setViewport({ width: W, height: H, deviceScaleFactor: 2 });
  await page.setContent(`<html><body style="margin:0;background:#fff">${svg}</body></html>`);
  await page.screenshot({ path: "system-architecture.png", clip: { x: 0, y: 0, width: W, height: H } });
  await browser.close();
  console.log("rendered", W, H);
})();
