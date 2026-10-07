# Replay export: recording day

The public link is a static replay of real saved runs, labelled honestly as a replay with its
recording date. `tools/export_replay.py` records it: for each snapshot it starts the real
`app.server` on a throwaway copy, GETs every URL the site needs, saves each 200 body
byte-for-byte, copies `ui/` with the shim line added to every page, and writes the replay shim
and landing page with their placeholders filled. Nothing in `app/` or `ui/` changes, the input
folders are never modified, and no model is called.

## The command

```sh
python3 tools/export_replay.py \
  --before /path/to/saved-runs-before \
  --after /path/to/saved-runs-after \
  --recorded-on 2026-10-06 \
  --out /path/to/replay-site \
  --secrets-file .env
```

- `--before DIR` — the saved-runs folder as it stood **before** the human decision.
- `--after DIR` — the same folder copied and updated **after** the human decision.
- `--recorded-on YYYY-MM-DD` — the recording date, exactly `YYYY-MM-DD`; it is printed in the
  banner and on the landing page.
- `--out DIR` — the output site. It must be missing or empty; an existing non-empty folder is
  refused and left untouched.
- `--allow-mock` — required when any replayed run's `run.started` event says
  `"llm_provider": "mock"`. It also prefixes the banner with `TEST REPLAY (mock model). `.
  A real recording omits it.
- `--secrets-file PATH` — the file scanned for secret values (length >= 8) before anything is
  published; defaults to `.env` at the repository root. A missing file means no secrets to check.
  Each value is matched in every form it can ship in: raw, JSON-escaped (ASCII and not),
  HTML-escaped and percent-encoded.

Every refusal exits 2, prints one line on stderr starting with `export_replay: `, and leaves
nothing in `--out`.

## Path refusals

`--out`, `--before` and `--after` are resolved before anything runs, so symlinks and `..` cannot
hide a collision. `--out` may not equal or sit inside `--before`, `--after`, the repository's
`ui/` folder or `tools/replay/`, and `--before` and `--after` may not resolve to the same folder.
A missing `--out` outside those trees is created; a sibling folder whose name only starts with an
input's name (`before-site` next to `before`) is fine.

## The provider gate

Without `--allow-mock`, the exporter reads **every** `run.started` event of every replayed run in
both snapshots. A run is mock when any of its payloads says `"llm_provider": "mock"` and gets the
existing mock refusal. A run whose provider could not be read — no `events.jsonl`, no
`run.started` event, a `payload_ref` that is missing, empty or escapes the run folder, a payload
that is missing or not a JSON object, or an `llm_provider` that is missing or not a non-empty
string — refuses before anything is recorded:

    export_replay: the model provider of run(s) <ids> could not be read; pass --allow-mock to export a test replay

## The two replayed cases

- **NS-0202** — a no-show case the AI decided alone (trip id `T-NS0202`). The banner's "after"
  snapshot shows the ruling and the party's status page.
- **RD-0109** — an above-cap detour held for a human (trip id `T-RD0109`). The console opens on
  the held case (step 2 of the landing page, before the decision); step 3 shows the human's
  approval.

Each snapshot must hold exactly one run for each trip id, and it must be the same run id in
both. Otherwise the export refuses.

## The landing steps are built from the saved runs

Steps 1-3 of `replay/index.html` are read from the recorded `GET /api/review/<run>/case` bodies,
so the page states what the replay shows, not a fixed claim. Every step text is HTML-escaped
when it is written. A ruling or proposal is phrased from its `action` and
`recommended_amount_sgd`; the human decision from its `action` and `amount_sgd`. When the after
snapshot holds no decision the third step reads `No human decision was recorded`.

## After the export

Open `replay/index.html` in the exported site and walk the four steps in order. The banner on
every page switches between the before and after snapshots, and every `/api/` request is
answered from the recorded bodies under `replay/data/<snapshot>/` — nothing reaches a server.
