# W30 compact shared filing frame

the operator approved restoring the page context hidden by the fixed trip card and moving the demo explanations to bottom fine print. Apply the same frame across all three rider/driver filing steps. Parent's disposable reference has passed the suite and real-browser checks and is deleted; derive your own implementation from this contract.

## Scope and tools
- Edit ONLY `ui/party/party.css`, `ui/party/index.html`, `ui/party/driver-filing.html`.
- No JS, tests, tools, app, data, docs or settings edits. No commits/pushes. Parent owns all test executions, HTML digest and colour ledger rebaselines.
- Read/Edit/Glob/Grep only. You have no shell; do not seek one. No external reference reads.
- This approval supersedes the earlier HTML freeze and fixed-trip-card layout, not the trip request ownership or code.

## Contract
- Add `filing-shell` to both existing main elements. Preserve every existing id, href, script, form control, required marker and role-specific field. No new ids. Keep header title/intro/eyebrow/navigation in place and unmodified; remove demo-note paragraphs from header and put the exact paragraphs in a `footer.filing-fine-print` after the outcome section. Give footer `aria-label="About this demo"` and `tabindex="0"` for keyboard scrolling.
- Driver reference-saving hint: remove the header copy only, keep receipt copy verbatim. Do not modify outcome behaviour or the notice attached to mock rulings.
- Category: wrap category-options/error in `div.filing-fields`; actions stay outside it. Details: wrap fields, question-list, claim/error in `div.filing-fields` INSIDE details-form, with actions OUTSIDE that wrapper but INSIDE the form. Trip keeps its existing direct children/list.
- Remove fixed positioning/viewport dimensions from `#step-trip:not([hidden])`, retain display:flex/flex-direction:column/min-height:0. Delete old `body:has(#step-trip:not([hidden]))` scroll lock. Keep all other pre-frame CSS unchanged, including trip natural sizing, fade, hover padding and landing margin. Update obsolete comments describing fixed overlay.
- Exact authorized selector set and source contracts: `tests/test_w30_filing_frame.py` SELECTORS/expected, plus `tests/test_w30_trip_scroll.py`. No unlisted new selectors. Do not change tests if you disagree; stop and report.
- `.filing-shell:has(#form-steps:not([hidden]))`: height 100vh fallback then 100dvh; flex column, padding 0.5rem 1.25rem, gap 0.5rem. Body scoped to visible filing form has overflow:hidden. Receipt restores normal page scrolling.
- Frame header: flex 0 0 auto; max-height `max(5rem, min(45%, calc(100% - 15rem)))`; overflow-y:auto. h1 font-size 1.25rem, line-height 1.2, margin 0.25rem 0. Eyebrow font-size 0.65rem/padding 0.1rem 0.5rem. Intro 0.85rem/margin 0. Nav margin 0.375rem 0 0; existing wrapped links remain >=44px.
- Frame form-steps, visible step and details-form: flex 1 1 auto, min-height:0, display:flex, flex-direction:column. Visible step margin:0/padding:0.75rem. Scoped step h2 margin-bottom:0.5rem; trip hint margin:0 0 0.5rem.
- Frame actions: flex 0 0 auto; margin-top:1rem; padding-top:0.5rem. Action buttons: font-size:0.9rem, padding:0.5rem 1rem, min-height:44px. Remain normal flow, never overlay controls.
- Filing-fields: flex 1 1 auto/min-height:0/overflow-y:auto/overscroll-behavior:contain; padding:0.5rem/margin:-0.5rem for focus/hover clearance.
- Footer: flex 0 0 auto/max-height:12%/overflow-y:auto/font-size:0.75rem/color:var(--muted). Footer p margin 0 0 0.25rem, padding 0, border 0, background none, font-size inherit. Readable plain fine print, not big tinted callouts. On extremely short panes header/footer scroll internally, all links/copy must remain keyboard reachable.
- Current trip error: scoped `#step-trip:has(#trip-error:not([hidden])) > .hint` and `#step-trip:has(#trip-error:not([hidden])) #trip-options` display:none (list is empty and hint is inapplicable); its `> .step-actions` margin-top:auto keeps error-state actions at the bottom. Successful retry restores list/hint via existing JS hidden flag, unchanged.

## Verified target
Parent runs the suite and browser contracts. Target: full suite green, frame 16 views/320 checks across three steps and five live height changes, trip 18 views/180 stages, loading/empty/error 12 cases/60 checks. User visual review follows, not a commit.
