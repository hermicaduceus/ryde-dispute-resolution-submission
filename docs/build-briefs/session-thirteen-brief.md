# Session thirteen brief — W18 console token pass + W17 selected-choice outline

Two deliverables, both CSS-level. Touch nothing else.

1. **W18:** the operator console (`ui/index.html` + `ui/styles.css`) wears the Ryde theme.
2. **W17:** on the party form, the selected Yes/No button keeps the pink outline
   (`ui/party/party.css`, one declaration).

This is a **token pass**: colour, typography and shape only. No layout restructure, no
copy changes, no new DOM elements or ids, no behaviour change. `ui/app.js` must stay
**byte-identical** (a test pins its SHA).

## The design rule that governs every choice

**Ryde pink is chrome. Status colours carry meaning and keep it.** The console tells an
operator whether a ruling was delivered (green), withheld or human-only (amber), in error
(red), or routed to a human / waiting on the party (blue). Those four keep their exact
token values and stay on the rules that use them. Pink replaces the console's *decorative*
blue and navy: headings, section numbers, the loader panel, the rider's claim quote, the
advocate cards, citation chips, the event log's sequence numbers and actor tags, the focus
ring. A withheld ruling must never read as brand pink.

The canvas is **neutral** (the operator ruling): a warm light grey, not the party page's pastel pink.

## What to build

### 1. `ui/index.html` — head change only

Add, immediately BEFORE the existing `styles.css` link:

```html
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;600;700&display=swap">
```

Change nothing else. The font fetch may fail (offline demo); the fallback stack carries it.

### 2. `ui/styles.css` — tokens

Replace the `:root` token values:

| Variable | Old | New | Note |
|---|---|---|---|
| `--ink` | `#182334` | `#31373E` | brand ink |
| `--muted` | `#657085` | `#5A6470` | derived, same as party page |
| `--faint` | `#8b96a8` | `#646C77` | derived: old value was 2.74:1, fails AA |
| `--line` | `#d7dee8` | `#E5E0DC` | derived warm grey, same as party page |
| `--panel` | `#ffffff` | `#ffffff` | unchanged |
| `--canvas` | `#f3f5f8` | `#F5F4F3` | derived **neutral** warm grey |
| `--navy` | `#213b5a` | **remove** | every `var(--navy)` becomes `var(--ink)` |
| `--accent` | — | `#E93864` | **new**, brand pink: borders, rules, fills |
| `--accent-text` | — | `#C8284F` | **new**, derived pink for small TEXT (brand pink is 3.7:1 on the canvas and fails AA for text) |
| `--accent-wash` | — | `#FFF0F3` | **new**, brand pink tint for chip/header backgrounds |
| `--shadow` | navy-tinted rgba | ink-tinted rgba | your pick, keep it subtle |

**Keep exactly:** `--blue #2a638c`, `--blue-wash #edf5fa`, `--amber #9b5c18`,
`--amber-wash #fff6e8`, `--red #a33f3f`, `--red-wash #fff0ef`, `--green #2e6b51`,
`--green-wash #edf7f0`.

Rule of thumb: pink **text** uses `--accent-text`; pink **borders/rules** use `--accent`;
pink **backgrounds** use `--accent-wash`.

### 3. `ui/styles.css` — chrome moves from blue to pink

Each of these rules uses the blue as decoration today. Move it to the accent family and
remove every trace of the blue family from it (`var(--blue)`, `var(--blue-wash)`, and the
blue's own tints `#b9d3e3`, `#dceef7`, `#c9deeb`):

`.loader-panel`, `.header-note`, `.section-index`, `.grievance-marker`, `.claim-text`,
`.claim-card`, `.claim-card-header`, `.citation`, `.citation:hover`, `.event-seq`,
`.event-actor`, `.event-row summary::before`, `#load-status[data-state="loading"]`.

The driver advocate's card keeps its amber variant (`.claim-driver` and
`.claim-driver .claim-card-header`): rider = pink, driver = amber reads as two sides.

The focus ring (`button:focus-visible, input:focus-visible, a:focus-visible,
summary:focus-visible`) becomes `var(--accent)`.

### 4. `ui/styles.css` — status rules stay put

Do **not** move these to the accent: `.outcome-ruled`, `.outcome-ruled-badge`,
`.outcome-withheld`, `.outcome-withheld-badge`, `.human-only-region`,
`.party-facing-region`, `.outcome-human-review`, `.outcome-needs-info`,
`.routing-explanation`, `.citation-unresolved`, and everything else keyed to
`--green`/`--amber`/`--red`. `.routing-explanation` is informational routing and stays blue.

### 5. `ui/styles.css` — typography and shape

- The `:root` font stack becomes
  `Poppins, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif`.
  Monospace stacks (event log, payloads, ids) stay monospace: they are data, not brand.
- `h1`, `h2`, `h3` are set in `var(--ink)`. You may retune weights for Poppins
  (600/700 exist; 720 and 580 do not render as intended in Poppins).
- `.story-section` (and `.loader-panel` if you like) gets `border-radius` 12–20px.
- `.citation` chips become pills (`border-radius` ≥ 12px).
- The dark payload viewer (`.event-payload` and its children) may stay dark; retint its
  hard-coded navy toward the new ink if you want it to match. Your call.

### 6. `ui/party/party.css` — W17

Add `border-color: var(--accent);` to `.choice-button.selected`. Leave `:hover` as it is.

## Prohibitions (a test or review enforces each)

1. `ui/app.js` byte-identical (SHA-pinned). No JS changes anywhere.
2. No new, renamed or removed ids in `ui/index.html`. Only the three `<link>` lines are added.
3. No copy changes. Every visible string stays exactly as it is.
4. No layout restructuring, no new CSS files, no build tooling, no frameworks.
5. In `ui/party/`, only the one W17 declaration changes.
6. The old chrome values `#213b5a #657085 #8b96a8 #d7dee8 #f3f5f8` must be gone from
   `styles.css` entirely, including comments.

## Acceptance

```
python3 -m unittest discover -s tests -t .
```

Expected: **434 tests OK** (416 existing + 18 in `tests/test_console_rebrand.py`).
The new file is RED now (12 failing) on purpose. Make it green by shipping this brief.
If a test cannot be satisfied, or the brief conflicts with anything in the repo: **stop
and report** rather than guessing.

## Provenance note (for the record, not a build instruction)

Brand values (`#31373E`, `#E93864`, `#FFF0F3`) are Ryde's real brand system, the same
values the party page already uses (W10). Derived values are our own picks for WCAG AA,
flagged as derived. The reference lives in the private planning repo and is not copied here.
