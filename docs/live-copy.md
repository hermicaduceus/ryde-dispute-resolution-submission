# Ryde local live copy

This is a local Ryde source copy, not an online demo link. Inspect `MANIFEST.json`'s `package.purpose`: a `rehearsal` package is private and is not public-release clearance, while a `submission` package still waits for separate release gates. It starts the existing Ryde dispute-resolution system locally with the real Tencent AI provider when the operator supplies private access through a sidecar.

## Extract and prepare

1. Extract the ZIP first. Keep the single top-level folder intact so `MANIFEST.json` stays beside the source tree.
2. Use Python 3.9 or newer. The runtime is standard-library-only; no installer or package download is needed.
3. The live run needs internet access to reach Tencent AI. It does not need CodeBuddy at runtime.
4. Receive `.env.live` through the agreed private credential channel and place it at the package root. It must contain the three role app keys, one each for the rider advocate, driver advocate and judge. The optional endpoint line is accepted only when it is the reviewed Tencent ADP destination. Never paste keys into a command line, a recording, a screenshot, a public issue or a source file.

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

Use synthetic inputs only. Coordinate one live caller at a time across machines, keep each run reference and its provider evidence, and preserve the local `runs/` directory across restarts. Real model waits can be several seconds per agent; provider errors are possible and must be reported as they occurred. Do not replace a failed live result with mock output or narrate a planned ending.

The agreed pair is one no-show rehearsal and one above-cap rehearsal using the supplied sample trips. Keep to the agreed two-rehearsal-filing allowance; do not invite unlimited retries or silently broaden it. The above-cap case demonstrates the human-review gate. If the real result differs from the filming narrative, stop for the operator and record the difference rather than changing the case, policy or outcome.

The accepted recording script is a separate teammate handoff: `drafts/w26/demo-script.md`, target 6:30. `tools/deployment/demo-video-script.md` is an included source file in the complete-source ZIP; it is an older build-repository script, not approval to use its 7:25 timing. Settle the filming edit before production footage. Never film credentials or account consoles.

## Package and release boundaries

The packager selects a committed Git revision, records included and excluded source entries in `MANIFEST.json`, and preserves the executable macOS wrapper and Windows CRLF bytes. A `rehearsal` package is private. A `submission` package still waits for the separate release scrub, history and secret checks, verified access, approved private credential channel and any required form fields. The pattern scan is narrow and is not proof that no real key exists; the parent-owned gate compares against the ACTUAL live key bytes. Do not include actual keys in any package, instruction or manifest.
