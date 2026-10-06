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

Every refusal exits 2, prints one line on stderr starting with `export_replay: `, and leaves
nothing in `--out`. The two snapshots must each hold exactly one run whose `dispute.json` trip
is `T-RD0109`, and it must be the same run id in both.

## The two replayed cases

- **NS-0202** — a no-show refund decided by the AI alone. The banner's "after" snapshot shows
  the ruling and the party's status page.
- **RD-0109** — an above-cap detour held for a human. The console opens on the held case
  (step 2 of the landing page, before the decision); step 3 shows the human's approval.

## After the export

Open `replay/index.html` in the exported site and walk the four steps in order. The banner on
every page switches between the before and after snapshots, and every `/api/` request is
answered from the recorded bodies under `replay/data/<snapshot>/` — nothing reaches a server.
