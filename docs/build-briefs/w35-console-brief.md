# W35 lane C brief: one run-folder picker, Recent runs, readable prompt full text

Operator console round. The acceptance contract is `tests/test_w35_C.py` plus the real-browser
scripts `tests/browser/w35_C.cjs` and `tests/browser/w35_C_replay.cjs`, committed by the planner
together with the updates to existing tests this round needs. Every item below was built and proven
on a reference copy first; the code in this brief is that reference. Make the tests pass without
editing any file under `tests/`. If a test looks wrong, stop and report the test name and the reason.

## Protocol (obey it on every turn)

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

- `ui/index.html`
- `ui/app.js`
- `ui/styles.css`
- `app/server.py`
- `tools/export_replay.py`

Nothing else. In particular `tools/replay/replay-shim.js` and `README.md` stay as they are (the
replay needs no shim change), and everything under `ui/party/`, `ui/start/` and `ui/switch-bar.css`
belongs to the sibling lane: do not open them for writing.

## Expected sibling RED and the colour ledger

The shared baseline you start from carries BOTH lanes' RED tests. The sibling lane's test files
`tests/test_w35_P.py`, `tests/browser/w35_P_filing.cjs`, `tests/browser/w35_P_status.cjs` and
`tests/browser/w35_P_contrast.cjs` fail on purpose in that baseline, and they belong to the
other lane. Do not touch them and do not try to make them pass. `tests/browser/w15_actions.cjs` was
corrected by the planner in the same baseline (the old script measured clipped boxes inside the
W30 scroll region) and passes on the unchanged application; nothing in this round changes its
result. The colour ledger test (`tests/test_session_sixteen.py`,
`test_colour_declarations_match_the_approved_ledger`, `sheet='ui/styles.css'`) stays red until
the planner re-baselines it after merge, because this round adds colour declarations to
`ui/styles.css` on purpose. Do not run `tools/colour_ledger.py --write`.

## 1. `app/server.py`: `GET /api/review/runs`

A read-only list of the run folders the console can open by id, newest first, at most 100.

**1a.** Directly after the `_DISPUTE_ID_RE = ...` line, add:

```python
#: W35: the console's Recent runs list shows at most this many runs, newest first.
RECENT_RUNS_LIMIT = 100
```

**1b.** Directly after `_review_overrides` (after its `return {"approved_count": ...}` line and before
the `# --- filing builder` comment), add these two functions:

```python
def _recent_run_entry(run_id: str, case: Dict[str, Any], run_dir: Path) -> Optional[Dict[str, Any]]:
    """One Recent runs row, or None when the case file lacks a field the console relies on.

    The case must name this folder as its run_id (the console opens the folder by that id
    and asks for its prompts by the case's run_id), carry a dispute id, and record an
    outcome. Category and generated_at are shown when they are strings, else as "".
    """
    if case.get("run_id") != run_id:
        return None
    dispute_id = case.get("dispute_id")
    if not isinstance(dispute_id, str) or not dispute_id:
        return None
    resolution = case.get("resolution")
    if not isinstance(resolution, dict):
        return None
    outcome = resolution.get("outcome")
    if not isinstance(outcome, str) or not outcome:
        return None
    category = case.get("category")
    generated_at = case.get("generated_at")
    return {
        "run_id": run_id,
        "dispute_id": dispute_id,
        "category": category if isinstance(category, str) else "",
        "outcome": outcome,
        "generated_at": generated_at if isinstance(generated_at, str) else "",
        "has_human_decision": load_decision(run_dir) is not None,
    }


def _recent_runs(out_dir: Path) -> List[Dict[str, Any]]:
    """W35: the newest run folders the console can open by id, newest first. Read-only.

    A folder is listed only when GET /api/review/<run_id>/case would open it: its name
    passes the run-id rule, it resolves inside out_dir and is not out_dir itself (a
    symlink that escapes is skipped), and it holds a case file that is a JSON object
    with the fields the row needs. Anything else, a plain file included, is skipped,
    never a 500. Ties on generated_at go to the larger run id; the list is cut at
    RECENT_RUNS_LIMIT.
    """
    try:
        root = out_dir.resolve()
        children = list(out_dir.iterdir())
    except OSError:
        return []
    found: List[Tuple[Any, str, Dict[str, Any]]] = []
    for child in children:
        run_id = child.name
        if not _RUN_ID_RE.fullmatch(run_id) or run_id in (".", ".."):
            continue
        try:
            run_dir = child.resolve()
            if run_dir == root or not run_dir.is_relative_to(root):
                continue
        except (OSError, RuntimeError):
            continue
        case = _read_json_object(run_dir / CASE_FILE_NAME)
        if case is None:
            continue
        entry = _recent_run_entry(run_id, case, run_dir)
        if entry is None:
            continue
        found.append((_timestamp_key(case.get("generated_at")), run_id, entry))
    found.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [entry for _key, _run_id, entry in found[:RECENT_RUNS_LIMIT]]
```

**1c.** In `_route_api_get`, directly before `if split.path == "/api/review/queue":`, add:

```python
        if split.path == "/api/review/runs":
            self._send_json(200, {"runs": _recent_runs(state.out_dir)})
            return
```

The response is exactly `{"runs": [...]}`; each entry has exactly the six keys above. The route never
writes (a test snapshots every byte and mtime of the output folder around three calls).

## 2. `tools/export_replay.py`: the replay records the list

Replace the `FIXED_PATHS` line with:

```python
FIXED_PATHS = ("/api/review/queue", "/api/review/overrides", "/api/demo/rider", "/api/demo/driver",
               "/api/review/runs")
```

Append it LAST so the numbering of every existing recorded body is unchanged. The exporter already
records `/api/review/<run_id>/case` for every run in the snapshot, so every run the recorded list
shows opens in the replay; the shim needs no change.

## 3. `ui/index.html`

**3a.** Directly after the closing `</section>` of `#overrides-panel` and before the
`<section class="loader-panel" ...>`, add:

```html
    <section id="runs-panel" aria-labelledby="runs-title">
      <div class="section-heading">
        <div>
          <p class="eyebrow">OPERATOR CONSOLE</p>
          <h2 id="runs-title">Recent runs</h2>
        </div>
      </div>
      <p id="runs-status" role="status" aria-live="polite">Loading recent runs…</p>
      <div id="runs-content"></div>
    </section>

```

**3b.** In the loader panel, replace these four lines

```html
      <label for="case-picker">Case file JSON</label>
      <input id="case-picker" type="file" accept=".json,application/json">
      <label for="run-folder-picker">Run directory for event payloads (optional)</label>
      <input id="run-folder-picker" type="file" webkitdirectory directory multiple>
```

with these three (the hint is ONE line, exact text):

```html
      <label for="run-folder-picker">Run folder</label>
      <p id="run-folder-hint" class="loader-hint">Pick one run folder inside runs/, named like 20260921T161731Z-RD-0109. Select the folder itself, not the files inside it.</p>
      <input id="run-folder-picker" type="file" webkitdirectory directory multiple aria-describedby="run-folder-hint">
```

Nothing else in the page changes. `#case-picker` must not appear anywhere in the page or the script.

## 4. `ui/app.js`

Plain ES5 like the rest of the file. Apply each change at the named anchor.

**4a.** In the `state` object, after `currentQueueRun: null,` add `currentList: null,`.

**4b.** Replace `var picker = document.getElementById("case-picker");` with these constants (keep the
`runFolderPicker` line that follows):

```js
  var CASE_FILE_NAME = "case_file.json";
  var RUN_FOLDER_NO_CASE_FILE = "This folder has no case_file.json. Pick the run folder itself, "
    + "named like 20260921T161731Z-RD-0109, not a folder inside it such as payloads/.";
  var RUN_FOLDER_SEVERAL_RUNS = "This folder holds run folders, not one run. "
    + "Open it and pick one run folder, named like 20260921T161731Z-RD-0109.";
  var RUNS_UNAVAILABLE = "Recent runs are not available here. Open the console from the running server to use them.";
  var RUNS_EMPTY = "No runs yet.";
```

**4c.** After `var overridesContent = document.getElementById("overrides-content");` add:

```js
  var runsStatus = document.getElementById("runs-status");
  var runsContent = document.getElementById("runs-content");
```

**4d.** Directly after the function `relativeRunPath`, add:

```js
  // W35: a picked run folder carries its case file at <picked>/case_file.json. The browser
  // names every file "<picked folder>/<path inside it>", so the case file is the one whose
  // path has exactly two parts. A case file one level further down means the picked folder
  // holds run folders (runs/ itself), which is a different mistake with its own message.
  function pickedRunFolder(files) {
    var found = { file: null, label: "", error: RUN_FOLDER_NO_CASE_FILE };
    var nested = false;
    Array.prototype.forEach.call(files || [], function (file) {
      var parts = String(file && file.webkitRelativePath || "").split("/");
      if (parts.length === 2 && parts[0] !== "" && parts[1] === CASE_FILE_NAME) {
        found = { file: file, label: parts[0] + "/" + CASE_FILE_NAME, error: null };
      } else if (parts.length === 3 && parts[2] === CASE_FILE_NAME) {
        nested = true;
      }
    });
    if (!found.file && nested) {
      found.error = RUN_FOLDER_SEVERAL_RUNS;
    }
    return found;
  }
```

**4e.** Replace the whole function `handleFile(file)` with these four functions (the read, the
generation guard and both JSON messages are unchanged; the reset and the failure display become
shared, and the picked folder's files attach only after the case loaded):

```js
  // A local load is a user action: it wins over a pending deep link, drops every pending
  // server open and any late /prompts reply, and clears the server selection. Returns the
  // generation the local read must still own when it settles.
  function beginLocalLoad() {
    state.userActionSeen = true;
    state.openRun = null;
    state.currentQueueRun = null;
    state.currentList = null;
    invalidatePendingOpens();
    state.promptsGeneration += 1;
    applyQueueSelection();
    if (decisionSection) {
      decisionSection.hidden = true;
    }
    state.payloadFiles = {};
    setPayloadStatus("Payload files are not attached.", "idle");
    return state.openGeneration;
  }

  function showLoadFailure(message) {
    state.openRun = null;
    if (decisionSection) {
      decisionSection.hidden = true;
    }
    workspace.hidden = true;
    clear(metadataList);
    clear(grievanceContent);
    clear(evidenceContent);
    if (promptsContent) {
      clear(promptsContent);
    }
    clear(claimsContent);
    clear(policyContent);
    clear(resolutionContent);
    clear(eventsContent);
    setStatus(message, "error");
  }

  function handleFile(file, label, runFiles) {
    if (!file) {
      return;
    }

    var readGeneration = beginLocalLoad();
    var name = label || file.name;
    setStatus("Reading " + name + "…", "loading");
    file.text().then(function (text) {
      if (readGeneration !== state.openGeneration) {
        return;
      }
      var parsed;
      try {
        parsed = JSON.parse(text);
      } catch (error) {
        throw new Error("The selected file is not valid JSON.");
      }
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        throw new Error("The selected JSON must contain one case-file object.");
      }
      renderCase(name, parsed);
      if (runFiles) {
        attachRunFiles(runFiles);
      }
    }).catch(function (error) {
      if (readGeneration !== state.openGeneration) {
        return;
      }
      showLoadFailure(error.message);
    });
  }

  // W35: one picker. The picked run folder's own case_file.json loads through handleFile and
  // every file in the folder is attached for the event payloads, in one action.
  function handleRunFolder(files) {
    var list = Array.prototype.slice.call(files || []);
    if (list.length === 0) {
      return;
    }
    var picked = pickedRunFolder(list);
    if (!picked.file) {
      beginLocalLoad();
      showLoadFailure(picked.error);
      return;
    }
    handleFile(picked.file, picked.label, list);
  }
```

**4f.** Replace the head of `applyQueueSelection` so the marker logic serves both lists. The old
function starts:

```js
  function applyQueueSelection() {
    if (!queueContent || typeof queueContent.querySelectorAll !== "function") {
      return;
    }
    var rows = queueContent.querySelectorAll(".queue-row");
    Array.prototype.forEach.call(rows, function (row) {
      var button = typeof row.querySelector === "function" ? row.querySelector(".queue-open") : null;
      if (!button) {
        return;
      }
      var current = state.currentQueueRun !== null
        && Boolean(row.dataset) && row.dataset.runId === state.currentQueueRun;
```

Replace exactly those lines with the following; the rest of the old body (from `if (current) {` to the
closing `});` and `}`) stays as it is and becomes the body of `applyListSelection`:

```js
  // The open case is marked in the list it was opened from (queue or Recent runs), so exactly
  // one row on the page carries aria-current even when both lists show the same run.
  function applyQueueSelection() {
    applyListSelection(queueContent, ".queue-row", ".queue-open", "queue");
    applyListSelection(runsContent, ".run-row", ".run-open", "runs");
  }

  function applyListSelection(container, rowSelector, buttonSelector, list) {
    if (!container || typeof container.querySelectorAll !== "function") {
      return;
    }
    var rows = container.querySelectorAll(rowSelector);
    Array.prototype.forEach.call(rows, function (row) {
      var button = typeof row.querySelector === "function" ? row.querySelector(buttonSelector) : null;
      if (!button) {
        return;
      }
      var current = state.currentQueueRun !== null && state.currentList === list
        && Boolean(row.dataset) && row.dataset.runId === state.currentQueueRun;
```

**4g.** Replace the function `loadReviewPanels` with the following (the Recent runs panel, its
loader, the panels loader that now also loads the runs, and the user's Refresh):

```js
  function outcomeLabel(outcome) {
    if (outcome === "ruled") {
      return "Ruled";
    }
    if (outcome === "withheld") {
      return "Held for a human";
    }
    if (outcome === "human_review") {
      return "Passed to support";
    }
    if (outcome === "needs_info") {
      return "Asked for more information";
    }
    return "Outcome: " + displayValue(outcome);
  }

  // A row needs a run id the open path accepts; anything else (null, arrays, {}, strings,
  // numbers, a malformed id) is skipped.
  function isRunEntry(entry) {
    return Boolean(entry) && typeof entry.run_id === "string" && RUN_ID_PATTERN.test(entry.run_id);
  }

  function renderRuns(data) {
    clear(runsContent);
    var runs = data && typeof data === "object" && !Array.isArray(data) && Array.isArray(data.runs)
      ? data.runs.filter(isRunEntry)
      : null;
    if (runs === null) {
      runsStatus.textContent = RUNS_UNAVAILABLE;
      return;
    }
    if (runs.length === 0) {
      runsStatus.textContent = RUNS_EMPTY;
      return;
    }
    runsStatus.textContent = runs.length === 1 ? "1 run, newest first." : runs.length + " runs, newest first.";
    var list = element("ol", "runs-list");
    runs.forEach(function (entry) {
      var row = element("li", "run-row");
      row.dataset.runId = entry.run_id;
      row.appendChild(element("span", "run-id", entry.run_id));
      row.appendChild(element("span", "run-category", categoryLabel(entry.category)));
      row.appendChild(element("span", "run-outcome", outcomeLabel(entry.outcome)));
      row.appendChild(element("span", "run-generated", typeof entry.generated_at === "string" && entry.generated_at
        ? entry.generated_at
        : "Time not recorded"));
      if (entry.has_human_decision === true) {
        row.appendChild(element("span", "run-decided", "Human decision recorded"));
      }
      var open = element("button", "run-open", "Open case");
      open.type = "button";
      var openStatus = element("p", "run-open-status");
      openStatus.setAttribute("role", "status");
      openStatus.setAttribute("aria-live", "polite");
      open.addEventListener("click", function () {
        state.userActionSeen = true;
        openCase(deepLinkEntry(entry.run_id), open, openStatus, "runs");
      });
      row.appendChild(open);
      row.appendChild(openStatus);
      list.appendChild(row);
    });
    runsContent.appendChild(list);
    applyQueueSelection();
  }

  function loadRuns() {
    if (!runsStatus || !runsContent) {
      return Promise.resolve();
    }
    return fetchJson("/api/review/runs").then(function (data) {
      renderRuns(data);
    }).catch(function () {
      clear(runsContent);
      runsStatus.textContent = RUNS_UNAVAILABLE;
    });
  }

  function loadReviewPanels() {
    var queueLoad = loadQueue();
    loadOverrides();
    loadRuns();
    return queueLoad;
  }

  // A Refresh the user asks for invalidates every pending open: the row it came from is
  // about to be replaced. (No local read can be pending while a server open is.)
  function refreshReviewPanels() {
    if (state.pendingOpens.length > 0) {
      invalidatePendingOpens();
    }
    return loadReviewPanels();
  }
```

A Recent runs open goes through the queue's own `openCase` (pending label, disabled, row-local
failure with retry, generation guards on success, failure and the button restore, focus and scroll to
the case summary). It passes the queue's entry for that run when the queue lists it, so a held run
opened from either list gets the same decision form.

**4h.** In `openCase`: change the signature to `function openCase(entry, button, statusElement, list) {`
and, directly after `state.currentQueueRun = runId;`, add:

```js
      state.currentList = list === "runs" ? "runs" : "queue";
```

**4i.** Replace the function `deepLinkEntry` with these two:

```js
  function queuedEntry(runId) {
    var entries = state.queueEntries;
    if (Array.isArray(entries)) {
      for (var index = 0; index < entries.length; index += 1) {
        var entry = entries[index];
        if (entry && typeof entry === "object" && entry.run_id === runId) {
          return entry;
        }
      }
    }
    return null;
  }

  // The entry an open passes on: the queue's own row for a queued run (its proposal makes the
  // decision form identical to a queue click), else just the run id.
  function deepLinkEntry(runId) {
    return queuedEntry(runId) || { run_id: runId };
  }
```

**4j.** In `openDeepLink`, inside the `queueLoad.then(...)` callback, replace
`openCase(deepLinkEntry(runId), null, null);` with:

```js
        openCase(deepLinkEntry(runId), null, null, queuedEntry(runId) ? "queue" : "runs");
```

(The no-queue branch `openCase({ run_id: runId }, null, null);` stays as it is.)

**4k.** At the bottom, delete the `picker.addEventListener("change", ...)` block, replace the
run-folder listener body with `handleRunFolder(runFolderPicker.files);`, and wire Refresh to the new
function:

```js
  runFolderPicker.addEventListener("change", function () {
    handleRunFolder(runFolderPicker.files);
  });

  var startupQueueLoad = null;
  if (reviewUi && typeof fetch === "function") {
    queueRefresh.addEventListener("click", refreshReviewPanels);
    startupQueueLoad = loadReviewPanels();
  }
```

## 5. `ui/styles.css`

Append this block at the END of the file and change nothing else in it. The rules are pinned
exactly (selector, every declaration, count) because `tests/test_w15_feedback.py` skips exactly
these selectors in its console digest; any other edit to the file reddens that digest.

```css

/* W35: Recent runs. The panel matches the queue panel; each row is a wrapping flex line
   like a queue row, and a long list scrolls inside itself. */
#runs-panel {
  margin-top: 28px;
  padding: 20px 22px;
  background: var(--panel);
  border: 1px solid var(--line);
  border-left: 4px solid var(--accent);
  border-radius: 16px;
  box-shadow: var(--shadow);
}

#runs-panel .section-heading > div {
  min-width: 0;
}

#runs-status {
  min-height: 20px;
  margin: 0 0 12px;
  color: var(--muted);
  font-size: 13px;
}

.runs-list {
  display: grid;
  gap: 8px;
  max-height: min(26rem, 70vh);
  margin: 0;
  padding: 0;
  overflow-y: auto;
  list-style: none;
}

.runs-list > .run-row {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: center;
  padding: 12px;
  color: var(--ink);
  background: var(--panel);
  border: 1px solid var(--line);
}

.run-row > span {
  flex: 1 1 auto;
  min-width: 0;
  max-width: 100%;
  overflow-wrap: anywhere;
}

.run-row > .run-category {
  font-weight: 700;
}

.run-row > .run-id,
.run-row > .run-outcome,
.run-row > .run-generated,
.run-row > .run-decided {
  color: var(--muted);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
}

.run-row > .run-open {
  flex: 0 0 auto;
  min-height: 44px;
  max-width: 100%;
  padding: 8px 12px;
  color: var(--ink);
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 4px;
  font-weight: 600;
}

.run-row > .run-open:hover {
  background: var(--canvas);
  border-color: var(--muted);
}

.runs-list > .run-row.is-open {
  background: var(--canvas);
  border-color: var(--muted);
}

.run-open-status {
  flex: 1 0 100%;
  margin: 0;
  color: var(--red);
  font-size: 12px;
}

.run-open-status:empty {
  display: none;
}

/* W35: the run-folder picker's hint. */
.loader-hint {
  margin: 0 0 10px;
  color: var(--muted);
  font-size: 13px;
}

/* W35: the prompt card's full text takes the dark code panel of the event payloads, so the
   light text is readable (it sat on the white claim card at 1.15:1). */
#prompts-content details > .payload-json {
  margin-top: 10px;
  padding: 12px;
  background: #182334;
  border: 1px solid #2f455f;
  color: #e7eef7;
}
```

The prompt full text then reads at 13.52:1 (it measured 1.15:1). Event payloads are untouched: their
dark panel is the `.event-payload` container and their `<pre>` stays bare.

**Do not add an `--accent-strong` token to `ui/styles.css`.** This is a planner ruling and it
replaces the earlier instruction to add one. The console already has `--accent-text: #C8284F` for
pink text (5.42:1 on white, 4.94:1 on the page canvas) and has no white-on-pink fill, so the token
would be unused. The ruling was checked in a real browser on the reference: every text element in
the console was measured from its computed colours, with the queue, Overrides and Recent runs
loaded, a pending open, the prompt full text expanded, an event payload open, the decision form's
errors, row-local failures, "Recent runs are not available here", and each wrong-folder message
shown. Every console text pair measured 4.5:1 or higher. The lowest were `#646c77` on `#f5f4f3` at
4.84:1 and `#c8284f` on `#f5f4f3` at 4.94:1. The one pair under 4.5:1 on that page is the demo switch
bar's current link (white on `#e93864`, 4.03:1). It lives in `ui/switch-bar.css`, which the sibling
lane owns and fixes, so do not change it here. `tests/browser/w35_C.cjs` runs the same measurement
at six widths (switch bar excluded) and fails on any pair under AA.

## Verify, then stop

```bash
env -u PYTHONPATH /usr/bin/python3 -m unittest tests.test_w35_C
PUPPETEER_MODULE=[USER_HOME]/.hermes/cache/browser-verify/node_modules/puppeteer \
BROWSER_EXECUTABLE="/Applications/Brave Browser.app/Contents/MacOS/Brave Browser" \
  env -u PYTHONPATH /usr/bin/python3 -m unittest tests.test_w35_C
env -u PYTHONPATH /usr/bin/python3 -m unittest discover -s tests -t .
git status --short
```

Both numbers below were measured by the planner on the shared baseline (both lanes' tests and test
updates installed, both browser variables set), not computed.

**At the start (RED):** Ran 1513 tests, FAILED (failures=149), zero errors. 1513 is 1433 at
`57758ce`, minus 6 freeze tests the two lanes release, plus 25 tests in `tests/test_w35_P.py` and 61
in `tests/test_w35_C.py`. Every failure is in `tests/test_w35_P.py` (47), `tests/test_w35_C.py` (74)
or the nine existing console modules the console lane's updates touch (28).

**When you are done (measured on the planner's reference for this lane, in the shared tree):** Ran
1513 tests, FAILED (failures=48), zero errors. The 48 are exactly the party lane's 47 deliberate
failures in `tests/test_w35_P.py` plus one colour-ledger subtest, `sheet='ui/styles.css'`.
`tests.test_w35_C` alone runs 61 tests: OK with both browser variables set, OK (skipped=2) without
them. Any other failure, or any error, means stop and report.

Before your commit, `git status --short` must list only files from the allowed list. Report the
commit hash and the test lines. The parent runs the existing browser scripts.

## Stop and ask instead of guessing

- a test seems to contradict this brief;
- a fix needs a file outside the allowed list;
- the full suite fails outside `tests/test_w35_C.py`, the colour ledger test and the sibling's files.
