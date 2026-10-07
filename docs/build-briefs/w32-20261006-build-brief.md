# W32 build contract

Prepared against main `d50a89157cf9211aa1d5dce0ab13c1f08f552356`. This is a prompt clarification, not a money-policy change.

## Allowed files

- `app/agents/judge.py`
- `docs/prompts.md`

Do not modify tests, tools, data, configuration, UI, any other app module, policy, labels or saved runs. If a test looks wrong, stop and ask. No live model calls, credentials, provider changes, or paid verification.

## Required change

Add this exact sentence once to the actual Judge system prompt sent through the LLM request:

"deviation_fare_delta_sgd is the difference between the quoted fare and the metered fare for the route taken, not money the rider paid."

It must not exist only in a comment, user prompt, documentation or unused string. Preserve every existing system-prompt byte after removal of the sentence and its one adjoining separator. The acceptance helper accepts a space or newline next to the addition. Do not change existing role text, confidence instructions, evidence-citation instructions, HARD_RULES, output schema, user prompt or Python money gates.

The comment-free Judge AST is frozen to the baseline after stripping only the added sentence from string constants inside `Judge.system_prompt`. Formatting and comments are not money-policy changes. No new symbol or API is required. Tests use the existing `Judge.run`, `ScriptedLLM.complete` request seam, and `tests.support`.

In the `## Judge` section of `docs/prompts.md`, quote the exact shipped sentence once. Explain only what the system prompt says. Do not claim the change fixes live accuracy, improves autonomy, or changes a saved live result. Preserve the document's existing explanation that prompts request behavior while Python gates enforce delivery.

## Acceptance test

Parent transfers only this new file into the builder worktree:

`[USER_HOME]/.hermes/cache/scratch/w32-prep-20261006/tests/test_w32_judge_prompt.py`

Destination: `tests/test_w32_judge_prompt.py`.

SHA256: `bdaae2cd827bf5a23db83540ed356492ebed3e7e3ef3565a07cc7b6556cddfaf`.

Seven tests cover actual LLM request placement and uniqueness, absence from case-material user prompt, byte preservation of prior system instructions, comment-free Judge AST preservation, Judge-section exact quote equality, and retained RD-4/RD-5 withholding of scripted RD-0105/RD-0106 candidate refunds. Five tests pass on baseline because they preserve existing behavior. Two tests are intentionally RED. Existing tests updated on purpose: none.

Run from the builder worktree, with scratch TMPDIR if needed:

```sh
env -u PYTHONPATH /usr/bin/python3 -m unittest tests.test_w32_judge_prompt -v
env -u PYTHONPATH /usr/bin/python3 -m unittest discover -s tests -t .
```

## Measured proof

Independent tracked-source RED and REF trees are under `[USER_HOME]/.hermes/cache/scratch/w32-prep-20261006/`. REF is disposable preparation only. Parent must audit and delete it before dispatch. No REF implementation code is to be transferred to the builder.

- Unchanged RED: 7 focused tests, 2 assertion failures, 0 errors. Full suite: 1171 tests, the same 2 failures, 0 errors.
- Disposable REF: 7 focused tests OK; 1171 full tests OK. No older acceptance conflict.
- Final mutation data: `mutations.json`, 14 unique literal edit sets. Each applies exactly once per edit and causes W32 assertion failure in both focused and full runs, zero errors or survivors. Includes sentence deletion, paid-meaning contradiction, each quoted/metered/route distinction, difference changed to sum, duplication, comment-only and user-only placement, doc drift/wrong section/duplication, prior prompt drift, and money-ceiling drift.
- Evidence: `proof-results.json`, `mutation-results.json`, `source-test-hashes.json`, raw `logs/`, and `artifact-hashes.json`.

Re-aim literal mutations at the independent shipped source before post-build verification. Do not treat reference-targeted literals as shipped proof.

## What should be seen when done

Focused suite: 7 OK. Full suite at this baseline with only W32 transferred: 1171 OK. Existing money gates remain unchanged. These checks prove prompt construction, documentation alignment and preservation, not a live model's future judgment. A later W20 merge may increase the combined suite count and is outside this brief.


## Dispatch protocol

Work only inside this worktree. No other worktree or planning/scratch/reference reads. No subagents, web/network/API calls, package install, memory/config writes, or screenshot. No unrelated files. Read CODEBUDDY.md and this brief; scope carve-outs here supersede older write freezes only for this task. Use `/usr/bin/python3` with `PYTHONPATH` removed. Your sibling lane starts from the same prepared baseline and deliberately RED tests are committed: never repair your sibling's files or acceptance assertions. Run your focused suite plus the full suite and report remaining failures by test path, expected sibling RED vs any regression. Parent owns actual combined full GREEN, browser gates and review. Commit ONLY the allowed paths, explicit git add, never git add -A, never merge or push. End response with commit hash, full changed-file list and actual focused/full results. If tools denied, stop and report the tool and exact command.

Expected sibling RED: W20 validation/Back tests and new W16 refusal fixture. Do not edit them.
