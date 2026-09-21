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