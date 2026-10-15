# W59: CodeBuddy re-applies three planning-agent app edits

The operator ruled on 15 October that application code should be applied in CodeBuddy wherever
possible. Three application edits were made outside the build lane by the planning agent, under
operator-approved deadline exceptions:

| Original commit | Date | File | Change |
|---|---|---|---|
| `5a0c4ad` | 13 Oct | `ui/party/party.js` | W46: the rider no-show absence question sits directly after the question list, above the amount |
| `87f1c3e` | 15 Oct | `ui/party/status.js` | Replay step 1: a `?dispute=<id>` link shows only that dispute's card, falling open to the full list |
| `c40114e` | 15 Oct | `ui/party/party.js` | `showError()` scrolls the revealed message into view |

The preparation commit that added this brief also removed exactly those three edits, so the tree
you start from is the published tree minus them. Your job is to re-apply them in this session.
History is not rewritten: the original commits stay visible and the log entry below says so.

**The existing tests pin these files by digest, so the restored bytes must be identical to the
originals.** That is why this brief gives the exact text. Apply it exactly: same indentation (two
spaces per level), same comments, same quotes. Do not reformat, rename or improve anything.

## Only these paths may change

- `ui/party/party.js` (changes 1 and 3)
- `ui/party/status.js` (change 2)
- `CLAUDE.md` (delete it, change 4)
- `docs/tool-experiences.md` (changes 5 and 6)

Do not edit `tests/`, `app/`, `data/`, `docs/policy.md`, `evidence/`, `deploy/`, `tools/`,
`CODEBUDDY.md`, `README.md`, settings files or any other doc or brief.

## Change 1: `ui/party/party.js`, function that places the absence question

Find this line (it is the last statement of the block that builds the absence field):

```js
    absenceHost.appendChild(absenceField);
```

Replace that single line with exactly these seven lines:

```js
    // Sits directly after the question list, above the amount field: it is a question
    // about the incident, and the amount is the closing request before Send.
    if (absenceHost === host && typeof host.insertBefore === "function") {
      host.insertBefore(absenceField, questionList.nextSibling);
    } else {
      absenceHost.appendChild(absenceField);
    }
```

## Change 2: `ui/party/status.js`

Directly before the line `  function loadAccount() {`, insert exactly these seven lines (the
seventh is an empty line, so a blank line separates the new function from `loadAccount`):

```js
  // One dispute to focus on, when a link asks for it by reference (the replay's landing
  // step 1 opens the no-show case by id). Null when absent or not a plain string.
  function focusedDispute() {
    var focused = new URLSearchParams(window.location.search).get("dispute");
    return typeof focused === "string" && focused ? focused : null;
  }

```

Then inside `loadAccount`, directly after the line

```js
      var disputes = Array.isArray(payload.disputes) ? payload.disputes : [];
```

insert exactly these nine lines:

```js
      var focused = focusedDispute();
      if (focused) {
        var matched = disputes.filter(function (entry) {
          return typeof entry === "object" && entry !== null && entry.dispute_id === focused;
        });
        if (matched.length > 0) {
          disputes = matched;
        }
      }
```

## Change 3: `ui/party/party.js`, `showError()`

Directly after the line `    node.hidden = false;` inside `showError`, insert exactly:

```js
    node.scrollIntoView({ block: "nearest" });
```

## Change 4: delete `CLAUDE.md`

Run `git rm CLAUDE.md`. CodeBuddy never read it; the same rule already lives in `CODEBUDDY.md`.
Do not move its text anywhere.

## Change 5: `docs/tool-experiences.md`, tidy one entry

These two lines currently read (wording damaged by an earlier mechanical name substitution):

```text
- The a second-model cross-family review (pinned per round, unset after; served id another coding agent-a second-model
  — `a second-model` 404s in the delegation layer) found the acceptance tests were false-green:
```

Replace them with exactly:

```text
- The second-model cross-family review (pinned per round and unset after; the delegation layer
  needs the full versioned model id, as the short alias returns 404) found the acceptance tests were false-green:
```

Leave the rest of that entry untouched.

## Change 6: `docs/tool-experiences.md`, append one dated entry

Append a new section at the END of the file, matching the file's style (a `## ` heading, then
short `- ` bullets wrapped near 95 columns, "the operator" and "the planning agent" for people).
Heading: `## 2026-10-15: CodeBuddy re-applies three planning-agent app edits`. It must state these
facts, and nothing it cannot know:

- The three original commits above (ids, dates, files, one-line purpose each), and that they were
  made by the planning agent outside the build lane under operator-approved deadline exceptions.
- At the operator's direction the planning agent removed them in the preparation commit, and this
  CodeBuddy session re-applied them from this brief's exact text. Existing digest pins require
  identical bytes. The earlier commits remain in history; nothing was rewritten.
- Separately, the planning agent corrected explanatory wording in `docs/policy.md` on 15 October
  after the publication review, with no rule, parameter or code change. The policy has been written
  by the planning lane since the start, by design, so it was not re-run here.
- `CLAUDE.md` was removed because CodeBuddy never used it; the same rule remains in `CODEBUDDY.md`.
- Name the model and effort this session ran on. Do not claim review, full-suite or release
  results; the parent verifies those afterwards.

## Verify (focused; the parent runs the full suite and the browser matrix)

Use the system interpreter by absolute path with `PYTHONPATH` removed. The browser variables are
already exported in your environment; do not change them. Run, as separate commands:

```sh
env -u PYTHONPATH /usr/bin/python3 -B -m unittest tests.test_step1_dispute_target
env -u PYTHONPATH /usr/bin/python3 -B -m unittest tests.test_w15_feedback tests.test_w24_fix_round tests.test_w34_launcher
env -u PYTHONPATH /usr/bin/python3 -B -m unittest tests.test_w30_trip_requests
env -u PYTHONPATH /usr/bin/python3 -B -m unittest tests.test_w46_absence_order tests.test_w58_error_on_screen
env -u PYTHONPATH /usr/bin/python3 -B -m unittest tests.test_adp_hardening tests.test_architecture_doc tests.test_w6_publication_corrections
```

Before your edits the first four commands report 17 failures in total and zero errors (3 in
`test_step1_dispute_target`, 1 each in `test_w15_feedback`, `test_w24_fix_round` and
`test_w34_launcher`, 4 in `test_w30_trip_requests`, 5 in `test_w46_absence_order`, 2 in
`test_w58_error_on_screen`). After your edits all five commands must report OK with zero
failures and zero errors. Also run
`git diff --stat` and confirm only the four allowed paths appear. Never run the whole suite in a
single foreground call.

## Commit and report

Stage explicitly by path: `git add ui/party/party.js ui/party/status.js docs/tool-experiences.md`
plus the `git rm CLAUDE.md` above. Never `git add -A`, merge, push, stash, reset or rebase. No
subagents and no network. Commit message:

```text
W59: re-apply three planning-agent app edits in CodeBuddy; remove CLAUDE.md
```

Report the commit id, the files it changed, and the exact test output lines.
