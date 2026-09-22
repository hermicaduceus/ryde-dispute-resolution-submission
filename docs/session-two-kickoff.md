# Build session two — kickoff prompt

**Paste the block below into CodeBuddy CLI as the first message of a fresh session.**

Before you paste, run these three:

```bash
cd ~/hermes-workspace/projects/ryde-build
codebuddy --version          # expect 2.156.0 — the CLI self-updates and a bad update bricked it once
git log --oneline -1         # expect 644d910 Add the session-two kickoff prompt and refresh the layout map
python3 -m unittest discover -s tests -t .    # expect 178 tests, OK
```

Then `codebuddy` (no `--model` flag; the x0.00 default is what we want).

**Screenshots: at least four this session, and at least one showing the CodeBuddy banner**
(product name + version). The §8 gate is unrecoverable if left late, and a shot with no
branding cannot be proven to be CodeBuddy. Save into `evidence/` as
`2026-09-22_codebuddy-cli_NN-<topic>.jpg`.

---

## THE PROMPT

Build the case-file view in `ui/`. This is the observability surface the challenge statement
requires: "inter-agent communication must be observable to a judge." It is also the screen the
demo is built around, so it carries more of the score than the code behind it.

Read first, in this order: `CODEBUDDY.md` (locked scope), `docs/statement-extract.md` (the
requirement in the organisers' own words), then run the pipeline and read its output:

```bash
python3 -m app.cli --dispute data/disputes/RD-0101.json --out runs/
```

That writes `runs/<run_id>/case_file.json`. **Read that file before designing anything.** It is
the contract. It was frozen deliberately in the previous session so this one does not build
against a shape that then moves, and it will not change under you.

### What the view must show

One dispute per screen, reading top to bottom as a story:

1. **The grievance** — from `intake`: who filed, what they claim, how much, and their form
   answers. The reader must know what is being argued about before anything else.
2. **The evidence** — from `evidence_pack`. Every number here was computed in Python, never by
   a model. Route deviation in km and %, fare recomputation, timestamps, chat signals. Fields
   are `null` when the record could not support them, and `notes` explains why — **render the
   note, never a blank.** A silent null is the failure this layer exists to prevent.
3. **The two cases** — from `claims.rider` and `claims.driver`, side by side. Each carries
   `claim_summary`, `argument`, `requested_outcome`, `requested_amount_sgd`, `evidence_cited`
   and `policy_rule_ids`. Showing them adjacent is the point: a judge should see two agents
   reading the same evidence and disagreeing.
4. **The ruling** — from `resolution`. Action, amount, confidence, explanation, plus
   `cited_rule_ids` and `cited_evidence_refs`. A citation should be visibly linked to the
   evidence field or rule it names; that link is what makes the ruling auditable rather than
   merely stated.
5. **The event strip** — from `events`. Each event has `seq`, `ts`, `type`, `from`, `to`,
   `summary`. This is literally the agent-to-agent traffic the statement asks to be observable.
   Compact by default, full payload one click deeper (`payload_ref` is a path relative to the
   run directory).

### Three outcomes, not one

`resolution.outcome` is `ruled`, `withheld` or `human_review`, and **each must render
differently.** This is the most important instruction in this prompt.

- `ruled` — the decision is shown to the parties.
- `withheld` — the Judge was below the confidence threshold, or the amount exceeded the SGD 50
  autonomous cap. `ruling` is `null`; the candidate ruling sits in `withheld_candidate` for a
  human reviewer. **The parties must never see the withheld figure** — only the neutral
  `party_message`. If your view leaks `withheld_candidate` into the party-facing area, the
  system's central safety claim is false. Mark the human-only region clearly.
  Try it: `python3 -m app.cli --dispute data/disputes/RD-0109.json --out runs/`
- `human_review` — filed outside the two supported categories. `evidence_pack` is `null` and
  both `claims` are `null`, because no agent ran and no LLM was called. Show
  `intake.category_as_submitted` against the routed `category`: the party chose "Property
  Damage / Mess" and the system declined. **Do not render this as an error or an empty state.**
  It is the system correctly refusing to act outside its competence, and it is probably the
  most persuasive thing in the whole demo.
  Try it: `python3 -m app.cli --dispute data/disputes/OS-0301.json --out runs/`

A view that only handles `ruled` is a third of the job.

### How it should work

- **Plain HTML/CSS/JS. No framework, no build step, no npm.** The whole repo runs on stock
  `python3` with zero installed packages and that property is worth protecting.
- Serve with `python3 -m http.server` from the repo root, or open the file directly. A small
  Python file server in `app/` is acceptable if the browser's file:// rules get in the way, but
  try the simple path first.
- Load a `case_file.json` and render it. A file picker or a dropdown of runs in `runs/` is
  enough; there is no need for a backend API this session.
- Every string shown comes from the JSON. **Do not hardcode any case's content into the
  markup** — the view must render a file it has never seen.
- Mock rulings carry a literal `MOCK` prefix in their text. Leave it visible. It is deliberate:
  it makes a mock run impossible to screenshot as if it were a real one.

### Design

40 of the 100 Demo Day points are story, design and presentation, against 10 for technical
execution. Treat the visual quality as load-bearing, not decoration. Aim for something that
looks like an internal ops console a real trust-and-safety team would use: dense, calm,
readable, no dashboard gimmicks. Clear visual separation between the two advocates and the
Judge. Confidence displayed as a number, not a gauge.

### Working rules

- One capability at a time, verified in a browser before moving on. Do not write the whole view
  and then check it.
- **Verify by running it, not by describing it.** Open the page, look at all three outcomes,
  confirm what renders.
- `ui/` and `app/` are yours. `tools/` and `tests/` are not; do not modify tests to make
  something pass.
- The existing 178 tests must still pass when you are done:
  `python3 -m unittest discover -s tests -t .`
- Commit after each verified step with a message explaining why, not just what.
- The repo is PUBLIC. Never commit credentials.

### If something is missing

The case-file contract was frozen for this session. If you find a field the view genuinely
needs and the JSON does not carry it, **stop and say so rather than inventing it or working
around it.** That is a contract gap worth fixing properly at the source.

---

## Notes for the operator (not part of the prompt)

**What "done" looks like:** all three outcomes render from real `case_file.json` files, nothing
hardcoded, 178 tests still green, and at least one screenshot showing the CodeBuddy banner.

**The thing most likely to go wrong:** the model builds a beautiful `ruled` view and treats
`withheld` and `human_review` as edge cases to tidy up later. Those two are where the whole
"responsible AI" story lives. If the session is running out of room, cut visual polish before
cutting either of them.

**The thing worth checking yourself afterwards:** whether `withheld_candidate` leaks into the
party-facing part of the screen. That is the one defect that would quietly make our central
claim untrue, and it is easy to miss because the page will look fine.

**Still open after this session:** the Tencent endpoint is unpinned (five TODOs in
`app/llm/tencent.py`, and it raises rather than silently falling back to mock), so every ruling
is still a MOCK. The eval harness scoring the pipeline against `data/ground-truth.json` comes
after that, because against the mock it would report a meaningless score.
