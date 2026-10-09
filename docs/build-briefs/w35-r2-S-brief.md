# W35 round 2, lane S brief: the status page's lookup controls can never be covered or lost

Status-page layout fix. The acceptance contract is `tests/test_w35_r2_S.py` plus the real-browser
script `tests/browser/w35_r2_S.cjs`, committed by the planner together with a small update to
`tests/test_w35_P.py` (it pinned the old status-frame rules byte for byte). Every item below was built and
proven on a reference copy first; the code in this brief is that reference. Make the tests pass
without editing any file under `tests/`. If a test looks wrong, stop and report the test name and the
reason.

## The defect, in one paragraph

On the party status page (`ui/party/status.html`), `ui/switch-bar.css` frames the page in a fixed
screen from 654px of height: switch bar, header, "Look up a reference number" box, "My disputes"
list. The lookup box was allowed to shrink (`flex: 0 1 auto; min-height: 0`) below its own title,
field, error line and Check status button, so the controls overflowed onto the list. The list painted
over the button: it could not be tapped. `body` is `overflow: hidden` there, so nothing could scroll
to it. In an exported replay the replay banner (inserted by `tools/replay/replay-shim.js` as the
first child of `<body>`, 48 to 120px tall) takes room the 654px figure never budgeted, and the same
overlap appears with no error showing at 320px wide. The same overlap appears live whenever the error
line or the text is bigger than the empty box was measured with.

## The fix, in one paragraph

The lookup box never shrinks (`flex: none`). The lookup RESULT leaves the box and becomes its own
block under it, so that the result (and the header, down to 4.5rem, and the list, down to 8rem) are
the only things that give way. The result keeps a floor of 5rem and scrolls inside its own window.
`.status-shell` gets `overflow-y: auto` as the last resort: when the floors still do not fit (a long
error message, big text, a replay banner on a short phone) the shell scrolls, so nothing is ever
covered and nothing is cut off with the page unable to scroll. The 654px threshold stays: it was
re-measured with the error line present (see Verify).

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

- `ui/switch-bar.css`
- `ui/party/status.html`

Nothing else. `ui/party/status.js` stays as it is: it finds the result block by
`document.getElementById("lookup-result")`, which still works wherever the block sits. Do NOT touch
`ui/party/party.css`, the filing pages, `tools/replay/replay-shim.js`, or anything the sibling lane
owns (`ui/app.js`, `ui/index.html`, `ui/styles.css`, `app/*`, `tools/*`).

Why markup had to change and CSS alone could not do it: the lookup box has to be at least as tall
as its controls while still being able to give room to a tall result. In CSS a box's minimum size
is its content size, and a scrolling result INSIDE the box counts in full toward that size. A
grid with a `minmax(0, auto)` result row was measured in Brave: the box then refuses to shrink at
all and the shell scrolls by 900 to 1500px for a tall result. Pulling the result out of the box is
the smallest change that makes the controls rigid and the result flexible.

## Expected sibling RED

The shared baseline you start from carries BOTH lanes' RED tests. The sibling lane's test files
`tests/test_w35_r2_K.py`, `tests/test_w35_r2_paths.py` and `tests/browser/w35_r2_K.cjs`
fail on purpose in that baseline (they cover `ui/app.js` and `app/`); they belong to the other lane. Do not touch them and do
not try to make them pass.

This lane changes no colour, so the colour ledger test is not affected by it.

## 1. `ui/party/status.html`

Move the result block out of the lookup `<section>`: it becomes the next child of `<main>`, between
the lookup section and the list section. Replace exactly this:

```html
      <div class="step-actions">
        <button id="reference-check" class="primary" type="button">Check status</button>
      </div>
      <div id="lookup-result"></div>
    </section>

    <section class="step status-list">
```

with exactly this:

```html
      <div class="step-actions">
        <button id="reference-check" class="primary" type="button">Check status</button>
      </div>
    </section>

    <div id="lookup-result"></div>

    <section class="step status-list">
```

## 2. `ui/switch-bar.css`

All edits are inside the `@media (min-height: 654px)` status block and the comment above it. The
media query itself stays `@media (min-height: 654px) {`.

**2a. The comment.** Replace the whole `/* W35: the status page is one screen too ... */` comment
(the one directly above `@media (min-height: 654px) {`) with:

```css
/* W35: the status page is one screen too, when the screen is tall enough. The
   header and the "Look up a reference number" box stay put; only the "My
   disputes" list scrolls, inside its own region, so scrolling the list never
   hides the lookup box. The lookup box itself never shrinks: its title, field,
   error line and Check status button always keep their room. A lookup result
   is its own block under the box and takes the room above the list: the list
   gives up height down to 8rem and the header down to 4.5rem, and only then
   does the result scroll, inside its own window (never below 5rem). If those
   floors still do not fit (a long error message, or the replay banner that
   sits above the switch bar in an exported replay) the shell scrolls, so
   nothing is ever covered or cut off. Below 654px the page scrolls normally
   instead: there, on a 320px phone, the fixed header and lookup box would
   press the list to its 8rem floor and then clip the header. */
```

**2b. The shell scrolls as a last resort.** In the `.status-shell { ... }` rule of that block, add
one declaration after `padding: 0.5rem 1.25rem;`:

```css
  .status-shell {
    flex: 1 1 auto;
    min-height: 0;
    width: 100%;
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    padding: 0.5rem 1.25rem;
    overflow-y: auto;
  }
```

**2c. The lookup box is rigid.** Replace these two rules:

```css
  .status-shell > .status-lookup {
    flex: 0 1 auto;
    min-height: 0;
    display: flex;
    flex-direction: column;
  }

  .status-shell > .status-lookup > :not(#lookup-result) {
    flex: none;
  }
```

with this one rule (same place):

```css
  .status-shell > .status-lookup {
    flex: none;
  }
```

**2d. The result is its own flexible block.** Replace these two rules:

```css
  .status-shell > .status-lookup > #lookup-result {
    flex: 0 1 auto;
    min-height: 0;
    overflow-y: auto;
    overscroll-behavior: contain;
  }

  .status-shell > .status-lookup > #lookup-result > .step {
    margin: 0.5rem 0 0;
    padding: 0.75rem;
  }
```

with these three rules (same place, in this order):

```css
  .status-shell > #lookup-result:empty {
    display: none;
  }

  .status-shell > #lookup-result {
    flex: 0 1 auto;
    min-height: 5rem;
    overflow-y: auto;
    overscroll-behavior: contain;
  }

  .status-shell > #lookup-result > .step {
    margin: 0;
    padding: 0.75rem;
  }
```

Every other rule in the block (header, list, fields, actions, `.status-list` and `#account-list`)
stays byte for byte. Do not add a gradient, mask or fade anywhere.

## Verify, then commit and stop

Set these browser variables once. They are read-only test dependencies, not permission to read
or modify their installation files. The tests may make loopback requests; no external network.

```bash
export PUPPETEER_MODULE=[USER_HOME]/.hermes/cache/browser-verify/node_modules/puppeteer
export BROWSER_EXECUTABLE="/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"
env -u PYTHONPATH /usr/bin/python3 -B -m unittest tests.test_w35_r2_S tests.test_w35_P
env -u PYTHONPATH /usr/bin/python3 -B -m unittest discover -s tests -t .
git diff --exit-code -- tests/
git status --short
```

The planner measured all of the following on one shared test baseline with the final browser
scripts and both browser variables set. Counts include failing subtests, not just failing methods.

- Before either fix: **1593 tests, 190 assertion failures, zero errors**. Attribution: 176 K, 5
  path-bound checks, 5 S, 4 existing P status-frame pins.
- With this lane done and the sibling application unchanged: **1593 tests, 181 failures, all in `tests.test_w35_r2_K` (176) and `tests.test_w35_r2_paths` (5), zero errors**.
- With BOTH reference implementations: **1593 tests, OK, no skips**.
- Focused tests for your lane must be green, including the browser wrappers. If a browser test
  is skipped, the verification is incomplete. Do not edit a test to repair a failure.

Before committing, `git status --short` may list only the allowed application files, and the test
working tree must be unchanged. Commit only `ui/switch-bar.css ui/party/status.html`, explicitly listing the files you changed
in `git add`. Report the commit hash, full-suite result, focused result and any deviations.

## Stop and ask instead of guessing

- a test seems to contradict this brief;
- a fix seems to need a file outside the allowed list (`ui/party/status.js` and `tools/*` are
  outside it, and not needed);
- the full suite has any failure beyond the declared sibling RED, or any error;
- the browser script `tests/browser/w35_r2_S.cjs` fails with a violation after the edits above are
  exactly in place (report the first violations it prints).
