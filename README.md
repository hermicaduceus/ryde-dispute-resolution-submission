# Ryde — Multi-Agent Autonomous Dispute Resolution

Entry for the **Tencent Cloud "AI CAN DO IT" Hackathon Singapore 2026**, Digital Native track
(the Ryde challenge statement, section 5 of the organisers' document).

**Status: building (since 2026-09-21).** The scope
is ruled: a two-category MVP (route deviation + no-show charge) with three agents, a
deterministic evidence layer, and an observable case-file view. The challenge statement is in
[`docs/statement-extract.md`](docs/statement-extract.md); the builder's contract is in
[`CODEBUDDY.md`](CODEBUDDY.md).

## The challenge

Ride-hailing platforms process thousands of dispute tickets daily: fare disputes, route deviations,
property damage, safety incidents, no-show charges. They are subjective, emotionally charged, and
currently resolved by humans reviewing GPS telemetry, chat logs, payment records and company policy
by hand. The result is slow, expensive and inconsistent.

The task is an autonomous multi-agent system that gathers evidence, builds both sides' cases, applies
company policy and issues a fair ruling with a confidence score and a plain-language explanation.

## Planned architecture

Three core agents, all MVP-required:

| Agent | Role |
|---|---|
| **Rider Advocate** | Gathers rider-side evidence, argues the rider's case from policy |
| **Driver Advocate** | Gathers driver-side evidence, argues the driver's case from policy |
| **Judge** | Weighs both cases, applies policy, rules, and explains the reasoning with a confidence score |

Inter-agent communication must be **observable** — a judge needs to see how the agents exchange
information and build their cases. That surface is a required deliverable, not a nice-to-have.

## Documents

- [`docs/statement-extract.md`](docs/statement-extract.md) — the challenge statement, verbatim
- `docs/architecture.md` — architecture diagram and system description (required deliverable, to come)
- `docs/policy.md` — policy rule set with stated provenance (to come)
- `docs/dataset.md` — dataset description and provenance (to come)
- [`docs/evidence-plan.md`](docs/evidence-plan.md) — development-process evidence rules
- [`CODEBUDDY.md`](CODEBUDDY.md) — builder's entry point and project memory

## Development tooling

Built with Tencent Cloud **CodeBuddy**. The competition mandates proof of product usage, so
development happens in the tool and evidence is captured as it occurs.

## Run

No dependencies and no API key needed for the skeleton: it runs on a stock Python 3.9+ with the
standard library only, using a deterministic mock in place of the LLM.

```bash
python3 -m unittest discover -s tests -t .        # 82 tests
python3 -m app.cli --dispute tests/fixtures/dispute_route_deviation.json \
                   --policy tests/fixtures/policy_min.md
```

That prints the agent-to-agent event strip and the ruling, and writes the run's artifacts to
`runs/<run_id>/`: `events.jsonl` (the observable traffic), `payloads/*.json` (the full payload
behind each event) and `case_file.json` (evidence, both claims, resolution).

Swap the fixture for `dispute_no_show_charge.json` to see the second category, or
`dispute_out_of_scope_category.json` to see an out-of-scope filing routed to human review
without an LLM call.

**Two caveats while the build is in progress.** `--policy` is needed because the real policy
document (`docs/policy.md`) is authored separately and is not in the tree yet; the fixture is a
minimal stand-in, not the project's policy. And every mock string is prefixed `MOCK`, because
the Tencent endpoint is not pinned yet (see the TODO block in `app/llm/tencent.py`) — a mock run
is a plumbing demonstration, never a real ruling.

The demo walkthrough and its recording land once the case-file UI and the real LLM call are in.
