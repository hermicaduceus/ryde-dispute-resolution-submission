# Build session six, fix round two — brief

**Status at handoff: 2026-09-23.** Suite 312 tests. **Every failure is in
`tests/test_session_six_fixes_2.py`** (the acceptance target, written RED-first). Done = the
whole suite green, and each fix proven by reverting it and watching its test go RED.

A second cross-family review (glm-5.3) of fix round one found these. Every item was
reproduced firsthand. None is MAJOR; all are small. Read `docs/build-briefs/session-six-fix-brief.md`
for the rules round one established; they still apply.

## The five items

### S1 — party_view: only a decision's message may vary

`app/server.py::party_view` fails closed only for `decided` and `needs_info`. A stale or
planted `human_review` case file relays its own message, e.g. "The AI agent judge will follow
up". **Fix:** every non-decision status shows its **canonical constant**, never the file's
text: `passed_to_support` → `HUMAN_REVIEW_MESSAGE`, `needs_info` → `NEEDS_INFO_MESSAGE`,
`under_review` → `UNDER_REVIEW_MESSAGE` (already). Only `decided` carries the file's message,
and it keeps the banned-word check. Questions keep their check.

### S2 — the banned-word filter misses word forms and ID variants

`is_party_safe` passes "models", "judges", "withhold", "judgement", "confident", "advocacy",
lowercase `rd-1`, `Esc-4` and 4-digit IDs. **Fix:** broaden `PARTY_UNSAFE_PATTERN` to stems
(`ai`, `agents?`, `advocat\w*`, `judg\w*`, `confiden\w*`, `withh[eo]ld\w*`, `escalat\w*`,
`models?`) and make the rule-ID pattern case-insensitive with up to 4 digits. Checked before
writing this: no non-ESC rule title, no intake template question and none of the three
canonical messages trips the broader pattern. The test pins that.

### S3 — near-duplicate questions

The gate emits a template for a blank field even when a safe model question already asks about
it, and exact-string dedup lets "Where were you?" and "where were you" both through. **Fix,
two parts:**
1. Templates are a **fallback**: collect the safe model questions first. Only if none survive,
   emit template questions for blank fields (at most 3, one per field).
2. Dedup on a **normalised** form: lowercase, drop punctuation, collapse whitespace. Keep the
   first original wording.

### S4 — a failed bookkeeping write bricks the run

In `_answer_run`, `claim_path.write_text(...)` (the `answered.json` record) sits outside the
failure handler. If it fails after the round-two run succeeded, the handler returns 500 and
the claim stays, so every retry gets 409. **But releasing the claim is wrong too**: the round-two
run already exists, so a retry would rule twice (the R4 defect by another route).

**Fix:** move the write into a module-level function `_write_answered_record(claim_path,
new_run_id, cleaned)` (the test patches this name). Call it in a `try`; on `OSError`, log to
stderr and **still return the 200 party view**. The claim file already exists (empty), so the
run stays answered.

### S5 — escalation rules must never appear in a Basis line

`ESC-4`'s title "Amount above the autonomous cap" passes the word filter, so a real Judge citing
it would show the cap mechanism to a party. **Fix:** in `_cited_rule_titles`, skip every rule
whose ID starts with `ESC-`, **by prefix**, before any word check. A ruling citing only ESC rules
gets no Basis line.

## Boundaries

Same as round one: no changes to `data/`, `docs/policy.md`, `tools/`, gates, threshold or cap,
and no test edits unless a test has a genuine bug (say so). The 35 corpus runs keep outcome,
action and amount; `party_message` wording may change only where S5 applies (the mock cites
GEN-1/GEN-2, so it should not change at all).

## Order

S1, S5, S2, S3, S4. Commit per item or pair with the suite count. Then revert proofs for S1,
S2, S3, S4 and S5: revert, show RED, restore. Finish with a summary of what changed and what
each revert showed.
