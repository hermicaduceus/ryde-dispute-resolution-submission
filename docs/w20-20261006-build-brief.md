# W20 build brief — dispatch authorized

Baseline: `d50a89157cf9211aa1d5dce0ab13c1f08f552356` (1164 existing tests). Three fix units only. Parent has opened acceptance artifacts, reproduced RED, rerun full reference GREEN after the the operator-approved hash exceptions, and deletes REF before dispatch. Reference app/UI code must never be transferred.

## Scope and allowed files

CodeBuddy may edit `app/server.py`, `ui/party/party.js`, and **only the party.js expected digest** in `tests/test_party_rebrand.py`, `tests/test_w12_demo_notice.py`, `tests/test_w15_feedback.py` and `tests/test_w15_layout.py`. No CSS/HTML, corpus, tools, prompts, policy, or other tests. `app/pipeline.py` is excluded: filing validation runs before record construction, run-directory creation and model execution; existing persisted-record/CLI readers can retain their permissive behavior untouched. Tests import existing `_validate_filing`, `_validate_reply`, `_HTTPError`; no new app symbol is required. Keep current server seams available.

Immutable acceptance files supplied by parent: `tests/test_w20_intake_validation.py`, `tests/test_w20_back_state.py`, `tests/w20_support.py`. If an assertion appears wrong, stop and ask; do not weaken it. Browser instrument: `tests/browser/w20_intake_contract.cjs` (existing Puppeteer conventions, no new dependency).

## Unit 1 — intake raw answer cap

Every incoming intake answer, every allowed key, rider/driver and route/no-show, is a string of at most **2000 Unicode code points**, including choice + delimiter + explanation. Refuse at 2001, accept 1999/2000, without trimming/coercion. Server returns HTTP 400 before model calls or run files. Keep the value unchanged. Missing answers remains valid; unanswered empty strings remain valid. Non-string values still refuse. This restriction is intake-only: do not cap follow-up replies or change saved-record parsing.

UI counts the complete serialized answer using Unicode code points, not UTF-16 code units. Above the limit, show exactly `Intake answers must be at most 2000 characters.`, keep the original textarea content and do not send a POST. Do not truncate. Preserve existing serialization: the UI already trims optional explanations and emits exact Yes/No or choice + ` - ` + trimmed explanation; open textarea values stay raw.

## Unit 2 — incoming choice grammar

For each yes/no key, accept exactly `''`, `Yes`, `No`, or `Yes - <explanation>` / `No - <explanation>` with at least one non-whitespace character in the explanation. Preserve the entire accepted server value, including multiline/trailing explanation whitespace. Reject random prose, casing/leading whitespace variants, malformed delimiters, empty/whitespace explanation, and a trailing newline on a bare choice. Open-answer keys remain free text. Historical malformed strings in saved records remain readable; CLI/corpus behavior stays intact.

## Unit 3 — Back draft state

On rider and driver forms, both categories and repeated Back/Continue cycles, retain the selected trip, every selected Yes/No and `aria-pressed` state, all open answers, explanations, description and amount. A same-trip re-click must keep the draft. A different trip must clear question answers; category change must clear them, including shared safety and returning later to the old category. Keep existing choice switching behavior: selecting the same choice keeps its explanation, switching Yes/No clears the previous explanation. No storage across reload is required.

Keep W30 ownership and landing behavior. The disposable proof retains the existing fresh GET on details Back, restores the selected trip when the returned list still contains it, and does not rebuild the questions for the unchanged trip/category. A no-reload implementation was discarded because it conflicts with the existing W30 fresh-request and landing tests; the acceptance contract does not require removing refresh. Do not copy reference code.

## Updated on purpose — parent-owned compatibility fixtures

Exactly two files, already updated in scratch; test counts unchanged. Apply `compatibility-fixtures.patch` before builder dispatch, not as builder-owned test edits.

1. `tests/test_w16_driver_filing.py::DriverHTTP.test_shared_safety_rider_legacy_strings_normalization_and_optional_answers`: malformed arbitrary choice now refuses; 10001-character open answer now refuses; canonical role normalization is still asserted using a valid 2000-character answer. Missing and optional-answer checks remain.
2. `tests/test_w23_queue_and_overrides.py::SafetyFlag.test_the_safety_pattern`: first file with valid `No`, then plant each original legacy safety string in the saved `case_file.json`. Every original regex row and queue assertion is retained, including case/leading-space/punctuation positives and `Yesterday`/`yess`/`no, yes`/`Not yes` negatives.

## the operator-authorized additional digest exceptions

the operator explicitly authorized 2026-10-06: change only the party.js SHA values in `tests/test_w15_feedback.py` and `tests/test_w15_layout.py`, preserving every assertion and every other hash. Together with the original two exceptions, there are four SHA values to derive from your independently authored party.js. No skips, no assertions removed, no reference hashes copied.

## Commands and expected checkpoints

Run from the relevant scratch tree / future build worktree:

```
env -u PYTHONPATH /usr/bin/python3 -m unittest tests.test_w20_intake_validation tests.test_w20_back_state
env -u PYTHONPATH /usr/bin/python3 -m unittest discover -s tests -t .
```

Current unchanged-source RED: 13 focused tests, 314 assertion failures, zero errors. Full RED with the two compatibility fixture updates: 1177 tests, 315 failures, zero errors (one additional W16 refusal assertion).

Parent rerun disposable REF: 1177 full tests OK after digest-only updates. Parent main focused combined RED: 20 tests, 316 assertion failures, 0 errors. Both reference full suites independently passed. Real combined suite has 1184 tests, must be measured after both merges.

Mutation proof: 30 unique literal edit sets, 30 targeted assertion kills, zero survivors, zero errors. `mutations.json` is aimed at the disposable reference only; re-aim every literal at independently shipped CodeBuddy source before using it to verify that source.

Parent audit commands from `[USER_HOME]`:

```
env -u PYTHONPATH /usr/bin/python3 [USER_HOME]/.hermes/cache/scratch/w20-prep-20261006/reprove.py
env -u PYTHONPATH /usr/bin/python3 [USER_HOME]/.hermes/cache/scratch/w20-prep-20261006/run_mutations.py
```

Browser gate after builder ships (rider/driver, route/no-show, 390px and desktop), using already available Puppeteer/Chrome paths:

```
PUPPETEER_MODULE=<existing module> BROWSER_EXECUTABLE=<existing Chrome> node tests/browser/w20_intake_contract.cjs <base-url> <scratch-output-json>
```

The helper syntax-checked this instrument but did not run a browser. Its fake-DOM green is not browser verification. Parent must also audit the real-browser different-trip/category reset flow and W30 async lifecycle; this narrow browser instrument covers Back/Continue preservation and cap boundaries, not every permanent acceptance case.


## Dispatch protocol

Work only inside this worktree. No other worktree or planning/scratch/reference reads. No subagents, web/network/API calls, package install, memory/config writes, or screenshot. No unrelated files. Read CODEBUDDY.md and this brief; scope carve-outs here supersede older write freezes only for this task. Use `/usr/bin/python3` with `PYTHONPATH` removed. Your sibling lane starts from the same prepared baseline and deliberately RED tests are committed: never repair your sibling's files or acceptance assertions. Run your focused suite plus the full suite and report remaining failures by test path, expected sibling RED vs any regression. Parent owns actual combined full GREEN, browser gates and review. Commit ONLY the allowed paths, explicit git add, never git add -A, never merge or push. End response with commit hash, full changed-file list and actual focused/full results. If tools denied, stop and report the tool and exact command.

Expected sibling RED: two W32 missing-sentence/doc assertions. Do not edit prompts or Judge.
