# How prompts drive the AI generation

This document explains, for each of the three agents, what its prompt contains, the output
format it must return, a real example of what it produced, what the code checks afterwards,
and what the party sees as a result. It exists because the challenge asks for it directly
("how prompts drive the AI generation"), and because the safety story of this system is
mostly a story about prompts and what surrounds them.

One rule governs everything below: **a prompt is a request, not a constraint.** Every rule
that moves money or withholds a decision is enforced again in Python after the model
answers. The prompts ask for good behaviour; the code guarantees it.

## How the three agents work

The system runs one LLM conversation per agent per dispute, and the agents never talk to
each other:

- **Rider Advocate** (`app/agents/rider_advocate.py`) reads the dispute, the Evidence Pack
  and the policy, and argues the rider's case.
- **Driver Advocate** (`app/agents/driver_advocate.py`) reads the same material and argues
  the driver's defence. Neither advocate sees the other's case.
- **Judge** (`app/agents/judge.py`) reads both advocate cases together with the same
  Evidence Pack and policy, and issues one ruling.

The Evidence Pack is computed deterministically by `app/evidence/compute.py` before any
agent runs. It is the only source of numbers: the intake form's free-text answers are
echoed verbatim into every prompt, but every figure the agents cite comes from the pack.
The pack also decides what may be cited at all: each prompt lists the exact dotted
references the pack contains, and any citation that does not resolve is recorded as a
validation failure on the case.

The pipeline in `app/pipeline.py` sequences the calls: both advocates run, the Judge runs
after them, and any follow-up questions the advocates requested are asked of the filing
party through fixed slot sentences (the party never sees text an agent writes in a
question). If the Judge cannot rule, the case is escalated to a human reviewer with the
full case file.

## Shared prompt anatomy

Every agent prompt is two strings built in `app/agents/base.py`:

**The system prompt** carries the role, the shared hard rules, the agent's output schema,
and the follow-up slot rule (advocates only). The Judge's system prompt adds two
role-specific sections: how confidence works (an honest low confidence produces a holding
message rather than a wrong ruling, and inflating confidence to clear the bar is itself
wrong) and how to cite only the fields the ruling rests on.

**The user prompt** carries the case material in fixed blocks, in this order:

1. `DISPUTE` — the intake-form submission exactly as filed: dispute id, category, who
   filed, the claim text, the amount claimed, the intake answers as JSON, and any
   follow-up answers the party gave.
2. `EVIDENCE PACK` — the computed pack as JSON, labelled "computed deterministically; the
   only source of numbers".
3. `CITABLE EVIDENCE REFS` — the dotted references the pack actually contains. This is
   the whitelist rule 2 of the hard rules refers to.
4. For the Judge: `RIDER ADVOCATE CASE` and `DRIVER ADVOCATE CASE`, the two cases as JSON.
5. `POLICY DOCUMENT` and `POLICY RULE IDS` — the full policy text and the rule IDs it
   contains.
6. `FOLLOW-UP QUESTION SLOTS` (advocates only) — the fixed sentences code can render for
   this category, so an agent can only choose from sentences a human wrote.
7. `YOUR TASK` — two sentences saying what to argue and what to return.

## The hard rules

Every agent's system prompt carries the same block, verbatim:

```text
HARD RULES
1. Never do arithmetic. Every number you state must be copied verbatim from the Evidence
   Pack. If a number you want is not in the pack, say it is unavailable — do not compute it.
2. Cite evidence only by the exact dotted references listed under CITABLE EVIDENCE REFS.
3. Cite policy only by rule IDs listed under POLICY RULE IDS. Never invent a rule ID.
4. Return exactly one JSON object matching the schema below. No prose around it, no code
   fence, no commentary.
```

Rule 1 exists because the model's arithmetic cannot be audited line by line, but the
pack's can: every number in the pack was computed by tested Python code. Rules 2 and 3
make citations machine-checkable, which is what the post-call validation below relies on.

## What the code checks after every call

The checks live in `app/agents/base.py` and `app/agents/judge.py`; none of them is asked of
the model:

- **Contract parse.** The reply must parse as exactly one JSON object matching the
  agent's schema (`parse_json_object`). One re-ask is allowed on a contract error; after
  that the call fails and the case escalates to a human rather than proceeding on a bad
  payload.
- **Citation validation.** Every evidence ref and rule ID is checked against the pack and
  the policy document. Failures are not removed: the case file keeps the model's own
  claims with the validation result beside them, so a reviewer sees what was claimed and
  what resolved.
- **The six gates.** In `app/agents/judge.py`, between the ruling and the parties:
  the confidence gate (below the threshold from `app/config.json`, currently 0.65, the
  ruling is withheld), ESC-4 (an amount above the autonomous cap of SGD 50.00 is withheld
  for a human), ESC-2 (a route case whose deviation or charged fare cannot be established
  from the records), NS-6 (a contested no-show refund that the record does not support
  automatically), RD-5 (a proven overcharge the ruling fails to refund) and RD-4 (a
  refund larger than the records prove, or any compensation on a route case). Every gate
  withholds the candidate ruling for a human; none rewrites what the Judge proposed.
- **Retry and time budget.** Transport failures retry with backoff inside a per-case
  time budget (`app/config.json`, `llm.case_budget_seconds`, currently 120); a budget
  that cannot cover the next call escalates the case instead of hanging the party.

## Rider Advocate

**Role.** Represent the rider's perspective, argue the rider's claim firmly but without
overstating it: the Judge sees the same Evidence Pack, so a claim the evidence does not
carry weakens the rider's case rather than strengthening it.

**Output schema** (from `app/agents/base.py`):

| Field | Contract |
|---|---|
| `claim_summary` | one or two sentences stating what this side's case is |
| `evidence_cited` | dotted evidence refs, from the citable list |
| `policy_rule_ids` | rule IDs from the policy |
| `argument` | the case for this side, referring to the cited evidence and policy |
| `requested_outcome` | refund, compensation, or no action |
| `requested_amount_sgd` | number, 0.00 for no action |
| `follow_up_slots` | at most 3 slot ids, or empty |

**What the party sees:** nothing from this agent's output except, if the intake form is
conflicting or incomplete, the fixed slot sentences chosen in `follow_up_slots`. The
argument text stays in the operator console and the case file.

## Driver Advocate

**Role.** Represent the driver's perspective. The driver is not on trial: a fare computed
correctly, a deviation with a recorded justification, or a wait that met policy are all
legitimate defences and should be argued as such.

**Output schema:** identical to the Rider Advocate's (same fields, same contract) — the
difference is only the side argued.

**What the party sees:** the same as the Rider Advocate: nothing, except fixed slot
questions via the same mechanism.

## Judge

**Role.** Weigh the two advocate cases, apply the company policy, issue one ruling.
Impartial: neither side has to win, and "no action" is a ruling like any other. Where the
evidence does not settle a question, the explanation must say so rather than fill the gap.

**Confidence** is defined in the prompt as the model's honest probability that the ruling
is the one the policy and evidence support, with the gate explained: an honest low
confidence produces a holding message to the parties instead of a wrong ruling.

**Output schema** (from `app/agents/judge.py`):

| Field | Contract |
|---|---|
| `action` | refund, compensation, or no action |
| `recommended_amount_sgd` | number in SGD; 0.00 for no action |
| `confidence` | number between 0 and 1 |
| `explanation` | the reasoning, in plain language, for both parties to read |
| `cited_rule_ids` | rule IDs the ruling rests on |
| `cited_evidence_refs` | evidence pack fields the ruling rests on |

**What the code checks after:** the citation validation, then the six gates above. Only a
ruling that clears every gate is delivered; a gate failure withholds the candidate ruling
(nothing is rewritten) and the case is queued for human review.

## Worked example

One real run, dispute RD-0103 (route deviation, 0.3 km / 6%), live Tencent ADP model,
10 October 2026 live evaluation. Both advocates ran on the same Evidence Pack and
disagreed:

The Rider Advocate asked for a refund of SGD 0.74 (the fare delta the deviation caused),
citing eleven pack fields including `route.deviation_km`, `fare.deviation_fare_delta_sgd`
and `fare.charged_sgd`, and reasoning from RD-1, GEN-3 and GEN-4. The Driver Advocate
asked for no action: the deviation is below RD-1's material thresholds, `fare.charged_sgd`
matches `fare.recomputed_sgd`, `fare.difference_sgd` is 0.0, so there is no overcharge.

The Judge ruled no action at confidence 0.90, citing RD-1 and RD-4:

```json
{
  "action": "no action",
  "recommended_amount_sgd": 0.0,
  "confidence": 0.9,
  "explanation": "The evidence shows a route deviation of 0.3 km (6.0%), which is below both material deviation thresholds under RD-1 (20% and 1.0 km, or 5.0 km). Since the deviation is immaterial, drivers are entitled to routing judgment. The fare charged (SGD 11.69) matches the recomputed fare for the actual route, and fare.deviation_fare_delta_sgd (SGD 0.74) represents the cost difference between the actual and estimated routes, not an overcharge. Under RD-4, with no fare consequence (the charged amount is correct for the route taken) and no evidence of agreement to a different route (chat.agreement_markers is 0), no monetary remedy is due. The rider was charged the proper fare for the journey received.",
  "cited_rule_ids": ["RD-1", "RD-4"],
  "cited_evidence_refs": [
    "route.deviation_km",
    "route.deviation_pct",
    "fare.charged_sgd",
    "fare.recomputed_sgd",
    "fare.deviation_fare_delta_sgd",
    "chat.agreement_markers"
  ]
}
```

Citation validation passed: every ref and rule ID resolves against the pack and the
policy document. The gates had nothing to withhold, so the ruling was delivered.

The other half of the story is the same pipeline one dispute later: RD-0108 is a route
case whose `route.deviation_pct` is not a recorded figure, so the ESC-2 gate withheld the
Judge's candidate ruling and the parties saw the neutral under-review message instead.
The withheld candidate and the gate reason are both on the case file for the human
reviewer — nothing is rewritten, nothing disappears.

## What the parties see

Party text is built in code, never relayed from the model. A delivered ruling shows the
action, the amount, and the plain titles of the rules cited (never the ESC codes); the
Judge's full explanation and both advocates' arguments stay in the operator console. A
withheld ruling shows one fixed sentence: "Your case is still under review. We will let
you know as soon as a decision is made." A human reviewer's decision later produces
another code-built message. The party never sees text an agent writes in a question, an
argument, or an explanation.

## Transport and the live endpoint

The provider is selected in `app/config.json`: `mock` by default (a deterministic
stand-in, so a fresh checkout needs no keys), `tencent` for the live model via
`--llm tencent`. The live adapter (`app/llm/tencent.py`) calls three separate Tencent
Cloud ADP apps, one per agent, each with its own key.

Two transport facts a reviewer will ask about:

- **Prompt cleaning before sending.** The endpoint's firewall refuses prompts where
  backticks and ASCII brackets occur together, so every prompt is cleaned before it goes
  out: backticks are dropped and `( ) < > ; | $` are swapped for their full-width forms,
  which the model reads identically.
- **Key redaction and response cap.** The AppKeys live in `.env`, never in the repo, and
  are redacted from every log line. A reply larger than 2 MB is refused rather than read
  (a Judge-sized reply measured 89 KB on the live endpoint, which echoes the prompt back).

Calls are paced at one per 6.5 seconds across the whole system, inside the per-case time
budget, with the model's usage and a request fingerprint recorded on every payload so a
run is reproducible after the fact.