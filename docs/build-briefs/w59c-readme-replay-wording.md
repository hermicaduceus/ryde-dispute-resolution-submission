# W59c: README replay description says two cases, not one

An independent review of W59b found that the README describes the guided replay as "one recorded
real case", but the replay page plays back two: a no-show the AI decided alone, and a detour it held
for a human decision. This is a documentation-only wording correction.

## Only this path may change

- `README.md`

Do not edit any other file.

## The change

In the `## Start here` section, replace exactly these three lines:

```text
  [guided replay](https://ryde-dispute-replay.edgeone.dev/replay/) walks through one recorded
  real case from filing to human decision. Hosted cases are not permanent: an idle restart or a
  redeploy clears them.
```

with exactly these three lines:

```text
  [guided replay](https://ryde-dispute-replay.edgeone.dev/replay/) plays back two recorded real
  cases: a no-show the AI decided alone, and a detour it held for a human decision. Hosted cases
  are not permanent: an idle restart or a redeploy clears them.
```

Change nothing else in the README.

## Verify

Use the system interpreter by absolute path with `PYTHONPATH` removed:

```sh
env -u PYTHONPATH /usr/bin/python3 -B -m unittest tests.test_adp_adapter tests.test_adp_hardening tests.test_architecture_doc tests.test_w16_driver_pages tests.test_w22_docs tests.test_w22_unproven_figures tests.test_w23_docs tests.test_w28_unproven_refunds tests.test_w29_no_show_refund_ceiling tests.test_w34_launcher tests.test_w43_should_rd5_floor tests.test_w43_should_run_id tests.test_w47_submission_package
```

It must report OK with zero failures and zero errors (two skips are expected). Then run
`git diff --stat` and confirm only `README.md` changed. Do not open any URL.

## Commit and report

`git add README.md` only. Never `git add -A`, merge, push, stash, reset or rebase. No subagents and
no network. Commit message:

```text
W59c: README says the guided replay plays back two recorded cases
```

Report the commit id, the files changed and the exact test output lines.
