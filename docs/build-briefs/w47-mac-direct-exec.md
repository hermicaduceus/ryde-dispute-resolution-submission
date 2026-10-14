# W47: direct shell argument forwarding, no exec override

This supersedes only the Mac-wrapper mechanics of the prior review-fix brief. All successful packager/doc corrections are complete and must not be repeated.

The parent discovered that the old exact-line regex incorrectly rejected normal `exec ... "$@"`. Parent corrected that owned test to require direct quoted argument forwarding and prohibit replacing Bash's exec builtin. The real argument-boundary test remains unchanged. No test edits are permitted by the builder.

Only permitted production edit: `start-live.command`. Replace this exact tail:

```sh
_live_args=("$@")
exec() {
  builtin exec "$@" "${_live_args[@]}"
}
exec python3 tools/launch_live.py
```

with:

```sh
exec python3 tools/launch_live.py "$@"
```

Keep every preceding byte, LF-only line endings and executable 0755 mode unchanged. No other files, new abstractions, investigation or refactoring. The test was defective, so do not devise another workaround.

Run only:

```sh
env -u PYTHONPATH -u W47_BASELINE_TREE /usr/bin/python3 -B -m unittest tests.test_w47_live_launcher.StartLiveCommand tests.test_w47_review_pins.MacArguments -v
```

Stage/commit ONLY `start-live.command`, explicitly. Report the scoped commit and test result, then stop. No subagents, other production/test/docs edits, actual credentials, app-model calls, merge or push. Parent runs full verification and GLM confirmation separately. the operator's existing local-build authorization applies, no new external actions.
