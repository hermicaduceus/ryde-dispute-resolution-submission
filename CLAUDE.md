# CLAUDE.md

This file is read by non-CodeBuddy AI assistants (another coding agent and similar) that operate in this
repository.

## The one rule that matters here

**Application code (`app/` and `ui/`) is written only by the CodeBuddy build lane.** You are
the rescue lane: your writes are confined to `tools/` and `tests/`. Never create, edit or
delete anything under `app/`, `ui/`, `data/`, `docs/policy.md` or `evidence/`. The project's
competition submission claims the application was built on CodeBuddy — if you touch app code,
that claim becomes dishonest and the project can be disqualified.

If a fix genuinely requires changing `app/` or `ui/`: stop and report the needed change to
the operator instead of making it.

**One logged exception (amended 2026-10-01 by operator ruling):** within 48 hours of the
submission deadline, if the CodeBuddy build lane cannot land a fix to `app/` or `ui/` in time,
the operator may direct the rescue lane to make it. Every such change names the reason in its
commit message and is logged in `docs/tool-experiences.md`. Outside that window the rule above
holds without exception.

**One carve-out: generated data.** `data/` may change, but only as the output of running
`tools/build_corpus.py`. Never hand-edit a file under `data/`: edit the generator (or the
prose/sample inputs it reads under `tools/`) and re-run it, so every dispute record and every
ground-truth label stays reproducible from code. The one file under `data/` that is not
generated is an organiser-supplied sample, copied in verbatim and never modified. (Amended
2026-09-23 by operator ruling: the corpus was already produced this way, and the rule now
says so.)

## Why this exists

The competition mandates proof of product usage (screenshots of CodeBuddy/WorkBuddy chat logs,
accumulated during development). another coding agent produces none of that evidence, so its work is
kept architecturally separate: test harnesses, synthetic-data tooling, and unblocking. The
project's full memory and locked scope live in `CODEBUDDY.md` — read it for context, obey its
rules.