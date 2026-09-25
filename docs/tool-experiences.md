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
- The a second-model cross-family review (pinned per round, unset after; served id another coding agent-a second-model
  — `a second-model` 404s in the delegation layer) found the acceptance tests were false-green:
  8 of 13 injected mutations passed, because whole-file greps are satisfied by decoy rules
  and comments. Reproduced firsthand (4 of 13 spot-checked), then rewritten rule-pinned:
  every assertion now targets a named selector's declaration block, and a 12-mutation
  battery goes all-red. The review's contrast math was recomputed independently and
  confirmed: --muted failed AA on the pastel canvas (3.70) and was darkened to #5A6470
  (4.70). One driver bug found by the human: a PTY prompt write needs its own \r — a prompt
  typed without the carriage return sits unsubmitted.
