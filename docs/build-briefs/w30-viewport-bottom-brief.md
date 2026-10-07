# W30 follow-up: viewport-bottom trip actions

the operator approved 2026-10-06 after live preview: Back/Continue must stay at the bottom of the visible screen on rider AND driver filing pages, including when the window becomes shorter/taller. The list shrinks and scrolls above them. Supersedes the two-trip minimum and short-screen page-scroll fallback. Step 2 only. the operator explicitly waived another GLM review. No commit or push.

## Your scope

Edit **only `ui/party/party.css`**. Do not edit JS, HTML, tests, docs, app, data, other stylesheets or settings. The request epochs/error/retry repairs must remain byte-identical. No shell: you have Read/Edit/Glob/Grep only. Parent owns all tests, generated ledger checks and browser verification.

## Implement

- Replace the W30 `#step-trip:not([hidden])` max-height/floor layout with a viewport-anchored flex-column card. Position fixed, top 1.5rem, left/right 1.25rem, max-width 680px, margin 0 auto, min-height 0, z-index 2. Height `calc(100vh - 3rem)` followed by `calc(100dvh - 3rem)`. Remove the old max-height/floor. The card fills the screen height minus the existing breathing room at top/bottom, independently of the long driver header and page scroll.
- Keep Back/Continue in NORMAL FLOW inside that fixed card, outside the list. Do not fix/stick the buttons over the options. Add one grouped rule for `#step-trip > h2`, `#step-trip > .hint`, `#step-trip > .error`, `#step-trip > .step-actions`, with `flex: 0 0 auto`. Only the list shrinks.
- Add `body:has(#step-trip:not([hidden])) { overflow: hidden; }`. Page scrolling unlocks automatically when Back/Continue leaves step 2; other pages/steps must retain their original scrolling.
- Preserve list `flex: 1 1 auto; min-height: 0; overflow-y: auto; overscroll-behavior: contain`, padding/negative margins and two-layer scroll-aware fade. Add `align-content: start; grid-auto-rows: max-content` so cards keep their natural height rather than stretching/compressing with the viewport.
- Update only the W30 CSS comments to describe the current rule, removing claims about a two-trip floor/page scrolling. All earlier CSS remains byte-identical.

## Parent acceptance

Updated `tests/test_w30_trip_scroll.py` and `tests/browser/w30_trip_scroll.cjs` are RED on the current implementation. Browser now checks every viewport, including 800x320 and narrow 360x320 during live resize, without a page-scroll rescue; each loaded page resizes through 320/480/700/900px and back. Buttons must remain on screen near the bottom, list above the bar, keyboard path intact, fade conditional, hover unclipped. Loading/empty/error are checked separately. JS and all HTML frozen. Return a short summary and actual files edited; do not claim you ran tests.
