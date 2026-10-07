# Session twenty brief: a figure the record cannot prove goes to a human

One defect class, ruled by the operator on 2026-10-01 after the review of session nineteen.

**The defect.** JSON readers accept the bare tokens `NaN`, `Infinity` and `-Infinity`. A record
carrying one gets past every check today, because NaN compares False against everything and
Infinity compares the wrong way. Reproduced:

- RD-0106 with `"charged_sgd": NaN` makes `fare.difference_sgd` NaN, RD-5 does not fire, and the
  pipeline **rules a 0.66 refund** on a case whose clean record is held for a human.
- RD-0106 with `charged_sgd` **missing** does the same: the policy (EV-1) says a route finding
  needs the fare charged, and no code checks it.
- `ns6_auto_refund_eligible` returns True for a NaN fee.
- A NaN `fraud_flags` (or any NaN or Infinity profile count) crashes `build_evidence_pack` with
  `ValueError` or `OverflowError`.
- A NaN tariff rate makes the recomputed fare NaN; a NaN breakdown component makes
  `breakdown_consistent` False, which EV-3 reads as evidence of an incorrect charge.

**The rule.** A number that is present but not finite is not a recorded figure. It reads as
missing everywhere, and a gate never compares it. Cover the whole class, not the five repros.

`docs/policy.md` already carries the new text (EV-1's fare paragraph and the ESC-2 enforcement
note dated 2026-10-01). Read both before you start.

**Target:** `tests/test_w22_unproven_figures.py` (39 tests), currently RED, goes green, and the full
suite (`/usr/bin/python3 -m unittest discover -s tests -t .`, **730 tests when done**) is green.

**Do not edit anything under `tests/`, `tools/`, `data/` or `ui/`.** If a test looks wrong, stop
and ask. One existing test was updated for this session on purpose (listed at the end).

## The contract, file by file

### `app/evidence/compute.py`: the evidence layer

1. `_as_float` and `_as_int` return `None` for NaN, Infinity and -Infinity, exactly as they do for
   a string or a bool today. `_as_int` must never raise on one.
2. **Tariff rates.** A rate that is present but not finite is left out of `fare.rates`, and it
   makes the recomputed fare unknown: `recomputed_sgd`, `recomputed_estimated_route_sgd`,
   `deviation_fare_delta_sgd`, `difference_sgd` and `difference_pct` are all `None`. Do not compute
   from the remaining rates: a dropped per-km rate reads as free distance, a dropped surge as 1.0.
   Add **one** note to the pack's `notes` naming every broken rate and containing the words
   `not a finite number`. In that case do **not** also add the "no tariff rates in the record" note
   or the "trip numbers needed to recompute were missing" note: the rates and the trip numbers were
   there. When every rate is broken, `fare.rates` is `{}` and the only rate note is the
   broken-rate note.
3. **Breakdown components.** A component that is present but not finite is left out of
   `fare.components_sgd`, and it makes the sum unknown: `component_sum_sgd` is `None` and
   `breakdown_consistent` is `None` (not False). Add **one** note naming every broken component,
   containing `not a finite number`. A broken **promo** component (`promo_sgd`, `promo` or
   `discount_sgd`) is also a fare-formula input, so it voids the recomputed fare as in item 2. Any
   other broken component leaves the recomputation alone.
4. **Charged fare.** A broken `charged_sgd` is `None` (item 1 does this). The recomputation does not
   depend on it and survives.
5. **Case cancellation terms** (`cancellation.case_policy`). A term whose value is present but not
   finite is left out of the stated terms; the other terms survive. Add one note naming the broken
   term(s), containing `not a finite number`.
6. **Fees.** A broken stated cancellation fee reads as missing, so the existing fallback to the
   fare breakdown's `cancellation_sgd` applies. When both are broken there is no fee.

After this, **no Evidence Pack ever holds a non-finite number**. A test breaks every numeric field
of all 35 corpus records, one at a time, three ways, and requires exactly that, with no crash.

### `app/dispute.py`: the claimed amount

`Dispute.claim_amount_sgd` returns `0.0` for a NaN or infinite amount, as it already does for a
string. Today a NaN claim reaches every agent's prompt.

### `app/agents/judge.py`: the gates

1. `_is_figure` is True only for a **finite** int or float (bool still excluded). This alone stops
   the NS-6 helper calling a broken fee eligible.
2. **ESC-2 widens; it does not split.** On a route-deviation case the gate fires when **either**
   the deviation is not a recorded finite figure (`pack.route` present and `deviation_pct` is
   `None` or not finite) **or** the fare charged is not one (`pack.fare` is `None`, or
   `fare.charged_sgd` is `None` or not finite). One gate entry, named exactly `"ESC-2"`, never
   two, even when both are missing. No-show cases are never gated on the charged fare.
   - Summary (the operator strip), joined with `" and "` when both apply, ending ` (ESC-2)`:
     `the route deviation could not be measured` and/or
     `the fare charged could not be established`. With only the deviation missing, the
     withheld event summary must still read exactly
     `Judge withheld the ruling: the route deviation could not be measured (ESC-2)`.
   - Reason (the notes): one entry naming `route.deviation_pct` and/or `fare.charged_sgd`, ending
     `(EV-1, ESC-2)`. A charge-only reason must not name `route.deviation_pct`.
3. **RD-5 refuses a broken difference.** On a route case where `fare.difference_sgd` is present but
   not finite, withhold under gate `"RD-5"` whatever the ruling says. Summary names `(RD-5)`; the
   reason names `fare.difference_sgd` and must not print `nan`. `None` still means "no overcharge
   figure", and RD-5 still does not fire on it. The existing RD-5 check for a finite difference is
   unchanged; the two are one `if` / `elif`.
4. Gate order is unchanged: confidence, ESC-4, ESC-2, NS-6, RD-5. No gate summary carries an amount
   or the string `SGD`. Every gate withholds; none rewrites the Judge's candidate.

### Docs

- `docs/architecture.md`, **Gates enforced in code**: the ESC-2 row's first cell names ESC-2 and
  the charge (for example "ESC-2, unmeasured deviation or charge"); its condition names
  `deviation_pct`, `fare.charged_sgd` and EV-1. The count stays **"Eight gates"**: this is one gate,
  wider, not a ninth.
- `docs/architecture.md`, **Components** table, Evidence layer row: add that a number which is not a
  finite number (NaN or Infinity) counts as missing. The phrase `not a finite number` must appear.
- `README.md`, the "Five gates" paragraph: the ESC-2 clause says it also withholds when the fare
  charged cannot be established (the words `fare charged` must sit between `ESC-2` and `NS-6`).
  Keep "Five gates"; do not touch the Mermaid blocks.

## Allowed files

`app/evidence/compute.py`, `app/dispute.py`, `app/agents/judge.py`, `docs/architecture.md`,
`README.md`. Nothing else. `docs/policy.md` is already done; do not edit it.

## Constraints

Standard library only. Python 3.9: no `match`, no `X | Y` unions. Run the full suite with
`/usr/bin/python3`, not a bare `python3`. Commit your work in small commits when the suite is green.

## Existing test updated for this session (read, do not edit)

- `tests/test_w22_money_gates.py`: `test_a_missing_fare_block_is_not_gated` is renamed
  `test_a_missing_fare_block_is_held_by_esc2_not_rd5`. A route case with no fare block was ruled;
  it is now held by ESC-2 (no provable charge), and RD-5 still does not fire on it.

## What you should see on the mock when you are done

**No corpus case moves.** Every one of the 35 records carries a finite charged fare and finite
figures, so `python3 -m app.eval --llm mock` gives exactly what it gives today: organiser pack 11
of 18 matching, 14 of 18 decided without a human, 0 round-one stops; synth pack 10 of 17, 13 of 17,
0. If any case's outcome changes, something outside this class moved: stop and report it.

## Out of scope

The party page, the console, the server, the eval harness. Do not run the live model.
