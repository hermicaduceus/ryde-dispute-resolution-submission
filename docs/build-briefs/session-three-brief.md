# Build session three — brief

> **SUPERSEDED 2026-09-22 (late). This brief is CLOSED — all five items were fixed, reviewed
> and verified.** Build head `62df2c3`, suite 189 tests. Round one shipped `a963410`→`239fb0e`;
> two review rounds then found five more defects (including a MAJOR: the F4 guard below was
> shape-incomplete and still admitted `[]`, `{}` and `[1,2]`), closed by `5e593c8`→`3c05863`.
> Kept as the record of what was asked for and why. **Do not work from it.**

**Status at handoff: 2026-09-22, after session two.** Head `bc3d751`. Suite 178 tests, green.
`ui/` now holds `index.html`, `app.js`, `styles.css`.

Pre-flight:

```bash
cd ~/hermes-workspace/projects/ryde-build
codebuddy --version          # the CLI self-updates; a bad update bricked it once
git status --short           # expect empty
python3 -m unittest discover -s tests -t .    # expect 178 tests, OK
```

---

## What session two delivered, verified by execution

Five commits (`537f899` → `ed061e1`) built the case-file view. Verified in a real browser by
the planner lane, not by reading the model's summary:

- All three outcomes render distinctly from real `case_file.json` files.
- **No hardcoded case content.** `RD-0101`, `RD-0109`, `OS-0301`, `NS-0201`, `8.0347`, `25.54`,
  `55.16`, `5.81` all absent from `ui/`.
- **The central safety property holds.** On RD-0109 the party-facing region contains only the
  neutral message. The Judge's confidence `0.86` appears nowhere outside the human-only region.
  `renderWithheldResolution` never passes the resolution object to the party renderer.
- XSS-safe by construction: zero `innerHTML`, all text through `textContent`.
- Path traversal blocked in `normalizedPayloadRef` (rejects absolute, drive-letter, `..`, empty).
- 178 tests still pass; `tools/` and `tests/` untouched.

A glm-5.3 adversarial review then attacked it. Its headline verdict ("central safety claim
false") was **not accepted**: it grepped for the string `55.16` and did not distinguish the
*claimed* amount, which the rider wrote on the intake form and which is public by definition,
from the *withheld ruling* amount. Those two are numerically identical in this fixture by
coincidence. The Judge's confidence, which exists only in the ruling, does not leak.

But the review found three real defects the author missed. All three were reproduced firsthand
in a browser before being written down here.

---

## The work, in priority order

### 1. F3 — `human_review` renders `resolution.notes` into the party-facing card (CRITICAL)

`ui/app.js:599`. `renderHumanReviewResolution` calls `appendResolutionNotes(body,
resolution.notes)`, and that card is marked `data-audience="parties"` at `app.js:589`.

The same `notes` field is treated as human-only in the withheld path (`app.js:581`). One field,
two different audience rulings, in one file. That inconsistency is the defect.

It is not live today only because `human_review` cases skip the Judge, so their notes carry no
ruling figures. But the producer does put ruling figures in notes: the shipped RD-0109 note
reads `"the ruling was not delivered: SGD 55.16 exceeds the autonomous decision cap of SGD
50.00"`. A future producer change, or a mislabelled outcome, leaks it straight to the parties.

**Reproduced:** take `runs/…-OS-0301/case_file.json`, set
`resolution.notes = ["INTERNAL: candidate refund SGD 55.16 at confidence 0.86"]`, load it.
The string renders under NOTES inside the parties-marked card. Observed
`PARTY_HAS_5516: true, PARTY_HAS_086: true`.

**Fix direction:** `notes` is operator commentary in every outcome. Render it outside the
party-facing card, consistently with the withheld path. Pin with a test that fails when the
notes go back into the party region.

### 2. F4 — `ruled` with a null `ruling` claims a delivery that never happened (MAJOR)

`ui/app.js:545` writes the header "RULING ISSUED / The Judge delivered this decision to the
parties" before `appendRulingDetails` early-returns on a null ruling (`app.js:519-521`).

**Reproduced:** `runs/…-RD-0101/case_file.json` with `resolution.ruling = null` renders the
delivery claim over an empty metrics grid, above the "still under review" party message. The
card contradicts itself.

This matters more than its severity label suggests. An observability tool that asserts a
delivery which did not occur is the exact failure this project exists to prevent. Branch on the
data, not on the outcome label alone: if `outcome` is `ruled` and `ruling` is null, that is a
malformed case file and the view should say so plainly.

### 3. F5 — one `null` element in `events` makes the whole case file unviewable (MAJOR)

`ui/app.js:672` reads `event.seq` on null and throws. `handleFile` catches it (`app.js:732`),
hides the entire workspace, and shows the raw JS message "Cannot read properties of null
(reading 'seq')".

**Reproduced.** One bad event should degrade that row, not the document.

### 4. `policy.source_path` renders an absolute home-directory path (MINOR, but it is a producer fix)

The Case metadata block shows
`[USER_HOME]/hermes-workspace/projects/ryde-build/docs/policy.md`.

`runs/` is gitignored so this never reaches the public repo, but it lands in every demo
screenshot and in the video. **The fix belongs in the pipeline, not the view** — emit a path
relative to the repo root. Check where `policy.source_path` is set before changing the view.

### 5. Event 9's summary restates the withheld amount (JUDGEMENT CALL, not a defect)

`runs/…-RD-0109` event 9 reads "Judge withheld the ruling: SGD 55.16 exceeds the autonomous
decision cap of SGD 50.00".

This page is the operator console; parties never see it, so this is not a leak. But the event
strip carries no audience marking at all, and a reviewer reading the page cold called it one.
Softening the summary to name the rule without restating the figure costs nothing and removes
the argument. Producer-side change, in the events layer.

---

## What is NOT in this session

**The Tencent endpoint (W3) is stalled, not skipped.** There is no API key yet. See the
acquisition note below — it is a the operator task, not a build task, and the build cannot proceed past
it.

**The party-facing surface does not exist and is not in scope here.** `ui/` is the internal ops
console. The locked scope (`CODEBUDDY.md:44-47`) has parties as spectators behind a
standardized intake form, with a follow-up question path and an outcome message. None of that
is built; disputes are read from `data/disputes/*.json` and nobody has ever typed into a form.
That is a separate session, to be scoped after the defects are closed.

---

## Working rules (unchanged)

- One capability at a time, verified in a browser before moving on.
- **Verify by running it, not by describing it.**
- `ui/` and `app/` are yours. `tools/` and `tests/` are not; do not modify tests to make
  something pass.
- **A fix is not done until a test fails when the fix is reverted.** Session one shipped a
  judge-citation repair against a fully green 178-test suite because nothing exercised the bad
  path. Each fix above needs a test that fails on reintroduction.
- Commit after each verified step with a message explaining why, not just what.
- The repo is PUBLIC. Never commit credentials.
