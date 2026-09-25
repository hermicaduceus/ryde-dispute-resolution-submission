# Session nine brief — W10 token pass: the Ryde visual rebrand of the party page

One deliverable: restyle `ui/party/party.css` and add the Poppins webfont link to
`ui/party/index.html`. Touch nothing else.

This is a **token pass**: color, typography and shape only. No layout restructure, no
copy changes, no new DOM elements or ids, no behaviour change. `party.js` must stay
**byte-identical** — a test pins its SHA.

## What to build

### 1. `ui/party/index.html` — head change only

Add, immediately BEFORE the existing `party.css` stylesheet link in `<head>`:

```html
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;600&display=swap">
```

Change nothing else in the file. Every existing `id` and the DOM structure stay exactly
as they are (tests pin them).

The font fetch is allowed to fail (offline demo): nothing may depend on it succeeding.
The CSS fallback stack carries the design when it does.

### 2. `ui/party/party.css` — token swap, font stack, shape

**Token table (old → new).** Replace the `:root` block values:

| Variable | Old | New |
|---|---|---|
| `--ink` | `#1d2733` | `#31373E` |
| `--muted` | `#5c6b7a` | `#6B7480` *(derived, not from the brand system — pick for AA contrast on white)* |
| `--line` | `#d8dfe6` | `#E5E0DC` *(derived, warm-gray to sit on the pastel canvas)* |
| `--paper` (page canvas) | `#f6f8fa` | `#F7DDE3` |
| `--card` | `#ffffff` | `#ffffff` (unchanged) |
| `--accent` | `#0f6b5f` | `#E93864` |
| `--accent-ink` | `#ffffff` | `#ffffff` (unchanged) |
| `--error` | `#a03024` | `#C0392B` *(derived)* |
| `--ok` | `#0f6b5f` | `#1EB848` |

NOTE: today `--accent` and `--ok` share one value. After the change they must differ:
accent is Ryde pink, ok is Ryde status green. The `.step-number` badge may stay on the
accent (pink) or move to ink — your call as the designer; both are in brand.

**Selected-state tint.** `.option-card.selected` currently uses
`box-shadow: 0 0 0 2px rgba(15, 107, 95, 0.25);`. Replace with
`box-shadow: 0 0 0 2px #FFF0F3;` and keep `border-color: var(--accent)`.

**Typography.** The `body` font stack becomes:

```css
font-family: Poppins, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
```

Headings (`.party-header h1`, `.step h2`) and `.field label` get `font-weight: 600`;
body text stays 400. Do not import any other family.

**Shape:**

- `button` (the base rule): `border-radius: 29px` (pill). `button.primary` keeps the pill.
- `.step` cards: `border-radius: 16px` (Ryde card range is 12–20px).
- `.option-card`, `textarea`, `input[type="number"]`, `.outcome-message`: `border-radius: 12px`.
- Focus outlines stay 2px, now `outline: 2px solid var(--accent)` (pink) — the existing rule
  already uses `var(--accent)` and needs no change once the token moves.

You may adjust paddings/letter-spacing within existing rules for the new typeface if
needed for legibility. Do not change the layout model: `.option-grid` stays a grid,
`.step-actions` stays a flex row, `.party-shell` stays one centered column.

## Prohibitions (a test or review enforces each)

1. No changes to `party.js`. Byte-identical, SHA-pinned.
2. No new, renamed or removed element ids in `index.html`. Only the three `<link>` lines are added.
3. No copy changes — every visible string of text stays exactly as it is.
4. No layout restructuring, no new CSS files, no build tooling, no frameworks.
5. No changes outside `ui/party/`. The operator console (`ui/styles.css`, `ui/app.js`,
   `ui/index.html`) is out of scope.
6. All nine old plain-theme hex values listed in the table must be gone from `party.css`
   entirely — including comments.

## Acceptance

```
python3 -m unittest discover tests
```

Expected: **375 tests OK** (366 existing + 9 new in `tests/test_party_rebrand.py`).

The new test file is RED right now, on purpose. Make it green by shipping the brief.
If a test cannot be satisfied, or the brief conflicts with anything in the repo: **stop
and report** rather than guessing.

## Provenance note (for the record, not a build instruction)

The token values are Ryde's real brand system, cross-checked across two independent
research lanes. The reference lives in the private planning repo and is deliberately not
copied here. Derived values (`--muted`, `--line`, `--error`) are our own picks for
contrast, flagged as derived.