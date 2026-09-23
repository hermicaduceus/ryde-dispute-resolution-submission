# Build session six, fix round — brief

**Status at handoff: 2026-09-23.** Suite 295 tests. **Every failure is in
`tests/test_session_six_fixes.py`** (the acceptance target, written RED-first), plus one
deliberately updated pin, `tests/test_contracts.py::test_the_party_message_states_the_action_and_amount`,
which now expects the new signature. Done = **the whole suite green**, and each fix proven by
reverting it and watching its test go RED.

A cross-family review (glm-5.3) of the session-six build found these. **Every item was
reproduced firsthand before it was written here.** R1 is a the operator ruling (option A,
2026-09-23), not a design choice left open.

## The standing rules this round serves

- **Gates live in code, not in prompts.** Nothing a model writes reaches a party unless code
  built it or code checked it.
- **A type check is not a shape check.** `typeof x === "object"` admits arrays and `{}`. R6 is
  this exact defect class, again; pin the whole family of wrong shapes.
- **A fix is not done until a test fails when the fix is reverted.**

## The ten items

### R1 — MAJOR — the decision message relays the Judge's explanation (the operator ruling A)

`app/schemas.py::party_message_for_ruling` appends `ruling.explanation` verbatim. The mock's
explanation names "the Judge" and "advocate cases" on every decided run; a real model's can
carry its confidence (reproduced: a party saw `0.91`). Pre-dates session six (09-21).

**Fix, as ruled:** the party message is **built in code** from structured fields only:
- the action and, for refund/compensation, the amount;
- the **plain titles** of the cited rules, e.g. `Basis: When a deviation is material.`
- **no rule IDs, no explanation.** Cited rules whose title would leak (the ESC-* family:
  "Low confidence", "escalation") are skipped. Filter titles through the same banned-word set
  the tests use; no more than 3 titles.

Add `PolicySet.rule_title(rule_id)` to `app/policy.py`: the heading text after the em dash,
provenance tag `[...]` stripped, ID stripped. Change the signature to
`party_message_for_ruling(ruling, policy=None)`; with no policy the message is action + amount
alone. Pass the policy through at `app/agents/judge.py:209`. **The Judge's explanation stays on
`resolution.ruling.explanation` for the operator console, unchanged.**

`party_view` (app/server.py) is the second line: for `decided` and `needs_info`, if the message
(or any question) matches the banned-word set, fail closed to the neutral under-review view.
Test: `test_party_view_fails_closed_on_a_leaky_planted_message`.

### R2 — MAJOR — follow-up questions reach the party as raw model text

`app/pipeline.py::_questions_for_party` passes advocate output straight through. **Fix:** a
code gate in the pipeline, before the questions are stored. Any question matching the banned
words or a rule-ID pattern (`[A-Z]{2,5}-\d{1,3}`) is **replaced by a template question** for a
blank intake field: `We didn't get an answer to "<form label>". Could you tell us?` Pick blank
fields not already covered; if none is left, drop the question. No duplicates, still at most 3.
If nothing survives, the run does **not** stop (no empty needs_info).

The template needs the form labels in Python. **Make one owner:** an `INTAKE_QUESTIONS` table in
`app/schemas.py` (`category -> ((key, label), ...)`), labels exactly as `ui/party/party.js`
shows them today. Derive `app/server.py::QUESTIONNAIRES` from it. The test reads party.js and
asserts the two agree.

### R3 (+R5) — MAJOR — category/trip mismatch crashes, or fabricates evidence

A `no_show_charge` filing on a route trip → `EvidenceInputError` → **500**. Reachable from the
page: pick "Something else", pick a route trip, switch the category card without pressing
Continue. Reverse direction (route filing on a no-show trip) → a "route distance" built from the
driver's waiting-around GPS (R5, contained by ESC-2 but false evidence).

**Fix, server side:** for the two locked categories, the trip's own category must match →
**400** `this trip does not match the category you picked`, and **no run directory created**.
Out-of-scope categories still accept any trip. **Page side:** changing the category card must
reset the trip choice and hide the later steps.

### R4 — MAJOR — two concurrent answers both succeed

TOCTOU between the `answered.json` check and the write, on a `ThreadingHTTPServer`. Reproduced:
4 concurrent POSTs → 4 × 200, 4 round-two rulings. **Fix:** claim the run atomically **before**
running: `os.open(answered_path, O_CREAT | O_EXCL | O_WRONLY)` (or a per-run lock plus the same
check). Loser → **409**. Test expects `[200, 409, 409, 409]` and exactly two run dirs.

### R6 — MINOR — console round-two guard admits arrays

`ui/app.js:224`, `if (item && typeof item === "object")`. **Fix:** require a non-array object
whose `question` and `answer` are both non-empty strings; otherwise skip. The test feeds arrays,
`[]`, `{}`, a numeric question, a missing answer, `null`, a string and a number.

### R7 — NIT — a crashed round two leaves litter and stays answerable

`_run_record` creates the run dir before the pipeline runs; a crash leaves a half-written dir.
**Fix:** on any exception inside `_run_record`, remove the new run dir (only that one, and only
if it is inside `out_dir`), then re-raise so the handler answers 500. **Release the R4 claim on
failure** so a retry is possible. The test asserts two consecutive 500s with no litter.

### R8 — NIT — the trip "fare" is a mix of fares and fees

`_trip_summary` falls through fare → cancellation fee → waiting fee under one key. **Fix:** add
`charge_label` (`"fare"`, `"cancellation fee"`, `"waiting fee"`, or `null`), and make
`fare_sgd` **null, not 0.0**, when no charge is known. The page shows the label ("SGD 6.61
cancellation fee"). `kind_label` is R9.

### R9 — the page shows raw `route_deviation`

**Fix:** add `kind_label` to each trip (plain words, e.g. "Route complaint", "No-show charge",
"Other"; no underscores); the page shows it instead of `kind`.

### R10 — the mock's question names the internal field

`app/llm/mock.py:93` says `the form answer for 'expected_route'`. **Fix:** quote the form label
from `INTAKE_QUESTIONS`. Keep the `MOCK` marker (a mock run must stay recognisable), and no
snake_case in the question.

## Boundaries

- **Do not change** `data/`, `docs/policy.md`, `tools/`, the ESC gates, the confidence threshold
  or the cap. **Do not edit** the test files except to fix a genuine bug in a test, and if you
  do, say so explicitly in the summary with the reason.
- The 35 existing corpus runs (17 × 2 packs + DISP-002) must keep the **same outcome, action and
  amount** as at `d117586`. Only the `party_message` wording changes.
- Stdlib only; plain HTML/CSS/JS; no `innerHTML`.

## Order

1. R1 (policy titles, message builder, judge call site, party_view second line).
2. R2 + R10 (`INTAKE_QUESTIONS`, question gate, mock wording).
3. R3/R5, R4, R7 (server).
4. R6, R8, R9 (UI + trip summary), including the category-reset on the page.
5. Full suite green. Revert proofs for R1, R2, R3, R4, R6: revert, show RED, restore.
6. Commit per step with the suite count in the message.
