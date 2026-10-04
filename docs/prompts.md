# How prompts drive the AI generation

This document explains, for each of the three agents, what its prompt contains, the output
format it must return, a real example of what it produced, what the code checks afterwards,
and what the party sees as a result. It exists because the challenge asks for it directly
("how prompts drive the AI generation"), and because the safety story of this system is
mostly a story about prompts and what surrounds them.

One rule governs everything below: **a prompt is a request, not a constraint.** The rules
the code enforces — six gates listed below, all of them in Python — decide whether a
ruling is delivered at all; the prompts ask for good behaviour, the code decides what
reaches the parties. The gates are deliberately narrow: each one names a specific defect
the records can show (low confidence, an amount above the autonomous cap, an
unmeasurable deviation, an unsupported contested no-show refund, a short refund of a
proven overcharge, an unproven refund), and anything they do not name is the model's
call. The gates do not decide the case; they decide who decides it. What is *not* gated
is equally deliberate and equally visible: on a no-show case with a recorded arrival
position, for example, the only bound on a refund is the autonomous cap — the policy's
fee-based limits for that case are left to the model and the evidence, not to a gate.

## How the three agents work

The system runs one LLM call per agent per dispute, and the agents never talk to each
other:

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
validation failure on the case (recorded, not blocked — see "What the code checks after
every call").

The pipeline in `app/pipeline.py` sequences a run, and the sequence has a stop in it:

1. Both advocates run.
2. **Stop-and-ask round.** If the advocates request follow-up questions and the party has
   not yet answered any, the run stops *before the Judge* and asks the filing party the
   fixed slot sentences. This is the `needs_info` outcome: the party answers, and the
   next run takes the answers and goes all the way to the Judge. A dispute is asked at
   most once — a second request from the advocates is recorded on the case but never sent.
3. The Judge runs — either immediately (no questions requested), or in the round after
   the party's answers arrive.
4. If no gate withholds the ruling, it is delivered; otherwise the case is queued for
   human review with the full case file.

## Shared prompt anatomy

Every agent prompt is two strings built in `app/agents/base.py`:

**The system prompt** carries the role, the shared hard rules, the agent's output schema,
and the follow-up slot rule (advocates only). The Judge's system prompt adds two
role-specific sections: how confidence works (an honest low confidence produces a holding
message rather than a wrong ruling, and inflating confidence to clear the bar is itself
wrong) and how to cite only the fields the ruling rests on.

**The user prompt** carries the case material in fixed blocks, in this order:

1. `DISPUTE` — the intake-form submission exactly as filed: dispute id, category, who
   filed, when, the claim text, the amount claimed, the intake answers as JSON, and any
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
7. `YOUR TASK` — one or two sentences saying what to argue and what to return.

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
make citations machine-checkable, which is what the post-call validation relies on —
though note what that validation does: it records failures, it does not block delivery
(see below).

## What the code checks after every call

The checks live in `app/agents/base.py`, `app/agents/judge.py` and `app/schemas.py`;
none of them is asked of the model:

- **Reply parsing.** The reply is parsed by `parse_json_object` (`app/llm/base.py`): it
  strips a code fence if the model added one despite rule 4, and takes the text from the
  first `{` to the last `}`. One re-ask is allowed on a contract error (the reply does not
  parse or fails the schema's from-payload validation); after that the call fails and the
  case escalates to a human rather than proceeding on a bad payload.
- **Citation validation.** Every evidence ref and rule ID is checked against the pack and
  the policy document. **A citation failure is recorded, not blocked:** the case file
  keeps the model's own claims with the validation result beside them, and a ruling that
  cites an invented rule still goes out unless a gate withholds it. The value is
  auditability — a reviewer sees what was claimed and what resolved — not enforcement.
- **Payload normalisation.** The payload is normalised where it is unambiguous: a
  no-action ruling's amount is forced to 0.00 (and noted on the case), amounts are
  rounded to the cent, confidence to four decimals. The gates see the normalised values;
  the case file carries the note, so nothing is silent.
- **The six gates.** In `app/agents/judge.py`, between the ruling and the parties, each
  withholding the candidate ruling (never rewriting it) for a human:
  - **Confidence.** Below the threshold from `app/config.json`, currently 0.65, the
    ruling is withheld.
  - **ESC-4.** A remedy above the autonomous cap of SGD 50.00 is withheld.
  - **ESC-2.** A route case whose deviation could not be measured, whose charged fare is
    not a recorded figure, or whose record states a fare input it cannot read, is
    withheld.
  - **NS-6.** A contested no-show (both sides asserting their presence) with no recorded
    driver arrival position: only a full refund of the recorded fee, for a low fee and a
    clean rider record, goes out automatically; every other ruling on such a case —
    including no action — is withheld.
  - **RD-5.** On a route case, when the records prove an overcharge of at least the
    SGD 1.00 de minimis, a ruling that refunds less than that proof is withheld; a
    difference figure that is present but not a finite number is withheld too.
  - **RD-4.** On a route case, a refund larger than the records prove the rider overpaid,
    or any compensation, is withheld.
- **Retry and time budget.** Transient transport failures (timeouts and 5xx) retry with
  backoff (2 s, 5 s, 10 s) inside a per-case time budget (`app/config.json`,
  `llm.case_budget_seconds`, currently 120); other transport errors (a refused
  connection, a firewall block) fail at once, and a budget that cannot cover the next
  call escalates the case instead of hanging the party.

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
| `explanation` | the reasoning, in plain language |
| `cited_rule_ids` | rule IDs the ruling rests on |
| `cited_evidence_refs` | evidence pack fields the ruling rests on |

One nuance worth naming: the prompt tells the model the explanation is for both parties to
read, but the party message never relays it. The code-built party message carries the
action, the amount and the cited rules' plain titles; the explanation itself stays in the
operator console and the case file, where a human reviewer reads it. The prompt's phrasing
keeps the model writing for a plain audience, which is the point of the sentence.

**What the code checks after:** the citation validation (recorded, not blocking), then the
six gates above. Only a ruling that clears every gate is delivered; a gate failure
withholds the candidate ruling and the case is queued for human review.

## Worked example

One real run, dispute RD-0103 (route deviation, 0.3 km / 6%), from the live evaluation of
3 October 2026 (run `2026-10-02T182133+0000-RD-0103`). Both advocates ran on the same
Evidence Pack and disagreed:

The Rider Advocate asked for a refund of SGD 0.74 (the fare delta the deviation caused),
citing 11 pack fields including `route.deviation_km`, `fare.deviation_fare_delta_sgd`
and `fare.charged_sgd`, and reasoning from six rules: RD-1, RD-2, RD-3, RD-4, GEN-3 and
GEN-4 — RD-3 is the one that asks for the refund of the delta. The Driver Advocate asked
for no action: the deviation is below RD-1's material thresholds, `fare.charged_sgd`
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
policy document. The gates had nothing to withhold, so the ruling was delivered. The
party message the run produced was: "Decision: no action. Basis: When a deviation is
material; Deviation with no fare consequence." — the action plus the plain titles of the
two cited rules, nothing of the explanation above.

The other half of the story is a run from the same evaluation: RD-0108 is a route case
whose `route.deviation_pct` is not a recorded figure, so the ESC-2 gate withheld the
Judge's candidate ruling and the parties saw the neutral under-review message instead.
The withheld candidate and the gate reason are both on the case file for the human
reviewer — the gates withhold, they never rewrite what the Judge proposed.

## What the parties see

Party text is built in code, never relayed from the model. The full set of code-built
messages (`app/schemas.py`):

- A **delivered ruling** shows the action, the amount, and the plain titles of the rules
  cited (never the ESC codes).
- A **withheld ruling** shows one fixed sentence: "Your case is still under review. We
  will let you know as soon as a decision is made."
- A **stop-and-ask round** shows a fixed lead-in ("Thank you — we need a little more
  information…") plus the fixed slot sentences.
- An **out-of-scope category** (anything outside route deviation and no-show) shows a
  fixed sentence routing it to the support team — it never reaches the agents:
  "Thank you for your report. It has been passed to our support team, who will follow
  up with you."
- A **human decision** later produces another code-built message, with the reviewer's
  name and reason recorded on the case but never shown.
- A run whose LLM record does not prove the live provider prefixes the **demo notice** to
  the decision text, so an illustrative run never reads like a live review:
  "Demo notice: this decision was produced by an illustrative run and is not a live
  review."

The Judge's full explanation and both advocates' arguments stay in the operator console
and the case file. The party never sees text an agent writes in a question, an argument,
or an explanation.

## Transport and the live endpoint

The provider is selected in `app/config.json`: `mock` by default (a deterministic
stand-in, so a fresh checkout needs no keys), `tencent` for the live model via
`--llm tencent`. The live adapter (`app/llm/tencent.py`) calls three separate Tencent
Cloud ADP apps, one per agent, each with its own key. Two structural facts about the live
shape: the system and user prompts are merged into a single text message when sent (the
endpoint takes one text field), and each ADP app also carries its own short role card
configured on the Tencent side, which this repo does not contain.

Transport facts a reviewer will ask about:

- **Prompt cleaning before sending.** The endpoint's firewall refuses prompts where
  backticks and ASCII brackets occur together, so every prompt is cleaned before it goes
  out: backticks are dropped and `( ) < > ; | $` are swapped for their full-width forms,
  which the model reads identically.
- **Key redaction.** The AppKeys live in `.env`, never in the repo. They are redacted
  from error messages the adapter raises; they never enter the request objects that are
  logged, so they do not appear in the event log or the case file.
- **Response cap.** A reply larger than 2 MiB is refused rather than read (a Judge-sized
  reply measured 89 KB on the live endpoint, which echoes the prompt back).
- **Pacing.** Calls are paced at one per 6.5 seconds across the whole system, with the
  model's usage and a request fingerprint (a hash of the prompts) recorded on every
  payload, so the exact prompt bytes of every call are verifiable after the fact. The
  fingerprint proves what was asked, not what was answered: reproducing an answer needs
  the model, but a reviewer can confirm the prompt a ruling came from, byte for byte.