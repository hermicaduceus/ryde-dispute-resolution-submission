# Build session seventeen — the evaluation harness

Nothing in the repo yet measures the pipeline against the labels in `ground-truth.json`, although
`docs/dataset.md` says the corpus is "the corpus the system is evaluated against". This session
adds that measurement: one command that runs every labelled case in a pack through the real
pipeline and scores each result, case by case, with a named reason.

**Target:** `tests/test_eval_harness.py` (37 tests, currently RED) green, and the full suite
(`python3 -m unittest discover -s tests -t .`, **547 tests**) green.

**Do not edit anything under `tests/`, `tools/`, `data/` or `ui/`.** If a test looks wrong, stop
and ask. **Only two files change:** a new `app/eval.py`, and `docs/dataset.md` (one new
subsection). Every other file under `app/`, including `app/cli.py`, `app/pipeline.py` and
`app/config.json`, stays byte-identical.

## What the harness does

```
python3 -m app.eval [--pack NAME ...] [--llm mock|tencent] [--out DIR]
```

- `--pack` is repeatable. With no `--pack`, run both packs in this order: `organiser-style-v1`,
  then `ryde-synth-v1`.
- `--llm` defaults to `app/config.json` (mock).
- `--out` defaults to `<config out_dir>/eval-<UTC yyyymmddThhmmssZ>`, which sits under the
  gitignored `runs/`.

For each pack, every dispute file in `disputes/`, in `sorted()` order, goes through
`run_dispute` exactly as `app/cli.py` runs it. Its resolution is scored against its label, and
the pack gets `<out>/<pack>/report.json` and `<out>/<pack>/report.md`. Each case keeps its own
artifacts in `<out>/<pack>/<dispute_id>/` (`events.jsonl`, `payloads/`, `case_file.json`).

## The labels

`<pack>/ground-truth.json` is `{"_readme", "policy_version", "case_count", "cases": [...]}`. Each
case holds:
- `dispute_id`
- `category`
- `expected_outcome`: `ruled`, `escalated` or `human_review`
- `expected_action`: `refund`, `no action` or null
- `expected_amount_sgd`: a float or null
- `decisive_rule_ids`
- `rationale`

**`app/eval.py` is the only file under `app/` that may read `ground-truth.json`**, and nothing
from a label may ever reach a prompt. A test enforces both.

`load_labels(pack_dir)` returns `{dispute_id: label}` and raises `EvalError`, naming the
offending id, when:
- `ground-truth.json` is missing or unreadable
- a label's id appears twice
- a dispute file has no label
- a label has no dispute file

## Scoring: `score_case(label, resolution) -> CaseScore`

`resolution` is `case_file.to_dict()["resolution"]`. The pipeline's outcomes are `ruled`,
`withheld`, `human_review` and `needs_info`. **The label's `escalated` is the pipeline's
`withheld`.** Check in this order; the first match wins:

| Condition | `reason` |
|---|---|
| outcome is `needs_info` | `asked the party` |
| outcome (with `withheld` read as `escalated`) ≠ `expected_outcome` | `wrong outcome` |
| outcome `ruled` and `ruling["action"]` ≠ `expected_action` | `wrong action` |
| outcome `ruled` and `round(amount, 2)` ≠ `round(expected_amount_sgd, 2)` | `wrong amount` |
| otherwise | `match` |

`decision_match` is True only for `match`.

A `needs_info` stop is a miss and stays in the count. Every corpus case carries a complete intake
form, so asking again means the model did not use what it had.

**Grounding** is a separate measure and never changes `reason`:
- The candidate is `resolution["ruling"]` or else `resolution["withheld_candidate"]`.
- If there is no candidate, or the outcome is `needs_info`: `grounded = None` and
  `rules_missing = []`.
- Otherwise `rules_missing` holds every `decisive_rule_ids` entry that does **not** start with
  `ESC-` and is not in the candidate's `cited_rule_ids`, **in label order** (not sorted), and
  `grounded = not rules_missing`.

`ESC-` rules are excluded because the escalation gates are enforced in Python, not cited by the
model.

`score_error(label, message) -> CaseScore` gives reason `run failed`, `decision_match` False,
`grounded` None, `rules_missing` [], and `error` holding the message.

**A failed case never stops the run.** Catch
`(DisputeError, PolicyError, LLMError, RuntimeError, ValueError)` around each case, as `app/cli.py`
does, record `score_error`, and carry on to the next case.

## `CaseScore` and `EvalReport`

`CaseScore` has these fields:
- `dispute_id`
- `expected`: `"ruled: refund 5.81"` for a ruled label (action, then amount to 2 dp), otherwise
  the bare outcome (`escalated`, `human_review`)
- `got`: outcome, action and amount when a ruling or withheld candidate exists (e.g.
  `withheld: refund 55.16`); otherwise the bare outcome; `run failed` for an error
- `reason`
- `decision_match`
- `grounded`
- `rules_missing`
- `error` (None unless the run failed)
- `case_file`: the path **relative to `--out`**, e.g. `organiser-style-v1/RD-0101/case_file.json`

`EvalReport` has these fields:
- `pack`, the pack directory name
- `provider`, which is `llm.provider_name`
- `threshold`
- `autonomous_cap_sgd`
- `generated_at`
- `cases`, in file order
- `totals`, a dict:
  `{"cases", "decisions_matching", "grounding_applicable", "grounded", "by_reason"}`

`grounding_applicable` counts cases whose `grounded` is not None. `by_reason` always holds all
six reasons, **in this order, zeros included**: `match`, `wrong outcome`, `wrong action`,
`wrong amount`, `asked the party`, `run failed`.

`report.json` has these top-level keys:
`pack, provider, threshold, autonomous_cap_sgd, generated_at, totals, cases`. Each case entry
carries exactly the `CaseScore` fields. Write it with `indent=2`.

## Module surface (the tests import these names)

- `EvalError`, `CaseScore`, `EvalReport`
- `load_labels`, `score_case`, `score_error`
- `run_eval(*, pack_dir, llm, policy, out_dir, confidence_threshold, autonomous_cap_sgd) -> EvalReport`
- `render_markdown(report) -> str`
- `main(argv=None) -> int`
- `MOCK_WARNING`, `CAVEAT`

Import `build_llm_client` and `resolve_pack_dir` at module level
(`from .llm import build_llm_client`, `from .config import load_config, resolve_pack_dir`) and
call them by those names: the tests replace them. Build the client exactly as
`app/cli.py:103-108` does.

## Fixed strings, verbatim

```
MOCK_WARNING = "MOCK RUN: the mock is a deterministic stand-in, not a solver. This score checks the wiring, not the system."
CAVEAT = "Measured on a synthesised demonstration corpus against the team's own labels: a check of internal consistency, not real-world accuracy."
```

`MOCK_WARNING` appears in `report.md` and on stdout **only** when the provider is `mock`.
`CAVEAT` always appears. **No `%` character anywhere** in `report.md` or on stdout:
`docs/dataset.md` forbids quoting a percentage from this corpus without its denominator.

## `report.md`

```
# Evaluation: organiser-style-v1, provider mock

MOCK RUN: ...                     (mock only)
Measured on a synthesised ...

Decisions matching the label: 10 of 18
Rulings citing every decisive rule: 0 of 17

| Case | Expected | Got | Result | Missing rules |
|---|---|---|---|---|
| DISP-002 | ruled: no action 0.00 | ruled: no action 0.00 | match | NS-2, NS-3, NS-6 |
...
```

There is one row per case. The Missing rules cell joins with `, `.

## stdout and exit codes

For each pack, print:
1. a line naming the pack and provider
2. the warning if mock
3. the caveat
4. one line per case (id, expected, got, reason)
5. the two headline lines, exactly as in `report.md`
6. the path of `report.md`

Exit codes:
- **0** when every case ran, however low the score.
- **1**, with `error: ...` on stderr, for a config, policy, LLM-setup, unknown-pack or label-file
  error. Validate **every** requested pack's labels **before any case runs**, so a broken label
  file never burns live model calls.
- **2** when any case scored `run failed`, so a live run with an outage can never be read as
  clean.

## Constraints

- Standard library only.
- **Python 3.9**: no `match` statement, no `X | Y` type unions.
- One `EventLog(run_dir, run_id)` per case.
- Read config through `load_config()`.

## `docs/dataset.md`

Under `## Verification`, after the paragraph ending "Every case also runs end to end through the
real pipeline without error.", add a subsection **`### Evaluation`** covering:
- the command `python3 -m app.eval`, its three flags and where the reports land
- what "decisions matching the label" and "rulings citing every decisive rule" each mean, in one
  sentence apiece
- that a stop to ask the party counts as a miss
- that a mock run checks the wiring only

Keep it under 15 lines. **Do not put any score in the doc.**

## Expected result on the mock

For reference, the tests pin this exactly:
- `organiser-style-v1`: 10 of 18 decisions match, 0 of 17 rulings cite every decisive rule.
- `ryde-synth-v1`: 9 of 17 match, 0 of 16 cite every decisive rule.

The mock is a stand-in, not a solver, so these numbers prove the wiring and say nothing about
the system.
