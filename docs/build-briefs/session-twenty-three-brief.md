# Session twenty-three brief (W23, part B2): the review queue, the decision form, and Overrides

Rulings by the operator on 2026-10-01 and 2026-10-03. Session twenty-two built the server half of the human
decision: `app/human_review.py`, `POST /api/review/<run_id>/decision`, `GET /api/review/queue` and
`GET /api/review/overrides`. Nothing in the operator console calls them yet: the console only renders a case
file the operator picks from disk. This session builds the console screens on top of those endpoints, plus two
small read-only endpoints the screens need.

**Target:** the new test files go from RED to green, and the full suite
(`/usr/bin/python3 -m unittest discover -s tests -t .`) is green when you are done. The new tests drive
`ui/app.js` in Node, so `node` must be on your PATH.

**Do not edit anything under `tests/`, `tools/` or `data/`, with the exceptions below.** If a test looks wrong,
stop and ask.

**The test edits you must make (and no others):**
- `tests/test_console_rebrand.py`: set `APP_JS_SHA = "..."` to the SHA-256 of your final `ui/app.js`
  (`shasum -a 256 ui/app.js`). Change nothing else in that file.
- `tests/fixtures/colour_ledger.json`: re-baseline it once, at the end, with
  `/usr/bin/python3 tools/colour_ledger.py --write`, and list every added ledger line in your final report.
  Every colour you add must follow the colour rule below.

**Principle carried from every earlier session: rules live in code, never in the page.** The decision checks
are Python (`app/human_review.py`, already built, do not change it). The console is a client: it shows what the
server returns, sends what the operator typed, and displays the server's refusal text. It never re-implements a
decision rule, never computes the final amount of an approve, and never re-sorts the queue.

## 1. `app/server.py`: two read-only operator endpoints

Both are GET, JSON, `Cache-Control: no-store`, and resolve the run with the existing `_resolve_run_dir` (same
run-id rules as the decision endpoint: direct children of the output directory only, never a path outside it).

1. `GET /api/review/<run_id>/case` -> 200 `{"case_file": <the parsed case_file.json object>, "human_decision":
   <load_decision(run_dir) or null>}`. Exactly those two keys. Unknown run, or a `case_file.json` that is
   missing, unreadable or not a JSON object -> 404 `{"error": "unknown run"}`. Works on any run (party-filed or
   command-line, any outcome).
2. `GET /api/review/<run_id>/payloads/<name>` -> 200 with the parsed JSON value of
   `<run_dir>/payloads/<name>`. `<name>` must fully match `^[0-9]{4}-[A-Za-z0-9._-]+\.json$` and resolve to a
   file inside `<run_dir>/payloads`; anything else (bad name, `..`, missing file, unparseable JSON) -> 404
   `{"error": "unknown payload"}`. Unknown run -> 404 `{"error": "unknown run"}`.

No party endpoint changes. No party page may call `/api/review/` (a test checks every file under `ui/party/`).

## 2. `ui/index.html`: three new regions

Keep every existing id. Add exactly these ids (the console id test now lists them):

- Before the loader panel, `<section id="queue-panel" aria-labelledby="queue-title">` holding an `h2#queue-title`
  with the text `Review queue`, a `button#queue-refresh` (`type="button"`, text `Refresh`), a
  `p#queue-status` (`role="status"`, `aria-live="polite"`) and a `div#queue-content`.
- After the queue panel, `<section id="overrides-panel" aria-labelledby="overrides-title">` holding an
  `h2#overrides-title` with the text `Overrides`, a `p#overrides-status` (`role="status"`) and a
  `div#overrides-content`.
- Inside `#case-workspace`, directly after `#resolution-section` and before `#events-section`:
  `<section id="decision-section" class="story-section" aria-labelledby="decision-title" hidden>` with a
  section heading (index `05`, eyebrow `HUMAN DECISION`, `h2#decision-title` text `Decide this case`) and a
  `div#decision-content`. The events section's index becomes `06`.

The decision form itself is built by `app.js` inside `#decision-content` (section 4), so its ids are not in the
HTML.

## 3. `ui/app.js`: the queue and Overrides

On page load the console fetches `GET /api/review/queue` and `GET /api/review/overrides` once each. The
`Refresh` button fetches both again. If a fetch rejects or answers non-200 (the console opened as a file, or the
server down), `#queue-status` reads exactly
`The review queue is not available. Open the console from the running server to use it.` and the file picker
keeps working as before. Overrides fails the same way, silently: `#overrides-status` reads
`Overrides are not available.`

**Queue** (`#queue-content`): an `ol.queue-list` with one `li.queue-row` per case, **in the order the server
sent** (the server sorts safety first, then amount, then waiting time; the page never re-sorts). Each row holds,
as separate elements with these classes:
- `.queue-category`: `Route deviation` for `route_deviation`, `No-show charge` for `no_show_charge`,
  `Other` for anything else.
- `.queue-safety` with the text `Safety`, present **only** when `safety` is true.
- `.queue-amount`: `SGD 55.16 proposed` (amount_source `proposed`), `SGD 30.00 claimed` (`claimed`),
  `No amount on record` (amount null). Two decimals always.
- `.queue-held`: `Held by: ` plus the `held_by` entries joined with `, `; the entry `model_failure` reads
  `model failure`; an empty list reads `Held by: not recorded`.
- `.queue-waiting`: `Waiting ` plus the formatted wait, from `waiting_seconds` (floored):
  under 60 -> `under a minute`; under 3600 -> `<m> min`; under 86400 -> `<h> h <m> min`; otherwise
  `<d> d <h> h`. Examples: 59 -> `Waiting under a minute`, 125 -> `Waiting 2 min`, 7500 -> `Waiting 2 h 5 min`,
  90061 -> `Waiting 1 d 1 h`.
- `button.queue-open` (`type="button"`) with the text `Open case`.

An empty queue: `#queue-status` reads `No cases are waiting for a human decision.` and the list is empty. A
non-empty queue: `#queue-status` reads `<n> cases waiting.` (`1 case waiting.` for one).

**Opening a case.** `Open case` fetches `GET /api/review/<encodeURIComponent(run_id)>/case` and renders the
returned `case_file` through the existing `renderCase` path (the loaded-file line shows the run id). The console
remembers the open run id, the queue entry the row came from, and the returned `human_decision`. A failed fetch
sets `#load-status` to `The case could not be opened.` with state `error`. Loading a file through the picker
afterwards clears the remembered run (a picked file is never decidable from the console).

**Payloads of a server-opened case.** When the open case came from the server, expanding an event fetches its
payload from `/api/review/<encodeURIComponent(run_id)>/` followed by the event's `payload_ref` (already
validated by `normalizedPayloadRef`, e.g. `payloads/0009-judge-ruling-withheld.json`), instead of asking for the run
directory. A non-200 answer shows the existing `The payload could not be read.` text. A picked file keeps the
existing attach-the-directory behaviour.

**Overrides** (`#overrides-content`): a `p.overrides-approved` reading exactly `Approved as proposed: <n>`
(from `approved_count`); then one `article.override-group` per group in the order sent, each with an `h3` reading
exactly `<category label> · <held> · <decision> to <action> · <count> case(s)` where `<held>` is the held_by
entries joined with `, ` (`model failure` for `model_failure`, `not recorded` for empty), and `case(s)` is
`case` for 1 and `cases` otherwise. Example: `Route deviation · ESC-4 · change to refund · 2 cases`. Under it, one
`li.override-entry` per decision showing its dispute id (or run id when the dispute id is empty), reviewer,
`SGD <amount>` to two decimals, the AI's proposal (`AI proposed SGD 55.16`, or `No AI proposal` when `proposed`
is null), and the reason. No groups: `#overrides-status` reads `No changed or rejected decisions yet.`
(The reviewer's name and reason are operator data; they appear here and nowhere a party can reach.)

## 4. `ui/app.js`: the decision form and the confirm screen

`#decision-section` is shown only when the open case came from the server **and** its resolution outcome is
`withheld`. Otherwise it stays hidden.

**A case that already has a human decision** (the `/case` answer carried one): no form. `#decision-content`
shows an `article.human-decision-record` with the decision, reviewer, reason, action, `SGD <amount>` and
`decided_at`, under the heading `Human decision recorded`.

**Otherwise, the form** (`form#decision-form`), every element built with `textContent`, never `innerHTML`:
- Three radio inputs, `name="decision"`, ids `decision-approve`, `decision-change`, `decision-reject`, values
  `approve`, `change`, `reject`, each with a `<label for>` reading `Approve the AI's proposal`,
  `Change the decision`, `Reject: no action`. None is pre-selected.
- When the queue entry's `can_approve` is false (no AI proposal, e.g. a model-failure case), `decision-approve`
  is `disabled` and a `p.decision-note` reads exactly `No AI proposal to approve; use Change.`
- `input#decision-reviewer` (text, `maxlength="80"`) with a label `Your name`.
- `textarea#decision-reason` (`maxlength="1000"`) with a label `Reason (staff only, never shown to the party)`.
- `select#decision-action` with options `refund`, `compensation`, `no action` (value = text), and
  `input#decision-amount` (`type="number"`, `step="0.01"`, `min="0"`), labelled `Action` and `Amount (SGD)`.
  Both are `disabled` unless `Change` is selected.
- `button#decision-review` (`type="submit"`) with the text `Review decision`.
- `p#decision-error` (`role="alert"`), empty until the server refuses something.

**Review decision does NOT send anything.** Submitting the form (with a decision selected) hides the form and
shows `div#decision-confirm`, which restates the decision as these exact lines, each its own `p`:
1. `Decision: Approve` / `Decision: Change` / `Decision: Reject`
2. `Amount: <action> of SGD <x.xx>` or `Amount: no action`, where the amount is:
   approve -> the queue entry's `proposed` action and amount; change -> the typed action and the typed amount
   rounded to two decimals; reject -> `no action`.
   A change whose typed amount is not a finite number reads `Amount: <action>, amount not a number`.
3. `Trip fare charged: SGD <x.xx>` from the open case file's `evidence_pack.fare.charged_sgd` when it is a
   finite number, else exactly `Trip fare charged: not on record`.
4. `AI proposed: <action> of SGD <x.xx>` (or `AI proposed: no action`) from the queue entry's `proposed`,
   else exactly `AI proposed: no proposal on record`.
5. Only when the restated amount and the fare are both finite numbers and the amount is greater than the fare:
   `p.confirm-warning` reading exactly `This amount is more than the trip fare.`

Then two buttons: `button#decision-confirm-send` (`type="button"`, text `Confirm and send`) and
`button#decision-confirm-back` (`type="button"`, text `Go back and edit`). Back hides the confirm screen and
shows the form again with every typed value kept. Submitting with no decision selected shows
`Choose approve, change or reject.` in `#decision-error` and opens no confirm screen.

**Confirm and send** is the only thing that POSTs. It disables itself while the request is in flight (a second
click sends nothing) and POSTs to `/api/review/<encodeURIComponent(run_id)>/decision` with a JSON body of
exactly:
- approve or reject: `{"decision", "reviewer", "reason"}` (never `action` or `amount_sgd`; the server refuses
  them);
- change: `{"decision", "reviewer", "reason", "action", "amount_sgd"}`, with `amount_sgd` the typed value as a
  JSON number (`Number(value)`), not rounded by the page.

Reviewer and reason are sent as typed; the server strips them.

- **200:** the form and confirm screen go away; `#decision-content` shows a `div.decision-result` with a `p`
  reading exactly `Decision recorded. The party now sees:` followed by a `blockquote` holding the returned
  `party_view.message` (textContent). Then the queue and Overrides are fetched again.
- **Any non-200:** the confirm screen hides, the form shows again with the typed values kept, and
  `#decision-error` shows the server's `error` text exactly (e.g. `this case already has a human decision`). A
  body without an `error` string shows `The decision could not be recorded.`

## 5. `ui/styles.css`: the colour rule

Colour means status only (operator ruling 2026-09-27). Use existing tokens only (`var(--...)`), no new hex
values. Chrome may take the accent as the existing sections do. Status colour only where it is a status:
`.queue-safety` and `.confirm-warning` amber, `#decision-error` red, `.decision-result` green. Everything else
neutral (`--ink`, `--muted`, `--line`, `--panel`, `--canvas`).

## 6. Docs

`docs/architecture.md`, in the existing `## Human decision` section: a paragraph on the console review queue, the
decision form with its confirm screen, and the Overrides view, naming the two new paths
`/api/review/<run_id>/case` and `/api/review/<run_id>/payloads/<name>`.

## Fixed strings the tests pin exactly

Every quoted string in sections 2-4, including: `Review queue`, `Refresh`, `Overrides`, `Decide this case`,
`HUMAN DECISION`, `The review queue is not available. Open the console from the running server to use it.`,
`Overrides are not available.`, `No cases are waiting for a human decision.`, `<n> cases waiting.` /
`1 case waiting.`, `Open case`, `Held by: `, `model failure`, `not recorded`, `No amount on record`,
`The case could not be opened.`, `Approved as proposed: <n>`, `No changed or rejected decisions yet.`,
`Human decision recorded`, the three radio labels, `No AI proposal to approve; use Change.`, `Your name`,
`Reason (staff only, never shown to the party)`, `Review decision`, the five confirm lines,
`This amount is more than the trip fare.`, `Confirm and send`, `Go back and edit`,
`Choose approve, change or reject.`, `Decision recorded. The party now sees:`,
`The decision could not be recorded.`, `unknown run`, `unknown payload`.

## Allowed files

Edited: `app/server.py`, `ui/index.html`, `ui/app.js`, `ui/styles.css`, `docs/architecture.md`, plus the
`APP_JS_SHA` value and the colour ledger re-baseline named above. Nothing else. Do not touch
`app/human_review.py`, `app/agents/`, `app/evidence/`, `app/eval.py`, `app/pipeline.py`, `app/schemas.py`,
`docs/policy.md`, or anything under `ui/party/`.

## Constraints

Standard library only. Python 3.9: no `match`, no `X | Y` unions. The console stays plain HTML/JS with no
build step and no library. `textContent` only: no `innerHTML`, `outerHTML`, `insertAdjacentHTML` or
`document.write` anywhere in `app.js`. Run the suite with `/usr/bin/python3`, never a bare `python3`. Commit in
small commits when the suite is green. Do not run the live model.

## What you should see when you are done

- Full suite green.
- `/usr/bin/python3 -m app.eval --llm mock` on both packs: unchanged (organiser 11 of 18 matching, 11 of 18
  decided without a human, 0 round-one stops; synth 10 of 17, 10 of 17, 0). This session must not move any eval
  number. If one moves, stop and report it.
- On the mock server: file trip `T-RD0109` with a claim of 55.16 on the party page. The console's queue shows it
  (`Route deviation`, `SGD 55.16 proposed`, `Held by: ESC-4`). `Open case` renders it with the decision form
  under the Resolution section. Choose Change, refund, 45, review: the confirm screen reads
  `Amount: refund of SGD 45.00`, `Trip fare charged: SGD 112.56`, `AI proposed: refund of SGD 55.16`, no warning.
  Confirm and send: `Decision recorded. The party now sees:` and
  `Decision: refund of SGD 45.00. A member of our team reviewed your case.` The queue no longer lists it, and
  Overrides shows `Route deviation · ESC-4 · change to refund · 1 case`.

## Out of scope

The decision rules (built), the party pages, the Judge, every gate, the evidence layer, the eval harness, the
policy, the data packs. Any change to what the AI decides. Authentication on the operator endpoints (the hosted
demo's password is a later item).
