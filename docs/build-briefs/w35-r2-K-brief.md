# W35 fix round R2, lane K brief: console panel loads, bounded file reads, folder case shape

Operator console + server round. The acceptance contract is `tests/test_w35_r2_K.py`, `tests/test_w35_r2_paths.py` plus the
real-browser script `tests/browser/w35_r2_K.cjs`, committed by the planner together with one update
to an existing test (`tests/test_w34_launcher.py`: the `app/human_review.py` entry of `FROZEN_W34` is
released). Every change below was built and proven on a reference copy first; the code in this brief
is that reference. Make the tests pass without editing any file under `tests/`. If a test looks wrong,
stop and report the test name and the reason.

The five defects (reviewer findings 2-6 of the W35 review), each fixed as a class:

- **K2** an older Recent runs / queue / Overrides response (success OR failure) overwrote or cleared a
  newer refresh. Now only the newest load of a list renders, clears or restores its status.
- **K3** an Open clicked while a Refresh's list load was in flight was orphaned when the new rows
  rendered. Now the list is `aria-busy="true"` and its Open buttons are disabled for exactly that
  window, so no open can start against rows about to be replaced.
- **K4** `case_file.json` / `human_decision.json` (and `dispute.json`) that is a symlink OUT of its
  run folder was followed by the runs list, the queue, Overrides, `/case`, the decision and answers
  POSTs and the party views. Now ONE helper bounds each leaf read, and the directory scan rejects
  a run folder that resolves outside the output root or to the root itself.
- **K5** one 1200-deep `human_decision.json` made `load_decision` raise `RecursionError` (HTTP 500 on
  six routes). Now it is "no decision".
- **K6** the run-folder loader accepted `{}` and `{"run_id": "partial"}` as a case. Now it needs a
  run id, a dispute id and a resolution with an outcome.

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
- `app/server.py`
- `app/human_review.py`

Nothing else. `ui/index.html` and `ui/styles.css` stay byte-identical (no colour, markup or style
change is needed: a disabled Open button and an `aria-busy` attribute are enough, and
`tests/test_w35_C.py` pins `ui/styles.css` rule by rule). `app/agents/*`, `app/llm/*`, `docs/policy.md`
and `data/` stay byte-identical (a test hashes them). In `app/human_review.py` change ONLY
`load_decision` and the helper added before it; every validity rule stays as it is (a test hashes the
rest of the module). Everything under `ui/party/`, `ui/start/` and `ui/switch-bar.css` belongs to the
sibling lane: do not open them for writing.

## Expected sibling RED

The shared baseline you start from carries BOTH lanes' RED tests. The sibling lane's test files
`tests/test_w35_r2_S.py` and `tests/browser/w35_r2_S.cjs`, plus the four updated
status-frame pins in `tests/test_w35_P.py`, fail on purpose in that baseline and belong to the other lane. Do not touch them and do not try to make them pass. This lane changes no colour
declaration, so the colour ledger test stays as it is.

## 1. `app/human_review.py`: the bounding helper and `load_decision`

Replace the whole function `load_decision` (the last function before the
`# ---- party message` section) with these two functions. Nothing else in the file changes.

```python
def bounded_run_file(run_dir: Path, name: str) -> Optional[Path]:
    """W35: the resolved path of `name` inside `run_dir`, or None. Fails closed.

    Every read of a run's case file or decision file goes through here. A leaf that is a
    symlink is followed only while it stays inside the run directory (compared as resolved
    paths); one that leaves it, loops, or cannot be resolved reads as missing. A leaf that
    does not exist yet comes back as its would-be path, so the caller's own read reports it.
    """
    try:
        base = Path(run_dir).resolve()
        leaf = (base / name).resolve()
    except (OSError, RuntimeError):
        return None
    if leaf == base or not leaf.is_relative_to(base):
        return None
    return leaf


def load_decision(run_dir: Path) -> Optional[Dict[str, Any]]:
    """The stored decision record, or None. Fails closed on any bad shape or file."""
    path = bounded_run_file(run_dir, HUMAN_DECISION_FILE_NAME)
    if path is None:
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        return None
    return data if decision_record_is_valid(data) else None
```

## 2. `app/server.py`: every case-file and dispute-record read through the helper

**2a.** In the `from .human_review import (...)` block add `bounded_run_file,` directly after
`HumanDecisionError,` (alphabetical: `HumanDecisionError`, `bounded_run_file`, `decision_record_is_valid`, ...).

**2b.** Directly after `_read_json_object` (before `_direct_runs`) add:

```python
def _read_run_json(run_dir: Path, name: str) -> Optional[Dict[str, Any]]:
    """W35: a JSON object in a run directory, or None. The leaf must resolve inside run_dir.

    A case file or dispute record that is a symlink out of its run directory reads as
    missing (see bounded_run_file); so do the cases _read_json_object already covers.
    """
    leaf = bounded_run_file(run_dir, name)
    return None if leaf is None else _read_json_object(leaf)


def _read_case_file(run_dir: Path) -> Optional[Dict[str, Any]]:
    """The run's case file as a JSON object, or None. Every case-file read goes through here."""
    return _read_run_json(run_dir, CASE_FILE_NAME)
```

**2c.** Replace `_direct_runs` with the following complete function. The root bound is
required as well as the leaf bound: a run directory linked outside the output root must not bypass
`bounded_run_file`. Internal directory links still work. `tests/test_w35_r2_paths.py` pins this.

```python
def _direct_runs(out_dir: Path) -> List[Tuple[Path, Dict[str, Any]]]:
    """Every run that is a DIRECT child of out_dir and holds a readable case file.

    Eval runs live one level deeper (out_dir/<eval-name>/<run>/case_file.json) and are
    never seen. An unreadable or corrupt case file is skipped, never a 500.
    """
    if not out_dir.is_dir():
        return []
    root = out_dir.resolve()
    runs: List[Tuple[Path, Dict[str, Any]]] = []
    for child in sorted(out_dir.iterdir()):
        try:
            resolved = child.resolve()
            if resolved == root or not resolved.is_relative_to(root) or not resolved.is_dir():
                continue
        except (OSError, RuntimeError):
            continue
        case = _read_case_file(child)
        if case is not None:
            runs.append((child, case))
    return runs
```

**2d.** `_party_record`: the last line becomes `return _read_run_json(run_dir, DISPUTE_FILE_NAME)`
(the `is_file()` test above it stays).

**2e.** `_recent_runs`: `case = _read_json_object(run_dir / CASE_FILE_NAME)` becomes `case = _read_case_file(run_dir)`.

**2f.** `_review_case` and `_record_human_decision`: in each, `case_file = _read_json_object(run_dir / CASE_FILE_NAME)`
becomes `case_file = _read_case_file(run_dir)`.

**2g.** `_answer_run`: replace

```python
        case_path = run_dir / CASE_FILE_NAME
        dispute_path = run_dir / DISPUTE_FILE_NAME
        try:
            case_file = json.loads(case_path.read_text(encoding="utf-8"))
            record = json.loads(dispute_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raise _HTTPError(404, "unknown run")
        if not isinstance(case_file, dict) or not isinstance(record, dict):
            raise _HTTPError(404, "unknown run")
```

with

```python
        case_file = _read_case_file(run_dir)
        record = _read_run_json(run_dir, DISPUTE_FILE_NAME)
        if case_file is None or record is None:
            raise _HTTPError(404, "unknown run")
```

After this, `CASE_FILE_NAME` appears in `app/server.py` only in its definition and inside
`_read_case_file` (a test pins that), and `bounded_run_file(` is called exactly once there.

## 3. `ui/app.js` (plain ES5 like the rest of the file)

**3a.** In the `state` object, directly after `pendingOpens: [],` add:

```js
    panelLoads: { queue: 0, overrides: 0, runs: 0 },
    panelBusy: { queue: false, overrides: false, runs: false },
```

**3b. (K6)** Directly before `function handleFile(file, label, runFiles) {` add:

```js
  function isNonEmptyString(value) {
    return typeof value === "string" && value !== "";
  }

  // W35: the least a case file must carry before it renders or attaches anything: a run id,
  // a dispute id, and a resolution object that records an outcome. An outcome the console
  // does not know still passes: the renderer shows its unknown-outcome warning. Strings,
  // numbers and arrays carry none of these members, so they fail the member checks.
  function isCaseFileShape(value) {
    var resolution = value ? value.resolution : null;
    return Boolean(value)
      && isNonEmptyString(value.run_id)
      && isNonEmptyString(value.dispute_id)
      && Boolean(resolution)
      && isNonEmptyString(resolution.outcome);
  }
```

and in `handleFile` replace the condition
`if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {` with
`if (!isCaseFileShape(parsed)) {`. The thrown message stays exactly
`The selected JSON must contain one case-file object.` (the existing string; every wrong shape gets it).

**3c. (K2, K3)** Replace the whole function `restoreOpenButton` with these five functions (the
panel load state; `restoreOpenButton` itself now respects a busy list):

```js
  // The container of each review list and the list's name; used for the panel load state.
  function panelContent(panel) {
    return panel === "queue" ? queueContent : panel === "overrides" ? overridesContent : runsContent;
  }

  // True while the button sits in a list whose load is in flight: its rows are about to be
  // replaced, so it must not start an open (the replacement row would not own the pending state).
  function isInBusyPanel(button) {
    for (var node = button; node; node = node.parentNode) {
      if ((node === queueContent && state.panelBusy.queue)
        || (node === runsContent && state.panelBusy.runs)) {
        return true;
      }
    }
    return false;
  }

  function restoreOpenButton(button) {
    if (button) {
      button.textContent = "Open case";
      button.disabled = isInBusyPanel(button);
    }
  }

  // A load of a review list owns the list until a newer load begins. Beginning marks the
  // list aria-busy and disables its Open buttons; only the owner's settle clears both, and
  // an older response (success or failure) that finds a newer owner touches nothing.
  function beginPanelLoad(panel) {
    state.panelLoads[panel] += 1;
    state.panelBusy[panel] = true;
    var container = panelContent(panel);
    if (container) {
      container.setAttribute("aria-busy", "true");
      if (typeof container.querySelectorAll === "function") {
        Array.prototype.forEach.call(container.querySelectorAll("button"), function (button) {
          button.disabled = true;
        });
      }
    }
    return state.panelLoads[panel];
  }

  function ownsPanelLoad(panel, generation) {
    return state.panelLoads[panel] === generation;
  }

  function endPanelLoad(panel) {
    state.panelBusy[panel] = false;
    var container = panelContent(panel);
    if (container) {
      container.setAttribute("aria-busy", "false");
    }
  }
```

(Use `setAttribute("aria-busy", "true"/"false")`, never `removeAttribute`: the test DOM has no
`removeAttribute`.)

**3d.** In `applyListSelection`, in the `if (current) {` branch, change `button.disabled = false;` to
`button.disabled = isInBusyPanel(button);` (the line after `button.setAttribute("aria-current", "true");`).
The not-current branch already calls `restoreOpenButton`.

**3e. (K2, K3)** Replace the three loaders `loadQueue`, `loadOverrides` and `loadRuns` with:

```js
  function loadQueue() {
    var generation = beginPanelLoad("queue");
    return fetchJson("/api/review/queue").then(function (data) {
      if (!ownsPanelLoad("queue", generation)) {
        return;
      }
      endPanelLoad("queue");
      renderQueue(data);
    }).catch(function () {
      if (!ownsPanelLoad("queue", generation)) {
        return;
      }
      endPanelLoad("queue");
      clear(queueContent);
      state.queueEntries = null;
      queueStatus.textContent = "The review queue is not available. Open the console from the running server to use it.";
    });
  }

  function loadOverrides() {
    var generation = beginPanelLoad("overrides");
    return fetchJson("/api/review/overrides").then(function (data) {
      if (!ownsPanelLoad("overrides", generation)) {
        return;
      }
      endPanelLoad("overrides");
      renderOverrides(data);
    }).catch(function () {
      if (!ownsPanelLoad("overrides", generation)) {
        return;
      }
      endPanelLoad("overrides");
      clear(overridesContent);
      overridesStatus.textContent = "Overrides are not available.";
    });
  }

  function loadRuns() {
    if (!runsStatus || !runsContent) {
      return Promise.resolve();
    }
    var generation = beginPanelLoad("runs");
    return fetchJson("/api/review/runs").then(function (data) {
      if (!ownsPanelLoad("runs", generation)) {
        return;
      }
      endPanelLoad("runs");
      renderRuns(data);
    }).catch(function () {
      if (!ownsPanelLoad("runs", generation)) {
        return;
      }
      endPanelLoad("runs");
      clear(runsContent);
      runsStatus.textContent = RUNS_UNAVAILABLE;
    });
  }
```

Keep `renderQueue`, `renderOverrides`, `renderRuns` as they are. The ownership test comes BEFORE
`endPanelLoad` and the render/clear in both the success and the failure callback: a stale response
must neither render, clear, restore a status, nor end the newer load's busy state.

**3f. (K3)** Replace `loadReviewPanels` and DELETE `refreshReviewPanels` (the whole function and its
comment), then wire Refresh to `loadReviewPanels`:

```js
  // Every panels load replaces the rows an open may have started from, so it first drops the
  // pending opens (their buttons return to Open case, then the loads disable them until the
  // new rows arrive). The Refresh button and a recorded decision both come through here.
  function loadReviewPanels() {
    if (state.pendingOpens.length > 0) {
      invalidatePendingOpens();
    }
    var queueLoad = loadQueue();
    loadOverrides();
    loadRuns();
    return queueLoad;
  }
```

At the bottom: `queueRefresh.addEventListener("click", loadReviewPanels);`.

Why the invalidation moved: the reload after a recorded decision (`loadReviewPanels()` in
`sendDecision`) replaces the queue rows exactly as Refresh does, so a queue Open pending at that
moment was orphaned the same way; `tests/test_w35_r2_K.py` pins both entries.

## Verify, then commit and stop

Set these browser variables once. They are read-only test dependencies, not permission to read
or modify their installation files. The tests may make loopback requests; no external network.

```bash
export PUPPETEER_MODULE=[USER_HOME]/.hermes/cache/browser-verify/node_modules/puppeteer
export BROWSER_EXECUTABLE="/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"
env -u PYTHONPATH /usr/bin/python3 -B -m unittest tests.test_w35_r2_K tests.test_w35_r2_paths
env -u PYTHONPATH /usr/bin/python3 -B -m unittest discover -s tests -t .
git diff --exit-code -- tests/
git status --short
```

The planner measured all of the following on one shared test baseline with the final browser
scripts and both browser variables set. Counts include failing subtests, not just failing methods.

- Before either fix: **1593 tests, 190 assertion failures, zero errors**. Attribution: 176 K, 5
  path-bound checks, 5 S, 4 existing P status-frame pins.
- With this lane done and the sibling application unchanged: **1593 tests, 9 failures, all in `tests.test_w35_r2_S` (5) and `tests.test_w35_P` (4), zero errors**.
- With BOTH reference implementations: **1593 tests, OK, no skips**.
- Focused tests for your lane must be green, including the browser wrappers. If a browser test
  is skipped, the verification is incomplete. Do not edit a test to repair a failure.

Before committing, `git status --short` may list only the allowed application files, and the test
working tree must be unchanged. Commit only `ui/app.js app/server.py app/human_review.py`, explicitly listing the files you changed
in `git add`. Report the commit hash, full-suite result, focused result and any deviations.

## Stop and ask instead of guessing

- a test seems to contradict this brief;
- a fix needs a file outside the allowed list;
- the full suite has any failure beyond the declared sibling RED, or any error;
- `tests.test_w35_C` or `tests.test_w34_launcher` fails (they must stay green; the launcher's
  `FROZEN_W34` release is already in the committed tests).
