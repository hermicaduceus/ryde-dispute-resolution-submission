# W35 fix round R3 brief: a stale open spares the newer current-row open; a non-string decision action

Two small fixes from the R2 review (both reproduced by the planner). The acceptance contract is
`tests/test_w35_r3.py` plus the real-browser script `tests/browser/w35_r3.cjs`, committed by the planner
together with one update to an existing test (`tests/test_w35_r2_K.py`: `HUMAN_REVIEW_REST_SHA` is
re-baselined to the module WITH the R3 change below, byte for byte). Every change below was built and
proven on a reference copy first; the code in this brief is that reference. Make the tests pass without
editing any file under `tests/`. If a test looks wrong, stop and report the test name and the reason.

- **R3-1** `ui/app.js`, `applyListSelection`, the current-row branch. An open dropped by Refresh (or the
  reload after a recorded decision) can still answer, success or failure, while a NEWER open of the same,
  already-current row is in flight. Its settle calls `applyQueueSelection()`, and the current-row branch
  wrote `Currently open` and re-enabled the button without asking whether that button had an open in
  flight. The non-current branch already asks (`isButtonPending`). Now the current branch asks too.
- **R3-2** `app/human_review.py`, `decision_record_is_valid`. `value.get("action") not in {set}` raises
  `TypeError` for a list or object action (unhashable), so a corrupt `human_decision.json` like
  `{"action": [], "amount_sgd": 0}` made seven GET views answer HTTP 500. Now a non-string action is
  simply not a valid decision. This is strictly more fail-closed; no rule weakens.

## Protocol (obey it on every turn)

This round runs headlessly on `glm-5.3-flash` at max effort. Do not switch models.

- Work only in this repository. No other worktrees, planning or scratch folders, no subagents, no
  network, no live model (never pass `--llm tencent`; the server defaults to the mock).
- Interpreter: `/usr/bin/python3` with `PYTHONPATH` removed (`env -u PYTHONPATH ...`).
- A server you start binds a port in 18000-18999, never 8000-8010, and you stop it before you finish.
- Never `rm -rf`, never `git add -A`, never merge, never push. Commit once at the end with an
  explicit `git add` of the files you changed.
- Never read or print `.env` or any key file.
- The two browser variables in the verify block point at a Puppeteer install and the Brave app
  outside this repository. They are read-only tool dependencies that the tests execute; do not
  open, list or modify anything there.

## Allowed files (this round)

- `ui/app.js`
- `app/human_review.py`

Nothing else. Every other file stays byte-identical. In `ui/app.js` change ONLY the current-row branch
of `applyListSelection`. In `app/human_review.py` change ONLY the action check inside
`decision_record_is_valid`; `tests/test_w35_r2_K.py` hashes the rest of the module INCLUDING this
function, so the new lines must match this brief exactly (same text, same comments, same indentation).

## 1. `ui/app.js`: the current-row branch of `applyListSelection`

Replace this block:

```js
      if (current) {
        row.classList.add("is-open");
        button.textContent = "Currently open";
        button.setAttribute("aria-current", "true");
        button.disabled = isInBusyPanel(button);
        return;
      }
```

with:

```js
      if (current) {
        row.classList.add("is-open");
        button.setAttribute("aria-current", "true");
        // A newer open of this same row may still be in flight (an older, invalidated open
        // settling calls this too): its "Opening…" and disabled state belong to that open.
        if (isButtonPending(button)) {
          return;
        }
        button.textContent = "Currently open";
        button.disabled = isInBusyPanel(button);
        return;
      }
```

The row keeps `is-open` and `aria-current="true"` either way; only the text and the disabled state wait
for the pending open's own settle (which calls `applyQueueSelection()` again once it is no longer
pending). Nothing else in the file changes.

## 2. `app/human_review.py`: `decision_record_is_valid`

Replace these two lines:

```python
    if value.get("action") not in {member.value for member in RulingAction}:
        return False
```

with exactly:

```python
    action = value.get("action")
    # The type check comes first: a list or object action is unhashable, so the set
    # membership test would raise instead of answering no.
    if not isinstance(action, str) or action not in {member.value for member in RulingAction}:
        return False
```

The `isinstance(value, dict)` check above it and the `_finite_number` line below it stay as they are.
`load_decision` and `bounded_run_file` do not change. `app/server.py` does not change: its second caller
(`party_view`, the `decision_record_is_valid(human_decision)` test) is fixed by this same function.

## Expected baseline

The planner measured all of the following with both browser variables set:

- On this branch's starting commit (RED tests, application unchanged): the full suite fails ONLY in
  `tests.test_w35_r3` and in `tests.test_w35_r2_K.NothingElseMoved.test_human_review_changes_only_load_decision_and_its_bounding_helper`
  (the re-baselined hash), all by assertion, zero errors.
- With the reference implementation: the full suite is OK with zero skips.

There is no sibling lane this round.

## Verify, then commit and stop

```bash
export PUPPETEER_MODULE=[USER_HOME]/.hermes/cache/browser-verify/node_modules/puppeteer
export BROWSER_EXECUTABLE="/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"
env -u PYTHONPATH /usr/bin/python3 -B -m unittest tests.test_w35_r3 tests.test_w35_r2_K
env -u PYTHONPATH /usr/bin/python3 -B -m unittest discover -s tests -t .
git diff --exit-code -- tests/
git status --short
```

- Focused: green, including the browser classes. If a browser test is skipped, the verification is
  incomplete.
- Full suite: OK, no failures, no errors, no skips.

Before committing, `git status --short` may list only `ui/app.js` and `app/human_review.py`, and the test
working tree must be unchanged. Commit only those two files with an explicit `git add ui/app.js
app/human_review.py`. Report the commit hash, the full-suite result, the focused result and any deviations.

## Stop and ask instead of guessing

- a test seems to contradict this brief;
- a fix needs a file outside the allowed list;
- the full suite has any failure or error after your change;
- `tests.test_w35_r2_K` fails on its hash pin after you applied the code above (it means the new lines
  differ from this brief; compare them character by character rather than editing the test).
