# W30: the trip step is a viewport-fit card with its own scroll region

the operator rulings, 2026-10-06. Build lane: headless CodeBuddy, `deepseek-v4.1-flash`, effort max. The parent runs every test, hash re-baseline and browser check; you have Read/Edit/Glob/Grep only, so do not look for a shell.

## Allowed files (exactly two)

- `ui/party/party.css`
- `ui/party/party.js`

Do not edit HTML, `ui/styles.css`, `ui/app.js`, `tests/`, `tools/`, `data/`, `app/`, or docs. The HTML is frozen: use the ids the pages already carry. If a test looks wrong, stop and say so.

## Problem

On the rider page (`ui/party/index.html`) and the driver filing page (`ui/party/driver-filing.html`, same `party.css` and `party.js`), step 2 ("Which trip?") lists 8 to 9 trips. The list is 860 to 1210 px tall and the Continue/Back bar sits 1260 to 2150 px down the page, below the fold at every width from 360 to 1200. The rider page also jumps to the page top when step 2 opens, which hides the buttons on a phone.

## The four rulings

1. **Own scroll region.** The trip list (`#trip-options`) scrolls inside itself. The Continue/Back bar (`.step-actions`) stays in normal flow directly under it, outside the scrolling region, never over an option. The W15 rule (`position: static`, no sticky/fixed bar) holds. Step 3 and the category step are untouched.
2. **Viewport-fit card.** The whole trip card (heading, hint, list, bar) never exceeds the viewport height, with a floor: when the screen is too short, the list keeps room for about two trip cards and the page scrolls instead of the list collapsing. A trip card is 99 to 143 px tall.
3. **Landing.** Opening the trip step brings the whole card on screen, buttons included, on both pages, once the list has rendered (not while "Loading trips…" is showing). The old `window.scrollTo(0, 0)` on category Continue goes. Returning to the category step with Back also brings that card on screen. Coming back from step 3 re-renders the list, so the trip card lands again by the same path.
4. **Fade hint.** A soft bottom fade shows while more trips are below and disappears once the list is scrolled to its end. Pure CSS, colour tokens only (`var(--card)`, `var(--line)`; no hex, no `rgb()`). A next-card peek is not guaranteed and not required.

A lifted (hover) or selected card must not be clipped at the region edge.

## Contract the tests read

CSS, exact selectors (the W15 preservation test excludes exactly these four selectors and nothing else, so add no other rule and no other selector):

| Selector | Must declare |
|---|---|
| `#step-trip:not([hidden])` | `display: flex`; `flex-direction: column`; a `max-height` using `100vh` first (fallback), then a second `max-height` of the form `max(calc(100dvh - Nrem), Mrem)` (viewport minus a gap, never below a floor) |
| `#step-trip #trip-options` | `flex: 1 1 auto`; `min-height: 0`; `overflow-y: auto`; `overscroll-behavior: contain`; `padding` and an equal negative `margin` on top and bottom of at least `0.5rem` so hover lift and the selected border are not clipped; a two-layer `background` of `linear-gradient`s: a card-coloured cover with `local` attachment and the fade with `scroll` attachment, both bottom-aligned |
| `#step-category, #step-trip` (one rule) | `scroll-margin` with a vertical value of at least `1rem` (two values, `V 0`), so a landed card never sits flush with the screen edge |

JS (`party.js`):

- One small function that lands the trip card with `stepTrip.scrollIntoView({ block: "start" })`. The card is at most one screen tall, so aligning its top shows the bar too; on a very short screen the top stays visible.
- Call it after the trip list has rendered, in both the "has trips" and the "no trips" branch of `loadTrips`. Do not call it from the failure path.
- It must do nothing while `#step-trip` is hidden: a slow response that arrives after the party pressed Back must not move the page.
- Remove `window.scrollTo(0, 0)` from the category Continue handler. Leave the trip Continue handler's `window.scrollTo(0, 0)` (step 3) as it is.
- In the trip Back handler, after the existing `show(stepCategory)` / `hide(stepTrip)`, land the category card with `stepCategory.scrollIntoView({ block: "start" })`.
- Keep the file's style: `var`, `function`, double quotes, two-space indent, comments in the existing voice. Add a short comment on the new function.

## What the parent will run, and what it should show

- `tests/test_w30_trip_scroll.py`: 18 tests, all red before your edit, all green after. They read your CSS by exact selector with comments stripped, and drive your `party.js` in a fake DOM that records each `scrollIntoView`/`scrollTo` with the visible-step vector and how many trip cards were rendered at that moment.
- `tests/browser/w30_trip_scroll.cjs`: real Brave, both pages, nine viewports from 360×740 to 800×320. For a tall screen (height 600 or more) the whole card including both buttons must be on screen with at least 16 px above and below; for a short one the card top stays on screen and the list keeps two trip cards. Reference numbers at 390×844 on the driver page: card 24 to 820, list height 625, bar 730 to 795, list `scrollHeight` 1190.
- Expected, by design, to go red on your edit and be re-baselined by the parent: the four `party.js` SHA-256 freezes, the W15 unrelated-CSS digest and the colour ledger. Do not try to fix them.

## Finish

Read both files back and report the exact diff in prose: which selectors you added and which functions or handlers you touched. No commit, no push, no settings changes.
