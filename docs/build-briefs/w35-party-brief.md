# W35 lane P brief: party pages (status list region, step 3 summary, pending send, contrast)

Prepared against `main` `57758ce` (full suite 1433 OK, skipped=2). The acceptance contract is
`tests/test_w35_P.py` plus the three real-browser scripts `tests/browser/w35_P_filing.cjs`,
`tests/browser/w35_P_status.cjs` and `tests/browser/w35_P_contrast.cjs`, and the updated existing
tests listed under "Tests the planner prepares", to be committed by the planner before your
worktree is cut. Make the tests pass without editing any file under `tests/`. If a test looks
wrong, stop and report the test name and the reason.

## Protocol (obey it on every turn)

- Work only in this repository. No other worktrees, planning or scratch folders, no subagents, no
  network, no live model (the server's default mock only; never pass `--llm tencent`).
- Interpreter: `/usr/bin/python3` with `PYTHONPATH` removed (`env -u PYTHONPATH ...`).
- A server you start binds a port in 18000-18999, never 8000-8010, and you stop it before you finish.
- Never `rm -rf`, never `git add -A`, never merge, never push. Commit once at the end with an
  explicit `git add` of the files you changed.
- Never read or print `.env` or any key file.
- The two browser variables in the verify block point at a Puppeteer install and the Brave app
  outside this repository. They are read-only tool dependencies that the tests execute; do not
  open, list or modify anything there.

## Allowed files (this round)

- `ui/party/index.html`
- `ui/party/driver-filing.html`
- `ui/party/status.html`
- `ui/party/party.js`
- `ui/party/party.css`
- `ui/start/start.css`
- `ui/switch-bar.css`

Nothing else. In particular `ui/party/driver.html`, `ui/party/status.js`, `ui/party/driver.js`,
`ui/start/index.html` stay byte-identical (their freeze pins are still live), and `ui/index.html`,
`ui/app.js`, `ui/styles.css`, `app/`, `tools/`, `README.md` and `tests/` belong to others.

## Exact strings (copy verbatim)

| Where | String |
|---|---|
| step 3 summary label | `You are disputing` |
| Send button while pending | `Sending…` (one U+2026 ellipsis character, not three dots) |
| Send button at rest | `Send my dispute` |
| pending status line | `Sending your dispute. This can take a little while, so please keep this page open.` |
| new token | `--accent-strong: #CC2852;` |

## 1. Step 3 summary (P2+P3), `index.html` and `driver-filing.html`

In BOTH pages, make the first child of `<section class="step" id="step-details" hidden>` this
block, directly above the existing `<h2><span class="step-number">3</span> Tell us more</h2>`:

```html
        <div class="filing-summary">
          <p class="filing-summary-label">You are disputing</p>
          <p class="filing-summary-category" id="summary-category"></p>
          <div class="filing-summary-trip" id="summary-trip"></div>
        </div>
```

It is read-only: no button, link, `tabindex` or `role` anywhere inside it.

## 2. Pending-send markup, `index.html` and `driver-filing.html`

In BOTH pages, inside `<form id="details-form" novalidate>`, insert the status line between the
closing `</div>` of `.filing-fields` and `<div class="step-actions">`, and the spinner between
Back and Send, so the end of the form reads:

```html
          <p class="status-line sending-status" id="details-status" role="status" aria-live="polite"></p>
          <div class="step-actions">
            <button type="button" id="details-back">Back</button>
            <span class="sending-spinner" id="details-spinner" aria-hidden="true" hidden></span>
            <button type="submit" id="details-submit" class="primary">Send my dispute</button>
          </div>
```

## 3. `ui/party/party.js`

3a. After `var outcomeStatus = document.getElementById("outcome-status");` add:

```js
  var summaryCategory = document.getElementById("summary-category");
  var summaryTrip = document.getElementById("summary-trip");
  var detailsSubmit = document.getElementById("details-submit");
  var detailsBack = document.getElementById("details-back");
  var detailsSpinner = document.getElementById("details-spinner");
  var detailsStatus = document.getElementById("details-status");

  // W35: the pending state of "Send my dispute". Fixed text, built here.
  var SUBMIT_LABEL = "Send my dispute";
  var SENDING_LABEL = "Sending…";
  var SENDING_STATUS = "Sending your dispute. This can take a little while, so please keep this page open.";
  var sending = false;
```

3b. Extract the trip card's lines into one function, placed directly above `function loadTrips()`:

```js
  // The visible lines of a trip: route, date and kind, then the trip id and the
  // charge. W35: the step 2 card and the step 3 summary both render through here,
  // so the summary repeats exactly what the party picked.
  function tripLines(trip) {
    var meta = [trip.date, trip.kind_label].filter(Boolean).join(" · ");
    var charge = "";
    if (trip.fare_sgd !== null && trip.fare_sgd !== undefined) {
      charge = " · SGD " + Number(trip.fare_sgd).toFixed(2)
        + (trip.charge_label ? " " + trip.charge_label : "");
    }
    var detail = element("span", "trip-meta", "");
    detail.textContent = "Trip " + trip.trip_id + charge;
    return [
      element("strong", null, trip.label),
      element("span", "trip-meta", meta),
      detail
    ];
  }
```

and in `loadTrips`, build each card with it. The card loop's first lines become exactly:

```js
        state.trips.forEach(function (trip) {
          var card = element("button", "option-card trip-card");
          card.type = "button";
          tripLines(trip).forEach(function (line) { card.appendChild(line); });
          card.addEventListener("click", function () {
```

(delete the old `meta`/`lines`/`charge`/`detail` locals and the two `appendChild` lines they fed;
the card's DOM is unchanged: `strong`, `span.trip-meta`, `span.trip-meta`.)

3c. In the `trip-next` click handler, call `renderSummary();` directly before `show(stepDetails);`.

3d. Directly under the `// --------------------------------------------------------- step three`
comment, add:

```js
  // W35: a read-only summary of what is being filed, rebuilt every time the party
  // continues to this step, so a changed category or trip always shows.
  function renderSummary() {
    var category = CATEGORIES.filter(function (c) { return c.id === state.category; })[0];
    summaryCategory.textContent = category ? category.label : "";
    while (summaryTrip.firstChild) {
      summaryTrip.removeChild(summaryTrip.firstChild);
    }
    var trip = state.trips.filter(function (t) { return t.trip_id === state.tripId; })[0];
    if (trip) {
      tripLines(trip).forEach(function (line) { summaryTrip.appendChild(line); });
    }
  }

  function setSending(on) {
    sending = on;
    detailsSubmit.disabled = on;
    detailsBack.disabled = on;
    detailsSubmit.textContent = on ? SENDING_LABEL : SUBMIT_LABEL;
    detailsSpinner.hidden = !on;
    detailsStatus.textContent = on ? SENDING_STATUS : "";
  }
```

3e. In the `details-form` submit handler: the first statements after `event.preventDefault();` are

```js
    if (sending) {
      return;
    }
```

Replace the old local submit-button toggle and the whole request chain with this final code.
Keep it after all the existing validation, never before it:

```js
    setSending(true);
    request("POST", "/api/disputes", {
      category: state.category,
      filed_by: role,
      trip_id: state.tripId,
      description: description,
      claim_amount_sgd: amount,
      answers: answers
    })
      .then(function (view) {
        renderOutcome(view);
      })
      .catch(function (error) {
        setSending(false);
        showError("details-error", error.message);
      });
```

The success path is unchanged (`renderOutcome(view)`). No delay, no timer: the pending state lasts
exactly as long as the request.

## 4. `ui/party/party.css`

4a. Contrast (the operator ruling): add `--accent-strong: #CC2852;` to `:root` directly after `--accent`;
change `.party-header .eyebrow` `color`, `.step-number` `background`, and `button.primary`
`background` AND `border-color` from `var(--accent)` to `var(--accent-strong)`. Every other
`var(--accent)` (borders, outlines, focus rings, the selected-card border, hover borders) stays.

4b. Append at the end of the file:

```css
/* W35: step 3 opens with a read-only summary of what is being filed: the
   category from step 1 and the trip card from step 2, in the same words. It is
   not a control. */
.filing-summary {
  overflow-y: auto;
  margin: 0 0 0.5rem;
  padding: 0.4rem 0.75rem;
  font-size: 0.9rem;
  line-height: 1.35;
  background: var(--tint);
  border: 1px solid var(--line);
  border-radius: 14px;
}

.filing-summary p {
  margin: 0;
}

.filing-summary-label {
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--muted);
}

.filing-summary-category {
  font-weight: 600;
}

.filing-summary-trip strong {
  display: block;
}

/* Inside the one-screen frame the summary keeps its natural height while the
   fields scroll; on a short pane it gives up height first, keeping 10rem of the
   card for the heading, a strip of fields and the actions, so Send and Back
   never move below the fold. */
.filing-shell:has(#form-steps:not([hidden])) .filing-summary {
  flex: 0 0 auto;
  max-height: calc(100% - 10rem);
}

/* W35: while a dispute is being sent, a fixed status line sits between the
   fields and the actions, and a small spinner sits beside the button. The
   fields region overhangs by 0.5rem, so 1rem leaves a clear 0.5rem gap. */
.sending-status {
  flex: 0 0 auto;
  margin: 1rem 0 0;
}

.sending-status:empty {
  margin: 0;
}

.sending-spinner {
  display: inline-block;
  flex: 0 0 auto;
  align-self: center;
  width: 1.25rem;
  height: 1.25rem;
  border: 3px solid var(--line);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: sending-spin 0.8s linear infinite;
}

.sending-spinner[hidden] {
  display: none;
}

@keyframes sending-spin {
  to {
    transform: rotate(360deg);
  }
}

@media (prefers-reduced-motion: reduce) {
  .sending-spinner {
    animation: none;
  }
}
```

## 5. `ui/switch-bar.css`

5a. `.switch-bar a[aria-current]`: `background: #E93864;` becomes `background: #CC2852;`.

5b. Inside the existing `@media (max-height: 520px)` block, after the rule that hides the bar, add:

```css
  /* W35: the step 3 summary steps aside too, so the fields keep a usable strip
     above Send and Back. */
  .filing-shell .filing-summary {
    display: none;
  }
```

5c. Append at the end of the file (it lives here, not in `party.css`, because the party.css
source readers in the suite accept width media queries only):

```css
/* W35: the status page is one screen too, when the screen is tall enough. The
   header and the "Look up a reference number" box stay put; only the "My
   disputes" list scrolls, inside its own region, so scrolling the list never
   hides the lookup box. A lookup result takes the room above the list: the
   list gives up height down to 8rem and the header down to 4.5rem, and only
   then does the result scroll, inside the lookup box. Below 654px the page
   scrolls normally instead: there, on a 320px phone, the fixed header and
   lookup box would press the list to its 8rem floor and then clip the header. */
@media (min-height: 654px) {
  body:has(> .status-shell) {
    display: flex;
    flex-direction: column;
    height: 100vh;
    height: 100dvh;
    overflow: hidden;
  }

  body:has(> .status-shell) > .switch-bar {
    flex: none;
  }

  .status-shell {
    flex: 1 1 auto;
    min-height: 0;
    width: 100%;
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    padding: 0.5rem 1.25rem;
  }

  .status-shell > .party-header {
    flex: 0 1 auto;
    min-height: 4.5rem;
    overflow-y: auto;
  }

  .status-shell > .party-header h1 {
    font-size: 1.25rem;
    line-height: 1.2;
    margin: 0.25rem 0;
  }

  .status-shell > .party-header .eyebrow {
    font-size: 0.65rem;
    padding: 0.1rem 0.5rem;
  }

  .status-shell > .party-header .demo-note {
    margin: 0.25rem 0;
    padding: 0.2rem 0.6rem;
    font-size: 0.75rem;
  }

  .status-shell > .party-header .intro {
    font-size: 0.85rem;
    margin: 0;
  }

  .status-shell > .party-header > p:last-child {
    margin: 0.375rem 0 0;
  }

  .status-shell > .status-lookup,
  .status-shell > .status-list {
    margin: 0;
    padding: 0.75rem;
  }

  .status-shell > .status-lookup {
    flex: 0 1 auto;
    min-height: 0;
    display: flex;
    flex-direction: column;
  }

  .status-shell > .status-lookup > :not(#lookup-result) {
    flex: none;
  }

  .status-shell .step h2 {
    margin-bottom: 0.5rem;
  }

  .status-shell > .status-lookup .field {
    margin-bottom: 0.5rem;
  }

  .status-shell > .status-lookup .step-actions {
    margin-top: 0.5rem;
    padding-top: 0.5rem;
  }

  .status-shell > .status-lookup > #lookup-result {
    flex: 0 1 auto;
    min-height: 0;
    overflow-y: auto;
    overscroll-behavior: contain;
  }

  .status-shell > .status-lookup > #lookup-result > .step {
    margin: 0.5rem 0 0;
    padding: 0.75rem;
  }

  .status-shell > .status-list {
    flex: 1 1 0;
    min-height: 8rem;
    display: flex;
    flex-direction: column;
  }

  .status-shell > .status-list > h2 {
    flex: 0 0 auto;
  }

  .status-shell > .status-list > #account-list {
    flex: 1 1 auto;
    min-height: 0;
    overflow-y: auto;
    overscroll-behavior: contain;
    padding: 0.75rem;
    margin: -0.75rem;
  }
}
```

The final threshold is 654px, lowered from the parked draft's 740px after measurement.
At 320x739 a forced fixed frame still leaves a 176.31px list region, so 740px is not justified.
At 320x653 the natural fixed boxes leave 90.31px for the list, below its 90.39px content floor
inside the 128px section. At 320x654 there is 91.31px and the header is not clipped. Below
654px the page scrolls normally. The browser contract tests 653/654/655 at 320px and 1280px.
Screenshots and raw measurements are in `threshold/`; the planner's report explains the
measurement and its narrow-region trade-off. This is a height fallback, not a width snap.

## 6. `ui/party/status.html`

- `<main class="party-shell">` becomes `<main class="party-shell status-shell">`.
- The lookup section's `<section class="step">` becomes `<section class="step status-lookup">`.
- The list section's `<section class="step">` becomes `<section class="step status-list">`.
- `<div id="account-list"></div>` becomes
  `<div id="account-list" tabindex="0" role="region" aria-label="My disputes"></div>`.

## 7. `ui/start/start.css`

Add `--accent-strong: #CC2852;` to `:root` after `--accent`, and change `.start-header .eyebrow`
`color` and `.start-card .card-title` `color` from `var(--accent)` to `var(--accent-strong)`.
Borders stay `var(--accent)`.

## Tests the planner prepares (do not touch them)

`tests-updates.diff` releases the byte pins over the files this round edits and releases the
old exact token pins while keeping their shape assertions: `test_party_rebrand` (PARTY_JS_SHA test removed; the four W35 ids
released from the old no-new-id freeze; W35 requires their presence), `test_w12_demo_notice` and `test_w15_layout` (party.js digest tests
removed; old exact eyebrow text-token pin released; W35 requires `var(--accent-strong)`), `test_w15_feedback` (party.js FROZEN entry and
the PARTY_UNRELATED digest released; old exact fill-token pin released; W35 requires `var(--accent-strong)`), `test_w24_fix_round`
and `test_w34_launcher` (party.css/party.js FROZEN entries and three page digests released), and
`tests/browser/w15_actions.cjs` (corrected for the W30 scroll region; the app is unchanged by it).
`tests/test_w35_P.py` `W35Preservation` now pins every other declaration of `party.css`,
`switch-bar.css` and `start.css` against `57758ce`: add nothing beyond this brief.

## Expected sibling RED

The planner's shared builder baseline will also carry lane C's acceptance tests, `tests/test_w35_C.py`,
`tests/browser/w35_C.cjs` and `tests/browser/w35_C_replay.cjs`. They are deliberately failing in this baseline and are lane C's to
satisfy: do not run fixes against them and do not touch them. The colour ledger test
(`tests/test_session_sixteen.py` `test_colour_declarations_match_the_approved_ledger`, sheet
`ui/party/party.css`) is expected red until the planner re-baselines the ledger after both lanes
merge; do not edit `tests/fixtures/colour_ledger.json` and do not run `tools/colour_ledger.py --write`.

## Verify, then stop

The following is a verification command block, not application code to add.

```bash
export PUPPETEER_MODULE=[USER_HOME]/.hermes/cache/browser-verify/node_modules/puppeteer
export BROWSER_EXECUTABLE="/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"
env -u PYTHONPATH /usr/bin/python3 -m unittest tests.test_w35_P
env -u PYTHONPATH /usr/bin/python3 -m unittest tests.test_party_rebrand tests.test_w15_feedback tests.test_w15_layout tests.test_w30_filing_frame tests.test_w30_trip_scroll tests.test_w16_driver_filing tests.test_w20_back_state
env -u PYTHONPATH /usr/bin/python3 -m unittest discover -s tests -t .
git status --short
```

## What the suite shows, before and after

Both numbers below were measured by the planner on the shared baseline (both lanes' tests and test
updates installed, both browser variables set), not computed.

**At the start (RED):** Ran 1513 tests, FAILED (failures=149), zero errors. 1513 is 1433 at
`57758ce`, minus 6 freeze tests the two lanes release, plus 25 tests in `tests/test_w35_P.py` and 61
in `tests/test_w35_C.py`. Every failure is in `tests/test_w35_P.py` (47), `tests/test_w35_C.py` (74)
or the nine existing console modules the console lane's updates touch (28).

**When you are done (measured on the planner's reference for this lane, in the shared tree):** Ran
1513 tests, FAILED (failures=103), zero errors. The 103 are exactly the console lane's 102
deliberate failures plus one colour-ledger subtest, `sheet='ui/party/party.css'`. `tests.test_w35_P`
alone runs 25 tests, OK. Any other failure, or any error, means stop and report.

Before your commit, `git status --short` must list only files from the allowed list. Report the
commit hash and the test lines. The browser scripts are run by the parent; you do not need them.

## Stop and ask instead of guessing

- a test seems to contradict this brief;
- a change needs a file outside the allowed list;
- the full suite fails outside `tests/test_w35_P.py`, lane C's files and the colour-ledger subtest.
