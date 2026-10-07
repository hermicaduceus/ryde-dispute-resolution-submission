# Session twenty-one brief: a route refund may never be more than the records prove

One defect, ruled by the operator on 2026-10-02 after the first live evaluation on the real
model.

**The defect.** Two route cases paid the rider money the policy says is not owed, at high
confidence, and no gate stopped either:

- **RD-0105**: the Judge refunded **5.56** at confidence 0.95. The rider booked a fixed fare and
  paid exactly the quote (`fare.charged_sgd` 14.21 equals `fare.recomputed_estimated_route_sgd`
  14.21). RD-4 says no action. The model read `fare.deviation_fare_delta_sgd` (5.56), which is
  what the detour *would* have cost on a metered fare, not money the rider paid.
- **RD-0107**: the Judge refunded **4.91** at confidence 0.85, citing RD-5. But
  `fare.difference_sgd` is 0.00 and the breakdown adds up; the deviation is 0.2 km / 2.8%, below
  RD-1. It is a traffic delay (RD-6) and the time charge stands.

Every existing gate checks confidence, the SGD 50 cap, unreadable figures, or a refund that is
too SHORT (RD-5). Nothing checks a refund that is too LARGE.

**The rule.** On a route-deviation case, money may only move as far as the records prove it is
owed. A refund larger than what the records prove the rider overpaid is withheld for a human.
That covers both a refund with no proof at all and one that is merely too big. A ruling of no
action is never held by this gate.

`docs/policy.md` already carries the new text (the RD-4 "Enforcement (2026-10-02)" paragraph).
Read it before you start.

**Target:** `tests/test_w28_unproven_refunds.py` (54 tests), currently RED, goes green, and the
full suite (`/usr/bin/python3 -m unittest discover -s tests -t .`, **844 tests when done**) is
green.

**Do not edit anything under `tests/`, `tools/`, `data/` or `ui/`.** If a test looks wrong, stop
and ask. Six existing test files were updated for this session on purpose (listed at the end).

## The contract: `app/agents/judge.py`

### 1. Constants, beside `DE_MINIMIS_SGD`

```
MATERIAL_DEVIATION_PCT = 20.0
MATERIAL_DEVIATION_KM = 1.0
MATERIAL_DEVIATION_GROSS_KM = 5.0
```

### 2. `deviation_is_material(pack) -> bool` (module level, public)

RD-1 in code. True when `pack.route.deviation_km >= 5.0` whatever the percentage, or when
`deviation_pct >= 20.0` **and** `deviation_km >= 1.0`. Use `_is_figure` on each value: a
missing, non-finite or bool figure is not material. No route block is not material. When the km
clears the gross limb, the percentage is not needed at all (it may be missing).

### 3. `provable_refund_sgd(pack) -> float` (module level, public)

What the records prove the rider overpaid. Start at `0.0` and take the **largest** of:

1. `fare.difference_sgd`, when it is a figure (RD-5, a pricing error);
2. `fare.charged_sgd - fare.component_sum_sgd`, when `fare.breakdown_consistent is False` and
   both are figures (EV-3: the line items add up to less than the charge). This proof works
   **without tariff rates**;
3. `fare.charged_sgd - fare.recomputed_estimated_route_sgd`, only when `deviation_is_material(pack)`
   and both are figures (RD-3 / RD-4: the charge above the fare the expected route would cost).

**Never** use `fare.deviation_fare_delta_sgd`: that is exactly the live bug. A missing or
non-finite figure contributes nothing. No fare block proves `0.0`. Return `round(proven, 2)`;
the result is never below zero.

On the corpus (both packs): RD-0101 5.81, RD-0102 5.86, RD-0103 0.00, RD-0104 7.70, RD-0105 0.00,
RD-0106 3.40, RD-0107 0.00, RD-0108 0.00, RD-0109 55.16.

### 4. The gate in `Judge.run`, after the RD-5 `if` / `elif`, before `if not gate_failures:`

Fires only when **all** of these hold:

- `dispute.category == CATEGORY_ROUTE_DEVIATION`;
- `ruling.action` is not `no action`;
- the record is readable: no `"ESC-2"` entry is already in `gate_failures`, **and**
  `fare.difference_sgd` is not "present but not a figure" (that is RD-5's unreadable branch).
  An RD-5 entry for a SHORT refund does **not** suppress this gate. One record defect, one
  reason; two different problems, two reasons.

Then:

- **refund**: held when `round(ruling.recommended_amount_sgd, 2) > provable_refund_sgd(pack)`.
  Equal goes out; one cent over is held. Less than proven is not this gate's concern.
- **compensation**: always held. A route record proves nothing owed to the driver.

When held, append `("RD-4", reason)` to `gate_failures` and append to `gate_summaries` exactly:

`the ruling pays more than the records prove is owed (RD-4)`

The summary carries no figure and no `SGD`. The reason (it lands in `resolution.notes`) carries
both figures, for example:

- refund: `RD-4: the records prove an overpayment of SGD 0.00; the proposed refund of SGD 5.56 is more than that`
- compensation: `RD-4: a route-deviation record proves nothing owed to the driver; the proposed compensation of SGD 2.00 is not supported`

The compensation reason must contain the word `driver`.

**Gate order** becomes: confidence, ESC-4, ESC-2, NS-6, RD-5, RD-4. The gate withholds; it never
rewrites the Judge's candidate (the human receives exactly what the Judge proposed). Update the
module docstring and the "gates" comment so they name RD-4.

## Docs

- `docs/architecture.md`, **Gates enforced in code**: the count sentence becomes **"Nine gates"**,
  and a new table row whose first cell names `RD-4` (for example "RD-4, unproven refund"), file
  `` `app/agents/judge.py` ``, condition naming `recomputed_estimated_route_sgd`,
  `difference_sgd` and `compensation`. Place it after the RD-5 row.
- `docs/architecture.md`, the summary paragraph near the top that lists "the two money gates NS-6
  and RD-5": name RD-4 as well.
- Both Mermaid blocks (`README.md` and `docs/architecture.md`, kept identical by a test): the gate
  node becomes `J --> G{"Gates pass? Confidence, cap, measured deviation, NS-6, RD-5, RD-4"}`.
- `README.md`, the gates paragraph under **Run**: **"Six gates"** and **"all six"**, adding a clause
  that RD-4 withholds a route refund larger than the records prove the rider overpaid. Keep the
  ESC-2 clause's words `fare charged` between `ESC-2` and `NS-6`.

## Allowed files

`app/agents/judge.py`, `docs/architecture.md`, `README.md`. Nothing else. `docs/policy.md` is
already done; do not edit it.

## Constraints

Standard library only. Python 3.9: no `match`, no `X | Y` unions. Run the full suite with
`/usr/bin/python3`, not a bare `python3`. Commit your work in small commits when the suite is
green.

## Existing tests updated for this session (read, do not edit)

The new gate moves results the old tests pinned. Each was re-pinned on purpose:

- `tests/test_eval_harness.py`: on the mock, RD-0103, RD-0105 and RD-0107 move from
  "wrong action" to "wrong outcome"; organiser totals: decided without a human 14 -> 11, by reason
  wrong outcome 1 -> 4, wrong action 6 -> 3.
- `tests/test_w22_eval_round_two.py`: decided without a human 14 -> 11 (organiser) and
  13 -> 10 (synth); the held list gains RD-0103, RD-0105, RD-0107.
- `tests/test_party_form_ux.py`: the 35-run drift baseline holds RD-0103, RD-0105 and RD-0107 as
  withheld on both packs.
- `tests/test_w22_money_gates.py`: `test_refunding_more_than_the_overcharge_is_issued` is renamed
  `test_refunding_more_than_the_overcharge_is_withheld_by_rd4` (the operator ruled 2026-10-02
  that a refund above the proof is held). Compensation on RD-0106 is now held by
  `["RD-5", "RD-4"]`.
- `tests/test_w22_docs.py`: "Eight gates" -> "Nine gates" (9 rows), "five gates" -> "six gates".
- `tests/test_w22_unproven_figures.py`: the same two counts.

## What you should see on the mock when you are done

`python3 -m app.eval --llm mock` on the organiser pack: **11 of 18** matching (unchanged),
decided without a human **11 of 18** (was 14), 0 round-one stops. Synth pack: **10 of 17**,
**10 of 17** (was 13), 0. Exactly three cases move on each pack: RD-0103 (0.74), RD-0105 (5.56)
and RD-0107 (4.91), each from a ruled refund to withheld by RD-4. If any other case moves, stop
and report it.

## Out of scope

The evidence layer, the party page, the console, the server, the eval harness. Do not run the
live model.
