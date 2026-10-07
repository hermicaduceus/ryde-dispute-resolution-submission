# W27 follow-up: export path guards compare folders, not spelling

Prepared against main `c4fc33c` (full suite 1368 OK, skipped=2). You resume the W27 session in its worktree. One function changes; nothing else.

## What is wrong (reproduced)

`tools/export_replay.py` `_refuse_unsafe_paths()` compares `Path.resolve()` results with `==` and `is_relative_to`. On macOS's default case-insensitive disk `resolve()` keeps the letters as typed, so `UI` and `ui` are one folder but different strings. `--out <repo>/UI/x` therefore passes the guard and the replay site is written into the real `ui/`; a case-changed spelling of `--before`/`--after` passes the same way, and `--before X --after x` (same folder) is accepted.

## Required behaviour

1. Every guard in `_refuse_unsafe_paths()` decides "is this the same folder / inside it" by disk identity (for example `os.path.samefile` on `--out` and each of its existing parent folders), not by comparing path strings. This covers `--out` inside `--before`, `--after`, the repo's `ui/` and `tools/replay/`, and `--before`/`--after` being the same folder.
2. Refusal lines, exit code 2 and "nothing created, inputs unchanged" stay exactly as today. A folder beside the inputs whose name differs by more than letter case still exports.
3. No other behaviour changes.

## Allowed files

- `tools/export_replay.py` only (add `import os` if you need it).

Do not modify any test, doc, `app/`, `ui/` or any other file. If a test looks wrong, stop and report.

## Acceptance tests

The planner committed `tests/test_w27_case_paths.py`, SHA256 `d0285992bc565791ba635e6f15e2d31da3b63aa5b956e1f47c28441c69a10ecd`: 6 tests, run only on a case-insensitive disk (this Mac is one). On `c4fc33c` 5 fail by assertion with 0 errors; the sixth is the sibling-folder control and passes. A disposable reference (one function plus two small helpers) made focused 105 OK and full 1374 OK, and six planted bugs (check only `--out` itself, compare by spelling, same-folder check by spelling, drop the ui/, tools/replay/ or input check) each turned the tests red by assertion. No reference code is transferred to you.

```sh
env -u PYTHONPATH /usr/bin/python3 -B -m unittest tests.test_w27_case_paths tests.test_w27_fix_round tests.test_w27_replay_export tests.test_w27_replay_shim tests.test_w27_replay_prompts
env -u PYTHONPATH /usr/bin/python3 -B -m unittest discover -s tests -t .
```

Expected when done: focused 105 OK; full 1374 OK (skipped=2); `git diff --stat` shows only `tools/export_replay.py`.

## Dispatch protocol

Work only inside this worktree. No other worktree or planning/scratch/reference reads. No subagents, web/network/API calls, package install, memory/config writes or screenshots. Use `/usr/bin/python3` with `PYTHONPATH` removed. Any server you start binds port 0 or a port in 18800-18899. Run the focused suite and then the full suite and report any failures by test path. Commit ONLY `tools/export_replay.py` with an explicit `git add tools/export_replay.py`; never `git add -A`, never merge, never push. Do not run `rm -rf`. End your response with the commit hash, the full changed-file list and the actual focused/full results. If a tool is denied, stop and report the tool and the exact command.
