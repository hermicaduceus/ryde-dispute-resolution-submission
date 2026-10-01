# Architecture

This document explains the system to someone who has read the README and has five minutes.
Every claim here describes the code as it stands; nothing is planned or partial except where
the Limits section says so plainly.

## Overview

Ryde is a multi-agent dispute resolution system for ride-hailing: a party files a dispute
through a web intake form, and the system resolves the two categories it handles — route
deviation and no-show charge — end to end. Three agents do the work: a Rider Advocate and a
Driver Advocate each build their side's case from the evidence, and a Judge weighs both
cases, applies company policy and issues a ruling with a confidence score. Every computed
figure the agents argue from comes from a deterministic Evidence Pack calculated in Python
before any model is called; agents cite pack fields by reference and are forbidden from
doing their own arithmetic, and the only other number they see is the amount the party
asked for. The decisions that must never depend on a model's obedience — the confidence
threshold, the SGD 50 autonomous cap, the requirement that a route ruling rest on a measured
deviation, the two money gates NS-6 and RD-5, the one-round follow-up limit, and the routing of
out-of-scope categories to human review — are enforced in Python code, not asked of the model in
a prompt. The system
has two surfaces: an operator console that shows the full case file and the agent-to-agent
traffic, and a party page where the filing party submits the form and reads only what they
are allowed to read.

## Diagram

The whole system on one page. A dispute arrives either through the web intake form or the
command-line runner; the two swappable inputs (the policy document and the dataset pack)
enter from the side. Every step of a run lands in the event log, and the operator console
renders the event strip embedded in the case file — opening each event's full payload from
the run files the operator attaches.

```mermaid
flowchart TD
    PACK["Dataset pack"] --> B["Server"]
    PACK --> CL["Command-line runner"]
    A["Rider intake form"] --> B
    B --> C{"Category in scope?"}
    CL --> C
    C -- "Out of scope" --> H["Human review"]
    C -- "Route deviation or no-show" --> E["Evidence Pack"]
    POL["Policy document"] --> RA["Rider Advocate"]
    POL --> DA["Driver Advocate"]
    POL --> J["Judge"]
    E --> RA
    E --> DA
    RA --> S{"Questions for the party?"}
    DA --> S
    S -- "Yes, first round" --> O4["Needs info"]
    O4 --> PA["Party answers follow-ups"]
    PA -- "Fresh run with the answers" --> B
    S -- "No" --> J
    J --> G{"Gates pass? Confidence, cap, measured deviation, NS-6, RD-5"}
    G -- "Yes" --> O1["Ruled"]
    G -- "No" --> O2["Withheld"]
    O2 -- "Candidate ruling queued" --> H
    J -- "Model could not answer" --> H
    B -. "Every step emits an event" .-> L["Event log"]
    J -.-> L
    L -- "Embedded in the case file" --> K["Operator console"]
```

## Components

| Component | File(s) | Responsibility |
|---|---|---|
| Pipeline | `app/pipeline.py` | Runs one dispute end to end, moves the case between agents, records every step |
| Dispute record and routing | `app/dispute.py` | Parses the two record shapes, normalises categories, routes out-of-scope filings away |
| Evidence layer | `app/evidence/compute.py` | Computes the Evidence Pack by plain arithmetic; a missing input inside a record becomes a null with a note, never a guess — a number that is present but **not a finite number** (NaN or Infinity, which a JSON reader accepts) counts as missing, and it voids what it feeds rather than being dropped from a formula. A route case with no trip record, or a no-show case with no cancellation record, aborts the run before any pack is built |
| Agent scaffolding | `app/agents/base.py` | Shared prompts, the LLM call, and citation validation against the pack and the policy |
| Rider Advocate | `app/agents/rider_advocate.py` | Argues the rider's side from the pack and the policy |
| Driver Advocate | `app/agents/driver_advocate.py` | Argues the driver's side from the pack and the policy |
| Judge | `app/agents/judge.py` | Weighs both cases, issues one ruling, withholds it behind the gates |
| Event log | `app/events.py` | The append-only record of who said what to whom, with full payloads on disk |
| Output contracts | `app/schemas.py` | The typed shapes agents must produce; builds the party-facing decision message |
| Policy loader | `app/policy.py` | Reads the policy document, extracts rule IDs, fails loudly when it is missing |
| Mock LLM | `app/llm/mock.py` | Deterministic stand-in provider; its free-text fields — claim summaries, arguments, the Judge's explanation — carry a `MOCK` prefix, while actions, rule IDs and evidence refs do not |
| Tencent adapter | `app/llm/tencent.py` | The real provider: calls one Tencent Cloud ADP app per agent over HTTP |
| HTTP server | `app/server.py` | The intake API, the party view allowlist, and static files for both pages |
| Command-line runner | `app/cli.py` | Runs one dispute from the terminal and prints the event strip |
| Runtime configuration | `app/config.json` | Confidence threshold, autonomous cap, default dataset pack, provider settings |
| Operator console | `ui/app.js` | Renders the case file: grievance, evidence, both claims, resolution, event strip |
| Party page | `ui/party/party.js` | The intake form and the outcome view the filing party sees |
| Policy document | `docs/policy.md` | The rule set the agents cite, with per-rule provenance |

## Lifecycle of a dispute

`run_dispute` in `app/pipeline.py` walks one dispute through these steps, in this order,
emitting an event at each:

1. `run.started` — the system records the dispute id, category, LLM provider, confidence
   threshold and the policy rule IDs in force.
2. `dispute.filed` — the raw intake-form submission is logged exactly as it arrived.
3. **Routing.** If the category is outside the two handled ones, the run emits
   `dispute.routed_to_human_review`, then `party.notified` with the neutral support message,
   then `run.completed` — and no agent runs at all.
4. `evidence.pack_built` — the Evidence Pack is computed in Python, before any LLM call,
   and offered to the agents as the source of every computed figure — the only other
   number they see is the amount the party claimed.
5. `case.assigned` — once to each advocate.
6. Each advocate runs and emits `advocate.case_submitted` to the Judge with its case. When
   an advocate needs more from the filing party, it selects offered slot IDs and emits
   `advocate.follow_up_requested` in the first round with both the selected slots and the
   rendered questions. Code renders a bank sentence for a rider-filed dispute, or a form
   sentence from an intake label for either filer; any question text written by the model
   is ignored. The party-safety check remains a backstop, and only rendered questions that
   pass it reach the party.
7. **Stop and ask.** If there are questions to send and the dispute does not already carry
   the party's answers, the run stops before the Judge: `party.notified` carries the
   rendered questions — or, when none survive the backstop, plain template questions the
   pipeline builds for blank intake fields — then `run.completed` records the `needs_info`
   outcome. The party's answers start a fresh run, which is guaranteed to reach the Judge.
8. `judge.deliberation_started` — both cases are handed to the Judge together.
9. The Judge rules: `judge.ruling_issued` when every gate passes, or
   `judge.ruling_withheld` when one fails — the candidate ruling is recorded either way.
10. `party.notified` — the message the parties actually receive, as opposed to what was
    decided internally.
11. `run.completed` — the outcome is recorded and the case file is written.

## The four outcomes

| Outcome | When it happens | Did the Judge run? | Party page shows |
|---|---|---|---|
| `ruled` | The Judge issued a ruling and every gate passed | Yes | `decided` |
| `withheld` | A gate stopped the ruling, or the model could not answer after its allowed retries | Yes for a gate — the candidate is recorded for a human reviewer, never delivered; no candidate exists for a model failure | `under_review` |
| `human_review` | The category is outside the two the agents handle | No — routed away before any agent | `passed_to_support` |
| `needs_info` | The advocates selected offered follow-up slots in the first round, or a blank form answer produced a template question | No — the run stops before the Judge | `needs_info` |

## Gates enforced in code

Eight gates stand between a filing and a ruling, and each is enforced in Python, not asked of
the model in a prompt:

| Gate | File | Condition as written in code |
|---|---|---|
| Confidence threshold | `app/agents/judge.py` | `ruling.confidence < confidence_threshold` — the threshold is 0.65, read from `app/config.json` |
| ESC-4, the autonomous cap | `app/agents/judge.py` | A money ruling whose `recommended_amount_sgd` exceeds the cap is withheld; the cap is SGD 50 from `app/config.json` |
| ESC-2, unmeasured deviation or charge | `app/agents/judge.py` | On a route-deviation case, the ruling is withheld when `route.deviation_pct` is not a recorded finite figure, or when `fare.charged_sgd` is not one (or the fare block is absent) — EV-1 names the deviation and the fare charged as the figures a fare finding needs, and a figure the record cannot prove is a missing figure |
| NS-6, contested no-show | `app/agents/judge.py` | On a no-show case where the driver marked a no-show, the rider claims the driver was absent, and `cancellation.driver_distance_from_pickup_m` is null, the fee has no GPS proof: a refund is issued automatically only when the fee is at most SGD 10 and the rider's `fraud_flags` are recorded and zero with no more than half of past disputes rejected; any other ruling is withheld, and the refund must equal the fee to the cent |
| RD-5, proven overcharge | `app/agents/judge.py` | On a route-deviation case where `fare.difference_sgd` is recorded and at least SGD 1.00, a ruling that refunds less than the proven difference is withheld |
| One-round follow-up limit | `app/pipeline.py` | `if questions and not dispute.follow_up_answers` — a dispute is asked at most once; with answers present the Judge always runs and fresh questions are recorded but not sent |
| Out-of-scope routing | `app/pipeline.py` | `if not dispute.is_agent_handled` — anything outside route deviation and no-show charge goes to human review before any agent runs; an unrecognised category normalises to "other" in `app/dispute.py` |
| Answer once | `app/server.py` | The answers route claims the run with an exclusive create (`O_CREAT \| O_EXCL`) before re-running it — a `needs_info` run can be answered exactly once and cannot produce two rulings |

Why in code? Because a prompt is a request — a model can misread it, and there is no
recourse when it does. Code is a guarantee: the branch either runs or it does not, and the
event log shows which. ESC-4 in particular moves money, so it must not depend on the LLM
having read its instructions carefully.

## Observability

Every run writes three things under `runs/<run_id>/`:

- `events.jsonl` — one JSON line per event, append-only, never rewritten: who sent what to
  whom, when, with a one-line summary.
- `payloads/` — the full payload behind each event, named by sequence number and event
  type, so the strip stays readable and the detail stays one click away.
- `case_file.json` — the assembled record: what was claimed, the evidence pack, both
  advocate cases, the resolution, and the event strip. Self-contained, so one file tells
  the whole story of one run.

A run filed through the server writes one more file: `dispute.json`, the record the pipeline
actually ran on (the command-line runner does not write it). When a `needs_info` run is
answered, its directory also gains `answered.json`, recording which run the answers
produced.

The operator console (`ui/app.js`) renders the case file: the event strip shows one row per
event — sequence, time, sender to recipient, summary — and expanding a row opens the full
payload from the run directory attached in the browser. Payload references are sanitised, so
a console loaded with a hostile file can be pointed at nothing outside the run. The
command-line runner prints the same strip to the terminal.

## What the parties see

`party_view` in `app/server.py` is an allowlist that fails closed. The party page is handed
exactly five keys — run id, dispute id, status, message, questions — and any malformed case
file degrades to the neutral under-review message with no questions. A withheld ruling's
amount and the Judge's confidence are structurally absent from everything the party is
sent, not merely unrendered. `party_message_for_ruling` in `app/schemas.py` composes the
decision message in code from structured fields — the action, the amount, and the plain
titles of the policy rules cited — and the Judge's explanation never crosses this boundary:
it stays in the operator console. Every non-decision status shows a canonical constant
message, whatever a stale or planted case file might say. The two kinds of party-facing text
are protected differently. The decision message is composed in code from structured fields,
so nothing model-written reaches it: it names the action and the amount — a no-action ruling
carries no amount — and at most three rule titles, never the escalation (ESC) rules. On a
decided view the message leads with a demo notice whenever the ruling's LLM record does not
prove the real provider — only a record that is a non-array dict whose provider field is
exactly `tencent` suppresses it, and any other record, missing, mock or malformed, keeps it —
so a decision made on an illustrative run never reads like a live review, while a proven
real-provider decision shows no notice.
Follow-up questions are selected by the advocates as slot IDs; code renders each sentence
from the fixed category bank or from an intake form label. Bank slots are offered only when
the rider filed, while form slots work for either filer. Any question text written by the
model is ignored, so no model-written text reaches a party. The word check (`is_party_safe`,
applied in `_questions_for_party` in `app/pipeline.py` and again in `party_view`) remains a
backstop, as it is for the code-composed decision message. When no rendered question survives,
the pipeline falls back to plain template questions built from the form's own labels. A run
that asked for more information is answered through `POST /api/disputes/<run_id>/answers`, and
the answers start a fresh run on the same dispute.

## Policy and dataset packs

`docs/policy.md` is data, not code: rules with IDs (GEN, EV, RD, NS, ESC families),
preconditions written against pack fields in plain language, and per-rule provenance
stating whether a rule comes from Ryde's own published policy, a comparable operator, or
the project team. The pipeline reads it at the path in `app/config.json`; a different
policy document drops in with no code change. Nothing in the code evaluates the
preconditions — the Judge reads the rules and applies them in its reasoning. Citing a rule
that does not exist is recorded rather than blocked: an unknown ID is logged under the
ruling's `validation.unknown_rule_ids` with a note and the ruling still issues, but only
titles of rules the policy actually defines can reach the party message.

Two dataset packs live under `data/packs/`: `organiser-style-v1` — the default in
`app/config.json` — which holds the corpus in the organisers' record shape, including their
own DISP-002 verbatim; and `ryde-synth-v1`, the same 17 cases in this project's own record
shape. Swapping corpora is a directory copy, never a code change. Each pack carries a
`ground-truth.json` of expected outcomes, kept out of what the agents see: the agents get
the dispute record, the evidence pack and the policy — never the answer — so replayed-run
consistency can be measured honestly.

## LLM provider

Agent logic never talks to a vendor SDK. Every agent builds a request and calls one seam:
the `LLMClient` interface in `app/llm/`, a single `complete` method whose response carries
the text plus provenance (provider, model, usage, finish reason). Two adapters implement
it. The mock provider, `app/llm/mock.py`, returns deterministic contract-shaped responses,
so the full pipeline runs with no API key and the same dispute always produces the same
decisions and the same computed figures (the run id and the event timestamps differ from
run to run). Its free-text fields — claim summaries, arguments, the Judge's explanation —
carry a `MOCK` prefix, so a mock run can never be mistaken for a real ruling; actions, rule
IDs and evidence refs are not prefixed. The party decision message, composed in code, is
marked differently: on a decided party view it leads with a fixed demo notice stating that
the decision came from an illustrative run and is not a live review, shown whenever the
ruling's LLM record does not prove the Tencent provider, and only a record whose provider
field is exactly `tencent` shows a decision with no notice. The Tencent adapter,
`app/llm/tencent.py`, implements the same interface over Tencent Cloud ADP (Agent
Development Platform). Each agent is its own published ADP app with its own key: Rider
Advocate, Driver Advocate and Judge. The apps carry only a short role card; the adapter
sends the full role prompt on every call, so the prompts live in this repo and every gate
stays in Python. Three things about the endpoint shape the adapter. Tencent's web firewall
blocks prompts that mix backticks with ASCII brackets, so the adapter drops backticks and
sends full-width brackets, which the model reads the same way; a blocked call is classified
as permanent and is never asked again. ADP reports errors inside a successful HTTP response,
so the adapter reads every event rather than trusting the status code. The free plan allows
10 calls a minute, so calls are spaced at least 6.5 seconds apart. The agent layer retries a
transient failure up to three times, with waits of 2, 5 and 10 seconds; a contract failure
is asked again once. A parsed reply is final: a low confidence or capped ruling is never
asked again. One case shares a 120 seconds time budget from `llm.case_budget_seconds`; each
retry is recorded as `llm.call_retried`. When the budget cannot cover a call or wait, or the
model still cannot answer, the pipeline returns a withheld case and emits
`dispute.escalated_on_model_failure`; the case file keeps the `model_failure` record for the
reviewer. There is no silent fallback to the mock. The mock stays the default provider, so
the tests and a fresh checkout need no keys; `--llm tencent` selects the real model.

## Limits

What the system does not do yet, stated plainly:

- **A failed model call is escalated.** The party waits while retries run and sees the neutral
  under-review message; after the case is queued for human review, the party is not notified later.
- **Amounts must come back as JSON numbers.** A model reply carrying an amount as a string
  is rejected, never converted, because the value moves money.
- **Two categories only.** Route deviation and no-show charge. Property damage and safety
  incidents route to human review by design.
- **The driver-side form is not built.** The party page files as the rider only; the
  pipeline itself accepts driver-filed disputes, but no web form offers it yet.
- **Follow-up wording is code-owned.** Advocates select slot IDs; code renders each question
  from the fixed category bank or an intake form label, and model-written question text is
  ignored. Bank slots are rider-only; form slots are available to either filer.
- **The word check is a backstop.** Rendered follow-up questions and the code-composed decision
  message pass the keyword gate, which is not a semantic guarantee; blank fields still use
  template questions built from the form's own labels.
- **Policy preconditions are not evaluated by code.** The rules are written against pack
  fields in plain language; nothing checks them mechanically, and the Judge applies them by
  reading them.
