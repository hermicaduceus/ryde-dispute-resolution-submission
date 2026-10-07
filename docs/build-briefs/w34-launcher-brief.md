# W34 build brief: one-click launcher, start page and switch bar

The acceptance contract is `tests/test_w34_launcher.py`, committed RED on `main` before this
session. Make it pass, keep the full suite green, and edit no file under `tests/`. If a test looks
wrong, stop and report the test name and the reason. Do not work around it.

## Protocol (obey this on every turn, including a resumed one)

- Work only in this repository. Do not read other worktrees, the planning folder or any scratch
  folder. No subagents, no network calls, no live model (`--llm tencent` is never used here).
- Interpreter: `/usr/bin/python3`, with `PYTHONPATH` removed (`env -u PYTHONPATH ...`).
- A server you start for a manual check binds a port in 18000-18999, never 8000-8010, and you stop
  it before you finish.
- Never `rm -rf`, never `git add -A`, never merge, never push.
- Commit at the end with an explicit file list: `git add <each allowed file you changed>`, then one
  commit. The parent verifies and merges.

## Allowed files

New:

- `start.command` (executable, mode 755, Unix line endings)
- `start.bat` (CRLF line endings on every line)
- `.gitattributes` containing the line `*.bat -text`, so git never rewrites the `.bat` line endings
- `tools/launch.py`
- `ui/start/index.html`
- `ui/start/start.css`
- `ui/switch-bar.css`

Edited:

- `app/server.py`: `parse_args` and `main` only. Nothing above `def parse_args(` may change (a test
  hashes that prefix).
- `ui/index.html`, `ui/party/index.html`, `ui/party/driver-filing.html`, `ui/party/driver.html`,
  `ui/party/status.html`: exactly one added stylesheet line and one added nav line each.
- `README.md`: the `## Run` section only.

Everything else is out of scope: every existing `.js` and `.css` file, all of `app/` except
`server.py`, `data/`, `docs/policy.md`, `tools/replay/`, `tools/export_replay.py`, and every test.
The baseline commit already released the old freeze pins on the five pages and `app/server.py`;
there is no test edit for you to make.

## 1. `app/server.py`: `--port`

Add `--port` to `parse_args`: integer, default `DEFAULT_PORT` (8000), accepted range 1 to 65535.
Refuse `0`, `65536`, `-1`, `abc`, `80.5` and the empty string through argparse (exit 2), before
anything binds. `main` passes `args.port` to `make_server` instead of `DEFAULT_PORT`. `--llm` is
unchanged.

## 2. `tools/launch.py`

The launcher picks a port, opens the browser, and runs the EXISTING server entry point. It does
not re-implement server startup.

Module surface the tests import or patch by name (all module-level):

| Name | Contract |
|---|---|
| `FIRST_PORT`, `LAST_PORT` | `8000`, `8010` |
| `START_PATH` | `"/start/"` |
| `start_url(port)` | `"http://127.0.0.1:%d/start/" % port` |
| `RUNNING` | `"Ryde demo running at {url}"` |
| `STOP_HINT` | `"Close this window (or press Ctrl+C) to stop the demo."` |
| `ALREADY_RUNNING` | `"The Ryde demo is already running at {url}. Opening it in your browser."` |
| `NO_FREE_PORT` | `"Ports {first} to {last} are all in use by other programs. Close one of them, then open this file again."` |
| `OPEN_YOURSELF` | `"Could not open a browser. Open {url} yourself."` |
| `is_ryde_demo(port)` | True only if `GET /start/` on that port answers 200 AND the `Server` header starts with `RydePartyServer/`. Nothing listening, another program's 200, or the Ryde header on a 404 are all False. Use a short timeout (about 1 s) so a silent listener cannot stall it. |
| `pick_port(first, last)` | Walk the ports in order. A port running the demo returns `(port, True)`. A port with any other listener (HTTP or silent) is skipped. The first free port returns `(port, False)`. None free returns `(None, False)`. "Free" means a TCP connect to 127.0.0.1 is refused. The whole call over a silent listener finishes well under 5 s. |
| `server_argv(port)` | `["--llm", "mock", "--port", str(port)]` |
| `open_when_ready(url, timeout=...)` | Poll `url` until it answers 200, then call `webbrowser.open(url)` exactly once. If that returns False or raises `webbrowser.Error`, or the timeout passes first, print `OPEN_YOURSELF` and return. Print nothing on success. |
| `main(argv=None)` | See below. Returns an int exit code. |
| `server` | the `app.server` module, imported at module level |
| `webbrowser` | the standard `webbrowser` module, imported at module level |

**Import constraint.** The tests patch `launch.server.main`, `launch.open_when_ready`,
`launch.pick_port` and `launch.webbrowser.open`, so `main` must reach each through these
module-level names at call time. Do not import `main` or `open` into local names. The file is run
as `python3 tools/launch.py`, where `sys.path[0]` is `tools/`, so insert the repository root into
`sys.path` before `import app.server`. Use the stock `webbrowser.open`: it already honours the
`BROWSER` environment variable that the end-to-end tests use. Do not parse `BROWSER` yourself.

`main(argv)`:

1. Parse `--ports A-B` (default `8000-8010`) and call `pick_port(A, B)`.
2. No port: print `NO_FREE_PORT` with the range, return 1. No server, no browser.
3. A running demo: print `ALREADY_RUNNING`, call `webbrowser.open(url)` (print `OPEN_YOURSELF` if it
   fails), return 0. Never start a second server.
4. A free port: print `RUNNING` then `STOP_HINT`. Start `open_when_ready(url)` in a DAEMON thread,
   then call `server.main(server_argv(port))` on the MAIN thread and return its exit code.

Step 4's layout is load-bearing. The browser must open only after the server answers, so the waiter
cannot run before the server on the same thread. With the server on the main thread, Ctrl+C reaches
the existing server's own `KeyboardInterrupt` handler, which closes the socket and returns 0, and a
closed terminal window (SIGHUP) ends the single process, freeing the port.

## 3. `start.command` (macOS)

- First line `#!/bin/bash`, Unix line endings, executable. Run `chmod 755 start.command` before
  committing so git records mode 100755.
- Change to the script's own folder first (`cd "$(dirname "$0")"`), so a double-click from any
  folder works. Use only bash builtins plus `dirname`.
- If `python3` is missing, or `python3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)"`
  fails, print exactly this line, wait for one keypress (`read`), and exit non-zero:
  `Python 3.9 or newer is needed to run the Ryde demo. Install it from https://www.python.org/downloads/ and then open this file again.`
  The version check text must contain `sys.version_info >= (3, 9)`.
- Otherwise hand over with `exec python3 tools/launch.py` (a relative path, after the `cd`), so the
  Terminal window owns one process.

## 4. `start.bat` (Windows)

- CRLF on every line. First line `@echo off`. Then `cd /d "%~dp0"`.
- Try `py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)"` first, then the same
  with `python -c "..."`. Remember which one passed.
- If neither passes, print the same sentence as section 3 (either `echo <sentence>`, or
  `set "VAR=<sentence>"` followed by `echo %VAR%`), then `pause` on its own line, then `exit /b 1`.
- Otherwise run `tools\launch.py` with the interpreter that passed, ONCE. If it exits non-zero, `pause`
  so the window does not vanish.
- Avoid parenthesised `if (...)` blocks around lines that contain `(3, 9)`; use `goto` labels. This
  file cannot be run on the build machine; the teammate tests it on Windows.

## 5. Start page: `ui/start/index.html` + `ui/start/start.css`

Served at `/start/` by the existing static handler (no server change). Required:

- A `<head>` line on its own (the replay exporter inserts a script after it), the viewport meta
  `width=device-width, initial-scale=1`, and the local `./start.css`. No `<script>`.
- `<title>` and `<h1>`: `Ryde dispute resolution demo`.
- One `<p>`: `Runs on your computer with sample trips. The AI is a stand-in (mock), so no key is needed.`
- Exactly two links, in this order. A link's text is all its text nodes joined by single spaces:
  1. `href="../party/"`, text `File a dispute As a rider or a driver, on a sample trip`
  2. `href="../"`, text `Operator console The review queue, human decisions and every case file`
  (for example a title line and a smaller description line inside each link).
- Readable at 390 px (cards stacked) and 1280 px. Match the Ryde look of the existing pages (Poppins,
  the pink accent). Do not write that nothing leaves the computer: the pages load Google Fonts.

## 6. Switch bar on the five pages

On each page add, as one line directly after `<body>`, so the bar is the first element in the body:
`<nav class="switch-bar" aria-label="Demo pages">` with three links, in order `Start`,
`File a dispute`, `Operator console`, and `</nav>` on the same line.

| Page | `Start` href | `File a dispute` href | `Operator console` href | `aria-current` |
|---|---|---|---|---|
| `ui/index.html` (served `/`) | `./start/` | `./party/` | `./` | `page` on Operator console |
| `ui/party/index.html` (`/party/`) | `../start/` | `./` | `../` | `page` on File a dispute |
| `ui/party/driver-filing.html` | `../start/` | `./` | `../` | `true` on File a dispute |
| `ui/party/status.html` | `../start/` | `./` | `../` | `true` on File a dispute |
| `ui/party/driver.html` | `../start/` | `./` | `../` | `true` on File a dispute |

Exactly one link per bar carries `aria-current`. `page` marks the page itself; `true` marks the
party section on the other party pages. All links are relative, because the static replay copies
`ui/` under a sub-path.

Add one stylesheet line per page, after the existing local stylesheet: `./switch-bar.css` on the
console, `../switch-bar.css` on the party pages. Those two lines are the ONLY change to each page: a
test deletes them and requires the original bytes back.

`ui/switch-bar.css`: a compact single row that wraps on narrow screens, readable tap targets, the
current link visibly marked. It must not use `position: sticky` or `position: fixed`. It scrolls
away with the page, because a pinned bar would push the filing form's buttons off a phone screen.

## 7. README `## Run`

Lead with the one-click route, before the manual command. State: double-click `start.command`
(macOS) or `start.bat` (Windows); Python 3.9 or newer, no API key; the browser opens
`http://127.0.0.1:8000/start/`; if 8000 is busy it reuses a running demo or tries 8001 to 8010; a
macOS ZIP download may need System Settings, Privacy & Security, **Open Anyway**; Windows SmartScreen
may need **More info**, then **Run anyway**; closing the terminal window (or Ctrl+C) stops the
server, closing only the browser does not. Keep the manual `python3 -m app.server` block and the
`http://127.0.0.1:8000/` and `http://127.0.0.1:8000/party/` lines as the fallback.

## Baseline you start from

On the committed baseline every test passes except `tests/test_w34_launcher.py`, which fails by
assertion (no import errors): that file is your target. A failure anywhere else, or any ERROR line,
is a blocker to report, not a test to edit.

## Verify, then stop

```bash
env -u PYTHONPATH /usr/bin/python3 -m unittest tests.test_w34_launcher
env -u PYTHONPATH /usr/bin/python3 -m unittest discover -s tests -t .
git status --short
```

What you should see when you are done: the W34 file runs 48 tests, OK. The full suite runs 1422
tests, OK (skipped=2). `git status --short` lists only the allowed files before your commit, and is
empty after it. Report the commit hash and both test lines.

## Stop and ask instead of guessing

- a test seems to contradict this brief;
- a requirement needs a file outside the allowed list;
- the existing `app.server.main` cannot be called as described;
- the full suite fails outside `tests/test_w34_launcher.py`.
