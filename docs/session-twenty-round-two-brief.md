# Session twenty, round two: the same class, the inputs round one missed

Round one made NaN and Infinity read as missing. A review of round one found the same defect
class reaching money through a token the guards do not recognise, plus three places round one
did not cover. The operator ruled all of it as one round on 2026-10-01.

**The defects, reproduced:**

1. **MAJOR.** A JSON reader returns an integer of any size, and `float(10**400)` raises
   `OverflowError`. A tariff rate of `10**400` is caught by `_as_float`, returned as `None`, and
   silently dropped from `fare.rates`; the fare is then recomputed from the remaining rates. On
   RD-0106 the recomputed fare falls from 15.76 to 9.20, the "overcharge" rises from 3.40 to 9.96,
   RD-5 enforces it, and a Judge refund of **SGD 9.96 reaches the party** with no gate firing.
   `main` crashes on the same input, so this branch turned a crash into money moving. The same
   integer as a breakdown component makes `breakdown_consistent` False (EV-3 evidence of an
   incorrect charge), and as a profile count it crashes the pack (`integer division result too
   large for a float`).
2. Voiding the fare is not enough on its own: with no recomputed fare there is no
   `difference_sgd`, so RD-5 has nothing to read and the refund still reaches the party. The
   operator ruled that **a route case whose record states a fare input it cannot read is held
   under ESC-2**.
3. The evidence layer's own arithmetic can overflow from finite inputs (a distance of `1e308`
   over an estimate of `1e-300`), and `round(inf, 2)` is `inf`, so Infinity reaches the pack,
   the prompts and the case file.
4. An intake answer is echoed verbatim into all three agents' prompts and the case file, so an
   unreadable number there reaches both. A party identifier (`party_id`, or the organiser
   shape's `rider_id`/`driver_id`) carries one into the pack.
5. A model reply whose amount is an integer too large for a float crashes the contract parse
   with `OverflowError` instead of failing the contract.

**The rule, widened.** A number is *unreadable* when it is present but cannot be read as a finite
float: NaN, Infinity, -Infinity, **or an integer too large for a float**. Everywhere round one
treats NaN as missing, an unreadable number is treated the same way.

`docs/policy.md` already carries the new text (the ESC-2 enforcement note and EV-1's fare
paragraph). Read both before you start.

**Target:** `tests/test_w22_unreadable_numbers.py` (40 tests), currently RED, goes green, and the
full suite (`/usr/bin/python3 -m unittest discover -s tests -t .`, **770 tests when done**) is
green. Round one's file `tests/test_w22_unproven_figures.py` must stay green.

**Do not edit anything under `tests/`, `tools/`, `data/` or `ui/`.** If a test looks wrong, stop
and ask.

## The contract, file by file

### `app/evidence/compute.py`

1. `_is_non_finite_number` (round one's helper) returns True for an unreadable number as defined
   above: a non-bool int or float whose `float()` either raises `OverflowError` or is not finite.
   Everything that already uses it (`_as_int`, the broken-rate and broken-component keys, the
   case-policy terms) then covers huge integers with no further change.
2. `_round` and `_round_up` return `None` for a value that is not finite, so a figure the layer's
   own arithmetic overflowed never reaches the pack. `_round_up` must also return `None` when
   scaling the value by `10 ** places` overflows.
3. A breakdown component sum that is not finite is `None`, and `breakdown_consistent` stays `None`.
4. `FareEvidence` gains `unreadable_inputs` (see `schema.py`). Fill it with `"rates.<key>"` for
   every broken tariff rate, sorted, followed by `"breakdown.<key>"` for a broken **promo**
   component (`promo_sgd`, `promo` or `discount_sgd`), sorted. Any other broken component is not
   a fare-formula input and is not listed. A record with no rates at all lists nothing.

### `app/evidence/schema.py`

- `FareEvidence.unreadable_inputs: List[str]`, defaulting to an empty list, after `notes`.
- Add `"unreadable_inputs"` to `_NON_CITABLE_KEYS`: a list of record defects is not evidence a
  ruling can rest on.
- `EVIDENCE_SCHEMA_VERSION` becomes `"1.4"`, with a comment line in the existing version history
  saying 1.4 added `fare.unreadable_inputs` (additive).

### `app/agents/judge.py`: ESC-2 widens again

On a route-deviation case, ESC-2 also fires when `pack.fare` is present and
`pack.fare.unreadable_inputs` is non-empty. It stays **one** gate entry named `"ESC-2"` whatever
combination fires.

- Summary part: `the fare inputs in the record could not be read`, joined with the other parts by
  `" and "`, ending ` (ESC-2)`. With only this clause the withheld event summary reads exactly
  `Judge withheld the ruling: the fare inputs in the record could not be read (ESC-2)`.
- Reason (notes): one ESC-2 entry naming each input as `fare.<input>` (so
  `fare.rates.per_km_sgd`), ending `(EV-1, ESC-2)`. It must not name `route.deviation_pct` or
  `fare.charged_sgd` unless those clauses also fired.
- No-show cases are never gated on it.

### `app/dispute.py`

1. `Dispute.intake` holds the intake answers with every unreadable number, **at any depth**
   (inside nested objects and lists), replaced by `None`. Key order is preserved; every other
   value is unchanged; a finite number survives.
2. `Dispute.profiles`: for each party block, an unreadable `party_id` or `id` becomes `None`.
   Leave the other profile fields alone (the evidence layer reads them). The organiser shape's
   `rider_id`/`driver_id` already maps to `party_id` before this runs; verify that, do not
   re-map it.
3. `raw` keeps the record exactly as filed. Do not clean it.

### `app/schemas.py`

`_require_number`: an integer too large for a float raises `ContractError` naming the field and
saying it must be a finite number, exactly like NaN. It must never raise `OverflowError`.

### Docs

- `docs/architecture.md`, **Components** table, Evidence layer row: an integer too large to read
  as a number also counts as missing, and so does a figure the layer's own arithmetic would
  overflow. The phrases `integer too large` and `overflow` must appear in that row.
- `docs/architecture.md`, **Gates enforced in code**, the ESC-2 row: add the unreadable fare
  input clause, naming `fare.unreadable_inputs`. The count stays "Eight gates".

## Allowed files

`app/evidence/compute.py`, `app/evidence/schema.py`, `app/agents/judge.py`, `app/dispute.py`,
`app/schemas.py`, `docs/architecture.md`. Nothing else. `docs/policy.md` is already done.

## Constraints

Standard library only. Python 3.9: no `match`, no `X | Y` unions. Run the full suite with
`/usr/bin/python3`. Commit in small commits when the suite is green.

## What you should see on the mock when you are done

**No corpus case moves.** `python3 -m app.eval --llm mock` gives exactly what it gives today:
organiser pack 11 of 18 matching, 14 of 18 decided without a human, 0 round-one stops; synth pack
10 of 17, 13 of 17, 0. If any case's outcome changes, stop and report it.

## Known limits, deliberately not fixed (do not report them)

The server's trip list and filing endpoint, the eval label text, and the config cap are out of
scope this round. RD-3's "escalate when no fare consequence can be computed" stays with the model
for a record that states no rates at all.

## Out of scope

The party page, the console, the server, the eval harness. Do not run the live model.
