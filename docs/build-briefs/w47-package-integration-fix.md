# W47: fix actual-source packaging and release wording

This is a delta to the original W47 brief. the operator authorized scoped local commits, Luna-max build/fix work, GLM review and merge only after verification. No push, real Tencent app calls, keys, rotation or credential handoff. Resume the existing Luna session at this integration item. Do not redo its completed launcher work or its initial absent-file preflight.

## What the parent actually reproduced

The committed branch has the six permitted production files and its focused tests pass. But packaging its actual Git tree, rather than the tiny test fixture, refuses four preserved evidence transcripts:

- `evidence/conversation-history/2026-09-28_codebuddy-cli_03-tencent-adp-adapter.jsonl`
- `evidence/conversation-history/2026-09-29_codebuddy-cli_04-adp-hardening.jsonl`
- The corresponding two files under `evidence/conversation-history/archive/`.

The parent classified the matched bearer examples without printing values. Each is a literal `<KEY>` example, not a populated bearer credential. The current `authorization...bearer...\S+` matcher also consumes JSON-escaped newlines and closing Markdown/JSON delimiters. This makes the complete-source package impossible even though the small fixture tests pass. All four historical files must remain byte-identical and included. Do not delete, redact, rewrite or exempt evidence files, extensions or whole directories.

The short live-copy instructions also assert three things too strongly: that this is always a private rehearsal, that the live launcher is the only route in the source tree that selects Tencent, and that no actual key is present before the private real-key comparison has happened. Existing direct server/CLI entry points can select Tencent; the package-purpose field distinguishes rehearsal from submission; the narrow scan is not a complete absence proof.

## Allowed change

Only:

- `tools/package_submission.py`
- `docs/live-copy.md`

Do not change the live helper, wrappers, UI, tests, app, data, policy, old launchers, evidence, settings or other documents. The new acceptance tests are parent-owned and already committed. No broad scanner weakening or new imports beyond the existing acceptance import allowlist.

## Fix contract

1. Recognize the exact documented literal `<KEY>` bearer placeholder, including its ordinary Markdown closing delimiter and JSON-escaped newline/closing delimiter forms. Treat case variants of the literal marker consistently. Do not treat a real token, an unknown angle-wrapped token, or `<KEY>` followed by an attached non-placeholder suffix as that marker. An opaque non-placeholder bearer value remains a refusal. Retain the other content/path/sidecar/private-key/LFS protections.
2. Handle serialized transcript text narrowly. Do not omit JSONL evidence or skip content scanning by path. Preserve every committed evidence byte and its inclusion.
3. Keep synthetic negative fixtures assembled at runtime so the acceptance test source itself remains packagable. Never read actual keys or credential stores to debug this item.
4. Make live-copy wording apply to either package purpose. Tell readers to inspect `MANIFEST.json`'s `package.purpose`; private rehearsal is not public-release clearance. Describe the supplied live entry point without denying the existing raw server/CLI routes. Replace the factual guarantee of actual-key absence with the prohibition on including keys and the separate real-key comparison gate. Preserve the accepted script's separate handoff and the older script's included-source status.
5. Prove an actual-source ZIP is now created from the branch's committed HEAD, with all four evidence files included byte-for-byte. Use explicit `--repo`, `--revision`, `--purpose rehearsal`, `--out` outside this repository. Package only after the scoped fix is committed so the source is unambiguous. Do not distribute the resulting candidate.

## Verification and Git protocol

Read the new tests:

- `tests.test_w47_submission_package.PackageInterface.test_bearer_examples_do_not_hide_credential_like_values`
- `tests.test_w47_submission_package.PackageInterface.test_live_copy_claims_match_the_release_and_available_entry_points`

The first includes both benign plain/Markdown/JSON examples and synthetic non-placeholder values. The second pins truthful release and entry-point wording. Make both and the existing acceptance suite green without editing tests.

Use the existing writable TMPDIR. Remove `PYTHONPATH` and `W47_BASELINE_TREE` for builder runs. No actual app-model request is needed:

```sh
env -u PYTHONPATH -u W47_BASELINE_TREE /usr/bin/python3 -B -m unittest tests.test_w47_live_launcher tests.test_w47_submission_package tests.test_w34_launcher -v
```

Report opt-in skips explicitly. Do not attempt one long full-suite run in a short foreground tool call; the parent owns authoritative extracted-package/browser/full-suite/mutation checks.

Stage and commit only `tools/package_submission.py` and `docs/live-copy.md` by name. No `git add -A`, test edit, merge, push, stash or reset. The parent installs the committed test delta into this clean branch before resuming you. The parent owns rollback and the independent GLM review. If the exact example exception is insufficient, report the new value-free classification rather than inventing a broader exemption.

Report the new scoped commit, real focused test results, actual-source packaging result, evidence-byte/inclusion checks and remaining limits. Stop for a protected-file change, a test contradiction, a denied tool, an unexpected actual secret indicator, or a need to widen this two-file scope.
