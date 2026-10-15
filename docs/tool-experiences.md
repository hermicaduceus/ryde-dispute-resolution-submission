# Tool experiences — running log

Honest notes on how the development tools behaved, good and bad. The submission's product
sharing item wants real development-process experience; this log is its raw material. One line
per session is enough; date each entry.

## 2026-09-21

- Session: build kickoff prep (planning repo, no CodeBuddy interaction yet). First real
  CodeBuddy interaction log entry lands with the first build session.
- Session 1 (CodeBuddy CLI v2.156.0, Deepseek-V4.1-Flash, 13m48s): built the vertical skeleton
  from a single self-contained kickoff prompt. Config layer, LLM adapter interface with mock
  and an unpinned Tencent stub, append-only event log, three agents, deterministic Evidence
  Pack, pipeline, CLI and 82 tests, committed in ten steps. It read the project docs before
  touching anything, and it did the right thing on the environment: it discovered the machine
  has only system Python 3.9.6 with no third-party packages, and wrote the whole thing against
  the standard library instead of assuming pytest and python-dotenv were available.
- **Every credit line for the session logged `credit=0`.** The x0.00 default model held for a
  387-record, 109-tool-call session, so a substantial build turn genuinely cost nothing.
- **It asks before editing.** The approval prompts ("No, and tell CodeBuddy what to do
  differently") are the moments where the product name is on screen, which turns out to matter
  for evidence: a mid-session frame of code scrolling past looks like any other terminal agent.
  The session banner is the better anchor frame.
- It writes its own project memory to `~/.codebuddy/projects/<dir>/memory/MEMORY.md`, separate
  from the repo's `CODEBUDDY.md`. Worth knowing: that file is outside the repo, so it is not
  part of the submission and is not covered by the read fence.
- Verification (planner lane, same day): 82/82 tests pass on stock python3.9 with no installs,
  all three fixtures run end to end, and the Evidence Pack's route arithmetic was recomputed
  independently and matched to the last decimal (8.0347 km, 25.54% deviation, SGD 4.87 delta).
  The skeleton is real, not a plausible-looking shell.

## 2026-09-24

- Session seven (CodeBuddy CLI v2.157.0, GLM-5.3-Flash at max effort, 18m16s, 6.21 credits): wrote
  `docs/architecture.md` against 14 acceptance tests written before the document existed. It read 44
  files before writing and listed, per section, which files each claim came from. It also reported two
  code oddities it noticed but did not fix, because the session rules forbade code edits, which is
  the behaviour we asked for.
- The tests could only check form, so a second model family reviewed the text against the code. It
  found real errors (the README named two of the Judge's three checks; one safety sentence was true
  for the decision message but false for follow-up questions). The fix round ran in the same session
  after an in-session switch to Deepseek-V4.1-Flash: 3m37s, 0 credits (the transcript names
  deepseek on every record of that round and bills none of them).
- Miora's first attempt at the polished diagram kept every label but scrambled the arrows (the
  "Out of scope" branch pointed into processing). A generic image model did better but still
  misrouted the top of the chart. Exact wiring is hard for image models; the Mermaid render stays the
  reference until an image matches it arrow for arrow.

## 2026-09-25

- Session eight (CodeBuddy CLI v2.158.0, auto-updated overnight, GPT-5.6-Luna at max effort,
  22m20s then 11m38s, 27.49 credits for both rounds): replaced model-written follow-up questions
  with question ids that code turns into fixed sentences. It entered plan mode unprompted, sent an
  explore agent and a plan agent, and showed a plan for approval before editing, as luna did in
  session two. It changed only the files the brief allowed and committed in four logical steps.
- The tests were written first, so "done" was decided by the tests, not by the model. A second
  model family then reviewed the work and found one real bug the tests had missed (the same
  terminal label error on a third outcome). New tests were written for it and CodeBuddy fixed it
  in the same session in 11 minutes.
- Even three small fixes got a full explore-and-plan cycle at max effort. That is thorough but
  slow for 20 lines of code; a cheaper setting would suit small follow-up rounds.
- Session nine (CodeBuddy CLI v2.158.0, GPT-5.6-Luna at max effort, 5m50s build + 12s
  acknowledge, 8.54 credits): the W10 token pass — restyled ui/party/ to Ryde's real brand
  system (pink #E93864, ink #31373E, pastel canvas #F7DDE3, Poppins, pill buttons) against
  9 RED-first tests. It edited exactly two files, kept party.js byte-identical, and stopped
  to report rather than guess when the brief's own acceptance command was wrong (the brief
  said `discover tests`; the repo documents `-s tests -t .` — the brief's error, correctly
  refused by the builder).
- The second-model cross-family review (pinned per round and unset after; the delegation layer
  needs the full versioned model id, as the short alias returns 404) found the acceptance tests were false-green:
  8 of 13 injected mutations passed, because whole-file greps are satisfied by decoy rules
  and comments. Reproduced firsthand (4 of 13 spot-checked), then rewritten rule-pinned:
  every assertion now targets a named selector's declaration block, and a 12-mutation
  battery goes all-red. The review's contrast math was recomputed independently and
  confirmed: --muted failed AA on the pastel canvas (3.70) and was darkened to #5A6470
  (4.70). One driver bug found by the human: a PTY prompt write needs its own \r — a prompt
  typed without the carriage return sits unsubmitted.

## 2026-10-05 to 2026-10-06

- W15 UI review follow-ups used CodeBuddy CLI v2.161.3 on Deepseek-V4.1-Flash at
  max effort. The scoped CSS fixes separated the driver's amount helper, aligned
  console card gaps and made driver-header links quiet outlined pills.
- Independent review caught a sticky action bar covering filing options. A rendered
  check found the same defect at desktop sizes, so a mobile-only exception would
  have missed it. the operator approved normal-flow action bars at every width. RED tests
  preceded CodeBuddy's two-declaration repair; the bar's visual styling stayed intact.
- Verification finished with 1104 tests OK, 41 unique regression mutations failing
  assertions with no errors or survivors, and 36 filing-stage checks across 12 real
  browser views. Final GLM-5.3 review endorsed the repair and closed the overlap finding.
- the operator supplied genuine CLI screenshots at close-out. Evidence frames 45 and 46 show
  the product/model banner and the repair completion report respectively. The second
  frame's test table is builder output; the independent verification is separate.

## 2026-10-06: compact rider and driver filing flow

- the operator authorized a headless CodeBuddy build on Deepseek-V4.1-Flash at max effort.
  The changes keep the filing header visible, scroll options and fields internally,
  reserve space for Back/Continue and move sample-data notices to bottom fine print.
- Independent GLM-5.3 review found a stale trip-request race. RED-first tests preceded
  CodeBuddy's request-ownership repair, error-card landing and retry error reset.
  The final scoped re-review endorsed those repairs. Its verdict does not cover the
  later shared-frame layout.
- the operator's final visual passes removed the trip-list shade and added the existing 2px
  hover lift and soft shadow to Yes/No buttons, with reduced-motion support.
  GLM-5.3 endorsed the shade removal. the operator waived another GLM round for the
  viewport-bottom fix and the final Yes/No motion change, then approved the UI.
- Parent verification reached 1164 passing tests and exercised both filing roles in
  real-browser layout, resize, keyboard, request-race and hover checks. Regression
  mutations and source reverts failed assertions. Physical-phone toolbar behaviour
  remains unverified. Genuine CLI transcripts are retained; no new chat screenshot
  was captured for this authorized headless work.

## 2026-10-15: CodeBuddy re-applies three planning-agent app edits

- Three application edits had been made outside the build lane by the planning agent, under
  operator-approved deadline exceptions: `5a0c4ad` (13 Oct, `ui/party/party.js`: the rider
  no-show absence question sits directly after the question list, above the amount), `87f1c3e`
  (15 Oct, `ui/party/status.js`: replay step 1 — a `?dispute=<id>` link shows only that
  dispute's card, falling open to the full list) and `c40114e` (15 Oct, `ui/party/party.js`:
  `showError()` scrolls the revealed message into view).
- At the operator's direction the planning agent removed them in the preparation commit
  `9ca8aec`, and this CodeBuddy session re-applied them from this brief's exact text. Existing
  digest pins require identical bytes. The earlier commits remain in history; nothing was
  rewritten.
- Separately, the planning agent corrected explanatory wording in `docs/policy.md` on
  15 October after the publication review, with no rule, parameter or code change. The policy
  has been written by the planning lane since the start, by design, so it was not re-run here.
- `CLAUDE.md` was removed because CodeBuddy never used it; the same rule remains in
  `CODEBUDDY.md`.
- Session: CodeBuddy CLI v2.164.0 (headless), Deepseek-V4.1-Flash at max effort.
