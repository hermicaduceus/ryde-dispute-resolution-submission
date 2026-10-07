# Session thirteen, round three — the event log and citation chips go neutral

the operator ruling 2026-09-27, from live review: brand pink on dense, repeated UI reads as error red
(`--accent-text #C8284F` sits about 15° of hue from `--red #A33F3F`). The agent-traffic log
had pink on every row, and the citation chips were a row of pink pills. Both go neutral.
After this, pink is a thin brand accent only: section numbers, eyebrow labels, the loader
panel edge, the focus ring.

The payoff: in the event log, the `judge.ruling_withheld` row (amber, `.event-internal`)
becomes the only coloured row, and among citations only the null (amber) and unresolved
(red) chips carry colour. Colour marks the exceptions.

## Changes, all in `ui/styles.css`

| Rule | Now | Becomes |
|---|---|---|
| `.citation` | pink border, pink text, pink wash | `var(--line)` border, `var(--ink)` text, `var(--panel)` background |
| `.citation:hover` | pink wash, pink border | `var(--canvas)` background, `var(--muted)` border |
| `.event-seq` | pink text | `var(--ink)` |
| `.event-actor` | pink text, wash, border | `var(--ink)` text, `var(--canvas)` background, `var(--line)` border |
| `.event-row summary::before` (the `+` marker) | pink text + border | `var(--muted)` text, `var(--line)` border |

Keep shapes (pill radius, sizes, weights) as they are. `.citation-null`, `.citation-unresolved`,
`.event-internal` and `.event-internal .event-type/.event-payload-ref` are **not** touched.

## Trap: selectors appear in more than one rule

`.event-seq` appears in **three** rules (a shared monospace group, its own rule, and a
media-query override); `.event-actor` and `.event-row summary::before` in two each. The test
reads every rule carrying the selector, including the one inside `@media`. Leave no pink copy.

## Prohibitions

Only `ui/styles.css` changes. `ui/app.js` byte-identical, no HTML/id/copy/layout changes,
no test edits, do not commit.

## Acceptance

`python3 -m unittest discover -s tests -t .` → **437 OK** (currently 1 failing test on purpose,
covering 5 selectors). Stop and report on any conflict.
