# W24 fix round (lane B): deep link uses the queue entry; a local-file pick retires pending prompts and stale reads

Prepared against main `1ae5a84cc2ea67fea54df1f9fa6c55b0954fc1ec` (full suite 1287 OK, skipped=1). You resume the W24 session in a fresh worktree. This round changes the console's client code only: no server, agent, model, pipeline, schema, evidence, dispute, policy, markup or stylesheet change.

## What is wrong at BASE (both reproduced)

- **P1+F2, deep link.** `openDeepLink()` calls `openCase({run_id}, null, null)` as soon as the page loads, before the review queue has answered. The open run then carries no `proposed`/`can_approve`, so for a queued case that HAS a proposal (RD-0109, refund SGD 55.16) the decision form disables Approve and shows `No AI proposal to approve; use Change.`, while the queue row for the same run says `Currently open`. Clicking that row re-opens it with the queue entry and Approve becomes enabled.
- **F1 sibling, stale local read.** `handleFile()`'s own `file.text()` read has no generation guard: a slow read that settles after a newer queue click renders the local file under the queue run's decision form; a slow first pick overwrites a newer second pick; a read failure that settles late clears the newer case.
- **F1, stale prompts.** `handleFile()` invalidates pending case opens when a local file is picked but never bumps `state.promptsGeneration`, so a slow `/prompts` reply for the previously opened server case still settles and renders into the panel (three cards in a hidden workspace after a failed pick; the old case's cards or failure sentence after a successful pick, until the file is read).

## Required behaviour (the fix contract)

1. Deep link, when the review queue is available (reviewUi present and fetch available): the deep-link open waits for the first queue load to settle, then opens the run with the matching queue entry object (the same object a queue click passes) if the queue lists that run_id, otherwise with {run_id}. If the queue load fails, open with {run_id}. Result: after `?run=<queued id>` the decision form is identical to the queue-click path (Approve enabled iff the queue entry has can_approve true and a proposal; no 'No AI proposal' note when a proposal exists), and the queue row state is consistent.
2. If the user opens any case (queue click) or picks a local file before the deep link fires, the deep link does nothing (a user action always wins).
3. Invalid run id: unchanged (immediate PROMPTS_UNKNOWN_RUN status, nothing rendered). Deep link without a queue (no reviewUi/fetch): unchanged behaviour.
4. handleFile bumps state.promptsGeneration as soon as a local file is picked (same place it invalidates pending opens), so any pending /prompts reply (late success OR late failure) for a previous case never renders, whether the local file then fails or succeeds.
5. (Added by the planner after the blast-radius check, the operator ruling 2026-10-07: fix the class, not the instance.) A local-file read that settles after any newer selection never renders and never clears: `handleFile()`'s own `file.text()` result, success or failure, is ignored when a queue open or another local-file pick happened after this pick. A read failure that is still current is reported as today. Reason: at BASE a slow read that lands after a queue click draws the local file under the queue run's open decision form, so Send would decide a different case than the one shown.
6. No other behaviour changes. Allowed shipped file for the builder: ui/app.js only. Carve-outs: the builder must re-baseline the app.js sha256 pins in tests/test_console_rebrand.py (APP_JS_SHA) and tests/test_w15_feedback.py (FROZEN['ui/app.js'] entry) and nothing else in those files. Frozen as before: app/agents, app/llm, app/evidence, app/pipeline.py, app/schemas.py, app/dispute.py, app/policy.py, app/server.py, app/prompt_view.py, ui/styles.css, ui/party/, ui/index.html.

How the tests read the contract (precise points, no new rules):

- **"The first queue load"** is the load the page starts at start-up. A load started by the Refresh button does not count, even if it settles first: firing the deep link when any queue load first renders fails `test_a_queue_open_before_the_first_queue_load_settles_wins`.
- **"The matching queue entry object"** is the entry of the row the queue SHOWS when the deep link fires, matched on `run_id` (never the first row, never an entry from a load the queue no longer shows, never a copy with fields dropped). The tests prove which entry was used by choosing Approve and reading the confirmation's `AI proposed: ...` line.
- **"Identical to the queue-click path"** is measured by snapshot: `#decision-section`, `#decision-content`, `#queue-content`, `#loaded-file`, `#load-status`, `#prompts-content` and `#case-workspace` after `?run=A` must equal those after opening A with a queue click. Exactly one row carries `aria-current="true"`.
- **"A user action"** is any queue open or any local-file pick after page load, including a pick whose file then fails to parse (checking whether a case is currently loaded does not cover that one).
- **Invalid id "immediate"**: `#load-status` reads `Unknown run.` before the queue answers. **No queue "unchanged"**: with no review UI (or no fetch) the `/case` request is made during page load, as at BASE.
- **F1**: every late-reply run is compared with a control run in which the old `/prompts` request never answers. The panel must equal the control's panel, both while the picked file is still being read and after it has loaded or failed. Bumping the counter only on failure, only on success, or only after the file is read all fail.

Seams in the existing code (where the reference changed it; the implementation is yours): `loadReviewPanels()`/`loadQueue()` (make the start-up queue load's settlement observable), `renderQueue()` (the entries the queue shows), `openDeepLink()`, and `handleFile()`. `openCase()`, `settlePrompts()`, `renderPrompts()` and the decision form need no change.

## Allowed files

- `ui/app.js`
- `tests/test_console_rebrand.py` line 28 `APP_JS_SHA` -> sha256 of YOUR final `ui/app.js`, and nothing else in that file
- `tests/test_w15_feedback.py` line 26 `FROZEN['ui/app.js']` -> the same sha256, and nothing else in that file

Do not modify any other file: no other test, `tests/test_w24_prompt_panel.py` or `tests/browser/w24_prompt_panel.cjs` (sha256 `31efc922...7e84` / `ec6cfb27...a428`, pinned by the new file), the new acceptance files below, tools, data, configuration, `docs/`, `ui/index.html`, `ui/styles.css`, `ui/party/*`, `app/server.py`, `app/prompt_view.py` or any other app module. The frozen list above is byte-pinned by test (`FixRoundFreeze` plus the existing W24 runtime and stylesheet freezes). If a test looks wrong, stop and ask. No live model calls, credentials, provider changes or paid verification.

## Acceptance tests

The planner transfers these files into the worktree before you start:

- `tests/test_w24_fix_round.py`, SHA256 `a20db39b6081a05b80656e6b6c4cc243d515e126b6208f4296ad2f09e96cb837`
- `tests/browser/w24_fix_round.cjs`, SHA256 `54999b5a924265aa44456fd57a5846326497923bad4d31178cf2823f930bd0af`
- `tests/test_w24_file_read_guard.py`, SHA256 `e09d9b1f4f44d5645faffe22e3b79b77e1d67aac02c99f724e5c55960b358f43` (contract item 5: 4 tests, 3 fail on BASE by assertion; the fourth pins that a current read failure is still reported)

21 tests: deep link uses the queue entry (8), user action wins (4), unchanged paths (3), F1 stale prompts (4), freeze (1), and one real-browser test that runs the `.cjs` against the real server on an ephemeral port (`?run=<queued RD-0109-style run>` at 1280 and 390 px: Approve enabled, no note, decision form HTML equal to the queue-click path). The browser test runs only when `PUPPETEER_MODULE` and `BROWSER_EXECUTABLE` are set; the planner runs it, and it skips otherwise. On BASE, 12 test methods fail (14 assertion failures counting subtests) with 0 errors. Eight pass on BASE because they pin behaviour the fix must PRESERVE: Approve disabled when the matching entry cannot approve, a run not in the queue opens with `{run_id}`, a failed queue load still opens, a queue click wins over a pending deep-link `/case`, an invalid id rejected at once, no review UI opens at once, no fetch fails at once, and the freeze. The browser test fails on BASE (`the deep link leaves Approve disabled at 1280`).

```sh
env -u PYTHONPATH /usr/bin/python3 -B -m unittest tests.test_w24_fix_round tests.test_w24_file_read_guard tests.test_w24_prompt_panel -v
env -u PYTHONPATH /usr/bin/python3 -B -m unittest discover -s tests -t .
```

## Measured proof (scratch, `[USER_HOME]/.hermes/cache/scratch/w24-fix-prep-20261007/`)

- BASE + the two files: focused 75 tests, 14 failures (all in `test_w24_fix_round`), 0 errors, skipped=2. Full 1308 tests, the same 14 failures, 0 errors, skipped=2.
- Planner re-proof on fresh trees with all three test files: BASE focused 79 tests, 17 failures, 0 errors; reference (with the item-5 guard on both the success and failure path) focused 79 OK, full 1312 OK (skipped=2). Dropping either guard alone turns `test_w24_file_read_guard` RED.
- Disposable reference (ui/app.js only, plus the two carve-outs): focused 75 OK (skipped=2); full 1308 OK (skipped=2); real browser: the new test OK at 1280 and 390, and the existing W24 browser test still OK. Before the carve-outs, the only failures were `test_console_rebrand.ConsoleTokensTest.test_app_js_unchanged` and `test_w15_feedback.W15Feedback.test_all_html_and_javascript_bytes_stay_frozen`.
- Mutation battery: 25 unique literal edit sets against the reference, each applied exactly once: 25 killed by assertion in `test_w24_fix_round`, 0 errors, 0 driver crashes, 0 survivors; baseline GREEN before and after. Browser mini-battery: 4 of 4 RED by assertion, baseline GREEN.
- The reference is preparation only. No reference code is transferred to you. The planner re-aims the battery's literals at your shipped source before verification.

## What should be seen when done

Focused: 79 tests OK (skipped=2 without browser variables). Full suite: 1312 OK (skipped=2). `git diff --stat` shows exactly `ui/app.js`, `tests/test_console_rebrand.py` (1 line) and `tests/test_w15_feedback.py` (1 line). Opening `/?run=<the RD-0109 run>` from the local server shows the decision form with Approve enabled, no `No AI proposal` note, and the queue row `Currently open`, exactly as a queue click shows it.

## Dispatch protocol

Work only inside this worktree. No other worktree or planning/scratch/reference reads. No subagents, web/network/API calls, package install, memory/config writes or screenshots. No unrelated files. Read CODEBUDDY.md and this brief; the carve-outs here supersede older write freezes only for this task. Use `/usr/bin/python3` with `PYTHONPATH` removed. Any server you start binds port 0 or a port in 18800-18899. Run the focused suite and then the full suite, and report any remaining failures by test path. The planner owns the browser gate, the battery and review. Commit ONLY the allowed paths with an explicit `git add ui/app.js tests/test_console_rebrand.py tests/test_w15_feedback.py`. Never `git add -A`, never merge, never push. End your response with the commit hash, the full changed-file list and the actual focused/full results. If a tool is denied, stop and report the tool and the exact command.

Expected sibling RED (planner, measured on the combined RED tree): the W27 fix lane's deliberately failing tests are committed in the same baseline. Your full suite therefore runs 1366 tests and, before your fix, fails 67: 14 in `tests/test_w24_fix_round.py` and 3 in `tests/test_w24_file_read_guard.py` (yours), plus 49 in `tests/test_w27_fix_round.py` and 1 in `tests/test_w27_replay_export.py` (the landing test; sibling). After your fix exactly the 50 sibling failures may remain, 0 errors. Never edit the sibling's files or its acceptance assertions.
