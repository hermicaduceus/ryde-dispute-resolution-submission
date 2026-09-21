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

## Why this exists

The competition mandates proof of product usage (screenshots of CodeBuddy/WorkBuddy chat logs,
accumulated during development). another coding agent produces none of that evidence, so its work is
kept architecturally separate: test harnesses, synthetic-data tooling, and unblocking. The
project's full memory and locked scope live in `CODEBUDDY.md` — read it for context, obey its
rules.