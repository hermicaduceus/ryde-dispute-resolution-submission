# W27 fix round: exporter fixes after the cross-family review

Prepared against main `1ae5a84` (full suite 1287 OK, skipped=1, on `env -u PYTHONPATH /usr/bin/python3 -B`). You are resuming the W27 session in a worktree. The original contract, `docs/w27-replay-export-brief.md`, still holds. This brief changes it in five places:

| Finding | Defect |
|---|---|
| M1 | The mock refusal fails open. A run whose provider cannot be read exports as real, and only the first `run.started` event is read. |
| M3 | `--out` inside `--before`/`--after`/`ui/`/`tools/replay/` is accepted, and so is `--before` == `--after`. |
| m1 | The landing step texts are fixed claims, not facts about the recorded runs. |
| M2 | The secret scan matches raw UTF-8 only. |
| m2 | The shim lets the bare `/api` path reach the network. |

the operator ruling 2026-10-07: the landing text must always be true and must never block recording day.

## Allowed files

- `tools/export_replay.py`
- `tools/replay/replay-shim.js`
- `tools/replay/index.html` (only if the template needs placeholders for the step texts)
- `docs/replay.md` (document the new refusals and the data-built steps)

## Frozen

- Everything under `app/` and `ui/`.
- Every other file under `tools/`.
- Every file under `tests/`, including the two files below. They arrive already committed.
- Data, configuration, policy, labels and saved runs.

If a test looks wrong, stop and report. Do not edit it.

## Required behaviour

### 1. Provider check (without `--allow-mock`)

Read EVERY `run.started` event of every replayed run (a direct child folder with `case_file.json`) in both snapshots.

- **Mock run.** A run is mock if any of its `run.started` payloads says `"llm_provider": "mock"`. It gets the existing refusal, unchanged: `export_replay: run(s) <ids> were recorded with the mock model; pass --allow-mock to export a test replay`, naming that run.
- **Unreadable run.** A run's provider cannot be read when any of these holds:
  - there is no `events.jsonl`, or it cannot be read (for example it is a directory);
  - there is no `run.started` event (unreadable or invalid-JSON lines are skipped, as now);
  - a `run.started` event's `payload_ref` is missing, not a string, empty, or escapes the run folder. "Escapes" means the resolved path is not inside the resolved run folder: `../other-run/...`, an absolute path elsewhere, and a symlink pointing outside all count;
  - the payload file is missing or not a JSON object;
  - `llm_provider` is missing or is not a non-empty string.

  If any one of a run's `run.started` events is unreadable, the run is unreadable.
- **Unreadable refusal.** Exactly one line: `export_replay: the model provider of run(s) <ids> could not be read; pass --allow-mock to export a test replay`. `<ids>` are sorted and joined with `", "`. Exit 2, and `--out` is left empty. This check runs before recording. Today the server answers 404 for an invalid-JSON payload, so a check placed after recording reports the wrong line.
- **With `--allow-mock`.** Both cases export, with the TEST banner prefix as today.
- **Genuine runs are unaffected.** The parent verified that all 234 stored runs under the repo's `runs/` have a readable `run.started` (tencent or mock). A tencent-provider fixture still exports without `--allow-mock`.
- **Unpinned.** A run that is both mock and unreadable is not pinned. The reference reports it as mock.

### 2. Path refusals (before anything is written)

Resolve `--out`, `--before` and `--after` with `Path.resolve()`. Relative paths resolve against the exporter's cwd. Symlinks are followed. Refuse when:

- `--out` equals, or is inside, `--before` or `--after`;
- `--out` equals, or is inside, the repo's `ui/` or `tools/replay/` folder (the exporter's own inputs);
- `--before` and `--after` resolve to the same folder.

Each refusal prints one `export_replay: ` line, exits 2 and creates nothing. Inputs stay byte-identical. A missing `--out` outside those trees still works, including a sibling whose name only starts with an input's name (for example `before-site` next to `before`).

### 3. Landing step text built from the saved runs

Find NS-0202 by trip id `T-NS0202` the same way RD-0109 is found by `T-RD0109`. Each snapshot must hold exactly one such run, with the same run id in both. Otherwise refuse, as for RD.

Read the facts from the recorded `GET /api/review/<run>/case` bodies (`{case_file, human_decision}`), so the landing page states what the replay shows. In particular, `human_decision` is whatever the server's `load_decision` returned. A record the server ignores (for example one whose `amount_sgd` is not a number) counts as no decision.

Every step text is inserted with `html.escape` (default `quote=True`).

**Field shape.** The contract was checked against the real recorded bodies, and the shape differs in one place:

- `case_file.resolution.ruling` and `case_file.resolution.withheld_candidate` carry `action` and `recommended_amount_sgd`. They do NOT carry `amount_sgd`.
- `human_decision` carries `decision`, `action`, `amount_sgd` and `proposed`.

The phrase rule therefore reads `recommended_amount_sgd` for rulings and proposals, and `amount_sgd` for the human decision. A rejected decision is stored as `action: "no action", amount_sgd: 0.0`.

**Phrase rule.** Apply it to an `action`/amount pair:

| Action | Phrase |
|---|---|
| `"no action"` | `no action` |
| a non-empty string, with a numeric amount (int or float, not bool, finite) | `<action> SGD <amount with 2 decimals>`, e.g. `refund SGD 6.60` |
| a non-empty string, no numeric amount | `<action>` |

A ruling or proposal that is not an object with a non-empty string `action` gives no phrase. That case takes the fallback text below.

**Step texts:**

- **Step 1**, NS-0202, from the after snapshot:
  - If `resolution.outcome` is `"ruled"`, `delivered_to_parties` is `true`, `human_decision` is null and the ruling gives a phrase: `A no-show case the AI decided alone: <phrase of resolution.ruling>`.
  - Otherwise: `A no-show case: <outcome>`. Never refuse here.
- **Step 2**, RD-0109, from the before snapshot:
  - If `outcome` is `"withheld"`, `human_decision` is null and `withheld_candidate` gives a phrase: `A detour case the AI held for a human: it proposed <phrase of resolution.withheld_candidate>`.
  - Otherwise: `A detour case: <outcome>`.
- **Step 3**, RD-0109, from the after snapshot's `human_decision`:

  | `human_decision.decision` | Step 3 text |
  |---|---|
  | `approve` | `The human approved: <phrase of action/amount_sgd>` |
  | `change` | `The human changed it to: <phrase>` |
  | `reject` | `The human rejected it: no action` |
  | null | `No human decision was recorded` |

  A `decision` value outside those three cannot be produced by `app.human_review.record_decision`. It is unpinned; keep the text true (the reference writes `The human decided: <phrase>`).
- **Step 4**, unchanged: `What the rider sees`.

The links, the title and the recorded-on sentence are unchanged. `<outcome>` is the outcome string; the reference writes `unknown` when it is not a non-empty string, and that case is unpinned.

On the mock fixture the four steps read:

1. `A no-show case the AI decided alone: no action`
2. `A detour case the AI held for a human: it proposed refund SGD 55.16`
3. `The human approved: refund SGD 55.16`
4. `What the rider sees`

### 4. Secret scan

For each secret value (length >= 8), the needles are the UTF-8 bytes of five forms:

- the raw value;
- `json.dumps(v)[1:-1]`;
- `json.dumps(v, ensure_ascii=False)[1:-1]`;
- `html.escape(v)`;
- `urllib.parse.quote(v, safe='')`.

Any hit in any output file refuses with the existing message (`export_replay: refusing to publish: a value from --secrets-file occurs in <relative path>`). The message never contains the value or any of its forms.

### 5. Shim

A request whose pathname is exactly `/api`, or starts with `/api/`, is intercepted:

- GET goes to the manifest, or returns 404 `{"error": "Not in this replay."}`;
- non-GET gets the existing refusals.

Nothing else changes. `/apiary.json` still passes through to the network.

### 6. Nothing else changes

No other behaviour changes. Existing messages, the order of the other refusals, the manifest, the copies and the banner all stay as they are.

## Acceptance tests (already committed in your baseline)

| File | SHA256 |
|---|---|
| `tests/test_w27_fix_round.py` (new, 54 tests) | `5bf003f35178300e556435459c5b7b9876ea32eb9c754add2c8fec5d82e2b688` |
| `tests/w27_replay_support.py` (amended) | `7ca15816e08c4aeac6de4773fe4b25e78f0839d29c000fe04856e3827e84808a` (was `3ac3a2b3…dfadd86f6`) |

**Existing assertions amended on purpose (1 file, 3 lines).** In `tests/w27_replay_support.py`, `LANDING_STEPS` holds the expected texts that `tests/test_w27_replay_export.py::ExportEndToEnd::test_landing_page_title_and_four_steps` asserts. It encoded the old fixed claims:

| Step | Before | After |
|---|---|---|
| 1 | `("A no-show refund decided by the AI alone", "/party/status.html?snapshot=after")` | `("A no-show case the AI decided alone: no action", "/party/status.html?snapshot=after")` |
| 2 | `("An above-cap detour held for a human", "/index.html?snapshot=before&run=%(rd)s")` | `("A detour case the AI held for a human: it proposed refund SGD 55.16", "/index.html?snapshot=before&run=%(rd)s")` |
| 3 | `("The human approves the held ruling", "/index.html?snapshot=after&run=%(rd)s")` | `("The human approved: refund SGD 55.16", "/index.html?snapshot=after&run=%(rd)s")` |

Two comment lines were added above the list. The hrefs, step 4 and everything else are unchanged. No other existing test contradicts this contract. `tests/browser/w27_replay_browser.cjs` checks only the step count and hrefs, and it passes unchanged.

**Doc pins.**

- The existing `ReplayDoc` needles stay satisfiable: `tools/export_replay.py`, `--before`, `--after`, `--recorded-on`, `--out`, `--allow-mock`, `--secrets-file`, `replay/index.html`, `NS-0202`, `RD-0109`, and a heading containing "recording day".
- The new file adds `ReplayDocFixRound`. `docs/replay.md` must contain three strings, each on one line: `could not be read`, `T-NS0202` and `No human decision was recorded`.

**What the tests cover:**

- **Provider gate.** Each unreadable shape: no events file, events as a directory, no `run.started`, an invalid-JSON `run.started` line, `payload_ref` missing/not a string/empty/`../`/absolute/symlink escape, payload file missing/not an object/not JSON, `llm_provider` missing/not a string (7, null, list)/empty, and a later unreadable `run.started`. Also: two unreadable runs sorted, a later `run.started` saying mock, mock in the after snapshot only, `--allow-mock` exporting an unreadable fixture with the TEST prefix, and tencent with two `run.started` events exporting without the prefix.
- **Path refusals.** `out == before`, out inside before, out inside after through a symlink, out inside `ui/` (relative path), out inside `tools/replay/` (spelled via `app/..`), and `before == after` (plain and via symlink). Each leaves inputs byte-identical and `--out` absent. A `before-site` sibling still exports.
- **Landing.**
  - Mock fixture.
  - Change (SGD 40), with NS-0202 undelivered and RD-0109 ruled before.
  - Reject, with NS-0202 withheld and RD-0109 decided before.
  - No decision (after is a separate copy of before), with NS-0202 carrying a human decision.
  - NS-0202 refunded SGD 6.6 → `6.60`, with a decision the server ignores.
  - Actions without an amount, and a change to no action.
  - HTML escaping of `<b>"R&D"</b>` and `held & 'waiting'`.
  - NS-0202 missing, duplicated, or with different run ids.
- **Secrets.** Natural recorded-body leaks: non-ASCII, `"` and `\`. Planted bodies (stubbed server bytes) for the raw, JSON-ASCII, JSON-unicode, HTML-escaped and percent-encoded forms, plus a planted body with no secret that still exports.
- **Shim.** `/api` GET, `/api?x=1`, POST and PUT are intercepted. `/apiary.json` passes through. `/api/demo/rider` still answers.

The path tests probe `ui/w27-fix-probe-*` and `tools/replay/w27-fix-probe-*` and remove them again. If a run is interrupted, delete any leftover `w27-fix-probe-*` folder. Never commit one.

```sh
env -u PYTHONPATH /usr/bin/python3 -B -m unittest tests.test_w27_replay_export tests.test_w27_replay_shim tests.test_w27_replay_prompts tests.test_w27_fix_round
env -u PYTHONPATH /usr/bin/python3 -B -m unittest discover -s tests -t .
```

## Measured proof (parent's scratch, not transferred)

- **Baseline `1ae5a84` plus the two test files.**
  - Focused: 97 tests, 50 failures (47 test methods, subtests counted), 0 errors.
  - Full: 1341 tests, the same 50 failures, 0 errors.
  - Every failure is in `tests/test_w27_fix_round.py`, plus the amended `test_landing_page_title_and_four_steps`.
  - Eight tests in the new file pass on the baseline on purpose. They pin behaviour that must survive: mock in after only, `--allow-mock` with an unreadable provider, tencent with two `run.started`, `out == before` (already refused as non-empty), the `before-site` sibling, the raw planted form, an unrelated planted body, and `/apiary.json` passthrough.
- **Disposable reference.** Focused 97 OK. Full 1341 OK (skipped=1). The real-browser gate `tests/browser/w27_replay_browser.cjs` passed at 390 and 1280 px against a reference export served on 127.0.0.1:18782.
- **Mutation battery.** 57 literal mutations against the reference, run under both the focused and the full suite: 57/57 killed by assertion failures in the target tests, 0 errors, 0 survivors, unmutated baseline GREEN.

The battery literals target the reference. Re-aim them at your shipped source before anyone treats them as proof of your build.

## What you should see when done

- Focused: 97 tests, OK.
- Full suite: 1341 tests, OK (skipped=1).
- The mock export's `replay/index.html` lists the four texts above.
- `python3 tools/export_replay.py --before X --after X ...` refuses with one `export_replay: ` line.
- On a tencent-copy fixture with `events.jsonl` removed from one run, the export refuses with exactly `export_replay: the model provider of run(s) <that run> could not be read; pass --allow-mock to export a test replay`.

## Dispatch protocol

1. Work only inside this worktree. No other worktree, and no reads of planning, scratch or reference folders.
2. No subagents, no web/network/API calls, no package installs, no memory or config writes, no screenshots, and no unrelated files.
3. Read `CODEBUDDY.md` and this brief. The scope carve-outs here supersede older write freezes, for this task only.
4. Use `/usr/bin/python3` with `PYTHONPATH` removed.
5. Any server you start for a check binds port 0 or a port in 18800-18899, never 8000 or 8765.
6. Run the focused suite and the full suite, and report any remaining failures by test path.
7. The parent owns the combined full GREEN, the browser gate and the review.
8. Commit ONLY the allowed paths, with an explicit `git add <path>` for each one. Never `git add -A`, never merge, never push.
9. End your response with the commit hash, the full list of changed files, and the actual focused and full results.
10. If a tool is denied, stop and report the tool and the exact command.

Expected sibling RED (planner, measured on the combined RED tree): the W24 fix lane's deliberately failing tests are committed in the same baseline. Your full suite therefore runs 1366 tests and, before your fix, fails 67: 49 in `tests/test_w27_fix_round.py` and 1 in `tests/test_w27_replay_export.py` (yours), plus 14 in `tests/test_w24_fix_round.py` and 3 in `tests/test_w24_file_read_guard.py` (sibling). After your fix exactly the 17 sibling failures may remain, 0 errors. Never edit the sibling's files or its acceptance assertions.

Post-merge test tightening (planner, 2026-10-07, the operator approved): the shipped-code battery left two survivors that were test gaps, not code defects (D01 doc refusal line, L20 approval phrase sourced from the proposal). `tests/test_w27_fix_round.py` gained `test_an_approval_states_the_decision_record_not_the_proposal` and `test_docs_replay_quotes_the_unreadable_provider_refusal_in_full`; both pass on 7bcba8a and fail by assertion under L20 and D01 respectively. New SHA256 of that file: `63f16e740de7f49e26b47f339f93377748a9c9cb7d11d6735e5103b612929228`. No shipped code changed.
