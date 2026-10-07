# Session twenty-five brief — W29: NS-8, the no-show refund ceiling

**Read this whole brief before writing anything.** Work in this repository only. If a test
looks wrong, stop and ask rather than editing it: `tests/` is NOT yours to change this
session (one carve-out below).

## What you are building

A seventh money gate, `NS-8`, in `app/agents/judge.py` beside the six that exist. The defect
it closes (reproduced 2026-10-04 with a stub Judge): on a no-show dispute with a clean
record (NS-0202, fee SGD 6.61, driver arrival recorded so NS-6 cannot fire), a Judge ruling
"refund SGD 45.00" reached the parties with no gate except the SGD 50 autonomous cap. The
policy's no-show rules (NS-1..NS-5, `docs/policy.md` §4) never order more than the
recorded fee back to the rider, and a no-show record proves nothing owed to the driver —
but nothing in code enforced either bound. Same class as RD-4: the records prove a
ceiling; the model must not move more than the records prove.

**The gate (withhold, never rewrite — the human receives exactly what the Judge proposed):**

1. Scope: `dispute.category == CATEGORY_NO_SHOW_CHARGE` and the ruling is not
   `no action`. No action is never held by this gate. Route cases are untouched (RD-4 owns
   route money).
2. `compensation` on a no-show case is always withheld, whatever the amount.
3. A refund larger than the recorded fee (`cancellation.cancellation_fee_sgd` via the
   evidence pack) is withheld. Equal or below passes.
4. A fee that is missing or not a finite figure withholds any refund: the records then
   prove no ceiling either way. (The existing `_is_figure` helper in `judge.py` is the
   readability check; bools are not figures.)
5. Gate label: `"NS-8"`. It appends to `gate_failures` / `gate_summaries` in the same
   style as the existing gates, and the reasons follow the existing wording pattern
   ("NS-8: ...").

**A module-level helper is part of the contract** (the no-show counterpart of
`provable_refund_sgd`):

```python
def ns8_provable_refund_ceiling_sgd(pack: EvidencePack) -> Optional[float]:
```

Returns the recorded fee rounded to the cent, or `None` when the pack has no cancellation
block or the fee is not a recorded figure. The gate and tests import this by name.

Order within the gate block: compensation first, then the missing-fee branch, then the
above-fee branch — pick the shape that keeps each branch testable; all three reasons are
pinned by exact text in the tests (`tests/test_w29_no_show_refund_ceiling.py`).

## Acceptance tests (already written, currently RED)

`tests/test_w29_no_show_refund_ceiling.py` — 17 tests, three groups:

- `NS8Gate` — the run path on the real corpus case NS-0202 with a scripted Judge:
  refund 45.00 withheld (candidate intact, gate label in the notes and in the withheld
  event's `gates_failed`), refund 6.61 and 3.00 delivered, no-action delivered,
  compensation 5.00 and 0.50 withheld, and NS-8 never fires on the route case RD-0103.
- `NS8MissingFee` — a hand-edited record with the fee nulled
  (`cancellation_policy.cancellation_fee_after_wait` in the raw record): refund withheld,
  no action delivered.
- `NS8Docs` — the four docs that must carry NS-8 (see below), plus the policy enforcement
  paragraph.

Four existing test files were re-pinned for the new gate and are RED until the docs
change: `tests/test_w22_money_gates.py` (three exact `gates_failed` lists gain `"NS-8"`,
one gains it third: `["ESC-4", "NS-6", "NS-8"]`), `tests/test_w22_unproven_figures.py`
(non-finite fee rows gain `"NS-8"`; architecture count sentence becomes "Ten gates"),
`tests/test_w22_docs.py` (README paragraph: seven gates, NS-8 named; architecture table:
10 rows), `tests/test_w28_unproven_refunds.py` (architecture "Ten gates" + 10 rows;
README "seven gates" + NS-8). **Read these files, do not edit them** — they pin the exact
strings your doc edits must produce.

## Docs to update (the doc pins are the spec)

- `docs/architecture.md` — "Gates enforced in code": lead sentence "Nine gates" → "Ten
  gates", and one new table row after the NS-6 row, first cell naming NS-8, file
  `app/agents/judge.py`, naming `cancellation_fee_sgd` and `compensation` (see the pinned
  row shape in `tests/test_w29_no_show_refund_ceiling.py::NS8Docs`).
- `README.md` — the "Seven gates" paragraph (currently says "Six gates"): add NS-8 to the
  enumeration, keep "RD-4" present, count becomes seven.
- `docs/prompts.md` — "The seven gates" list (currently "The six gates"): add an NS-8
  bullet in the style of the RD-5/RD-4 bullets, beginning exactly
  `- **NS-8.** On a no-show case,`; and the two other gate-count sentences
  ("seven gates").
- `docs/policy.md` — the NS-8 section already exists (written with the RED commit); do
  not edit it.

## Files you may touch

- `app/agents/judge.py` (the gate + helper)
- `docs/architecture.md`, `README.md`, `docs/prompts.md` (the pins above)

Do NOT touch: `tests/`, `tools/`, `data/`, `docs/policy.md`, anything under `app/` other
than `agents/judge.py`. `app/eval.py` needs no change.

## How to verify (no paid provider; mock stays default)

```
env -u PYTHONPATH /usr/bin/python3 -m unittest discover -s tests -t .
```

- **1040 tests, all OK** when you are done (currently 22 failures + 3 errors, all in the
  files above — nothing else may go red).
- The scripted-Judge battery that matters is inside
  `tests/test_w29_no_show_refund_ceiling.py`; every one of its 17 tests must pass.

**What you should see on the stand-in when done** (`env -u PYTHONPATH /usr/bin/python3 -m
app.eval`, both packs): the numbers unchanged from main — organiser pack 11 of 18 matching,
11 decided without a human, 0 stops; synth pack 10 of 17, 10 decided, 0 stops. NS-8 holds
no corpus case (every mock no-show refund is within the fee); if the eval moves, the gate
is too wide.

## Standing rules

- Gates withhold; they never rewrite a ruling.
- The confidence threshold and the cap come from config, never hard-coded.
- Commit your work with a message naming W29. Do not run the paid provider.