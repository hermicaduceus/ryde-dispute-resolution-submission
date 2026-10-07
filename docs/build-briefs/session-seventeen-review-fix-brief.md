# Build session seventeen review fixes — W4 evaluation harness

A glm-5.3 cross-family review of `app/eval.py` found two artifact/failure bugs, three smaller
contract gaps and one input-shape weakness. The operator reproduced every finding and wrote the
RED tests first.

**Target:** `tests/test_eval_harness.py` (45 tests, currently RED with 4 failures + 7 errors)
green, and the full suite (`env -u PYTHONPATH /usr/bin/python3 -m unittest discover -s tests -t .`,
**555 tests**) green.

**Do not edit anything under `tests/`, `tools/`, `data/`, `ui/`, or any doc.** If a test looks
wrong, stop and ask. **Only `app/eval.py` changes.** Every other file stays byte-identical.

## F1 — A failed case must never stop the pack

`app/eval.py`, `run_eval`, per-case handler around `load_dispute` → `run_dispute` → write →
`score_case`.

Today the handler catches only `(DisputeError, PolicyError, LLMError, RuntimeError, ValueError)`.
A provider or scoring bug raising `TypeError`, `KeyError` or `OSError` escapes, aborting the whole
pack and losing the report.

**Fix:** catch `Exception` around the per-case block and turn it into `score_error`, then continue.
Do not use `BaseException`: `KeyboardInterrupt`, `SystemExit` and cancellation must still stop the
process. This catch is deliberately broad at the pack boundary; it is the last isolation wall
between one bad case and every other case.

Tests: `test_unexpected_exception_is_also_contained_per_case`, plus the existing
`test_one_failed_case_does_not_stop_the_run`.

## F2 — Refuse to reuse a pack's output directory

Today `pack_out.mkdir(parents=True, exist_ok=True)` accepts an existing directory. A second run
then appends a second event stream to the same `events.jsonl`, overwrites payload files and makes
old events point at new payloads.

**Fix:** before the first case of any requested pack runs, fail with `EvalError` when
`<out>/<pack>` already exists, naming that path and saying it **already exists**. Never delete,
merge or overwrite it. Preflight every requested pack output path before any case runs, just as
every label file is preflighted before any case runs. Parent `<out>` may exist and contain other
files or other pack directories; only the requested `<out>/<pack>` is exclusive.

There must be no race between checking and creating. Use an exclusive directory creation:
`pack_out.mkdir(parents=True, exist_ok=False)`, convert its `FileExistsError` to `EvalError`, and
do not also create it later with `exist_ok=True`. For multiple packs, pre-create all requested
pack directories in `main` only after all labels pass, then pass an explicit internal flag to
`run_eval` or factor a helper so `run_eval` does not reject those freshly-created directories.
A simpler acceptable design: `run_eval` alone creates exclusively, and `main` first checks all
requested pack paths for existence before running the first pack. The test pins the one-pack case;
keep the preflight-all-packs property from the original brief.

Test: `test_existing_pack_output_is_refused_before_a_case_runs`.

## F3 — Unknown provider is exit 1, not argparse's exit 2

Today `choices=["mock", "tencent"]` makes argparse exit 2. Exit 2 belongs to "one or more cases
failed".

**Fix:** remove `choices` from `--llm`. Pass the string to `build_llm_client` inside `main`'s
existing setup `try`; its `LLMError` is printed as `error: ...` and returns 1. Keep the help text
naming mock and tencent.

Test: `test_unknown_llm_exit_1_not_the_run_failed_code`.

## F4 — A failed case has no case file

Today `score.case_file` is populated after the `try` regardless of success, but `case_file.json`
is never written when the case failed.

**Fix:** assign the relative `case_file` path only inside the successful path, after
`case_file.write(case_dir)` succeeds. A failed score keeps its dataclass default `None`. Partial
`events.jsonl` and payloads remain in that case's directory for debugging.

Test: `test_run_failed_case_file_is_null_and_partial_events_remain`.

## F5 — Scoring never coerces malformed amounts

Today `_expected_text`, `_decision_text` and the comparison call `float(value)`, so the string
`"5.81"` counts as the numeric amount 5.81, while `None`, list or dict raises.

**Fix:**
- Introduce a small helper that returns True only for an `int` or `float` that is not a `bool`
  (bool is an int subclass). No coercion.
- In `load_labels`, when `expected_outcome == "ruled"`, require `expected_amount_sgd` to pass that
  numeric check. Otherwise raise `EvalError` naming the dispute id and the amount field. This is a
  broken label file and therefore remains a preflight failure before any cases run.
- In `_decision_text`, render a malformed candidate amount without raising. Use the literal
  string `invalid amount` after the action, e.g. `ruled: refund invalid amount`. Do not call
  `float()` on it.
- In `score_case`, after the action check and before cent comparison, a candidate amount that does
  not pass the numeric check scores `wrong amount`; otherwise compare with `round(value, 2)`.

The real pipeline rejects string amounts before the harness, but the scorer must still fail closed.

Tests: `test_string_amount_never_matches_numeric_label`,
`test_ruled_label_requires_a_numeric_amount`.

## F6 — Pins for the review's two test survivors

No app behaviour changes are needed here; today's code is already correct. Keep it exact:
- Actions compare exactly. `Refund`, `REFUND`, `re fund`, and `re_fund` are all wrong when the
  label says `refund`. Upstream parsing normalises model values; the harness compares canonical
  output.
- `MOCK_WARNING` appears on stdout only when `report.provider == "mock"`, not based on the CLI's
  requested `--llm` string.

Tests: `test_action_comparison_is_exact_not_case_or_separator_normalised`,
`test_stdout_mock_warning_only_for_the_mock`.

## Constraints and verification

- Standard library only, Python 3.9.
- `app/eval.py` is still the only reader of labels under `app/`; no label content reaches a prompt.
- Mock totals stay organiser 10/18 and 0/17 grounded; synth 9/17 and 0/16 grounded.
- Only `app/eval.py` changes.
- Run the target, then the full command named at the top, and inspect `git diff --check` plus
  `git status --short` before finishing.
