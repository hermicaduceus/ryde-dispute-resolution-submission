# Build session six — brief: the party-facing surface

**Status at handoff: 2026-09-23.** Suite 273 tests: **the only failures are in
`tests/test_party_surface.py`** (27 tests, one passes trivially today), which is this session's
acceptance target. Read HEAD yourself with `git log -1`.

Pre-flight:

```bash
cd ~/hermes-workspace/projects/ryde-build
git status --short           # expect empty
python3 -m unittest discover -s tests -t .    # expect 273 tests, failures only in test_party_surface
```

---

## Why this session exists

`ui/` is the operator console. The parties have no surface at all: nobody has ever filed a
dispute through a form, and nobody has ever read an outcome. The locked scope says the parties
are **spectators behind a standardized intake form**, the advocates **ask the filing party
targeted follow-up questions only when the form is insufficient**, and the parties receive
either the ruling or the neutral "still under review" message. This session builds that.

Read `tests/test_party_surface.py` first. Its docstring carries the operator rulings.

## The deliverable

Make `tests/test_party_surface.py` pass **without editing it**, keep every other test green,
and ship a party page a non-technical judge understands without explanation.

### 1. A fourth outcome: `needs_info` (stop and ask, one round)

Operator ruling 2026-09-23: when either advocate returns follow-up questions, the run **stops
before the Judge**.

- `app/schemas.py`: add `OUTCOME_NEEDS_INFO = "needs_info"` and `NEEDS_INFO_MESSAGE`, a
  neutral message asking the party for a little more information. It must not mention AI,
  agents, a judge, confidence, or which way the case leans.
- `Resolution` gains `questions_for_party: List[str]`, always serialised (`[]` when none).
  For `needs_info`: `ruling` and `withheld_candidate` are `None`, `delivered_to_parties` and
  `escalated_for_human_review` are `False`.
- `app/pipeline.py`: after both advocates run, collect their questions, the filing party's own
  advocate first, de-duplicated, **capped at 3**. If any, emit `party.notified` with the
  questions and return the case file without calling the Judge. The evidence pack and both
  advocate cases stay on the file.
- **One round only, enforced in code, not in a prompt.** A dispute carrying follow-up answers
  never stops again: the Judge always runs, `questions_for_party` is `[]`, no
  `advocate.follow_up_requested` event is emitted, and `resolution.notes` records that further
  questions were not sent (the note contains the word `follow-up`).

### 2. Follow-up answers on the dispute

- `app/dispute.py`: `Dispute.follow_up_answers: List[Dict[str, str]]`, read from
  `ryde_extensions.follow_up_answers` (organiser shape) or top-level `follow_up_answers` (our
  shape). Absent means `[]`. Anything else must be a list of objects each with string
  `question` and string `answer`, or `DisputeError`.
- The case file's `intake` section gains `follow_up_answers` (always present).
- `dispute_block` in `app/agents/base.py` shows the answers to the advocates and the Judge.

### 3. The mock asks when a form answer is blank

So the path is demoable before a real model exists. Add to the advocate request metadata:
`filed_by`, `blank_intake_questions` (intake keys whose answer is empty after trimming), and
`has_follow_up_answers`. In `app/llm/mock.py`, only the **filing party's** advocate asks, one
question per blank key, at most 3, and never when `has_follow_up_answers` is true. Keep the
`MOCK` prefix on every string. No shipped record has a blank answer, so none of the 35
existing case runs may change outcome.

### 4. `app/server.py`: a local server, standard library only

- `make_server(port, pack_dir=None, out_dir=None, llm=None)` returns an `http.server`
  `ThreadingHTTPServer` bound to **127.0.0.1 only**. `None` means the config default.
  `python3 -m app.server` runs it on port 8000 with the configured LLM provider.
- `party_view(case_file_dict)` returns **exactly** `run_id`, `dispute_id`, `status`,
  `message`, `questions`. Mapping: `ruled` to `decided`, `withheld` to `under_review`,
  `human_review` to `passed_to_support`, `needs_info` to `needs_info`. **Build it from an
  allowlist and fail closed:** any malformed input (not a non-array object, missing or empty
  `party_message`, unknown outcome, `questions_for_party` not a list of strings) returns
  `under_review` with `UNDER_REVIEW_MESSAGE` and no questions. The page is only ever handed
  this view, never the case file.
- `GET /api/trips?category=<c>`: the trips the party can pick from, built from the pack's
  records, in file-name order. Route deviation lists route cases, no-show lists no-show
  cases, any other category lists every trip. Each trip exposes only `trip_id`, `label`,
  `kind`, `pickup`, `dropoff`, `date`, `fare_sgd`. **No names, profiles, ratings, fraud
  flags, GPS or chat.**
- `POST /api/disputes` with `category`, `filed_by`, `trip_id`, `description`,
  `claim_amount_sgd`, `answers`. Build a new record from the pack record for that trip: keep
  the **platform evidence** (trip data, GPS, chat, app events, profiles, cancellation policy)
  and replace **everything the party states** with the form's values. Party-stated fields the
  form does not collect (such as `rider_claims_driver_absent`) are removed, never carried
  over. New `dispute_id` per filing. Run the pipeline, write `dispute.json` beside
  `case_file.json` in the run directory, return `party_view`.
- `POST /api/disputes/<run_id>/answers` with `answers: [{question, answer}]`: 404 for an
  unknown or malformed run id, **409** if that run's outcome is not `needs_info` or it was
  already answered, **400** unless every question the run asked is answered exactly once with
  a non-blank string and nothing else is. Re-run with the answers attached, same
  `dispute_id`, new `run_id`, return `party_view`.
- Validation, all 400: category outside `route_deviation`, `no_show_charge`,
  `property_damage_mess`, `safety_incident`, `other`; `filed_by` not rider or driver; blank or
  over-2000-character description; `claim_amount_sgd` not null and not a number from 0 to 500
  (booleans and strings rejected); an answer key not in that category's questionnaire or a
  non-string answer. Unknown trip is 404. Invalid JSON is 400. A body over 64 KiB is 413.
- Static files: serve `ui/` only (`/` the console, `/party/` the party page). Any path that
  resolves outside `ui/` is 404. The run id and every path are checked **after** decoding.

### 5. `ui/party/`: the party page (plain HTML, CSS, JS, no framework, no npm)

A rider files a dispute in three steps: what went wrong (category), which trip, then the
questionnaire, a free-text description and an optional amount. The outcome screen has four
distinct states: **decided** (the message), **under review**, **passed to support**, and
**needs more information** (the questions, each with an answer box, then submit, then the
next outcome). Show the reference number.

- **Plain language only.** The party never reads the words AI, agent, advocate, judge,
  confidence, withheld, escalate or model anywhere on the page. The test checks this.
- `textContent` only. No `innerHTML`, `outerHTML`, `insertAdjacentHTML`, `document.write`
  or `eval`.
- Label the page as a demo whose trips come from the sample dataset.
- The page is rider-facing in this session. The API accepts `driver`; a driver-side form is
  out of scope.

### 6. The console renders the fourth outcome

`ui/app.js`: a `needs_info` case file gets its own state (waiting on the party, the
questions asked, the Judge did not run). A round-two case file shows its follow-up answers.
Older case files without `questions_for_party` or `follow_up_answers` must still render.

## Rules for this session

- **Gates live in code, not in prompts.** The one-round limit and the party allowlist are
  Python, not prompt text.
- **Do not edit anything under `tests/`, `tools/` or `data/`.** If a test looks wrong, stop and
  say so.
- Do not change the confidence threshold, the SGD 50 cap, ESC-2, or any policy rule.
- Keep the `MOCK` markers visible.
- **Cut order if the session runs short:** visual polish first. The `needs_info` stop, the
  one-round gate and the fail-closed party view are never cut.
- **A fix is not done until a test fails when it is reverted.** When green, revert the
  one-round gate and the `party_view` fail-closed branch in turn, name the tests that go red,
  restore both.
- Commit in small steps, each with the suite result in the message.
- On a conflict with `docs/statement-extract.md` or `CODEBUDDY.md`, stop and ask.

## Done means

```bash
python3 -m unittest discover -s tests -t .      # 273 tests, OK
python3 -m app.server                           # then open http://127.0.0.1:8000/party/
```
