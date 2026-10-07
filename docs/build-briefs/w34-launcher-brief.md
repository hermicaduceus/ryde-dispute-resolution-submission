# W34 build brief. The committed RED contract is tests/test_w34_launcher.py.

## Deliverable

Build the one-click local launcher for the Ryde mock demo. Work from the repository root and make the full suite green. Do not edit `tests/test_w34_launcher.py`, any other test file, or any file outside the allowed list below. If a test looks wrong, stop and report the exact test name and reason.

## Allowed files

New files:

- `start.command`, executable with Unix line endings
- `start.bat`, with CRLF line endings
- `.gitattributes`, only the rule that keeps `*.bat` as text with its line endings
- `tools/launch.py`
- `ui/start/index.html`
- `ui/start/start.css`
- `ui/switch-bar.css`

Edited files:

- `app/server.py`, only `parse_args` and `main`: add `--port`, default 8000, valid range 1 through 65535, and pass it to `make_server`. Do not change the code above `def parse_args(`.
- `ui/index.html`
- `ui/party/index.html`
- `ui/party/driver-filing.html`
- `ui/party/driver.html`
- `ui/party/status.html`
- `README.md`, only the `## Run` section
- `tests/test_w15_feedback.py`, only remove the five HTML entries from the existing HTML/JavaScript byte-freeze map so the W34 HTML edits are allowed. Preserve the four JavaScript hashes and the test's CSS contracts.
- `tests/test_w24_fix_round.py`, only remove W34-touched HTML entries and `app/server.py` from its old freeze map. Preserve all remaining runtime, CSS, JavaScript and test hashes.

Do not edit existing JavaScript or existing CSS. Do not edit agent, model, data, policy or replay code. Do not add a Linux launcher, packaged executable, live-model launcher option, browser-tab shutdown logic, or new application agent behaviour.

## Behaviour contract

### Server

`python3 -m app.server --port N` binds N. The default remains 8000. Reject 0, 65536, negative values, decimals, empty strings and non-numbers before binding. The existing `--llm` option continues to work unchanged.

### Launcher module

`tools/launch.py` must be importable from a direct script launch, so add the repository root to `sys.path` before importing `app.server`. It must:

1. Inspect ports 8000 through 8010, in order.
2. If a port serves HTTP 200 for `/start/` and its `Server` header starts with `RydePartyServer/`, reuse it and open that URL. Do not start a second server.
3. Skip ports occupied by another HTTP server or a non-HTTP listener.
4. Start on the first free port. Pass `--llm mock --port N` to the existing `app.server.main` function in the same process. Do not duplicate server startup logic.
5. Print these exact lines when starting: `Ryde demo running at http://127.0.0.1:N/start/` and `Close this window (or press Ctrl+C) to stop the demo.`
6. Open the browser exactly once, only after the start page answers HTTP 200. If opening fails or the server never answers, print `Could not open a browser. Open http://127.0.0.1:N/start/ yourself.`
7. If all ports are occupied, print `Ports 8000 to 8010 are all in use by other programs. Close one of them, then open this file again.` and exit non-zero.
8. Return the existing server's exit code. A SIGHUP or Ctrl+C to the launcher must stop the server and free its port.

The helper API expected by the RED tests is `FIRST_PORT`, `LAST_PORT`, `START_PATH`, `RUNNING`, `STOP_HINT`, `ALREADY_RUNNING`, `NO_FREE_PORT`, `OPEN_YOURSELF`, `start_url`, `is_ryde_demo`, `pick_port`, `server_argv`, `open_when_ready`, and `main`.

### Platform wrappers

Both wrappers run from any current directory by changing to the repository folder first. Both check Python 3.9 or newer before starting the launcher. The exact missing-Python sentence is in the RED test constant `MISSING_PYTHON`.

`start.command` uses `python3`, prints the plain missing-Python sentence, waits for one keypress on failure, and uses `exec` for the launcher so the terminal window owns one server process. It must be executable.

`start.bat` tries `py -3` first, then `python`, checks the same version expression, prints the sentence and runs `pause` on failure, then runs `tools\\launch.py`.

### Start page

Serve it at `/start/` from `ui/start/index.html`. It has its own `<head>` line, viewport meta tag, local stylesheet and no script. The title and heading are `Ryde dispute resolution demo`. Include the exact intro and exactly two links, in this order:

1. `../party/`, text `File a dispute As a rider or a driver, on a sample trip`
2. `../`, text `Operator console The review queue, human decisions and every case file`

Use readable responsive layout at 390 and 1280 px. Do not claim that nothing is sent anywhere because the existing pages load Google Fonts.

### Switch bar

Add one `<nav class="switch-bar" aria-label="Demo pages">` as the first body child on each of the five existing pages. It contains three relative links with these destinations and labels, in order: Start → `/start/`, File a dispute → `/party/`, Operator console → `/`. Mark exactly one current link with `aria-current`, using `page` on the console and rider form, and `true` on the other party pages, matching the RED contract. Link one relative `switch-bar.css` stylesheet from each page. The five page edits must be limited to that stylesheet line and the one nav line. The bar is not sticky or fixed. It must not alter existing JavaScript or existing stylesheet bytes.

Because the replay exporter copies `ui/` under a subpath, use relative links. Every HTML page must retain its own `<head>` line.

### README

Put the launcher instructions first in `## Run`, retain the manual `python3 -m app.server` fallback, name `/start/`, the 8000 to 8010 fallback, Python 3.9, macOS **Open Anyway**, Windows **Run anyway**, and the fact that closing the terminal stops the server while closing only the browser does not.

## Verification the builder must run

Use the absolute interpreter `/usr/bin/python3` with `PYTHONPATH` removed. Run:

```bash
env -u PYTHONPATH /usr/bin/python3 -m unittest tests.test_w34_launcher
env -u PYTHONPATH /usr/bin/python3 -m unittest discover -s tests -t .
```

Do not run a live model or network call. Do not alter the RED tests to make a failure disappear. Commit only the allowed implementation and README files. Do not commit, push, merge, or use `git add -A`; the parent handles the commit.

## Expected sibling RED

The existing W15 and W24 freeze tests have been adjusted in the baseline commit to remove only the W34-owned HTML and server entries. All other tests must remain green. The new W34 test file is deliberately failing on this baseline and is the builder's target. A failure in any unrelated test or an import error is a blocker, not a reason to edit tests.

## Stop conditions

Stop and report instead of guessing if the allowed files overlap an unrelated change, a current test pins a the operator ruling that this brief contradicts, the server's existing entry point cannot be called in-process, or a required browser/launcher behaviour cannot be implemented without editing a forbidden file.
