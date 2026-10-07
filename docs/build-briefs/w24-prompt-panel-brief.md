# W24 build contract: the console's "What each agent was asked" panel

Prepared against main `023d2ccb7e4897b02d8828009a00097bcb220a7f` (full suite 1190 OK). the operator rulings in force (2026-10-06): R1(a) the console deep link `?run=<run_id>` is in scope; R2(a) and R3(c) belong to the sibling lane; R5(a) `ui/styles.css` is untouched. This is a read-only view: no agent, model, pipeline, schema, evidence, dispute or policy code changes.

## Allowed files

- `app/prompt_view.py` (new)
- `app/server.py`
- `ui/index.html`
- `ui/app.js`
- `tests/test_console_rebrand.py` and `tests/test_w15_feedback.py`, ONLY the carve-out lines listed below

Do not modify any other test, tools, data, configuration, `docs/`, `ui/styles.css`, `ui/party/*`, any other app module, policy, labels or saved runs. `app/agents/`, `app/llm/`, `app/evidence/`, `app/pipeline.py`, `app/schemas.py`, `app/dispute.py` and `app/policy.py` are byte-frozen by test. If a test looks wrong, stop and ask. No live model calls, credentials, provider changes, or paid verification.

## Required change

### `app/prompt_view.py`: `build_prompt_view(run_dir: Path, policy) -> dict`

Rebuild each agent's `system_prompt` and `user_prompt` by calling the UNCHANGED builders (`RiderAdvocate`/`DriverAdvocate` `system_prompt()`/`user_prompt(dispute, pack)`, `Judge.system_prompt()`/`user_prompt(dispute, pack, rider_case, driver_case)`) on objects reconstructed from the run's stored payloads, with the `policy` passed in (the server passes `state.policy`, the policy it loaded). Wrap them in `app.llm.base.LLMRequest(agent=..., system_prompt=..., user_prompt=...)` and compare `.fingerprint()` to the stored `llm.request_fingerprint`. Feasibility is proven on BASE: all fingerprints rebuild exactly for ruled, withheld and needs_info runs with no edit to frozen code.

- Sources: the dispute from the `dispute.filed` payload through `app.dispute.parse_dispute`; the pack from the `evidence.pack_built` payload; each advocate's case and recorded fingerprint from the `advocate.case_submitted` payload whose event `from` is that agent; the Judge's recorded fingerprint from the `judge.ruling_issued` payload's `ruling` or the `judge.ruling_withheld` payload's `withheld_candidate`. Find payloads by event type and sender, never by sequence number: on a needs_info stop the driver's case is payload `0008`, not `0007`.
- Light stand-ins are allowed in the new module: a pack object exposing `to_dict()` and `field_refs()` (the same citable-ref walk as `EvidencePack.field_refs`, sorted), and a case object exposing `to_dict()` returning the stored payload. The Judge's user prompt embeds the stored advocate cases, so tampering an advocate's stored fingerprint also changes the Judge (pinned).
- Never call a model (tests patch `MockLLMClient.complete` and `TencentLLMClient.complete` at class level and require zero calls) and never write anything (tests digest the whole output folder before and after).

### `GET /api/review/<run_id>/prompts` in `app/server.py`

Resolve the run with the existing `_resolve_run_dir` (404 for unknown, malformed or traversal ids, e.g. `%2E%2E`, `..%2F..%2Fetc`, `a%2Fb`). Answer 200 with `{"run_id": str, "agents": [entry, entry, entry]}` in the order rider_advocate, driver_advocate, judge, and never a 500 (an empty run folder may answer 200 or 404).

```
entry = {
  "agent": "rider_advocate" | "driver_advocate" | "judge",
  "label": "Rider Advocate" | "Driver Advocate" | "Judge",
  "status": "match" | "changed" | "not_called" | "unavailable",
  "recorded_fingerprint": str | null, "rebuilt_fingerprint": str | null,
  "summary": {
    "role": exact strings:
      rider:  "Argues the rider's side from the Evidence Pack and the policy."
      driver: "Argues the driver's side from the Evidence Pack and the policy."
      judge:  "Weighs both cases and issues one ruling. Python gates decide whether it reaches the parties."
    "hard_rules": the 4 numbered rules of app.agents.base.HARD_RULES, each joined to one line with
                  single spaces, numbering kept ("1. Never do arithmetic. Every number ... Evidence Pack. If ..."),
    "case_facts": {"evidence_sections": [non-null top-level pack sections among route, duration, fare,
                   cancellation, filing, chat, profiles, IN PACK ORDER (the pack puts filing last)],
                   "citable_refs": int (count of the pack's citable refs),
                   "form_answers": int (number of entries in the parsed dispute's intake, blank answers included),
                   "claim_amount_sgd": number | null (the parsed Dispute.claim_amount_sgd)},
    "advocate_positions": null for advocates; for the Judge
                   [{"side": "rider", "outcome": str, "amount_sgd": number|null},
                    {"side": "driver", "outcome": str, "amount_sgd": number|null}]
                   from the stored advocate cases' requested_outcome / requested_amount_sgd,
    "policy": {"rule_count": len(policy.rule_ids()) of the policy passed in, "source": "docs/policy.md"},
    "asked_to_return": list(OUTPUT_SCHEMA keys) of that agent class, in schema order },
  "system_prompt": str | null, "user_prompt": str | null }
```

Status rules: `match` = rebuilt equals recorded; `changed` = both present and different (the prompts shown are today's rebuilt ones); `not_called` = the agent never ran (out-of-scope routing: no pack built, routed to human review; or the Judge on a needs_info stop: no deliberation started), with both fingerprints and both prompts null; `unavailable` = a payload that agent's rebuild or recorded fingerprint needs is missing, corrupt or not an object, with `rebuilt_fingerprint` and both prompts null. Scope of a broken payload: dispute or pack payload takes all three; one advocate's case takes that advocate and the Judge; the ruling payload takes the Judge only. A corrupt `events.jsonl` still answers 200 with legal statuses. A Judge model failure answers `not_called` or `unavailable` for the Judge (either is accepted). For `not_called` and `unavailable`, `summary` is still present with exact `role`, `hard_rules`, `policy` and `asked_to_return`; `case_facts` and `advocate_positions` are not pinned there.

### Console (`ui/index.html`, `ui/app.js`; `ui/styles.css` unchanged)

- New `<section id="prompts-section" class="story-section" aria-labelledby="prompts-title">` between `#evidence-section` and `#claims-section`, containing `<h2 id="prompts-title">What each agent was asked</h2>` and `<div id="prompts-content"></div>`. It carries NO `section-index` (the existing 01-06 stay as they are). Every class in the new markup and in the rendered panel must already exist in `ui/styles.css`.
- `renderCase(...)` clears `#prompts-content` synchronously and requests `GET /api/review/<case_file.run_id>/prompts` (the case file's own `run_id`, not the queue row's). One `<article>` per agent in contract order, its first heading = label; the summary as a `<dl>` (its text carries the role, every hard rule line, every `asked_to_return` key and, for the Judge, both advocates' outcomes); full text as `<details><summary>Show full text</summary><pre>` system prompt + `"\n\n"` + user prompt `</pre></details>`, one per agent with text, none for an agent without text. In a real browser the full text must stay inside its card (wrap, or scroll inside itself), with no page overflow at 390 px.
- Badge text, exact: match -> `"Matches what was sent (fingerprint " + first 8 chars + ")"`; changed -> `"The prompts have changed since this run. Showing today's version."`; not_called -> `"This agent was not called in this run."`; unavailable -> `"Not available for this run."`.
- Fetch failure, no server, a non-OK status, or an answer whose `agents` is not an array -> `#prompts-content` text is exactly `"Not available: open this case through the local server."`.
- Stale-response guard: one settle path consulting a generation counter. Opening case 2 before case 1's prompts return never renders case 1's panel, on success OR failure, and a stale success cannot replace case 2's current failure.
- R1(a) deep link: on page load, `?run=<id>` that matches `^[A-Za-z0-9._-]{1,128}$` (after URL decoding) is opened through the same path as a queue open (`openCase`), so a withheld run also gets its decision form; an invalid id sets `#load-status` to exactly `"Unknown run."`, requests neither `/case` nor `/prompts`, and leaves `#case-workspace` hidden. No `?run` opens nothing.
- The fake-DOM driver gives `app.js` `window.location` (search, pathname, hash, href), a global `location` (the same object), `URLSearchParams`, `URL`, `fetch`, `setTimeout`/`clearTimeout`; read the query through any of them.

Party safety: no party route (`/api/disputes*`, `/api/demo/*`, `/api/trips`) may carry `system_prompt`, `user_prompt`, `HARD RULES`, `Never do arithmetic`, `POLICY DOCUMENT`, `OUTPUT SCHEMA`, `CITABLE EVIDENCE REFS` or `/prompts`; no file under `ui/party/` may mention `prompts` outside comments.

## Acceptance tests

The planner transfers only these new files into the builder worktree:

- `[USER_HOME]/.hermes/cache/scratch/w24-prep-20261006/tests/test_w24_prompt_panel.py` -> `tests/test_w24_prompt_panel.py`, SHA256 `31efc92273e62edbdee289f49ea7de0d5271b7321993070591db517e7fa77e84`
- `[USER_HOME]/.hermes/cache/scratch/w24-prep-20261006/tests/browser/w24_prompt_panel.cjs` -> `tests/browser/w24_prompt_panel.cjs`, SHA256 `ec6cfb27c98f1b57faadd290574b32cbbdf66dbdf90206813617752819a8d428`

54 tests: route and module (11), summary (6), unavailable/never-500 (8), read-only and no-model (3), party safety (3), runtime and stylesheet freeze (2), console markup (4), fake-DOM panel driver (16), and one real-browser test that runs the `.cjs` against the real server on an ephemeral port only when `PUPPETEER_MODULE` and `BROWSER_EXECUTABLE` are set (the planner runs it; it skips otherwise). Nine pass on BASE because they pin behaviour the change must PRESERVE: the 01-06 section numbers, no party page mentioning prompts, no deep link opening nothing, the runtime freeze, the stylesheet freeze, 404 for unknown/traversal ids, an empty run folder never a 500, and the two party-route leak checks. The rest are intentionally RED.

```sh
env -u PYTHONPATH /usr/bin/python3 -B -m unittest tests.test_w24_prompt_panel -v
env -u PYTHONPATH /usr/bin/python3 -B -m unittest discover -s tests -t .
```

## Hash-pin carve-outs (the sole permitted test edits)

These pin the bytes or ids of files the contract must edit; re-baseline them to YOUR final bytes, nothing else in those files:

1. `tests/test_console_rebrand.py:28` `APP_JS_SHA` -> sha256 of your `ui/app.js`.
2. `tests/test_console_rebrand.py:30-40` `CONSOLE_IDS` -> add exactly `"prompts-section", "prompts-title", "prompts-content"`.
3. `tests/test_w15_feedback.py:25` `FROZEN['ui/index.html']` -> sha256 of your `ui/index.html`.
4. `tests/test_w15_feedback.py:26` `FROZEN['ui/app.js']` -> sha256 of your `ui/app.js`.

`app/server.py` has no byte pin. `docs/` needs no change: no doc test enumerates app modules or routes (proved green on the reference with no doc edit).

## Measured proof

Independent RED and REF trees are under `[USER_HOME]/.hermes/cache/scratch/w24-prep-20261006/`. REF is disposable preparation only; the planner audits and deletes it before dispatch. No REF implementation code is transferred to the builder.

- Step 0 feasibility: `spike.py` over mock CLI runs of NS-0202 (ruled), RD-0109 (withheld), RD-0101 with a blank intake answer (needs_info) and OS-0301 (out of scope): 8 rebuilt fingerprints, 8 matches, 0 mismatches; Judge not called on needs_info; no agent called out of scope.
- Unchanged RED (BASE + the two files): focused 54 tests, 59 assertion failures (44 test methods, subtests counted), 0 errors, 1 skipped. Full suite 1244 tests, the same 59 failures, 0 errors, 1 skipped. Real-browser test on BASE: fails (no panel renders).
- Disposable REF: focused 54 OK (1 skipped); full 1244 OK (1 skipped) after the four carve-outs; real-browser test OK, 6 cases (desktop and 390 px deep link, stale success, stale failure, invalid deep link, server gone).
- Mutation battery: `mutations.json`, 58 unique literal edit sets against REF, each applying exactly once. 58 RED, 0 survivors, 0 misapplied; every row fails the focused W24 file by assertion with 0 errors; baseline restored GREEN (54 focused, 1244 full). Browser mini-battery: 5 of 5 RED by assertion (stale guard, failure string, deep-link anchor, unstyled full text, summary text), baseline GREEN.
- Evidence: `logs/`, `battery-results.jsonl`, `logs/battery/`, `logs/browser-battery/`, `proof-results.json`, `artifact-hashes.json`.

Re-aim literal mutations at the independent shipped source before post-build verification. Do not treat reference-targeted literals as shipped proof.

## What should be seen when done

Focused suite: 54 tests OK (1 skipped without browser variables). Full suite at this baseline with only W24 transferred: 1244 OK (1 skipped). With the sibling's RED files also present, the only failures are the sibling's. The agent, model, pipeline, schema, evidence, dispute and policy sources and `ui/styles.css` are byte-identical to BASE. Opening the withheld RD-0109 run in the console shows three cards, each badged "Matches what was sent (fingerprint ...)" with the run's own first 8 characters; an out-of-scope run shows "This agent was not called in this run." three times. These checks prove display fidelity and isolation, not a live model's behaviour.

## Dispatch protocol

Work only inside this worktree. No other worktree or planning/scratch/reference reads. No subagents, web/network/API calls, package install, memory/config writes, or screenshot. No unrelated files. Read CODEBUDDY.md and this brief; scope carve-outs here supersede older write freezes only for this task. Use `/usr/bin/python3` with `PYTHONPATH` removed. Your sibling lane starts from the same prepared baseline and deliberately RED tests are committed: never repair your sibling's files or acceptance assertions. Run your focused suite plus the full suite and report remaining failures by test path, expected sibling RED vs any regression. The planner owns actual combined full GREEN, browser gates and review. Commit ONLY the allowed paths, explicit git add, never git add -A, never merge or push. End response with commit hash, full changed-file list and actual focused/full results. If tools denied, stop and report the tool and exact command.

Expected sibling RED: lane A's W27 replay tests, `tests/test_w27_replay*.py`. They are deliberately failing on the prepared baseline. Do not edit them.
