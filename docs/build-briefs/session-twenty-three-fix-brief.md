# Session twenty-three fix round: review findings N1, N2, N3, N5, N6, S1

Cross-family review of the B2 build (a second-model) found these; every one was reproduced by the planner before
being pinned. **Nine acceptance tests in `tests/test_w23_b2_review_fixes.py` are RED right now and must be
green when you are done.** They are the contract: read them before changing anything.

Run the suite with `/usr/bin/python3 -m unittest discover -s tests -t .` from the worktree
(`~/hermes-workspace/projects/ryde-build-worktrees/session-twenty-three`). The new file drives `ui/app.js`
in Node, so `node` must be on PATH (`[USER_HOME]/.hermes/tools/node-26.7.0-darwin-arm64/bin`).

## The fixes

**N1 — a decision response must not land on another case (`ui/app.js`).**
`sendDecision` reads the module globals `decisionUi` / `decisionContent` inside its promise callbacks, but
opening another case replaces both. Capture what the request was issued for, at send time:

```
var ui = decisionUi;
var runId = state.openRun.runId;
```

Use `runId` for the URL, and in BOTH callbacks return early when the operator has moved on
(`decisionUi !== ui`, or `!state.openRun || state.openRun.runId !== runId`). Do the same in the catch
branch. The POST target is already correct; do not change it. Success must render the recorded-decision card
on the case it was issued for, and a late 409 must neither throw nor display on another case.

**N2 — deep JSON is a 404, not a 500 (`app/server.py`).**
`json.loads` raises `RecursionError` on deeply nested input; it is neither `ValueError` nor `OSError`.
Add `RecursionError` to the except tuple in the payload reader (`_review_payload`) AND in
`_read_json_object`. Both then return their 404 (`unknown payload` / `unknown run`), never a 500.

**N3 — an approve of a `no action` proposal reads `Amount: no action` (`ui/app.js`).**
In `buildConfirmation`, the approve branch currently prints `Amount: <action> of SGD <x>` whenever the
proposal carries a finite amount, so a `no action` proposal with amount 12.5 shows
`Amount: no action of SGD 12.50` and can fire the fare warning. When the proposal's action is `no action`,
the line must read exactly `Amount: no action` and the line must not be used for the fare warning.
`AI proposed: no action` (line 4) is already correct.

**N5 — the endpoint table lists the two new paths (`docs/architecture.md`).**
The paragraph above the table names `/api/review/<run_id>/case` and
`/api/review/<run_id>/payloads/<name>`; the table below it does not. Add a row for each, matching the
existing row style (endpoint in the first column, purpose in the second).

**N6 — an unusable amount must not be a silent dead end (`ui/app.js`).**
Today, when the change amount parses to no number, the confirm screen shows `amount not a number` and
`Confirm and send` stays enabled and does nothing. Either disable the Send button in that state, or write a
short message to `#decision-error` when Send is pressed with no usable amount. The test accepts either.

**S1 — a symlinked `payloads` directory must not be followed (`app/server.py`).**
In `_review_payload`, after resolving `payload_path`, also require it to sit inside the RUN directory (not
merely inside the resolved payloads directory), so a `payloads` entry that is itself a symlink pointing
outside the run is refused with `unknown payload`. A normal payload in the same run must still serve.

## Rules

- Allowed files: `ui/app.js`, `app/server.py`, `docs/architecture.md`. Nothing else. **Do not edit
  `tests/`** — the nine pins are the contract; if one looks wrong, stop and ask.
- Do not change any fixed string the brief `docs/build-briefs/session-twenty-three-brief.md` pins, and do not weaken any
  existing guard. The full suite was 995 green before this round; it must be **1004 green** after (995 + 9).
- Standard library only; Python 3.9; `textContent` only in `app.js` (no `innerHTML`, `outerHTML`,
  `insertAdjacentHTML`, `document.write`).
- `/usr/bin/python3 -m app.eval --llm mock` on both packs must stay unchanged:
  organiser 11 of 18 matching / 11 of 18 without a human / 0 stops; synth 10 of 17 / 10 of 17 / 0.
- Commit in small commits when the suite is green. Do not run the live model.
