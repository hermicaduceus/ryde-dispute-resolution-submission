# W47: build the local live-LLM copy

Status: the operator authorized the scoped local RED/brief/build commits, isolated Luna-max build, GLM 5.3 review and conditional verified merge on 2026-10-14. the planner installs this brief and the verified acceptance files in the build repository before creating the isolated worktree. The CodeBuddy session reads this committed copy. Push/publication, real Tencent app calls, key rotation and credential delivery are not authorized.

## Deliverable and boundaries

Build a local source package that starts the existing Ryde dispute-resolution system with the real Tencent ADP provider. It is for a private teammate rehearsal first. The public/judge release waits for separate publication and credential gates. Do not describe a local ZIP as an online demo link.

the operator selected CodeBuddy `gpt-5.6-luna`, effort `max`, and GLM 5.3 for independent review. The parent will verify the serving model from the actual session records. Do not substitute another model, launch subagents, or use another coding product.

Keep Python 3.9 compatibility and standard-library-only runtime. No installers, bundled executables, frameworks, new agents, policy changes, cloud purchases or hosting.

### Allowed production files

Create:

- `tools/launch_live.py`
- `start-live.bat`
- `start-live.command`
- `tools/package_submission.py`
- `docs/live-copy.md`

Edit only the intro sentence in `ui/start/index.html`, to this exact text:

> Runs on your computer with sample trips. The standard launcher uses an illustrative mock; the live launcher uses Tencent AI and needs private access keys.

Nothing else in that page changes. Preserve its navigation, head structure and styling. The old mock launchers remain the keyless default.

### Acceptance files, owned by the planner

- `tests/test_w47_live_launcher.py`
- `tests/test_w47_submission_package.py`
- `tests/browser/w47_live_launcher.cjs`
- `tests/test_w34_launcher.py`, with only the measured intro expectation change already applied before dispatch.

Do not edit these or any other test. No preservation hashes may be released. If a test is impossible or contradicts this brief, stop with the exact assertion and a proposed ruling. Do not silently repair the tests.

All `app/`, `data/`, policy, prompts, original launchers, existing UI files apart from that sentence, evidence, memory/settings files and unrelated tools remain byte-identical to the baseline. Do not rewrite `CODEBUDDY.md`, `.gitignore` or `.gitattributes`.

## Dispatch and Git protocol

1. Read this brief, `CODEBUDDY.md`, the four acceptance files, and definitions of the existing server/config helpers they exercise. Read HEAD at runtime. The historical prep baseline is `4adbbbf30085a1132ee2b8e832f292c4f95f3252`; it is not a literal HEAD requirement after the RED/brief commit.
2. Confirm the worktree is clean and the five new production paths are absent. Inspect the acceptance tests' exported helper interfaces and CLI/manifest assertions before choosing an implementation.
3. Read only this worktree and installed runtime libraries. Do not read the planning repository, other worktrees, the scratch/reference implementations, real `.env`/`.env.live` files, credentials or account stores. Synthetic credential fixtures created by the acceptance tests are permitted.
4. No cloud/app-model requests, external downloads, package installation, browser-account automation, merge, push, stash, reset, cleanup of another session, or broad deletion. Tests may use their synthetic fixtures and loopback listeners only. Never start a live Tencent server with actual keys.
5. The parent pre-authorizes scoped Read/Glob/Grep/Edit/Write/Bash tools through process-local CLI settings. A denial is a stop condition, not permission to find a bypass. Do not modify permanent settings.
6. If the operator has authorized the W47 build commit, stage only the six allowed production paths by name and commit only those. Never use `git add -A`, `git add .`, or commit tests/briefs. No merge or push. Report the branch commit and exact changed-path list.
7. Give the parent the commands, counts, failures/errors/skips, wrapper mode/line-ending results, outstanding limits and the next reproducible step. Do not claim final review or live access succeeded; those are parent/recipient gates.

## Live launcher contract

### Credentials and endpoint

- Default credential file is `<package-root>/.env.live`. Support explicit `--credentials PATH` and `--port PORT`. Default live port is 8030. Help must work without a credential file.
- Use the existing application env parser for the selected file. Validate a UTF-8 text sidecar before exporting it. Refuse unreadable/invalid encoding, malformed assignments, unsupported variable names, duplicate names, absent/blank/placeholder role keys, and invalid endpoint values. Errors must not echo file contents, values, endpoints or constructor exception text.
- Require `TENCENT_ADP_RIDER_APP_KEY`, `TENCENT_ADP_DRIVER_APP_KEY`, `TENCENT_ADP_JUDGE_APP_KEY`. The selected sidecar wins over stale process values. Do not read a legacy root `.env` or export arbitrary settings.
- Pin the destination to `https://wss.lke.tencentcloud.com/adp/v2/chat`. An optional `TENCENT_ADP_ENDPOINT` sidecar entry must equal that reviewed destination. The shipped `app/config.json` `llm.endpoint` must also match. Refuse alternatives before constructing a provider.
- Explicitly set the reviewed endpoint in this process before construction, including when the sidecar omits it. A stale inherited endpoint must not steer the client. Malformed URL parsing must return a plain refusal, not raise.
- Do not print credentials or put them on command lines. Do not write to application config, create keys or rotate them.

### Provider and server ownership

- Call the existing `app.server.make_server` with explicit `provider="tencent"`. No fallback to mock, config-provider inheritance or new pipeline.
- This launcher owns its own bound loopback server. Refuse an occupied port, even if the listener advertises the same application or is another live instance. Never reuse a listener or open its page as if it belonged to this process.
- Verify the bound server's in-process provider is Tencent before opening a browser. If wrong, close it and refuse. Readiness precedes browser launch.
- Open `/party/`; print operator-console and status URLs with the actual chosen port. A browser-opening failure must leave useful manual URLs, not silently kill the owned server.
- Keep the server in the owning process. Ctrl+C shuts it down and calls `server_close`; closing a browser tab does not. Redact provider startup errors with fixed value-free text.

### Wrappers

- Windows `start-live.bat`: CRLF, correct quoting for paths with spaces, package cwd, Python 3.9+ using `py -3` with an appropriate `python` fallback, and readable failure text.
- Mac `start-live.command`: executable mode, quoted package cwd, Python 3.9+ check, and invocation of the live helper. No global security changes.
- Do not modify or replace `start.bat`, `start.command` or `tools/launch.py`.
- There is no Windows execution claim yet. Actual new-live-launcher execution on the teammate's Windows machine is a later handoff gate.

## Source packager contract

- CLI selects `--repo`, an explicit committed `--revision`, required `--purpose rehearsal|submission`, and `--out`. Output filename is `ryde-live-<purpose>-<12-hex-source-revision>.zip`; the archive has that single root folder.
- Inventory the selected Git tree and read its blobs. Do not recursively ZIP the development folder or collect untracked local files. Refuse tracked modifications and ambiguous/invalid source revision.
- Require the live helper, both live wrappers, instructions and preserved source entry points in the selected revision. Validate wrapper modes/CRLF, not just filename presence.
- Refuse tracked credential paths case-insensitively, filled credential examples, detected secret-shaped content, escaping/looping symlinks, Git LFS pointers, malformed/nonportable paths, case-fold collisions and unsafe output destinations. Failure writes no archive, does not overwrite an existing archive and leaves no partial ZIP.
- Check disk identity for output containment, including existing parents and case aliases. Path spelling or `resolve()` alone is insufficient on the default Mac filesystem. Cover Windows-style backslashes, drive names, reserved names and trailing dot/space components.
- Omit and record permitted junk such as run output, caches, editor locks, local CodeBuddy settings and OS files. Do not silently omit a tracked credential and call the source safe.
- Scan paths and source content. Secret-test fixtures must keep identical runtime values without embedding literal scanner-triggering tokens/headers into their distributed test source. Do not weaken the scanner to package tests.
- Include `MANIFEST.json` with the tested schema: exact source revision, purpose, included path/mode/hash records, excluded path/reason records, counts and narrow scan limitations. Match the supplied tests' field and helper interfaces.
- Keep complete source, tests and evidence subject to the separate release gate. Do not perform a privacy/history scrub or claim the scan proves absence of every real credential. A parent-owned comparison against actual key bytes remains a distribution gate.
- Two packages from the same revision must have matching extracted inventories/content hashes. Preserve executable Mac mode and Windows CRLF in ZIP entries and after normal OS extraction.

## Instructions and filming handoff

`docs/live-copy.md` explains extraction, Python 3.9+, internet, the privately delivered `.env.live`, live versus mock entry points, the terminal's lifetime, printed URLs, manual commands and narrowly scoped OS script-warning remedies. No package or instructions carry actual keys.

The operator uses synthetic inputs, keeps run references/provider evidence, coordinates one live caller at a time across machines, and preserves locally saved runs across restarts. Describe real model waits and provider errors without promising an outcome. A decision record does not transfer money.

Explain the agreed no-show and above-cap rehearsal pair. Do not invite unlimited retries or silently broaden the two-rehearsal-filing allowance. Stop for the operator if the real result differs from the filming narrative; do not replace it with mock output or narrate a planned ending.

The accepted recording script is the planning-side `drafts/w26/demo-script.md`, target 6:30, delivered separately by the operator. `tools/deployment/demo-video-script.md`, target 7:25, is an older build-repository script retained in the complete-source ZIP. Its inclusion does not approve it for filming. State that it is an included source file, and that the accepted recording script is a separate teammate handoff. Do not remove the older source file or tell the recipient both scripts are outside the ZIP. Their filming edit must be settled before production footage.

Label shortened waits and saved-run replay honestly. Never film credentials or account consoles. A rehearsal package is private, not public-release clearance. Judge delivery waits for release scrub/history/secret checks, verified access, approved private credential channel and form requirements.

## Verification protocol

Use `env -u PYTHONPATH /usr/bin/python3 -B` on this Mac. The parent supplies an existing writable TMPDIR. Do not create files under `/tmp` or copy stale browser paths. Clear `W47_BASELINE_TREE` for builder checks; that opt-in baseline archive check belongs to the parent.

First record RED:

```sh
env -u PYTHONPATH -u W47_BASELINE_TREE /usr/bin/python3 -B -m unittest tests.test_w47_live_launcher tests.test_w47_submission_package tests.test_w34_launcher -v
```

Then implement only the allowed files and run that same command to GREEN. Report the two deliberately disabled baseline checks as skips rather than hiding them. No application network/model call is required.

A single full-suite discovery took over ten minutes in parent verification. Do not require it to fit one short foreground tool call. Run any broader builder regression checks in bounded module/class groups with the same interpreter and environment, record every group's result, and let the parent perform the authoritative single-process full suite with the browser/opt-in environment on a frozen branch archive. A timeout is not a test result. Stop rather than modifying code for tests you did not complete.

The parent re-aims mutation literals at the actual CodeBuddy implementation, requires each planted defect to cause an assertion failure with no test errors, checks frozen-file byte preservation and the real browser at narrow/desktop widths, then verifies the actual extracted branch ZIP. The reference's mutation search strings are not a battery for rewritten code.

### Measured prep evidence, not a future branch claim

On the combined scratch reference extracted from its own ZIP:

- Full suite: 1817 tests, zero failures/errors/skips.
- Unmodified application baseline plus the same acceptance files: 1817 tests, 116 expected failures, zero errors/skips. Breakdown: live launcher 61, packager 54, old intro expectation 1.
- Browser: 7 checks passed at 390px and 1280px, using mock runtime only.
- Planted defects: launcher 30, packager 19, parent additions 3. All 52 caught, no survivors or test errors. A separate equivalent-rewrite control correctly stayed green.
- Actual ZIP: 498 included source files plus manifest; one editor lock omitted. Every included hash/byte matched reference source; normal Mac extraction preserved executable mode/CRLF in a spaces-and-Unicode path.

After that run, parent archive inspection exposed incorrect handoff wording: the old 7:25 script is a build-side source file and is actually included. A new assertion first failed on the old instructions, then the candidate instructions were corrected without changing launcher/packager code. The corrected candidate subsequently passed the full extracted suite at 1818 tests, zero failures/errors/skips. Focused baseline RED was 174 tests with 117 expected assertion failures, zero errors/skips, exactly the prior 116 failures plus this instruction pin. Reverting the instruction correction failed the new pin with clean start/end controls. Runtime source bytes remained identical to the earlier mutation-verified implementation. Re-derive these counts on the actual build branch. The brief itself also adds a source file, so future archive counts must be derived, not copied from the earlier measurement. Parent evidence is a feasibility/pinning proof, not proof that the unbuilt production branch is ready.

## Stop conditions and completion

Stop for any unexpected file edit, conflict with a protected byte/hash, denied tool, wrong served model, exposure of a real credential, missing interface, need for paid app-model requests, or proposed policy/outcome change. Never bypass the gate.

Builder done means its allowed files are implemented, its focused tests are green, wrapper bytes/modes are correct, the source diff stays within the exact allowed list, and it reports honest regression coverage and a scoped branch commit. Parent full verification, GLM 5.3 review, live-account checks, real extracted-package filings, private delivery and new Windows execution remain separate gates. No push or credential handoff follows from builder completion.
