# W27 build contract: static replay exporter

Prepared against main `023d2ccb7e4897b02d8828009a00097bcb220a7f` (full suite 1190 OK on `env -u PYTHONPATH /usr/bin/python3 -B`). Rulings in force: R1 (a) lane B adds the console `?run=<run_id>` deep link; R2 (a) before/after snapshots; R3 (c) guided walk-through; R4 (a) mock refusal unless `--allow-mock`; R5 (a) `ui/styles.css` untouched.

## Allowed files

- `tools/export_replay.py` (new)
- `tools/replay/replay-shim.js` (new)
- `tools/replay/index.html` (new)
- `docs/replay.md` (new: how to run it on recording day)

Do not modify tests, `app/`, `ui/` (no file under `ui/` changes, `ui/styles.css` included), data, configuration, policy, labels or saved runs. `tools/` is non-app: nothing in `app/` or `ui/` may import or load these files except through the exported site. If a test looks wrong, stop and ask. No live model calls, credentials, network, deploy or EdgeOne work.

## Required behaviour

### CLI

```sh
python3 tools/export_replay.py --before DIR --after DIR --recorded-on YYYY-MM-DD --out DIR \
    [--allow-mock] [--secrets-file PATH]
```

- Runs from the repository root as a plain script: insert the repository root into `sys.path` so `app` imports. Tests run it with `/usr/bin/python3 -B`, `PYTHONPATH` unset, cwd = repo root.
- Ends with `sys.exit(main())` under `if __name__ == "__main__":`. Tests also run it in-process through `runpy.run_path(<path>, run_name="__main__")` with `sys.argv` patched, with `app.server.make_server` and `app.server.RydeRequestHandler._route_api_get` patched. Reach the server only through `app.server.make_server` (a module attribute lookup or an import executed while the script runs both see the patch); never start a second server implementation.
- Exit 0 on success. Every refusal exits **2**, prints ONE line on stderr that starts with `export_replay: `, and leaves nothing in `--out` (absent, or the empty folder it was). The server's own request log also goes to stderr; tests read only the `export_replay: ` lines.
- `--secrets-file` defaults to `.env` at the repository root (`app.config.DEFAULT_ENV_PATH`); parse it the way `app.config.load_env_file` does (`#` comments, `export ` prefix, quoted values). A missing file means no secrets to check.

### Inputs

`--before` and `--after` each hold run folders (direct children with `case_file.json`) plus the `dispute.json` party records the server wrote, exactly as `app.server` expects in its out_dir.

### Recording (per snapshot label, `before` then `after`)

1. Copy that folder to a temp directory and start `app.server.make_server(0, out_dir=<the copy>, llm=<an LLMClient whose complete() raises>)` in a thread. Never pass the input folder itself; never pass `llm=None` or a mock.
2. GET every REQUIRED URL. Any status other than 200 refuses, the line naming the URL (path and query):
   `/api/review/queue`, `/api/review/overrides`, `/api/demo/rider`, `/api/demo/driver`, `/api/trips?category=<c>` for each category the party pages offer, and per replayed run `/api/disputes/<case_file.dispute_id>`, `/api/review/<run_id>/case`, `/api/review/<run_id>/payloads/<name>` for every file in that run's `payloads/`.
   Categories: read at export time from the option lists in `ui/party/*.js` (`{ id: "<value>", label: ... }`, rider and driver lists, first-seen order). The `.html` pages carry no category values; `party.js` renders them. Today that is `route_deviation, no_show_charge, property_damage_mess, safety_incident, other`.
3. GET the OPTIONAL URL `/api/review/<run_id>/prompts` per run: 200 is recorded, 404 is omitted, anything else refuses naming the URL.
4. Save each 200 body byte-for-byte to `<out>/replay/data/<label>/<NNNN>.json` (four digits, numbered in request order, deterministic for identical inputs) and write `<out>/replay/data/<label>/manifest.json` as `{"GET <path?query>": "<NNNN>.json"}`, the key being exactly the request path and query. No other files in that folder.
5. Shut the server down.

### Static site

- Copy every file under `ui/` to `<out>/` at the same relative path, byte-identical, except that every `.html` gets exactly ONE added line `<script src="/replay/replay-shim.js"></script>` (leading whitespace allowed, newline-terminated) inserted immediately after the `<head>` line, before any other script.
- Write `<out>/replay/replay-shim.js` and `<out>/replay/index.html` from `tools/replay/`, with every `{{...}}` placeholder filled (no `{{` or `}}` may remain in either file). No other files in `<out>` besides the ui copy, these two and the data folders.
- `{{RD_RUN_ID}}` is the run whose `dispute.json` trip (`trip_data.trip_id` or `trip.trip_id`) is `T-RD0109`. Each snapshot must hold exactly one such run and it must be the same run id in both, else refuse.

### Refusals (exit 2, nothing left in `--out`)

- `--recorded-on` not a real calendar date in exactly `YYYY-MM-DD` form (`2026-02-30`, `2026-10-6`, `20261006`, `2026-10-06T00:00`, a leading space are all refused).
- `--out` exists and is not empty (its existing files are left untouched). A missing `--out` is created; an existing empty one is accepted.
- Without `--allow-mock`: any replayed run (either snapshot) whose `run.started` event payload says `"llm_provider": "mock"`. The line names that run id, and only mock runs.
- Any secret value (length >= 8 from `--secrets-file`) found in ANY output file: ui copies, shim, landing page or recorded data. The line names the output file by its path relative to `--out` (posix, for example `replay/data/after/0036.json` or `app.js`) and never contains the value. Scan before anything is moved into `--out`.
- Never modify `--before`/`--after`: every input file's sha256 and the file list are equal before and after.

### Shim (`tools/replay/replay-shim.js`, plain ES5 like `ui/app.js`)

No `=>`, template literals, `let`, `const`, `class`, `async`, `await` (checked on the comment-stripped exported file). Build the banner with DOM methods (`createElement`, `createTextNode`, `setAttribute`, `id`, `appendChild`, `insertBefore` or `prepend`); `innerHTML` is not modelled by the test driver. It runs in `<head>`, where `document.body` is still null.

- Snapshot: `?snapshot=before|after` from `location.search`, else the value in `sessionStorage`, else `"after"`; any other `snapshot` value is ignored. Store the result in `sessionStorage` so in-site navigation keeps it.
- Wrap `window.fetch` (string URL, optional init; method case-insensitive, default GET):
  - GET whose `"GET " + pathname + search` is a key of the current snapshot's manifest: `Response(200, <the recorded file's bytes>)`.
  - Any other GET under `/api/`: `Response(404, {"error": "Not in this replay."})`.
  - POST `/api/review/<run>/decision`: `Response(403, {"error": "This is a replay. In the recorded run, the reviewer chose: <decision>, SGD <amount>. Use 'Show after the decision' in the banner to see the result."})`, read from the AFTER snapshot's recorded `GET /api/review/<run>/case` body's `human_decision`, whichever snapshot the page is on. `<amount>` has two decimals (`40` -> `40.00`); omit `, SGD <amount>` when the amount is null. A run with no recorded decision gets the next sentence instead.
  - Any other non-GET under `/api/`: `Response(403, {"error": "This is a replay. The recorded rider filed this case already. Use the replay page's steps to see what happened next."})`.
  - Nothing under `/api/` ever reaches the network. Non-`/api/` requests pass through to the original fetch.
- Banner: once the body exists, insert as the FIRST child of `<body>` exactly one `<div id="replay-banner" role="note">` whose text before the link is `Replay of saved runs recorded on <recorded-on>, before the human decision. Forms work as a guided walk-through; nothing you submit is processed.` (`after the human decision` on after pages), followed inside the same div by `<a id="replay-switch">` reading `Show after the decision` on before pages and `Show before the decision` on after pages, linking to the same pathname with `snapshot` flipped and every other query parameter kept. With `--allow-mock` the sentence starts `TEST REPLAY (mock model). `; without it, no prefix.

### Landing page (`tools/replay/index.html`)

Title `Ryde dispute resolution: replay`; shows the recorded-on date; ONE `<ol>` of four `<li>`, one link each, in order:

1. `A no-show refund decided by the AI alone` -> `/party/status.html?snapshot=after`
2. `An above-cap detour held for a human` -> `/index.html?snapshot=before&run={{RD_RUN_ID}}`
3. `The human approves the held ruling` -> `/index.html?snapshot=after&run={{RD_RUN_ID}}`
4. `What the rider sees` -> `/party/status.html?snapshot=after`

Steps 2 and 3 rely on lane B's `?run=` console deep link (R1). Until lane B merges, the console opens on the queue.

### `docs/replay.md`

A recording-day heading, the full command with `--before --after --recorded-on --out`, `--allow-mock`, `--secrets-file`, the output's `replay/index.html`, and the two replayed cases NS-0202 and RD-0109.

## Acceptance tests

The parent transfers only these files, at these destinations:

| File | SHA256 |
|---|---|
| `tests/w27_replay_support.py` | `3ac3a2b3ad13fb04d0857615c1d7a4c0500179d81835efd97d1d4f0bfadd86f6` |
| `tests/test_w27_replay_export.py` | `47be26391fadede9abb1dcf55fd3c5b8d79650990ec73e08163db24d862d639e` |
| `tests/test_w27_replay_shim.py` | `e56b780c50a6b7571f20ff3a9fb981d5239b6e43f3e15babf750fb69038a4e4f` |
| `tests/test_w27_replay_prompts.py` | `85b607ff9488cf77526f12f0961f9f6ff35bb3ac25d277dea9ccda24dd280146` |
| `tests/browser/w27_replay_shim.cjs` | `1fc019e467b71d65fbb3e800814dde0f7c2820022e3ad9a800152a3133d1f2d3` |
| `tests/browser/w27_replay_browser.cjs` | `cf11f1daaa3710d34fc2f4c2b084415633fce4f6c838997f225ea06546aea46b` (parent-run real-browser gate, not in the suite) |

Source: `[USER_HOME]/.hermes/cache/scratch/w27-prep-20261006/tests/`. 43 tests: export end to end (manifest coverage against the live server, byte-identical copies, landing page, input immutability), refusals, secret scan (data, ui copy, landing page, the 7/8 length boundary), the server contract in-process (temp copy, port 0, refusing model, each REQUIRED URL at 404 and 500, prompts at 404/500/200), the doc, and the shim in a Node vm driver (routing, both refusal sentences, banner text before/after/mock/real, switch link, sessionStorage persistence, unknown GET 404). The fixture is built inside the tests from the real pipeline on the mock (NS-0202 and RD-0109 filed through `POST /api/disputes`, copied to after/, RD-0109 approved with `app.human_review.record_decision`); tests pass `--allow-mock`, except two that rewrite only the `run.started` provider to prove the real-provider path. Existing tests updated on purpose: none.

```sh
env -u PYTHONPATH /usr/bin/python3 -B -m unittest tests.test_w27_replay_export tests.test_w27_replay_shim tests.test_w27_replay_prompts -v
env -u PYTHONPATH /usr/bin/python3 -B -m unittest discover -s tests -t .
```

## Measured proof

Trees under `[USER_HOME]/.hermes/cache/scratch/w27-prep-20261006/` (`red/`, `ref/`, `ref-plusB/`). REF is disposable preparation only; the parent audits and deletes it before dispatch, and no REF code is transferred to the builder.

- Unchanged BASE plus the tests: focused 43 tests, 73 failures (43 test methods, subtests counted), 0 errors. Full suite 1233 tests, the same 73 failures, 0 errors; every other test passes.
- REF: focused 43 tests, only the 4 subtests of `test_w27_replay_prompts` fail (expected sibling RED). Full suite 1233, the same 4, 0 errors. REF plus a lane-B-shaped stub of `/prompts`: full suite 1233 OK.
- Mutation battery: `mutations.json`, 55 unique literal edit sets, each applied exactly once to REF, focused and full suite per row with the sibling-RED prompts file removed (1232 tests). 55 KILLED by W27 assertion failures, 0 survivors, 0 errors; unmutated baseline GREEN. Table: `mutation-table.md`; raw: `logs/battery/`.
- Real browser (Chrome for Testing 154, Puppeteer 25.9, 390 and 1280 px) against a REF export served on 127.0.0.1:18810: passed (`logs/browser-gate.json`); the same gate fails on a shim whose decision POST returns the generic sentence.

Re-aim the literal mutations at the independent shipped source before post-build verification. Do not treat REF-targeted literals as shipped proof.

## What should be seen when done

Focused: 43 tests, exactly 4 failures, all subtests of `tests/test_w27_replay_prompts.py`, 0 errors. Full suite at this baseline with only the W27 files transferred: 1233 tests, the same 4 failures, 0 errors. If lane B's RED file is committed into the same baseline, add its tests and its expected failures to both numbers; nothing else may fail. On the fixture, each manifest holds 35 (before) and 36 (after) entries: 4 fixed, 5 trips, and per run 1 dispute, 1 case and 11 payloads, plus the approval's payload in after. The mock export's banner reads `TEST REPLAY (mock model). Replay of saved runs recorded on 2026-10-06, after the human decision. ...`. These checks prove the export and the shim's routing, not a live recording.

## Dispatch protocol

Work only inside this worktree. No other worktree or planning/scratch/reference reads. No subagents, web/network/API calls, package install, memory/config writes, or screenshot. No unrelated files. Read CODEBUDDY.md and this brief; scope carve-outs here supersede older write freezes only for this task. Use `/usr/bin/python3` with `PYTHONPATH` removed. Any server you start for a check binds port 0 or a port in 18800-18899, never 8000 or 8765. Your sibling lane starts from the same prepared baseline and deliberately RED tests are committed: never repair your sibling's files or acceptance assertions. Run your focused suite plus the full suite and report remaining failures by test path, expected sibling RED vs any regression. Parent owns actual combined full GREEN, browser gates and review. Commit ONLY the allowed paths, explicit git add, never git add -A, never merge or push. End response with commit hash, full changed-file list and actual focused/full results. If tools denied, stop and report the tool and exact command.

Expected sibling RED: `tests/test_w24_prompt_panel.py` (lane B's) and `tests/test_w27_replay_prompts.py`. Both are deliberately failing on the prepared baseline and turn green only on the tree that carries both lanes. Do not edit them.
