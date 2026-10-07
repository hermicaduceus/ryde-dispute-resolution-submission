# W16 second-model repair: F1 only in the CodeBuddy lane

the operator authorized repairing the findings in this session and requires W16 to stay separate from main. The operator already made parent-owned F2/F3 test repairs and F4 wording cleanup. Do not undo them. Work only in this launch worktree, branch w16-driver-intake, base HEAD 71eb71a, existing W16 code uncommitted. Do not read the planning repo or scratch reference/snapshot directories.

## Required change

At shared party.js boot, a missing data-filed-by marker defaults to rider. After that, accept only literal rider or driver. An inherited object property such as constructor, __proto__, toString, hasOwnProperty, valueOf or isPrototypeOf is not a role. Every other explicit value must show the existing approved error in the visible category-error element and return before rendering categories, binding filing handlers or fetching trips. Do not change the error copy or either valid role's behaviour. No URL, account or authentication changes.

The current code indexes plain-object role tables and accepts any truthy lookup, so those prototype names reach CATEGORIES.forEach and crash. The operator extended tests.test_w16_driver_pages.DrivenPages.test_invalid_explicit_marker_disables_all_requests to cover all six names. On your current source this test yields six assertion failures, zero errors. The operator also initialized error-node hidden states to match the real HTML and requires the exact error text in category-error and visible ancestors. tests.test_w16_driver_contract.TablesAndSlots.test_malformed_selector_and_enum_are_total now checks both rider and driver malformed categories, including the rider default. Production Python is already correct and is FROZEN in this repair.

## Exact write fence

Only:
- ui/party/party.js: the narrow role refusal guard at boot.
- tests/test_party_rebrand.py: PARTY_JS_SHA value only.
- tests/test_w12_demo_notice.py: matching party.js digest value only.

The two digest rebaselines are authorized only after rider+driver behavioural tests pass; compute the values from actual shipped party.js bytes. All other code, tests, docs, parent amendments, data, policy, fixtures and files are read-only. No new dependency, commit, stash, merge, push, memory edit, paid provider or default server launch. Main/rehearsal is outside this scope and must remain untouched. Do not modify the old docs/build-briefs/w16-acceptance-manifest.json; it records historical pre-build bytes. docs/build-briefs/w16-repair-acceptance-manifest.json records the operator's current files before this repair.

## Commands and acceptance

Every terminal command uses TMPDIR=[USER_HOME]/.hermes/cache/scratch/w16-staged-tmp. Use /usr/bin/python3 -B.

1. Read this brief and the new repair manifest. Present a short plan and wait for operator approval before editing.
2. Confirm the invalid-marker test fails for the six prototype names. Make the smallest guard repair.
3. Run the 33 W16 tests: /usr/bin/python3 -B -m unittest tests.test_w16_driver_contract tests.test_w16_driver_filing tests.test_w16_driver_pages. Require green.
4. Compute party.js SHA-256; update only the two authorized digest values.
5. Run /usr/bin/python3 -B -m unittest discover -s tests -t ., require all green, no skips.
6. Compare every repair-manifest file against its pre-repair bytes. Only party.js and the two expected digest literals may differ. Existing uncommitted changes against HEAD are the original build plus parent test/doc fixes, not your changes. Do not use git diff against HEAD to claim you made all of them.
7. Report exact commands, exit status/counts, actual shipped hash and the three changed paths. No commit or merge.

Stop on conflicts instead of widening the fence. The operator owns mutation/revert proof, browser verification and second-model re-verification after your repair.
