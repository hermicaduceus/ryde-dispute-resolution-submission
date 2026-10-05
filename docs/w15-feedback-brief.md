# W15 follow-up: the operator's narrow UI review feedback

the operator has finished reviewing the current W15 layout. Make only these three CSS changes. Existing uncommitted W15 party CSS and colour ledger are intentional and must be preserved. This follow-up explicitly authorizes the console spacing addition that the original docs/w15-brief.md prohibited. All its other scope limits stand.

## Allowed writes

- ui/party/party.css: only the driver amount-helper clearance and driver header navigation rules below.
- ui/styles.css: only top-level card vertical rhythm below.
- tests/fixtures/colour_ledger.json: regenerate with /usr/bin/python3 tools/colour_ledger.py --write.
- NOTHING ELSE. Do not modify HTML, JS, copy, fonts, app/, data/, tools/, tests/ source or docs. Do not rebaseline frozen hashes. If a test appears wrong, stop and ask.
- Do not commit, stash, reset, push or change branches. The existing W15 implementation and these follow-ups remain uncommitted until verification and review.

## 1. Driver amount helper

The paragraph after #claim-amount inherits .hint's negative top margin and touches the input. Add driver-only clearance using the existing selector:

#form-steps[data-filed-by="driver"] #claim-amount + .hint

Only margin-top changes, at least 0.5rem. Preserve the helper's words and all shared .hint heading rules, rider filing, status and driver account styles.

## 2. Console top-level card gaps

the operator marked Review queue to Overrides as too close and asked for the same gap as Overrides to Load a case file and all lower cards. Use the existing .loader-panel 28px top margin as the rhythm, not a new visual design.

- Final margin-top for #queue-panel, #overrides-panel, .loader-panel and #case-workspace: 28px.
- Remove or correct the later #overrides-panel zero-margin reset.
- #case-workspace remains a grid with 28px vertical gap between its .story-section cards.
- Bottom and horizontal margins stay zero. No inner layouts, padding, colors, borders, typography, breakpoints or behavior changes. No party layout tokens in the console.

## 3. Driver header secondary navigation

Replace the blue underlined appearance of the three existing driver-header anchors with quiet outlined pills. Keep their anchor semantics, hrefs and wording. Do not turn them into solid pink primary buttons or change any HTML. Continue and Send my dispute retain their existing filled-pink treatment.

Scope only to the existing driver filing header using:

.party-header:has(+ #form-steps[data-filed-by="driver"]) > p:last-child

Use the row selector above and its descendant anchors, hover and focus-visible selectors.

- Row is a wrapping flex row, gap at least 0.5rem, align items comfortably. Do not hide or manipulate the text separators with font-size, content or visibility hacks.
- Anchors: card/white background, var(--line) solid border at least 1px, var(--ink) text, no underline, pill radius at least 24px, vertical padding at least 0.5rem, horizontal padding at least 1rem, min-height at least 44px, max-width 100%, wrapping text and overflow-wrap anywhere or break-word. Do not disable shrinking.
- Hover and keyboard focus: var(--accent) border and var(--tint) background, ink text. Retain visible keyboard focus, adding an outline if needed.
- No global a style and no effect on rider, status, driver-account or outcome links.

## Acceptance and verification

the planner added tests/test_w15_feedback.py before your build. On the genuine current W15 snapshot it runs 12 methods with 12 assertion failures across seven methods, zero errors. The failures identify the requested defects; preservation checks already pass. It was proven satisfiable in a disposable reference with a green 1,103-test suite and 33 unique assertion-killed mutations. No reference implementation is provided.

Run:

- /usr/bin/python3 -B -m unittest tests.test_w15_feedback tests.test_w15_layout -q
- /usr/bin/python3 tools/colour_ledger.py --write
- /usr/bin/python3 -B -m unittest discover -s tests -t . -q
- git diff --check

Expected full suite: 1,103 tests OK. All HTML and JS stay byte-identical. The new tests enforce named selectors and freeze unrelated CSS, including inner-console layouts. They are source contracts, not rendered geometry proof. the planner will independently check real desktop and narrow-width rendering, amount clearance, link wrapping, hover, keyboard focus and filing, then run cross-family review.

Read the brief and relevant files, report a short plan, and wait for approval before edits. At completion report exact modified files and actual test results. Do not commit.
