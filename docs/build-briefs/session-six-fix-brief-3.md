# Build session six, fix round three (final) — brief

**Status at handoff: 2026-09-23.** Suite 325 tests. **Every failure is in
`tests/test_session_six_fixes_3.py`** (the acceptance target, written RED-first). Done = the
whole suite green, and each fix proven by reverting it and watching its test go RED.

A third cross-family review (glm-5.3) of round two found these. Every item was reproduced
firsthand. **This is the last round on the party-safety filter** (the operator ruling). The filter is a
backstop; the real protection is structural and already verified by three reviews. Round-one
and round-two rules in `docs/build-briefs/session-six-fix-brief.md` and `docs/build-briefs/session-six-fix-brief-2.md`
still apply.

## The four items

### T1 — rule IDs: match only the policy's real prefixes (a regression from round two)

Round two made `PARTY_UNSAFE_RULE_ID_PATTERN` (`app/schemas.py`) case-insensitive with 2-5
letters and up to 4 digits. It now blocks public text: the pack's own trip id
`TRIP-2026-09945`, "Sept-3", "covid-19". Consequence: a model question quoting the trip id is
silently swapped for a template, and a decided message quoting it fails closed to "under
review" while the party holds a real ruling.

**Fix:** match only the prefixes the policy actually uses, case-insensitive, up to 4 digits:
`\b(?:GEN|EV|RD|NS|ESC)-\d{1,4}\b`. The test derives every real rule id from
`docs/policy.md` and checks it in upper, lower and title case, so if a new prefix is ever
added to the policy the test goes red until the pattern learns it. Keep the prefix list in
one named constant with a comment saying so.

### T2 — four missed word forms

`is_party_safe` passes "agentic", "modelling"/"modelled", "A.I." / "A. I.", and the single-h
misspellings "withold"/"witheld". **Fix** in `PARTY_UNSAFE_PATTERN`:
- `agents?` → `agent\w*` (catches "agentic"; must NOT become `agen\w*`, which would block
  "agency").
- `models?` → `model\w*` (catches "modelling", "modelled"; "remodelled" and "modal" still pass
  because of the word boundary).
- `withh[eo]ld\w*` → `withh?[eo]ld\w*`.
- A.I.: add `a\.\s?i\.` as its own alternative. Careful with the trailing `\b`: after a
  literal `.` a word boundary does not behave the way it does after a letter. Put it outside
  the `\b(...)\b` group, e.g. `\ba\.\s?i\.`. It must not match "plan A. I walked" (only one
  dot after the I, none).

The look-alike list in the test must keep passing, and every non-ESC rule title must stay
party-safe.

### T3 — S4 catches only `OSError`

In `app/server.py::_answer_run`, the bookkeeping write's handler is `except OSError`. Any
other exception (e.g. `ValueError`) still returns 500 with the claim held, so the run is
bricked. **Fix:** `except Exception`, same body (log to stderr, still send the 200 view). The
round-two run already succeeded, so the answer happened.

### T4 — a blank message only matters for a decision

`party_view` rejects a blank or missing `party_message` *before* looking at the status. Since
S1, a non-decision status never shows the file's text, so that check now throws away a
needs-info file's safe questions for no reason. **Fix:** require a non-blank string message
only when the status is `decided`. Keep everything else: a leaky question still fails the
view closed, and a decision with a blank message still fails closed.

## Known limits, deliberately not fixed (write nothing for these)

- The dedup key does not fold accents ("Café?" and "cafe?" count as two).
- The template fallback only treats a *string* intake value as blank; a hand-crafted pack
  record with `None` or a number there skips the question. The filing form can only produce
  strings.
- The word filter will never be complete. It is the second line, not the first.

## Boundaries

Same as before: no changes to `data/`, `docs/policy.md`, `tools/`, gates, threshold or cap;
no test edits unless a test has a genuine bug (say so). The 35 corpus runs keep outcome,
action, amount and party message.

## Order

T1, T2, T3, T4. Commit per item or pair with the suite count. Then revert proofs for all
four: revert, show RED, restore. Finish with a summary of what changed and what each revert
showed.
