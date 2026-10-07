# W34 fix round brief: filing frame, proxy, port race, slow refusal

Follow-up to `docs/build-briefs/w34-launcher-brief.md`, on top of your commit `49ce669`. The
acceptance contract is the updated `tests/test_w34_launcher.py` plus the new real-browser script
`tests/browser/w34_pages.cjs`, both committed by the planner. Every finding below was reproduced
before it was pinned. Make the tests pass without editing any file under `tests/`. If a test looks
wrong, stop and report the test name and the reason.

## Protocol (unchanged from the first brief; obey it on every turn)

- Work only in this repository. No other worktrees, planning or scratch folders, no subagents, no
  network, no live model.
- Interpreter: `/usr/bin/python3` with `PYTHONPATH` removed (`env -u PYTHONPATH ...`).
- A server you start binds a port in 18000-18999, never 8000-8010, and you stop it before you finish.
- Never `rm -rf`, never `git add -A`, never merge, never push. Commit once at the end with an
  explicit `git add` of the files you changed.

## Allowed files (this round)

- `ui/switch-bar.css`
- `tools/launch.py`
- `README.md`: the `## Run` section only

Nothing else. In particular `ui/party/party.css`, every page, every `.js`, `app/` and `tests/` stay
as they are.

## 1. `ui/switch-bar.css`: the bar must not push the filing form off the screen

**Defect.** The rider and driver filing forms are a one-screen frame: `party.css` gives the filing
shell `height: 100dvh` and locks body scrolling while the form is open. The bar now sits above that
frame, so the frame overflows by the bar's height and the Continue button and the fine print fall
below the fold. This happens even on a 1280x844 laptop. `tests/browser/w30_filing_frame.cjs` and
`tests/browser/w30_viewport_states.cjs` pass before W34 and fail on `49ce669`.

**Fix.** Append these three rules to `ui/switch-bar.css`, after the existing rules, and change
nothing else in the file:

```css
/* The filing form is a one-screen frame (party.css). With the bar above it, the
   body becomes that screen: a column the bar sits at the top of, and the frame
   takes what is left, so the fine print and the actions stay on screen. */
body:has(.filing-shell #form-steps:not([hidden])) {
  display: flex;
  flex-direction: column;
  height: 100vh;
  height: 100dvh;
}

body:has(.filing-shell #form-steps:not([hidden])) > .switch-bar {
  flex: none;
}

body:has(.filing-shell #form-steps:not([hidden])) > .filing-shell {
  flex: 1 1 auto;
  min-height: 0;
  height: auto;
  width: 100%;
  box-sizing: border-box;
}

/* On a very short screen (a phone on its side) the filing form needs every pixel,
   so the bar steps aside while the form is open. The form's own header keeps its
   links, and the bar is back on the receipt and on every other page. */
@media (max-height: 520px) {
  body:has(.filing-shell #form-steps:not([hidden])) > .switch-bar {
    display: none;
  }
}
```

Every declaration is load-bearing, and each was removed in turn to prove it. Without
`width: 100%`, the shell's `margin: 0 auto` shrinks the rider form from 720 px to 556 px on a
desktop. Without `min-height: 0`, the frame overflows again. Without the media rule, a 360x480
screen leaves the form a scroll region under 20 px.

## 2. `tools/launch.py`: three fixes

**2a. Loopback probes ignore the user's proxy.** `urllib.request.urlopen` honours `http_proxy` and
the system proxy settings, and macOS's default proxy exceptions do not include `127.0.0.1`. With a
proxy configured, `is_ryde_demo` reads a running demo as absent and `open_when_ready` never sees the
server answer, so the browser never opens. Build one module-level opener with
`urllib.request.build_opener(urllib.request.ProxyHandler({}))` and make every probe in `_answer`
(and anywhere else the launcher fetches a loopback URL) use it instead of `urlopen`.

**2b. A port taken between the pick and the bind prints a plain line.** Two quick double-clicks
can both pick the same free port. The second server's bind raises
`OSError: [Errno 48] Address already in use` as a traceback, right after the window said the demo
is running. Add the constant

`PORT_TAKEN = "Port {port} was taken just as the demo started. Open this file again."`

In `main`, wrap the `server.main(server_argv(port))` call. If it raises `OSError` whose `errno` is
`errno.EADDRINUSE` or `10048` (Windows' WSAEADDRINUSE), print `PORT_TAKEN` with the port and return
1. Any other exception must propagate unchanged: catch the bind race only, not real bugs. Do not
retry. A second double-click then reuses the winning demo or takes the next free port, and
`start.bat` already pauses on a non-zero exit.

**2c. A slow refusal is still a free port.** Windows retries a refused loopback connect for about
one to two seconds before reporting it, so the current 1 s connect timeout can read every free port
as busy. Add `CONNECT_TIMEOUT = 3.0` and use it as the `timeout` of the `socket.create_connection`
call in the free-port check. Keep `PROBE_TIMEOUT` (1 s) for the HTTP probes. A refusal still means
free. Any other `OSError`, including a timeout, still means busy.

## 3. `README.md` `## Run`

In the one-click paragraph, directly after the sentence ending "uses the first free one.", add this
sentence verbatim:

`If you already started the demo yourself, the launcher reuses that copy as it is.`

(Reason: reuse checks only that the port serves this demo, not which model it runs. Someone who
started a live copy by hand gets that copy back.)

## Verify, then stop

```bash
env -u PYTHONPATH /usr/bin/python3 -m unittest tests.test_w34_launcher
env -u PYTHONPATH /usr/bin/python3 -m unittest discover -s tests -t .
git status --short
```

What you should see: the W34 file runs 59 tests, OK. The full suite runs 1433 tests, OK
(skipped=2). Before your commit, `git status --short` lists only the three allowed files. Report the
commit hash and both test lines. The browser scripts are run by the parent; you do not need them.

## Stop and ask instead of guessing

- a test seems to contradict this brief;
- a fix needs a file outside the three allowed files;
- the full suite fails outside `tests/test_w34_launcher.py`.
