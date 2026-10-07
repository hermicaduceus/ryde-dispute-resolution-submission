# Build session five — brief

**Status at handoff: 2026-09-23.** Head `65dc322`. Suite 246 tests: **the only failures are in `tests/test_input_integrity.py`** (30 failures + 2
errors, counted per subtest), which is this session's acceptance target.

Pre-flight:

```bash
cd ~/hermes-workspace/projects/ryde-build
codebuddy --version          # the CLI self-updates; a bad update bricked it once
git status --short           # expect empty
python3 -m unittest discover -s tests -t .    # expect 246 tests, failures only in test_input_integrity
```

---

## Why this session exists

A cross-family review of session four found five defects in how records are read. Every one
was reproduced before being written down. None changes an outcome on the 18 shipped records,
but each one does on a record the organisers could plausibly send. The rule behind all of
them is the Evidence Pack's own contract (`app/evidence/compute.py` docstring): **a field the
agents argue from is either right, or null with a note saying why. A plausible wrong number is
the worst of the three**, because the agents treat pack fields as established fact.

The test file's docstring lists the five findings. Read it first.

## The deliverable

Make `tests/test_input_integrity.py` pass **without editing it**, and keep every other test
green. The tests pin behaviour, not structure: where to put a helper is your call.

### 1. MAJOR — an unusable route point voids the distance (both record shapes)

Today `_build_route` in `app/evidence/compute.py` skips any leg whose haversine is `None` and
sums the rest, so RD-0101 with one broken point reports 16.67% instead of 50%, with no note.
**Operator ruling (2026-09-23, option a):** if ANY point in `actual_route` is unusable (not an
object, lat or lng missing, non-numeric, non-finite, or out of range), the trace has an
**unknown** length:

- `route.actual_distance_km`, `deviation_km` and `deviation_pct` are `None`;
- a note says which point was unusable, containing the word `unusable`;
- nothing downstream (fare recomputation) uses a distance from that trace.

Do **not** fall back to a stated `trip.actual_distance_km` when a trace is present but broken:
EV-1 prefers the trace, and a broken trace is a finding, not an absence.

### 2. MAJOR — ESC-2 is enforced in code for route cases

A route-deviation case whose `route.deviation_pct` is `None` is **withheld** by the Judge
under gate id `"ESC-2"`, beside the existing confidence gate and the SGD 50 cap
(ESC-4) in `app/agents/judge.py`. Same mechanics as the other two: the ruling is still
produced and kept as `withheld_candidate`, the parties get `UNDER_REVIEW_MESSAGE`, and
`gates_failed` names `"ESC-2"`. If several gates fail, all are listed.

Scope it exactly: **route-deviation cases only.** A no-show with no recorded arrival must NOT
be caught, because there the missing arrival IS the evidence (NS-4, NS-0204). RD-0108 (no
estimated distance) is the existing corpus case this gate now correctly withholds; its label
has always been `escalated`.

Do not change the confidence threshold or the cap, and do not move either gate.

### 3. MAJOR — `rider_claims_driver_absent` is never inferred

In `app/dispute.py`, the organiser reader currently sets it to `True` for any rider disputing
a no-show charge when the record has no `ryde_extensions`. Remove the inference: take it from
`ryde_extensions.rider_claims_driver_absent` when present, otherwise leave it **unset** so the
pack field is `None`. The rider's own words stay in `claim.text` for the Advocates. This was a
defect in the session-four brief, not in how it was implemented.

### 4. MINOR — `filed_by` is required and never defaulted

Both shapes: trim and lower-case the value; it must then be `"rider"` or `"driver"`, else raise
`DisputeError` naming the bad value. A missing key is also an error. Today both are silently
relabelled `"rider"`.

### 5. MINOR — unusable pickup or arrival coordinates are called unusable

In `_build_cancellation`, distinguish **absent** (block missing: keep today's note) from
**present but unusable** (block there, coordinates fail `haversine_km`): the distance stays
`None`, and the note says the coordinates were `unusable`, never that the position was absent.

### 6. MINOR — both fees survive

Add `waiting_fee_sgd` to the cancellation evidence (`app/evidence/schema.py`, additive; bump
`EVIDENCE_SCHEMA_VERSION` 1.2 → 1.3). In the organiser reader, map `trip_data.waiting_fee` to
it. `cancellation_fee_sgd` keeps today's value for the twin property (the cancellation fee if
present, else the waiting fee), and when a record carries **both**, the pack carries both and a
note says `both` fees were recorded. Our own shape has no waiting-fee field; `waiting_fee_sgd`
is `None` there, and `tests/test_organiser_reader.py` must stay green.

## Rules for this session

- **Gates live in code, not in prompts.** ESC-2 is a Python gate, not a prompt instruction.
- **Do not edit anything under `tests/`, `tools/` or `data/`.** If a test looks wrong, stop and
  say so; do not change it to pass.
- **Update `docs/policy.md` only where the code now enforces a rule it describes** (ESC-2's
  enforcement note, EV-1's broken-trace case). No other policy changes.
- **A fix is not done until a test fails when it is reverted.** After the suite is green,
  revert the ESC-2 gate and one other fix, name the tests that turn red, restore both.
- Commit in small steps, each with the suite result in the message.

## Done means

```bash
python3 -m unittest discover -s tests -t .      # 246 tests, OK
python3 -m app.cli --pack ryde-synth-v1 --dispute RD-0108 --out runs/   # withheld, ESC-2
python3 -m app.cli --pack organiser-style-v1 --dispute DISP-002 --out runs/   # still ruled
```
