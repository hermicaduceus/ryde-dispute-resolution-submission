# W43 MUST lane — CodeBuddy build brief (draft, prepared 2026-10-13)

Snapshot: `486bfa58df029ab23ea54ac1587b237d32c359ef` (the Ryde dispute-resolution build).
Lane: **MUST** — the three must-fix application defects from the Sol document review
(`drafts/reviews/2026-10-13-sol-doc-review/consolidated-report.md`, Tier 1 items 1, 2 and 4;
`laneA/report.md` F01, F02, F03; all three parent-reproduced in `parent-verification.md`).
The sibling lane (SHOULD) owns Tier 1 items 3, 5 and 6 and is named in the SIBLING RED section.

Prep artifacts beside this file (private scratch, not the repo): the RED acceptance tests,
a throwaway reference implementation (`ref/`), the proof they are GREEN there, the proof they
are RED on a clean HEAD clone (`red/`), and a 13-row mutation battery with zero survivors
(`battery.json`, `battery-report.json`). The reference implementation and its diff
(`ref-fix.patch`) show one working shape: the lane may implement differently, but the RED
tests below are the contract.

## Allowed files — NO other files

| Path | Why |
|---|---|
| `app/server.py` | M1 (filing validation + record builder), M3 (party view) |
| `app/evidence/compute.py` | M2 (the fare paths) |
| `app/dispute.py` | M2 (the organiser GPS trace) |
| `ui/party/` | M1: the one structured form question |
| `tests/test_w43_must_*.py` | the lane's own NEW test files (copy the prepared ones in unchanged) |
| `tests/test_w24_prompt_panel.py` | GRANTED (parent ruling, 2026-10-13): re-baseline the `FROZEN_RUNTIME` entries for `app/dispute.py` and `app/evidence/compute.py` ONLY. No other entry, no other edit. |
| `tests/test_w34_launcher.py` | GRANTED (same ruling): re-baseline the `FROZEN_W34` entries for `app/dispute.py` and `app/evidence/compute.py` ONLY. No other entry, no other edit. |

Do **not** touch: `app/schemas.py`, `app/agents/judge.py`, `docs/`, `README.md`,
`ui/app.js`, any other `ui/` file, any other `tests/` file. The freeze-inventory grant
above is line-disjoint from the sibling lane's own entries in the same two files (the
sibling re-points only `app/agents/judge.py` / `app/cli.py` / `app/events.py` entries);
your entries and the sibling's entries are different lines and must stay that way.

Corpus, packs, fixtures and the mock: read-only.

## Done means

Work in YOUR git worktree of this repo (the parent cut it for this lane). First MEASURE your
prepared baseline, then build, then verify against what you measured — never against a count
from this brief:

```bash
# 0. interpreter for every run (PATH-clean):
env -u PYTHONPATH /usr/bin/python3 -m unittest discover -s tests -t .
#    record this baseline BEFORE changing anything: the expected shape is
#    sibling-declared RED only — every FAIL: in tests/test_w43_should_*.py or
#    tests/test_w32_judge_prompt.py, plus this lane's own RED in
#    tests/test_w43_must_*.py, ZERO errors. Nothing else red.

# 1. the lane's acceptance tests, GREEN after the build
env -u PYTHONPATH /usr/bin/python3 -m unittest tests.test_w43_must_ns6_web_filing \
                   tests.test_w43_must_unreadable_components tests.test_w43_must_party_view_shapes
#    expected: Ran 51 tests ... OK   (20 + 16 + 15, 0 failures, 0 errors)

# 2. the whole suite after the build and the granted freeze re-baselines
env -u PYTHONPATH /usr/bin/python3 -m unittest discover -s tests -t .
#    expected: every remaining FAIL: is in a SIBLING file
#    (tests/test_w43_should_*.py or tests/test_w32_judge_prompt.py) — measure the count,
#    never add it up — and ZERO errors. Nothing else red.
```

`PYTHONDONTWRITEBYTECODE=1` for every run. Mock LLM only; no network, no live Tencent
calls, no credentials, no `.env` reads. Never edit a test to make a failure go away: an
acceptance test that is red is a finding, not an obstacle.

**Commits:** commit ONLY the files in ALLOWED FILES, on your branch, with a clear message
naming the fixes; never push, never touch `main`, never commit any file the brief does not
name. End your report with the exact commit hash.

## M1 — NS-6 must fire on no-shows filed through the web form

**The defect.** `_build_record` deletes `rider_claims_driver_absent` in both record shapes
because the form never collected it, so a contested no-show filed through the form can rule
"no action" or a short partial refund with no gate. The corpus path is protected.

**The contract.**

1. The rider no-show filing accepts ONE extra structured answer, under the pack's own field
   name — `rider_claims_driver_absent` — stating whether the driver ever showed up. It is
   accepted only for `("no_show_charge", "rider")`; a driver filing or a route filing must
   still be refused with 400. Validate it with the SAME choice grammar as every other yes/no
   intake key: `""`, `"Yes"`, `"No"`, `"Yes - <text>"`, `"No - <text>"`; prose is refused 400.
   Keep it out of the shared intake tables (`app/schemas.py` is not in the allowed set and the
   tables are pinned, one owner per fact).
2. The builder carries the answer into the record as the structured flag the NS-6 gate reads,
   in whichever slot the shape keeps it: `ryde_extensions.rider_claims_driver_absent` for the
   organisers' shape, `cancellation.rider_claims_driver_absent` for the pack shape.
   `"Yes…"` → `True`, `"No…"` → `False`. The answer is a choice; **never** parse the party's
   narrative for it (standing ruling: party text is structured, never relayed or parsed).
3. Unanswered is safe: when the form sends no absence answer, the pack's own flag is still
   deleted and the record says "not stated" — byte-for-byte today's behaviour, never a
   fabricated claim.
4. `ui/party/` asks the question as a real Yes/No control on the rider no-show flow, and sends
   it **only when the party chose one**: unanswered, the key must not be in the POSTed
   `answers` at all (also required by the existing "the form's answers are serialized exactly"
   pin). Two constraints on where it lives, from existing pins: the shipped markup's id set is
   frozen (no new id in `ui/party/index.html`) and every id `party.js` reads must exist in the
   driver shell too, and the rider no-show question list must keep exactly its three rows.
   A script-built field placed after the question list satisfies all three; the reference
   implementation does exactly that.
5. Nothing in `app/agents/judge.py` changes: the existing NS-6 gate does the withholding.

Acceptance: `tests/test_w43_must_ns6_web_filing.py` (20 tests) — server acceptance and the
choice grammar, the builder in both shapes, the default-safe/unanswered cases, a driver
filing that must not be gated, the end-to-end no-action and short-refund withholdings in both
shapes, the exact-fee refund still allowed, and the form (rendered question, serialized
answer, unanswered not sent, other flows unaffected, the three questionnaire rows unmoved).

## M2 — a value that is not a finite number voids what it feeds

**The defect.** `_is_non_finite_number` returns false for strings, booleans and null, so
`_finite_mapping` silently drops a non-numeric tariff rate, the rate defaults to zero and the
distance becomes free with `fare.unreadable_inputs` EMPTY: `per_km_sgd="unreadable"` on
RD-0103 recomputes 7.45 with a 4.24 "overcharge" that RD-5's floor and the party view then
treat as real. NaN/Infinity are handled correctly. The organiser parser also drops a
malformed (non-object) `gps_telemetry` row before the evidence layer can void the trace: an
11-row trace becomes 10 usable rows and still computes a distance, with no note.

**The contract.**

1. In the fare paths — the tariff rates and the fare breakdown, where every key is supposed to
   hold a figure — a present value that is not a finite number is unreadable: a string, a
   boolean, a list, an object, an explicit null, NaN, Infinity and an integer too large for a
   float. It is left out of the maps, it voids what it feeds (the recomputed fare, or the
   breakdown sum), it adds a note, and it is named in `fare.unreadable_inputs` under the same
   dotted path (`rates.<key>` / `breakdown.<key>`) with the same note wording that NaN already
   gets. A MISSING key is still "not stated", not unreadable.
2. Keep this separate from the shared helper: `_broken_keys` / `_is_non_finite_number` are
   also used for the case-policy terms, where a non-numeric value is ordinary metadata
   (DISP-002's `"source": "…"`), and widening the shared helper there drops a policy term
   (it goes red in `test_w22_unproven_figures` and `test_w24_prompt_panel`). Scope the new
   predicate to the fare paths.
3. Beware: `isinstance(True, int)` is True in Python, so booleans must be excluded explicitly
   or `float(True)` = 1.0 reads as a readable rate.
4. No gate change: ESC-2 already withholds a route ruling when `fare.unreadable_inputs` is
   non-empty. Your fix feeds it. `fare.unreadable_inputs` stays non-citable.
5. The organiser parser must not silently drop a malformed `gps_telemetry` row from a route
   trace: keep the row in `actual_route` so the evidence layer voids the whole length with its
   existing "unusable" note (one unusable point = unknown length, never a shorter one). Do not
   add a schema field; reuse the existing voiding path. Corpus records (all-dict rows) must be
   byte-identical afterwards.

Acceptance: `tests/test_w43_must_unreadable_components.py` (16 tests) — the parent's repro,
every rate and component across the family, the NaN-parity comparisons, the promo path, the
ESC-2 withholding at 4.24, the malformed-row voiding and the parsed-trace length, plus the
clean-record and no-show controls.

## M3 — `party_view` fails closed on every malformed shape

**The defect.** `resolution.outcome` is used as a mapping key before it is type-checked, so a
persisted case file with a list or dict outcome raises `TypeError` and surfaces as an HTTP 500
instead of the neutral five-key under-review view that every other malformed shape degrades to.

**The contract.** Type-check the member before the membership test (or catch around the whole
load path) so `[]`, `[1,2]`, `["ruled"]`, `{}`, a populated dict, null and numbers all return
the exact neutral response the code already produces: `run_id`, `dispute_id`,
`status: "under_review"`, the neutral message, `questions: []`. The shapes that already worked
(an unknown outcome string, a top-level list case file) must keep working; the good shapes
(a decided case with a safe message, a needs_info case with its questions, a withheld case)
must still be served, so an always-false guard cannot pass. Nothing else in `party_view`
changes: this is not the finding about relayed stale message text, which is out of scope here.

Acceptance: `tests/test_w43_must_party_view_shapes.py` (15 tests) — the wrong-shape family, the
controls, the five-key shape and id preservation, the served shapes, and one HTTP-level class
(`GET /api/disputes/<id>` answers 200 with the neutral view, not 500, for a persisted
unhashable outcome).

## AMENDMENT — RESOLVED by the parent (2026-10-13): GRANTED

`tests/test_w24_prompt_panel.py::RuntimeFreeze` (`FROZEN_RUNTIME`) and
`tests/test_w34_launcher.py::Preservation` (`FROZEN_W34`) pin the SHA-256 of every `app/**`
module, including `app/dispute.py` and `app/evidence/compute.py`. **Any** faithful M2 fix
moves those hash values, so the parent grants exactly those entries (see ALLOWED FILES):
re-baseline ONLY the entries for `app/dispute.py` and `app/evidence/compute.py`, from YOUR
final bytes, nothing else. Print the old and new hash values in your report. Verified by the
prep reference: with these four entries re-baselined the whole suite is
`Ran 1667 tests … OK (skipped=15)` — and with the sibling's RED tests also present, add the
sibling's declared failures (see below). If a re-pointed pin still fails, fix the CODE, never
the constant.

## SIBLING RED section (do not touch)

The sibling SHOULD lane ships its own RED acceptance tests as
**`tests/test_w43_should_*.py`** (Tier 1 items 3, 5, 6: the CLI run-id collision, RD-5's
breakdown-only floor, the Judge prompt's `deviation_fare_delta_sgd` sentence). It also authors
`ui/` and `docs/` changes.

* Those files are **expected to be red** until the sibling lane lands. Do not "fix" them, do
  not delete them, do not weaken them, and never revert a sibling test or a sibling's ui/docs
  edit. If a sibling test is red for a reason inside your three fixes, say so in the report
  instead of editing it.
* Conversely, `tests/test_w43_must_*.py` are this lane's; if the sibling's work turns one of
  them red, that is a merge finding for the parent, not a licence to edit either side.
* Overlap risk to avoid: `ui/party/` (this lane adds one script-built field; the sibling may
  restyle pages) and `docs/` (sibling only — this lane writes no prose).

## Fences

Work only in YOUR worktree and YOUR branch of this repo; no writes to the planning repo, no
writes anywhere outside the worktree; no network; mock provider only; never push, never touch
`main`; no server left running; `PYTHONDONTWRITEBYTECODE=1`; no `.env` reads.

## Prep evidence (from the reference implementation)

* Lane tests: 51 tests, GREEN in `ref/`, RED on a clean HEAD clone (160 failure records, 0 errors).
* Mutation battery: 13 literal one-aspect reverts, **13 red / 0 survivors**, every run loading
  all 51 tests with 0 errors.
* Full suite: `ref/` 1667 ran, 2 failures (the two inventories), 15 skipped; with the four
  hash re-baselines, 1667 ran, `OK (skipped=15)`.
