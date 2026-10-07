# W31: narrow navigation consistency and queue open feedback

the operator approved 2026-10-06. This round explicitly runs HEADLESS CodeBuddy, no TUI/screenshot requirement. Genuine transcript remains evidence. Model deepseek-v4.1-flash, effort max, no bypass permissions. Do not commit, push or change settings.

## Authorized changes

1. ALL navigation anchors within `.party-shell`, including generated status/account links and outcome links, get the driver header's quiet outlined-pill style. Use `.party-shell a`, `.party-shell a:hover`, `.party-shell a:focus-visible` in shared party.css. Ink text, white card, line border, full pill, 44px minimum tap target, wrapping, soft tint/pink border hover and keyboard outline. Destinations, wording, HTML, party scripts, form layout and console navigation stay unchanged. Keep driver header flex-row wrapping and helper spacing.
2. Queue Open case: clicked button says `Opening…` and disables while pending. Other rows remain selectable. After SUCCESS render the real case, scroll to `#case-summary`, focus it with tabindex -1 and preventScroll, add `case-open-highlight` briefly then remove. Honour reduced motion: instant scroll/static transient outline is fine. No toast-only fix.
3. Exactly one current row, `Currently open` on its button, `aria-current=true` only there, `.queue-row.is-open`. Refresh retains the correct marker. Local JSON-file loads clear queue selection and invalidate pending opens.
4. Failures show `The case could not be opened.` inside the clicked row in a role=status/aria-live region `.queue-open-status`. Restore retryable button. Preserve existing fail-closed decision behaviour. Clear obsolete error on retry. Out-of-order older success/failure MUST NOT replace or hide the latest case. Use request-generation identity, not merely run ID. Pending A then B, and pending A then local file, are pinned.
5. Only allowed console style additions: `.queue-row.is-open`, `.queue-open-status`, `.queue-open-status:empty`, `#case-summary.case-open-highlight`. Neutral status-free selection highlight consistent with console tokens. No animation/keyframes required, no layout redesign. Empty row-status must not consume space. Highlight is static and temporary, not a fake success colour. Do not alter money/human-decision logic.

## Files / test carve-outs

Application allowlist: `ui/app.js`, `ui/styles.css`, `ui/party/party.css` ONLY. No HTML/backend/party JS edits. Source constants frozen elsewhere remain unchanged.
Acceptance: `python3 -m unittest discover -s tests -p test_w31_navigation_queue.py -v` (12). the planner authored RED-first: 11 intentional assertion failures, 1 existing behaviour passing; disposable reference satisfies all 12.
Full suite: `python3 -m unittest discover -s tests -t .`. Always use `-t .` for package-relative imports. Focused W31 may use `python3 -m unittest tests.test_w31_navigation_queue -v`.
SOLE test edits allowed to builder: rebaseline APP_JS_SHA in `tests/test_console_rebrand.py` and only the `ui/app.js` value in FROZEN in `tests/test_w15_feedback.py`; regenerate `tests/fixtures/colour_ledger.json` with `python3 tools/colour_ledger.py --write`, then verify the delta contains ONLY authorized party-navigation selector changes and the new queue-feedback scopes. New W31 tests are immutable. the planner has already amended the W15 source-cascade profile/digest exclusions ONLY for the explicit scopes above. Do not broaden exclusions/rebaseline unrelated CSS digests or touch any other frozen bytes. If an older fake DOM lacks focus/scroll/clearTimeout, feature-check those optional methods, not production semantics. Do not impose new runtime dependencies.

## Finish

Run focused + full suite. Report exact diff/files, failures, session id. Do NOT commit anything. Headless authorization is scoped edit/read/test tools, not permission bypass; stop on a denied indispensable tool. Parent verifies actual browser geometry/keyboard/error/race paths and mutation-red proof independently, then cross-family review.
