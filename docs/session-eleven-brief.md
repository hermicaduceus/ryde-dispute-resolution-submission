# Session eleven brief — one step per screen (party intake swap-in-place)

**Ruling (the operator, 2026-09-27):** minimize scrolling on the party page. Today, clicking Continue
only SHOWS the next section and leaves the previous one on the page, so the form grows
downward. The fix: forward transitions swap the visible section (hide previous, show next)
and scroll to the top, exactly like the existing Back buttons and the outcome screen already
do. Each step is then a dedicated page under the fixed header. **No URL routing, no reloads,
no history entries — the in-page Back buttons remain the only navigation.**

## What must change (all in `ui/party/party.js`)

1. **`category-next` click handler** (`ui/party/party.js:134`): add `hide(stepCategory);`
   beside `show(stepTrip);`, and add `window.scrollTo(0, 0);`.
2. **`trip-next` click handler** (`ui/party/party.js:202`): add `hide(stepTrip);` beside
   `show(stepDetails);`, and add `window.scrollTo(0, 0);`.
3. The two Back handlers (`trip-back`, `details-back`) already swap correctly — do not
   change them. The category-card click handler (R3 reset, `party.js:111`) already hides both
   downstream steps — do not change it either. The outcome screen (`renderOutcome`) already
   scrolls to top — do not change it.
4. **Only these two handlers change.** No DOM/HTML changes, no copy changes, no CSS changes,
   no server changes. `index.html`, `party.css` and `app/` are out of scope.

## Why this is safe

- The three steps are already separate `<section class="step">` nodes (`index.html:22–60`),
  each with its own Back button where present. The swap pattern is the same one the Back
  handlers and `renderOutcome` use, so nothing new is being invented.
- Going back and forward again must not lose user input: `stepDetails` keeps the answers
  because `buildQuestions()` rebuilds from `QUESTIONNAIRES` on each entry and textareas are
  cleared only by the R3 reset path (which stays as-is). Note that going back from step 3
  re-runs `loadTrips()` and clears the trip selection — **keep that behavior unchanged**
  (out of scope for this pass).

## Acceptance (RED until you build it)

`python3 -m unittest tests.test_party_step_pages` — 8 tests, 4 RED right now. The test file
extracts each handler body with balanced-brace matching, so the assertions only pass when the
swap is in the right handler.

**Additionally:** the two byte-identical SHA pins on `party.js`
(`tests/test_party_rebrand.py:27` and `tests/test_w12_demo_notice.py:237`) WILL go red once
you touch the file. That is expected and correct — the pins exist to make you stop and
re-baseline consciously. When your change lands, update each SHA constant to the new digest
and note it in your commit message. Do NOT weaken or delete the pins.

## Guards you must not break

- Full suite must stay green apart from those two re-baselined SHAs:
  `python3 -m unittest discover -s tests` (392 tests before this change).
- The W13 label owner test (`tests/test_session_six_fixes.py::test_the_intake_labels_have_one_owner`)
  reads questionnaire labels out of `party.js` — you are not touching labels, so it stays green.
- The five-key party view contract is untouched (no server changes).

## Verification

After your change:
1. `python3 -m unittest discover -s tests` — expect 394+ OK, 0 FAIL.
2. Read your diff: exactly two handlers touched, two SHAs re-baselined, nothing else.
3. Do not run the browser verification; the planner lane does that.