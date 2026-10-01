# Session twenty, round three: impossible fare inputs go to a human

The review of round two found one more member of the same defect class. It is not a round-two
regression: `main` has it too. The operator ruled the fix on 2026-10-01 and declared this **the
last round on this class**: a further finding of the same kind becomes recorded residue unless it
moves money on a corpus case.

**The defect, reproduced.** Every guard so far refuses a number the record cannot *read*. A
number the record can read but that is *impossible* still reaches money. RD-0106 with a promo of
SGD 30 recomputes the fare as **-14.24**, reports a **33.40** "overcharge" on a **19.16** charge,
and RD-5 enforces it: a refund of SGD 33.40 reaches the party, while the honest refund of the
charge is withheld. A per-km rate of `-2.0` does the same (26.36). A surge of exactly `0` is read
as "no surge" (1.0) today and computed as though it were absent.

**The rule.** An impossible fare input is a record defect, exactly like an unreadable one. It
voids the recomputed fare with a note, and it is listed in `fare.unreadable_inputs`, so round
two's ESC-2 clause holds the case. No new gate, no new pack field.

`docs/policy.md` already carries the new EV-1 paragraph. Read it before you start.

**Target:** `tests/test_w22_impossible_fare_inputs.py` (20 tests), currently RED, goes green, and
the full suite (`/usr/bin/python3 -m unittest discover -s tests -t .`, **790 tests when done**) is
green, including both earlier session-twenty files.

**Do not edit anything under `tests/`, `tools/`, `data/` or `ui/`.** If a test looks wrong, stop
and ask.

## The contract: `app/evidence/compute.py`, `_build_fare`

1. **Impossible rates.** A rate in `rates` is impossible when it is negative, or, for the surge
   (`surge_multiplier` or `surge`), when it is zero or less. A rate of exactly 0 for any other
   key is a real, free component and is possible.
2. Any impossible rate makes **both** recomputations `None` (so `recomputed_sgd`,
   `recomputed_estimated_route_sgd`, `deviation_fare_delta_sgd`, `difference_sgd` and
   `difference_pct` are all `None`).
3. One note names every impossible rate, sorted, and contains the word `impossible`. Do not also
   add the "trip numbers needed to recompute were missing" note. The old zero-or-negative surge
   note and its constant go: the impossible-rate note replaces them.
4. **Negative result.** With every rate possible, a recomputed fare below zero can only come from
   a promo larger than the fare. If **either** recomputation (actual route or expected route) is
   below zero, both become `None`, because the same promo feeds both. Add one note containing
   `promo is larger than the fare`, and do not also add the "trip numbers needed to recompute
   were missing" note. A result of exactly zero is a free trip, not a negative fare.
5. **Listing.** `fare.unreadable_inputs` holds `"rates.<key>"` for every rate that is unreadable
   **or** impossible, each once, sorted; then round two's broken-promo entries; then, when the
   negative-result rule fired, `"breakdown.<key>"` for the promo under the name the record uses
   (`promo_sgd`, `promo` or `discount_sgd`, the first one present).

Do not change `app/agents/judge.py`: round two's ESC-2 clause already holds any route case whose
`fare.unreadable_inputs` is non-empty, and the tests require the withheld summary to read
exactly `Judge withheld the ruling: the fare inputs in the record could not be read (ESC-2)`.

## Docs

`docs/architecture.md`, **Components** table, Evidence layer row: add that an impossible input (a
negative rate, a surge of zero or less, or a promo larger than the fare) voids the fare the same
way. The words `impossible` and `negative rate` must appear in that row.

## Allowed files

`app/evidence/compute.py`, `docs/architecture.md`. Nothing else.

## Constraints

Standard library only. Python 3.9. Run the full suite with `/usr/bin/python3`. Commit in small
commits when green.

## What you should see on the mock when you are done

**No corpus case moves.** No corpus record has an impossible input (a test checks it).
`python3 -m app.eval --llm mock` gives exactly what it gives today: organiser pack 11 of 18
matching, 14 of 18 decided without a human, 0 round-one stops; synth pack 10 of 17, 13 of 17, 0.
If any case's outcome changes, stop and report it.

## Out of scope

Everything outside the two allowed files. Do not run the live model.
