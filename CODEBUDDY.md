# PROJECT: <name pending the scope ruling>

This file is CodeBuddy's memory for this project. It is the builder's entry point: a session that
reads only this should know what the project is, what it is not, and how work is done here.

**Status: scaffold only.** No scope has been agreed yet. Do not start building anything until the
planning map is closed and this file carries a ruled scope. The planning decisions live in a separate
repository; this folder deliberately cannot read it, by design — the permission fence in
`.codebuddy/settings.json` denies reads of that path, and it is verified to work.

## What this project is

Ryde track entry for the Tencent Cloud "AI CAN DO IT" Hackathon Singapore 2026. The challenge is a
**multi-agent autonomous dispute resolution system** for ride-hailing disputes: a Rider Advocate
agent, a Driver Advocate agent, and a Judge agent that weighs both cases, applies company policy and
issues a ruling with a confidence score.

`docs/statement-extract.md` holds the challenge statement verbatim. Read it before any build work.
It is the only source of requirements that counts.

## Hard requirements (non-negotiable)

- The project must be **original** and built on **at least one of CodeBuddy or WorkBuddy**.
- **Proof of product usage is mandatory.** Without it the project is **not scored at all**. Evidence
  is screenshots of CodeBuddy/WorkBuddy chat logs, minimum three, accumulated as work happens. It
  cannot be reconstructed later, so capture as you go.
- The project must be **demoable end to end for at least two dispute categories**.
- **Inter-agent communication must be observable** to a judge: a visible log or UI showing how the
  agents exchange information and build their cases.
- Deliverables include a public GitHub repo with complete source, an architecture diagram, and a live
  demo walkthrough.
- The repository is **PUBLIC**. Never commit credentials, API keys, tokens or personal data.

## Non-negotiable engineering rules

- Never commit `.env`, API keys, tokens, or any credential. The repo is public.
- Do not read or write anything outside this folder. The permission fence in
  `.codebuddy/settings.json` enforces this; treat it as a design constraint, not an obstacle.
- Verify work by running it, not by describing it. A feature is done when it has been exercised and
  the real output checked.
- Keep the demo path working at all times. A half-built stretch goal that breaks the main flow is
  worse than no stretch goal.

## How work is done here

- **One capability at a time**, verified before moving on.
- Commit with a clear message after each verified step.
- Log decisions as they are made. A future session starts from these files, not from memory.
- **Run from this folder.** `cd ~/hermes-workspace/projects/ryde-build && codebuddy`. Sessions are
  scoped by launch directory, and this folder carries its own memory file and permission fence.
- **Default model is `deepseek-v4.1-flash`** (global default, x0.00 cost multiplier). Override per
  task with `--model <id>` only when the work warrants the expense: GPT-5.6-Luna x0.14 is the cheap
  upgrade, Kimi-K3 x1.62 for hard reasoning. Never use Primary, Deep, Sol or GPT-6-Astra here.
- **Headless capture:** `codebuddy -p "<prompt>" --output-format json` returns machine-readable
  results and writes a transcript to `~/.codebuddy/projects/`. Useful when the build needs to be
  driven from outside the interactive session.

## Layout

```
ryde-build/
├── CODEBUDDY.md            # this file — project memory
├── .codebuddy/
│   ├── settings.json       # permission fence
│   └── rules/              # topic-scoped rules (added as the build needs them)
├── docs/
│   ├── statement-extract.md
│   └── architecture.md     # required deliverable
└── (application source — structure to be decided with the build stack)
```
