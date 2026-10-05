# W15 build brief: full-layout restyle of the party pages

You are building in the `ryde-build` repo. This brief carries the CONTRACT for the W15
layout pass. The acceptance tests are already committed and RED; your job is to make
them green by restyling `ui/party/party.css`. **Do not edit `party.js`** — two digest
freezes pin its bytes and this is a CSS/layout pass.

## What W15 is

The party pages already wear Ryde's brand tokens (W10, 09-25). W15 is the deferred second
half: the LAYOUT pass, so the pages read as a designed product rather than a token-swapped
prototype. Target: the four party pages (`index.html`, `driver-filing.html`, `status.html`,
`driver.html`) all styled by `ui/party/party.css`. The pages share one stylesheet; after the
restyle all four pages must keep their current HTML structure, ids and copy — this pass
changes CSS, not HTML (a `party.css` link and shell class must remain, asserted by tests).

## Allowed files

- `ui/party/party.css` — the whole restyle happens here.
- `tests/fixtures/colour_ledger.json` — re-baseline after your colour declarations change:
  `/usr/bin/python3 tools/colour_ledger.py --write`, then re-run the suite.
- NOTHING ELSE. Do not touch `ui/party/*.js`, `ui/party/*.html`, `ui/styles.css`,
  `app/`, `tests/` (beyond nothing), `data/`, `tools/`, `docs/`. If a test looks wrong,
  stop and ask.

## The layout contract (every value pinned by `tests/test_w15_layout.py`)

`:root` tokens: keep all existing tokens, add:
- `--tint: #FFF0F3` (the app's selected-row tint)
- `--float-shadow: 0 8px 24px rgba(0, 0, 0, 0.08)` (the app lane's floating-card shadow)

Canvas and rhythm:
- `.party-shell`: `max-width: 720px`, `padding: 2.5rem 1.25rem 5rem`
- `.party-header h1`: `font-size: 2.25rem`

Header:
- `.party-header .eyebrow` becomes a pill chip: `display: inline-block`,
  `border-radius: 9999px`, `background: var(--tint)`, `border: 1px solid var(--accent)`,
  `color: var(--accent)`, `font-weight: 600`, padding (e.g. `0.35rem 0.9rem`)
- `.demo-note` becomes a soft chip: `background: var(--tint)`, `border: 1px solid var(--line)`,
  `border-radius: 14px`, keep the muted text

Cards:
- `.step`: `border-radius: 20px`, `padding: 1.5rem`, `margin-bottom: 1.5rem`,
  `box-shadow: var(--float-shadow)` — white cards float on the pastel canvas
- `.option-card`: `border-radius: 16px`, padding `1rem 1.1rem`, a `transition` on
  transform/shadow/border-color
- `.option-card:hover`: `border-color: var(--accent)`, `transform: translateY(-2px)`,
  `box-shadow: var(--float-shadow)` (hover lift)
- `.option-card.selected`: the app's selected ride-row treatment — `background: var(--tint)`,
  `border: 2px solid var(--accent)`, `box-shadow: none`

Sticky step actions (the app's sticky bottom bar, kept inside the card):
- `.step-actions`: `position: sticky`, `bottom: 0`, `background: var(--card)`,
  `border-top: 1px solid var(--line)`, `border-radius: 0 0 20px 20px`, plus padding
  (e.g. `0.75rem 0 0.25rem`)

CTA and inputs:
- `button`: `font-weight: 600`, `padding: 0.7rem 1.5rem` (keep `border-radius: 29px`)
- inputs (textarea, number, text): `border-radius: 14px`, padding `0.7rem 0.9rem`
- `textarea:focus, input:focus`: keep the 2px accent outline, add
  `box-shadow: 0 0 0 4px var(--tint)` (focus halo)

You may also (not pinned): adjust `.choice-button`/`.trip-card`/`.outcome-message`/
`.status-line` styling to sit consistently in the new rhythm — but every COLOUR
declaration in the sheet must match the re-baselined `colour_ledger.json`, and the W10
rebrand pins in `tests/test_party_rebrand.py` must stay green (note: two of them were
re-baselined for W15 on purpose: option-card radius is now 16px, and the selected card
carries the tint as a token — see the updated test file, which is already committed).

## What you should see when done

- `/usr/bin/python3 -B -m unittest discover -s tests -t .` → **1091 tests OK**
  (NOTE: use `/usr/bin/python3`, not `python3` — the latter resolves a tools/ package
  collision that breaks 5 imports as loader errors)
- `tests.test_w15_layout` → 14/14 OK
- `tests.test_party_rebrand` → 12/12 OK
- The colour ledger re-baselined (`party.css` will report 57 rows)
- `ui/party/party.js` byte-identical to before you started (sha256 equals the two
  freeze literals in the test files)
- A quick visual sanity check by serving the party pages on a loopback port with the
  mock provider (`make_server(0, out_dir=<fresh tmp>, provider="mock")`, never the
  repo's `runs/`): rider and driver filing pages show the pastel canvas, floating
  white step cards, pill eyebrow chip, sticky step actions at card bottom.

## Out of scope (do not build)

- No JS changes of any kind (including adding classes from JS).
- No new pages, no HTML edits, no copy changes, no fonts beyond the existing Poppins link.
- No operator console changes (`ui/styles.css` is out of bounds; a test asserts the
  layout tokens do not leak there).
- No behaviour changes: filing, recovery, questions, outcomes all keep working — the
  suite's 1077 existing tests pin them.