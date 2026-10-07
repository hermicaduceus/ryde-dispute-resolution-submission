# Build session four — brief

**Status at handoff: 2026-09-23.** Head `1a20311`. Suite 225 tests: **209 pass, 16 fail on
purpose** in `tests/test_organiser_reader.py`, which is this session's acceptance target.

Pre-flight:

```bash
cd ~/hermes-workspace/projects/ryde-build
codebuddy --version          # the CLI self-updates; a bad update bricked it once
git status --short           # expect empty
python3 -m unittest discover -s tests -t .    # expect 225 tests, 16 errors, all in test_organiser_reader
```

---

## Why this session exists

The organisers shared a sample dispute, `DISP-002` (a no-show charge dispute), in a JSON shape
that differs from our record format. The operator ruled 2026-09-23 that **the organisers'
shape is the reference**, and that our own corpus stays available as a swappable alternative.

The data half is done (rescue lane, `tools/` + `tests/` only). `data/` now holds two packs:

```
data/packs/
  ryde-synth-v1/          our 17 cases, our format, byte-identical to the old data/
    disputes/  ground-truth.json  pack.json
  organiser-style-v1/     the same 17 cases in the organiser shape + DISP-002 verbatim
    disputes/  ground-truth.json  pack.json
```

Each organiser-style case is a **twin** of its ryde-synth-v1 case: the same facts, the same
numbers, in the organisers' field names. `tests/test_organiser_pack.py` proves that on the
records. `pack.json` in the organiser pack lists the fields we added where the organiser shape
had no slot (route-deviation trip fields, `ryde_extensions`).

**What is missing is the reader.** `app/dispute.py` only understands our format, so every
organiser-style record fails with `dispute_id is required`. That is this session.

## The deliverable

Make `tests/test_organiser_reader.py` pass **without editing it**, and keep every other test
green. Concretely:

1. **`app/dispute.py` reads both formats.** Detect the format from the record itself: an
   organiser record has a top-level `dispute_ticket` object; ours does not. Map the organiser
   record onto the existing `Dispute` fields so the Evidence Pack and the agents need no
   change. Keep the mapping in one function, and document the organiser shape in the module
   docstring next to ours.
2. **`app/config.json` + `app/config.py` gain the dataset pack.** A `dataset_pack` key
   (default `"organiser-style-v1"`) and a resolved `dataset_pack_dir`
   (`data/packs/<name>`). An unknown pack is a `ConfigError` with a clear message.
3. **`app/cli.py` gains `--pack`.** `--dispute` accepts either a path (as today) or a bare
   dispute id, resolved as `<pack_dir>/disputes/<id>.json`. `--pack` overrides the config for
   one run. An unknown pack or id prints `error: ...` and exits 1.
4. **Update `README.md` and `docs/dataset.md`** so every command and path points at the pack
   layout (the old `data/disputes/...` paths no longer exist). Do not touch `docs/policy.md`.

## The mapping, field by field

Read `data/packs/organiser-style-v1/disputes/DISP-002.json` (the organisers' own record),
`NS-0201.json` and `RD-0101.json` (our twins) next to `data/packs/ryde-synth-v1/disputes/`
before writing anything. The twins show exactly where each of our fields went.

| `Dispute` field | Organiser source |
|---|---|
| `dispute_id`, `filed_by`, `filed_at` | `dispute_ticket.*` |
| `category` | `dispute_ticket.dispute_type` (passes through `normalise_category` as today) |
| `claim` | `ryde_extensions.claim` when present; otherwise `{"text": dispute_ticket.description}` with no amount |
| `intake` | `ryde_extensions.intake` when present, else `{}` |
| `trip` | from `trip_data`: ids, `requested_time`→`requested_at`, `pickup_time`→`pickup_at`, `dropoff_time`→`dropoff_at`, `estimated_*`, `fare`; `actual_route` from `gps_telemetry` **only for route cases** (lat, lng, timestamp→t); `service_type` from `ryde_extensions` |
| `cancellation` | from `trip_data` + `app_events` + `gps_telemetry`, see below; **absent** when the trip has no arrival, cancellation or boarding facts (OS-0301) |
| `chat_log` | `chat_logs`: `timestamp`→`t`, `content`→`text`, keep `sender`, **keep `type`** |
| `profiles` | `rider_profile` / `driver_profile`: `rider_id`/`driver_id`→`party_id`, `total_trips`→`trips_completed`, `avg_rating`→`rating`, `dispute_history.total_disputes`→`disputes_total`, `dispute_history.upheld` (rider) / `upheld_against` (driver) →`disputes_upheld`; **keep `fraud_flags`** |

The cancellation block is where a wrong mapping changes rulings. Rules:

- `driver_arrived_at` ← `trip_data.driver_arrival_time`; `wait_started_at` ←
  `trip_data.driver_wait_start`.
- `cancelled_at` ← `trip_data.cancellation_time`, **or** `trip_data.rider_boarded_time` when
  the trip went ahead (NS-0207, a waiting fee). `cancellation_fee_sgd` ←
  `trip_data.cancellation_fee` or `trip_data.waiting_fee`.
- `matched_at` ← the timestamp of the `app_events` entry with `event_type`
  `"driver_assigned"`. **Never fall back silently to the booking time**: the Evidence Pack
  already flags a proxy anchor, and inventing one here would hide it (the NS-1 defect of
  2026-09-21 was exactly this).
- `driver_marked_no_show` ← `trip_data.cancellation_reason == "rider_no_show"`.
- `rider_claims_driver_absent` ← `ryde_extensions.rider_claims_driver_absent` when present;
  for a record without extensions (DISP-002) use `dispute_type == "no_show_charge"` and
  `filed_by == "rider"`: a rider disputing a no-show charge is contesting it.
- `pickup_point` ← `trip_data.pickup_location` (lat, lng).
- `driver_gps_at_arrival` ← the `gps_telemetry` row whose `status` is `"arrived"`. **If there
  is no such row, leave the field out.** Do not substitute the pickup point or the last row:
  a missing position is what escalates NS-0205, and a guessed one would rule it.
- `case_policy` ← the record's top-level `cancellation_policy`, passed through untouched. The
  Evidence Pack must carry it on its cancellation block as `cancellation.case_policy`
  (a small, additive change in `app/evidence/`), so the agents see which terms govern the
  case: DISP-002 carries the organisers' 5 / 8 minute terms, our cases carry Ryde's 3-minute
  terms.

The profile block of the Evidence Pack must also carry `fraud_flags` (additive; `None` where
the record has none).

## Rules for this session

- **Gates live in code, not in prompts.** Do not touch the confidence gate or the SGD 50 cap
  in `app/agents/judge.py`.
- **Do not edit anything under `tests/`, `tools/` or `data/`.** Those are the other lane's.
  If a test looks wrong, stop and say so; do not change it to pass.
- **A fix is not done until a test fails when it is reverted.** The acceptance tests already
  exist; after it passes, show one mapping line reverted turning a named test red.
- Commit in small steps, each with the suite result in the message.
- On any conflict with `docs/statement-extract.md`, stop and ask rather than guess.

## Done means

```bash
python3 -m unittest discover -s tests -t .      # 225 tests, OK
python3 -m app.cli --pack organiser-style-v1 --dispute DISP-002 --out runs/
python3 -m app.cli --pack ryde-synth-v1 --dispute RD-0109 --out runs/   # still withheld
```
