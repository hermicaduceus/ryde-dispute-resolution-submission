# Ryde local live copy

This is a local Ryde source copy, not an online demo link. Inspect `MANIFEST.json`'s `package.purpose`: a `rehearsal` package is private and is not public-release clearance, while a `submission` package still waits for separate release gates. It starts the existing Ryde dispute-resolution system locally with the real Tencent AI provider when the operator supplies private access through a sidecar.

## Extract and prepare

1. Extract the ZIP first. Keep the single top-level folder intact so `MANIFEST.json` stays beside the source tree.
2. Use Python 3.9 or newer. The runtime is standard-library-only; no installer or package download is needed.
3. The live run needs internet access to reach Tencent AI. It does not need CodeBuddy at runtime.
4. Use an explicitly approved private-access handoff. Receive `.env.live` through the agreed private credential channel and place it at the package root. An explicitly approved private teammate copy may already include it; that does not make the copy safe to forward or publish. The sidecar must contain the three role app keys, one each for the rider advocate, driver advocate and judge. The optional endpoint line is accepted only when it is the reviewed Tencent ADP destination. Never paste keys into a command line, a recording, a screenshot, a public issue or a source file.

The live launcher validates the UTF-8 sidecar before startup and refuses missing, blank, placeholder, duplicated or unsupported assignments. The standard `start.command` and `start.bat` remain the keyless mock entry points. They are useful when no private sidecar is available. The live entry points are `start-live.command` and `start-live.bat`; they explicitly select Tencent and never fall back to the mock.

## Start the local copy

On macOS, double-click `start-live.command`. If Finder warns about the script, use the narrow, local remedy **Open Anyway** in the file's context menu or Privacy & Security prompt; do not weaken global security settings. From a terminal, the equivalent manual command is:

```sh
python3 tools/launch_live.py
```

On Windows, double-click `start-live.bat`. It tries `py -3`, then `python`, and checks for Python 3.9 or newer. If Windows shows its script warning, use the file-specific **Run anyway** choice only after confirming that the ZIP came through the agreed private channel; do not change a machine-wide policy. The launcher changes to the package folder, so paths containing spaces remain usable.

The terminal owns the server process. Keep it open while filming or rehearsing; Ctrl+C stops the server and frees its port. Closing a browser tab does not stop it. The default live port is 8030, and an explicit port or credentials path can be supplied manually:

```sh
python3 tools/launch_live.py --credentials /private/path/.env.live --port 8030
```

The launcher prints the actual party page, operator-console URL and party status URL. It opens the party page only after its own loopback server answers. If the browser cannot be opened, use the printed URLs manually. A port already in use is refused rather than reused. The private sidecar is not printed in startup errors.

The mock route remains available for a keyless check:

```sh
python3 tools/launch.py
```

Do not describe that mock check as a live Tencent run. The supplied live launcher selects the real provider for this handoff; the existing raw `app.server` and `app.cli` entry points can also select Tencent when invoked with their provider options. A decision record does not transfer money.

## Rehearsal handoff

Use synthetic inputs only. Coordinate one live caller at a time across machines, keep each run reference and its provider evidence, and preserve the local `runs/` directory across restarts. Real model waits can be several seconds per agent; provider errors are possible and must be reported as they occurred. If a recording shortens a model wait, label it `Waiting time shortened`. Do not replace a failed live result with mock output or narrate a planned ending.

The agreed pair is one no-show rehearsal and one above-cap rehearsal using the supplied sample trips. The approved private teammate allowance is up to about 30 filings in total, not 30 per restart. This is recipient-specific, not permission for judges or public users to use the same access. Coordinate rehearsal outside another person's filming window; do not invite unlimited retries or silently broaden the allowance. The above-cap case demonstrates the human-review gate. If a saved run is shown, label the sequence `Replay of saved run` with its date so it cannot look like a fresh uninterrupted live interaction. If the real result differs from the filming narrative, stop for the recording coordinator and record the difference rather than changing the case, policy or outcome.

The accepted recording script is a separate teammate handoff, identified privately as `drafts/w26/demo-script.md`; it is not a file in this repository or source ZIP. Its current targets are about 6:05 for the demo section and about 7:30 with the teammate's business slides. These are planning targets; time the actual edit. `tools/deployment/demo-video-script.md` is an included source file in the complete-source ZIP; it is an older build-repository script, not the current filming authority. Use the supplied accepted script without replacing the active filming copy. Never film credentials or account consoles.

## Package and release boundaries

The packager selects a committed Git revision, records included and excluded source entries in `MANIFEST.json`, and preserves the executable macOS wrapper and Windows CRLF bytes. Public source packages must not contain keys. A `rehearsal` package is private and is not public-release clearance; a `submission` package still waits for the separate release scrub, history and secret checks, verified access and required form fields. The pattern scan is narrow and is not proof that no real key exists; a separate release gate compares source and history against the actual live key bytes.

The explicitly approved private teammate copy is a separate recipient-specific derivative, not an output containing keys from the source packager. If its `.env.live` sidecar is included for that private handoff, keep it outside Git and never forward or publish it. That exception does not authorize a key-bearing copy for judges. Any other recipient needs a separately approved recipient, channel, key lifetime and usage budget. No keys belong in public instructions or manifests. This guide does not approve a new delivery, credential change or release.
