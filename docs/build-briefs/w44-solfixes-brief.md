# W44 brief — three small fixes from the 2026-10-13 Sol code review (single session)

You are working in the worktree `w43`→`w44-solfixes` (branch cut from build `main` at `1f860c2`).
Read this brief completely before changing anything. It is your whole contract.

## Ground rules (unchanged from previous lanes)
- Allowed files, ONLY these:
  - `app/server.py`
  - `docs/prompts.md`
  - `tests/test_w24_prompt_panel.py` and `tests/test_w34_launcher.py` — ONLY the `"app/server.py"` hash lines in `FROZEN_RUNTIME` / `FROZEN_W34` may change (see Fix C)
  - two new files you author: `tests/test_w44_server_collision.py`, `tests/test_w44_ns6_real_route.py`
- No other file may be edited, created or deleted. Never touch `main`, never push, no network,
  no live model calls (mock/scripted LLM only), no `.env`, no server left running,
  `PYTHONDONTWRITEBYTECODE=1` on every test run.
- Baseline command: `PYTHONDONTWRITEBYTECODE=1 env -u PYTHONPATH /usr/bin/python3 -m unittest discover -s tests -t .`
  Expected on clean HEAD: `Ran 1690 tests ... OK (skipped=15)`.

## Fix A — S-F01: a refused run-id collision must never delete the prior run (RED first)
Where: `app/server.py`, `_run_record` (currently around lines 1369–1393).

Bug: `events = EventLog(run_dir, run_id)` now raises when the directory already holds a run
(`app/events.py` refuses reuse). The `except Exception:` handler then `shutil.rmtree`s the
directory — destroying the FIRST run's data — and the filer gets HTTP 500.

Contract:
1. First write `tests/test_w44_server_collision.py` and prove it RED on clean HEAD:
   - force `_new_run_id` to return the id of an existing complete run (monkeypatch or your own seam),
   - file a second valid dispute through the real `POST /api/disputes`,
   - assert: the prior run's directory is byte-identical afterwards (events, payloads, case file),
   - assert: the second filing does NOT return 500 — with a bounded retry over fresh ids
     (at least 3 attempts) it should SUCCEED with a new id and a complete run,
   - assert: after the retry succeeds, a fresh filing with a genuinely free id still works.
2. Then fix `_run_record`: track whether THIS call acquired the directory
   (acquisition = `EventLog` construction succeeded). Only rmtree what this call created.
   On refusal, retry with a fresh `_new_run_id()` a bounded number of times; if every attempt
   collides, return a clean error (the handler's raise is fine) but never delete anything.
3. Keep the R7 comment's promise literally true: "must remove only the directory this call
   created, never anything else" — update the comment if your fix changes its wording needs.

## Fix B — regression guard for NS-6 on the real filing route (green on merged code)
The W43 MUST acceptance tests call `_build` directly; a one-line removal of the absence
plumbing inside `_file_dispute` survives all 51 of them (proven by the review's
`route_mutation_survivor` probe). Close that hole.

Author `tests/test_w44_ns6_real_route.py`:
- Real `POST /api/disputes` with `answers` choosing Yes for the absence question
  (and one case with Yes plus an explanation), for BOTH record shapes
  (`organiser-style-v1` and `ryde-synth-v1`).
- Scripted LLM proposes no-action, then SGD 1.00 partial.
- Assert together, in each combination: HTTP 200; the stored record carries the boolean
  absence claim (`rider_claims_driver_absent` is `True`); the case is WITHHELD with the NS-6
  gate named; the party view is the neutral under-review response; and the filer-visible
  answer text is preserved.
- One control: the exact refund (SGD 6.61) still rules on the same shape.
- These must be GREEN on the merged code — they pin behaviour that already exists.
  If any assertion is red on clean HEAD, your test is wrong or Fix A's probe found a real
  bug: report it, do not silently widen the assertion.

## Fix C — qualify the prompt-fingerprint claim (docs only)
`docs/prompts.md`, the "Pacing" paragraph (currently lines 323–327), says:
"a reviewer can confirm the prompt a ruling came from, byte for byte."

This is now true only for runs recorded under the CURRENT prompt version. After W43's
fare-delta sentence fix, the prompt panel honestly marks older recordings as `changed`.

Rewrite the two over-broad sentences so they say, in your own words but factually:
- the fingerprint is recorded with every call and the exact prompt bytes remain verifiable
  for runs recorded under the current prompt version;
- when a prompt sentence changes between a run's recording and the review, the panel
  reports the mismatch (`changed`) rather than claiming a match — a fail-closed provenance
  check, so an old recording is never silently presented as matching today's prompt.
Keep the paragraph's other content (2 MiB cap, 6.5 s pacing, fingerprint = hash of prompts,
"fingerprint proves what was asked") unchanged. No other line of prompts.md may change.
Note: `tests/test_w32_judge_prompt.py` pins a SENTENCE elsewhere in this file and the
Judge system bytes; you must not touch either.

## Fix D — freeze re-baselines (granted, narrow)
Because Fix A edits `app/server.py`, re-baseline exactly these two hash entries from your
final `app/server.py` bytes, nothing else:
- `FROZEN_RUNTIME["app/server.py"]` in `tests/test_w24_prompt_panel.py`
- `FROZEN_W34["app/server.py"]` in `tests/test_w34_launcher.py`
Follow the existing comment convention (one comment line naming W44 and why).
No other entry, in either dict, may change. `tests/test_w35_r2_K.py` is NOT granted
(its protected tree does not include `app/server.py`; leave the file untouched).

## Done means (all on your branch, in this order)
1. Show your RED proof for Fix A: run `tests/test_w44_server_collision.py` on clean HEAD
   (before your `app/server.py` change) and record the failing output in your report.
2. Apply fixes A, C, D; author B.
3. Lane runs:
   `env -u PYTHONPATH /usr/bin/python3 -m unittest tests.test_w44_server_collision tests.test_w44_ns6_real_route tests.test_w24_prompt_panel tests.test_w34_launcher tests.test_w32_judge_prompt`
   → all OK.
4. Full suite: `Ran N tests ... OK (skipped=15)` with N = 1690 + your new tests, 0 failures, 0 errors.
5. Working tree clean; commit ONLY the allowed files with a message naming W44 and the three fixes.
6. Report: the RED proof verbatim, per-fix diff summaries, the two new hash values,
   suite lines verbatim, commit hash, and any decision this brief did not cover.