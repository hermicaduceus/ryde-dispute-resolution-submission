# PROJECT: Ryde — Multi-Agent Autonomous Dispute Resolution

**Status: BUILT, IN POLISH (updated 2026-10-07).** The system runs end to end on the mock and on
the real Tencent model; the application build freezes on **12 Oct 2026** (operator ruling), after
which only recording, documentation and deploy work continue. Building started 2026-09-21. Planning closed **2026-09-19** and the scope, stack and
workflow are ruled. This file is CodeBuddy's memory for this project: the builder's entry
point. The ruled scope lives in
the planning repository and is deliberately unreadable from here (the permission fence in
`.codebuddy/settings.json` denies reads of that path, and it is verified to work), so
**everything you need is in this file, `docs/` and the kickoff prompt the operator gives you**.
If a session needs a fact that is neither here nor in the docs: stop and ask; do not invent
scope.

## What this project is

Ryde track entry for the Tencent Cloud "AI CAN DO IT" Hackathon Singapore 2026. The challenge is a
**multi-agent autonomous dispute resolution system** for ride-hailing disputes: a Rider Advocate
agent, a Driver Advocate agent, and a Judge agent that weighs both cases, applies company policy and
issues a ruling with a confidence score.

`docs/statement-extract.md` holds the challenge statement verbatim. Read it before any build work.
It is the requirements floor: the locked scope below is the team's chosen subset of it, and the
locked scope never widens past the statement.

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

## Locked build scope

These decisions are ruled by the team and are **not open to re-litigation**:

- **Categories:** route deviation + no-show charge, end to end. No third category.
- **Agents:** exactly three decide each dispute — Rider Advocate, Driver Advocate, Judge. The
  Judge always emits a confidence score (0–1). Below a configurable threshold it does not rule;
  the parties see only a neutral "your case is still under review" message. Escalation is MVP, not stretch.
  *(Amended 2026-10-01.)* A fourth role, the **Policy & Precedent agent**, is a stretch item
  built only if time allows: it reads human decisions and **proposes** policy changes, a human
  approves or rejects each proposal, and it **never rules on a live case** and never edits the
  policy or the code gates itself.
- **Parties are spectators:** disputes arrive through a standardized intake form (category
  dropdown; "other" routes to a human-review queue with a neutral message). The advocates screen
  the submitted answers and may ask the party targeted follow-ups only when data conflicts or
  is insufficient. No fourth intake agent. Parties never chat with the agents.
- **Deterministic evidence layer:** all quantitative evidence (route deviation km/%, duration vs
  estimate, fare recomputation, cancellation timestamps, chat-log signals, behaviour profile)
  is computed in Python into a typed **Evidence Pack**. Agents may cite pack fields; they must
  never do the arithmetic themselves.
- **Policy as a swappable document:** `docs/policy.md`, rules with IDs and provenance stated
  in the file. The Judge and advocates cite rule IDs. Policy text can be loaded from another
  path, but it and the separately implemented Python safeguards must remain aligned; a text
  replacement does not change the gates or their configured thresholds.
- **Dataset as a swappable document:** synthesised corpus in `data/`, labelled with
  ground-truth rulings (the correct ruling per case, by design) so replayed-run consistency is
  measurable. Same swap rule.
- **Observability surface (required by the statement):** a case-file view — each side's claim,
  evidence and policy citations, with agent-to-agent traffic as a compact timestamped event
  strip (full text one click deeper). This screen is the demo's home.
- **Stack:** Python backend + plain HTML/JS front end. No heavy framework. The backend calls
  Tencent Cloud's LLM API directly (key in `.env`, never committed). CodeBuddy writes the code;
  it is never the runtime.
- **Repo layout:** `app/` (Python backend), `ui/` (front end), `docs/` (architecture diagram,
  policy set, dataset description), `evidence/` (development-process screenshots), `tools/` +
  `tests/` (marked **non-app**: helper scripts and tests only; `app/` and `ui/` never import
  from them). **The repo is PUBLIC at submission — never commit credentials or personal data.**
- **Deployment:** local run for the live demo (real backend, real LLM calls). *(Amended
  2026-10-01.)* The public link is a static replay on EdgeOne Pages of the **full loop** (filing →
  the Judge withholds → a human decides → the party's status page), labelled honestly as a
  replay of a real run with its date; it ships first. Optional polish on top: a hosted live
  system behind one shared judge password (every page and API), a daily case cap and a daily
  health check, with keys rotated before it goes up.

## Non-negotiable engineering rules

- Never commit `.env`, API keys, tokens, or any credential. The repo is public.
- Do not read or write anything outside this folder — **this is a rule you must honour, not
  something the fence guarantees.** The permission fence in `.codebuddy/settings.json` denies
  reads of the planning repository path and of secret files (`.env`, `*.pem`, `*.key`,
  `secrets/`), denies `curl`, `wget`, `rm -rf` and `git push`, and asks before `git remote`.
  It does NOT block other writes or other reads. Staying inside this folder is your job.
- Verify work by running it, not by describing it. A feature is done when it has been exercised and
  the real output checked.
- Keep the demo path working at all times. A half-built stretch goal that breaks the main flow is
  worse than no stretch goal.
- **Only the CodeBuddy build lane writes `app/` and `ui/`.** Any other AI assistant used for
  rescue or unblocking (e.g. another coding agent) is confined to `tools/` and `tests/` and must never
  touch application code — the project's "built on CodeBuddy" claim must stay honest.
  *(Amended 2026-10-01.)* A defect that lives only in `app/` or `ui/` follows the normal path:
  the planning agent writes a failing test and a brief, the CodeBuddy build lane fixes it (on
  the default flash model), the planning agent verifies. **One exception:** within 48 hours of
  the submission deadline, if the build lane cannot land a fix in time, the rescue lane may fix
  it, and every such change is logged with its reason in the commit message and in
  `docs/tool-experiences.md`.

## How work is done here

- **One capability at a time**, verified before moving on.
- Commit with a clear message after each verified step.
- Log decisions as they are made. A future session starts from these files, not from memory.
- **Effort follows the Demo Day rubric:** 40 of 100 points are story, design and presentation,
  so `README.md`, `docs/architecture.md` and the demo walkthrough are deliverables on the same
  footing as code — polished after the MVP floor is standing, never skipped.
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
├── CODEBUDDY.md            # this file — project memory + locked scope
├── README.md               # judge's entry point (judge-first: what it is → see it run → diagram)
├── .codebuddy/
│   └── settings.json       # permission fence
├── app/                    # Python backend — agents, evidence layer, LLM calls, server, eval
├── ui/                     # plain HTML/JS front end — operator console (case-file view)
│   └── party/              # rider and driver intake forms, driver account, status page
├── data/packs/             # two swappable dataset packs, ground-truth labelled:
│                           #   organiser-style-v1 (default) and ryde-synth-v1
├── docs/
│   ├── statement-extract.md  # challenge statement, verbatim — the only requirements source
│   ├── policy.md             # policy rule set (swappable; provenance stated in-file)
│   ├── dataset.md            # dataset description + provenance
│   ├── architecture.md       # required deliverable: diagram + system description
│   ├── prompts.md            # how the prompts drive each agent
│   ├── replay.md             # static replay export for the public link
│   ├── evidence-plan.md      # §8 evidence rules and naming
│   ├── tool-experiences.md   # running log of how the tools behaved
│   └── build-briefs/         # one brief per build session, kept as a process record
├── evidence/               # §8 screenshots (YYYY-MM-DD_<tool>_<topic>.png|.jpg)
├── tools/                  # NON-APP helper scripts — app/ never imports from here
│   └── replay/             # static replay page and its shim
└── tests/                  # NON-APP tests (stdlib only)
```

New session briefs go in `docs/build-briefs/`. Do not create a document as a side effect of
other work; each one is authored in the session whose brief names it.
