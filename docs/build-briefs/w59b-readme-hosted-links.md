# W59b: README points to the hosted EdgeOne sites

The operator asked for the README to link the three copies hosted on Tencent EdgeOne, so a reader
can try the project without installing anything. This is a documentation-only change.

## Only this path may change

- `README.md`

Do not edit any other file: no `app/`, `ui/`, `tests/`, `data/`, `docs/`, `deploy/`, `tools/`,
`evidence/`, `CODEBUDDY.md`, settings or briefs.

## Change 1: new first bullet under `## Start here`

Directly before the line that begins `- **Try it without a key:** [Run](#run).`, insert exactly
these seven lines (two-space continuation indent, as in the other bullets):

```text
- **Try it online, nothing to install:** three copies are hosted on Tencent EdgeOne. The
  [live AI site](https://ryde-dispute-live.edgeone.dev) runs the real Tencent model, with filings
  limited per visitor and per day ([deploy notes](deploy/edgeone/README.md)). The
  [practice site](https://ryde-dispute-demo.edgeone.dev) runs the deterministic mock. The
  [guided replay](https://ryde-dispute-replay.edgeone.dev/replay/) walks through one recorded
  real case from filing to human decision. Hosted cases are not permanent: an idle restart or a
  redeploy clears them.
```

## Change 2: one paragraph at the end of `### Live start (approved access only)`

That section ends with the two lines:

```text
does not silently fall back to the mock. If private access is unavailable, use the standard
keyless launchers instead and label the result as mock.
```

Directly after them, add one empty line and then exactly these two lines:

```text
To try the real model without keys, use the hosted [live AI site](https://ryde-dispute-live.edgeone.dev)
listed under [Start here](#start-here).
```

Change nothing else in the README, including line wrapping elsewhere.

## Verify

Use the system interpreter by absolute path with `PYTHONPATH` removed:

```sh
env -u PYTHONPATH /usr/bin/python3 -B -m unittest tests.test_adp_adapter tests.test_adp_hardening tests.test_architecture_doc tests.test_w16_driver_pages tests.test_w22_docs tests.test_w22_unproven_figures tests.test_w23_docs tests.test_w28_unproven_refunds tests.test_w29_no_show_refund_ceiling tests.test_w34_launcher tests.test_w43_should_rd5_floor tests.test_w43_should_run_id tests.test_w47_submission_package
```

These are every test module that reads `README.md`. It must report OK with zero failures and zero
errors (two skips are expected: archived-baseline checks that need an environment variable this
session does not set). Then run `git diff --stat` and confirm only `README.md` changed. Do not
open the URLs; the parent checked all three sites respond.

## Commit and report

`git add README.md` only. Never `git add -A`, merge, push, stash, reset or rebase. No subagents
and no network. Commit message:

```text
W59b: README links the hosted EdgeOne live, practice and replay sites
```

Report the commit id, the files changed and the exact test output lines.
