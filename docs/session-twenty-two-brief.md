# Session twenty-two brief (W23, part B1): the human decision, the status page, and "nothing more to add"

Rulings by the operator on 2026-10-01 and 2026-10-03. Today a case the Judge withholds says "still under
review" forever: no person can act on it, and a party who closes the tab cannot get back to their case. This
session builds the server half of closing that loop, plus the party-side pages. A later session builds the
operator console screens on top of the endpoints you build here, so **every endpoint below is in scope now**.

**Target:** five new test files go from RED to green, and the full suite
(`/usr/bin/python3 -m unittest discover -s tests -t .`) is green at **963 tests** when you are done:
`tests/test_w23_human_decision.py`, `tests/test_w23_status_and_accounts.py`,
`tests/test_w23_queue_and_overrides.py`, `tests/test_w23_party_pages.py`, `tests/test_w23_docs.py`
(helpers in `tests/w23_support.py`). `tests/test_w23_party_pages.py` drives `party.js` in Node, so `node` must be
on your PATH.

**Do not edit anything under `tests/`, `tools/` or `data/`, with ONE exception** (below). If a test looks
wrong, stop and ask.

**The one test edit you must make.** `ui/party/party.js` is frozen by a SHA-256 digest in two older tests,
and this session has to change it. When `party.js` is final, set exactly these two values to the SHA-256 of
your final `ui/party/party.js` (`shasum -a 256 ui/party/party.js`) and change nothing else in either file:
- `tests/test_party_rebrand.py`: the `PARTY_JS_SHA = "..."` constant;
- `tests/test_w12_demo_notice.py`: the digest string in the `assertEqual("...", digest)` line.

**Principle carried from every earlier session: rules live in code, never in the page.** The decision checks,
the decide-once lock and the party text are Python. The pages are clients.

## 1. New module `app/human_review.py` (all human-decision logic; server only routes)

Constants:
- `HUMAN_DECISION_FILE_NAME = "human_decision.json"`
- `HUMAN_AMOUNT_CEILING_SGD = 500.0`
- `HUMAN_REVIEWED_SENTENCE = "A member of our team reviewed your case."`
- `DECISIONS = ("approve", "change", "reject")`
- `REVIEWER_MAX_CHARS = 80`, `REASON_MAX_CHARS = 1000`

`class HumanDecisionError(Exception)` with `.status` (int HTTP code) and `.message` (str).

`validate_decision(body, case_file) -> dict` (pure; raises HumanDecisionError). Order of checks:
1. `case_file` must be a non-array dict whose `resolution` is a dict with `outcome == "withheld"`, else 409
   "this case is not waiting for a human decision".
2. `body["decision"]` in DECISIONS, else 400.
3. `reviewer`: str, non-blank after strip, <= 80 chars after strip, else 400. Stored stripped.
4. `reason`: str, non-blank after strip, <= 1000 chars after strip, else 400. Stored stripped.
5. Per decision:
   - **approve**: body must NOT carry `action` or `amount_sgd` keys (400 "approve takes no action or amount; use change").
     `resolution.withheld_candidate` must be a non-array dict with a valid action (RulingAction values) and a finite
     number amount (not bool), else 409 "there is no proposed ruling to approve" (model-failure cases).
     Final action/amount = the candidate's, amount `round(x, 2)` (no action -> 0.0).
     **The SGD 500 ceiling applies to approve too** (the model's amount has no upper bound): a rounded proposal
     above 500.00 -> 400 `the proposed amount is above SGD 500.00; use change`; exactly 500.00 is accepted.
   - **change**: `action` must parse via `RulingAction.parse` (so "No_Action" works), else 400.
     `amount_sgd` must be int/float, not bool, finite, else 400; a JSON int too large for float (10**400) -> 400, never 500.
     amount = round(float(x), 2). Then: `no action` requires amount == 0.00; `refund`/`compensation` require
     amount > 0.00 (checked AFTER rounding: 0.004 -> 0.00 -> refused); amount must be <= 500.00
     (500.00 accepted, 500.01 refused); negative refused. Each a 400.
   - **reject**: body must NOT carry `action` or `amount_sgd` (400). Final = `no action`, 0.0.
6. NO money gate is consulted (operator ruling): no confidence, ESC-4 cap, ESC-2, NS-6, RD-5, RD-4. A change to SGD 55.16
   on a case held by ESC-4 is accepted; a change to 5.56 on a case held by RD-4 is accepted.

Returns the record (exact keys, in this order):
`{"schema_version": "1.0", "run_id", "dispute_id", "decision", "reviewer", "reason", "action", "amount_sgd",
  "proposed": {"action", "amount_sgd"} or None (from withheld_candidate when valid), "decided_at"}`
`decided_at` = UTC ISO-8601 with seconds. run_id/dispute_id copied from the case file.

`record_decision(run_dir, case_file, body) -> dict`:
- validate first (nothing touches disk on a refused body).
- **Decide once, atomically:** the decision file is created so that exactly one of N concurrent requests wins
  (write to a temp file in run_dir, then `os.link(tmp, final)`; FileExistsError -> 409 "this case already has a
  human decision"; temp always removed). A second sequential decision -> 409. The file is never empty or partial.
- Then append ONE event to the run's `events.jsonl` via `app.events.append_event` (below):
  type `human.decision_recorded`, from `human_review`, to `parties`,
  summary exactly `"human reviewer <reviewer> decided: <decision>"` (no amount, no "SGD", no reason),
  payload = the record.
- If the event append raises, the decision stands: log to stderr, still return the record (same pattern as
  `_write_answered_record`). Patch point for that test: `app.events.append_event`.
- `case_file.json` is never modified (byte-identical before/after). `dispute.json` never modified.

`load_decision(run_dir) -> Optional[dict]`: the record if the file parses to a dict whose `action` is a RulingAction
value and `amount_sgd` is a finite non-bool number; else None (fail closed: missing, empty, corrupt, array, bad shape).

`party_message_for_human_decision(record, withheld_candidate, policy) -> str` (operator ruling 2026-10-03):
- **approve**: the AI's Basis line is kept, because the human accepted the proposal and its reasoning. Titles come
  from `withheld_candidate["cited_rule_ids"]` under exactly the `_cited_rule_titles` rules in `app/schemas.py`
  (ESC-* skipped by prefix, unknown/empty/unsafe titles skipped, at most 3, in citation order). Format:
  `"Decision: refund of SGD 55.16. Basis: When a deviation is material; A material deviation is not automatically a breach; Unjustified material deviation: remedy. A member of our team reviewed your case."`
  With no surviving title (or no policy): no Basis part.
- **change** and **reject**: never a Basis line (the AI's citations may contradict the human's decision).
- no action: `"Decision: no action. A member of our team reviewed your case."` (plus Basis only on an approve).
- else: `"Decision: %s of SGD %.2f. A member of our team reviewed your case."` e.g.
  `"Decision: refund of SGD 5.56. A member of our team reviewed your case."`
- Never the reviewer's name or reason. Must pass `is_party_safe`. The server passes its loaded policy
  (`state.policy`) wherever a party view is built from a human decision.

## 2. `app/events.py`

- `EventType.HUMAN_DECISION_RECORDED = "human.decision_recorded"`.
- `append_event(run_dir, run_id, event_type, *, from_, to, summary, payload=None) -> dict`: module-level function.
  seq = (max seq in existing events.jsonl) + 1 (1 if none); payload written first to
  `payloads/<seq:04d>-<slug>.json` like `EventLog.emit`; one line appended; nothing else rewritten.
  Same 9 schema fields, schema_version "1.0". Existing lines byte-identical after the append.

## 3. `app/server.py`

`party_view(case_file, human_decision=None, policy=None)`, two new optional args; the server passes
`state.policy` on every path that builds a view from a decision (decision response, lookup, both demo lists). When `load_decision`-shaped valid dict is given
AND the case file's resolution outcome is `withheld`: status `"decided"`, message =
`party_message_for_human_decision(...)`, questions `[]`, **no demo notice** (a human decided).
A human_decision that is not a valid shape is ignored (view stays under_review). A human_decision on a
non-withheld case file is ignored. The 5-key allowlist (`PARTY_VIEW_KEYS`) is unchanged.

Run discovery (helpers, module level):
- Only DIRECT children of `out_dir` that hold `case_file.json` are runs. Eval runs live in sub-subfolders and are
  never seen. Unreadable/corrupt case files are skipped, never a 500.
- **Party-filed** = the run folder also holds `dispute.json` (only the server writes it; CLI runs do not).
- **Current run of a dispute** = among party-filed runs with that `dispute_id`, the ones WITHOUT `answered.json`;
  if more than one, the latest `generated_at`, tie -> larger run_id. (A needs_info run that was answered is superseded
  by its round-two run; a released claim after a crash makes it current again.)

New endpoints (all JSON, `Cache-Control: no-store`, GET unless stated):

1. `GET /api/disputes/<dispute_id>` -> 200 party view (5 keys) of the current run, with its human decision applied.
   `dispute_id` must match `^[A-Za-z0-9._-]{1,64}$` else 404; unknown or not party-filed -> 404 "unknown dispute".
2. `GET /api/demo/rider` -> 200 `{"account": {"kind": "rider", "label": "Demo account"}, "disputes": [...]}`.
   One entry per party-filed dispute whose current run's `dispute.json` says `filed_by` rider (both record shapes:
   `dispute_ticket.filed_by` / top-level `filed_by`), newest `filed_at` first (tie: dispute_id asc).
   Entry keys exactly: the 5 party-view keys + `"filed_at"`, `"category"` (form category from dispute.json),
   `"trip_label"` (the trip summary label, `_trip_summary(record)["label"]`, "" if none).
3. `GET /api/demo/driver` -> 200 `{"account": {"kind": "driver", "label": "Demo account", "driver_id": DEMO_DRIVER_ID}, "disputes": [...]}`.
   `DEMO_DRIVER_ID = "D-2009"` (module constant; trip T-RD0109, the 33 km detour held by the SGD 50 cap; same id in
   both packs). Entries: party-filed disputes whose dispute.json trip driver_id (`trip_data.driver_id` /
   `trip.driver_id`) == DEMO_DRIVER_ID, any filer. Same entry keys as the rider list but **read-only**:
   `questions` always `[]`, `run_id` always `""`; status only `decided` (message = the decided party message) or
   `under_review` (message = UNDER_REVIEW_MESSAGE), needs_info and passed_to_support both show as under_review,
   because those texts address the filer.
4. `POST /api/review/<run_id>/decision` -> 200 `{"decision": record, "party_view": party_view(case, record)}`.
   Run id checked like `_answer_run` (regex, resolve inside out_dir, folder exists, case file readable) else 404.
   HumanDecisionError -> its status + `{"error": message}`. Works on CLI runs too (no dispute.json needed).
5. `GET /api/review/queue` -> 200 `{"cases": [...]}`: every run (party-filed or CLI) whose outcome is `withheld`
   and that has no valid human decision file. Entry keys exactly:
   `run_id, dispute_id, category, safety (bool), amount_sgd (float|None), amount_source ("proposed"|"claimed"|None),
   waiting_seconds (int >= 0), held_by (list of str), proposed ({"action","amount_sgd"}|None), can_approve (bool)`.
   - safety: `intake.form_answers.safety_concern` matches `^\s*yes\b` case-insensitive ("Yes", "yes - he shouted",
     "YES"); "No", "", missing, "Yesterday..." -> False.
   - amount: proposed candidate amount if a valid candidate exists, else `intake.claim_amount_sgd` if a finite number,
     else None.
   - held_by: the `gates_failed` list from the run's `judge.ruling_withheld` event payload (follow `payload_ref` in
     events.jsonl); `["model_failure"]` when the run's events carry `dispute.escalated_on_model_failure`; `[]` if
     neither is readable.
   - waiting_seconds: now (UTC) minus the case file's `generated_at`, floored, never negative.
   - can_approve: a valid candidate exists.
   - Sort: safety first (True before False), then amount desc (None counts as 0), then waiting_seconds desc, then run_id asc.
6. `GET /api/review/overrides` -> 200 `{"approved_count": int, "groups": [...]}`. Reads every run's valid decision.
   approve decisions only counted. change + reject grouped by `(category, held_by tuple, decision, action)`;
   group keys exactly `category, held_by, decision, action, count, decisions`; each decision entry keys
   `run_id, dispute_id, reviewer, reason, action, amount_sgd, proposed, decided_at`, oldest first.
   Groups sorted count desc, then category, then decision.

Answer endpoint: unchanged behaviour.

## 4. Party pages (`ui/party/`)

- `ui/party/party.js`: each round-two question box gets a button labelled exactly `I have nothing more to add`
  that sets that question's textarea value to exactly `I have nothing more to add` (the same string as
  `app/eval.py` `NOTHING_MORE_TO_ADD`). The answer POST already accepts it.
- New `ui/party/status.html` + `ui/party/status.js` (+ may reuse party.css): a reference-number lookup
  (`GET /api/disputes/<ref>`) and a "My disputes" list from `GET /api/demo/rider`, visibly labelled "Demo account"
  with the sentence `This is a demo account. It shows every dispute filed on this demo.`; a needs_info entry lets the
  rider answer its questions in place (same answer endpoint, with the nothing-more button). Link to it from
  `ui/party/index.html` outcome panel and header.
- New `ui/party/driver.html` + `ui/party/driver.js`: read-only list from `GET /api/demo/driver`, labelled
  "Demo account", sentence `This is a demo driver account. It shows the outcome of disputes about your trips.`;
  no form, no textarea, no answer request.
- All three JS files: textContent only (no innerHTML/outerHTML/insertAdjacentHTML/document.write); no internal
  vocabulary per the existing `PartyPagesSpeakPlainly` checks, which must be extended to the new files.

## 5. Docs

`docs/architecture.md`: a section `## Human decision` naming `app/human_review.py`, `human_decision.json`,
`human.decision_recorded`, the SGD 500 ceiling, and the four new API paths + two demo paths. README gets one
sentence under Run linking `/party/status.html`. 

## Fixed strings the tests pin exactly

- `this case is not waiting for a human decision` (409)
- `approve takes no action or amount; use change` (400)
- `there is no proposed ruling to approve` (409)
- `the proposed amount is above SGD 500.00; use change` (400)
- `this case already has a human decision` (409)
- `unknown dispute` (404)
- event summary `human reviewer <reviewer> decided: <decision>`
- the party messages in section 1 and the two page sentences in section 4.

Other 400 messages are yours to word; the tests check the status and that the message is not empty.

## Allowed files

New: `app/human_review.py`, `ui/party/status.html`, `ui/party/status.js`, `ui/party/driver.html`,
`ui/party/driver.js`. Edited: `app/events.py`, `app/server.py`, `ui/party/party.js`, `ui/party/index.html`,
`ui/party/party.css` (optional), `docs/architecture.md`, `README.md`, plus the two digest values named above.
Nothing else. Do not touch `app/agents/`, `app/evidence/`, `app/eval.py`, `app/pipeline.py`,
`app/schemas.py`, `docs/policy.md` or `ui/index.html` / `ui/app.js`.

## Constraints

Standard library only. Python 3.9: no `match`, no `X | Y` unions. Run the suite with `/usr/bin/python3`, never a
bare `python3`. Commit in small commits when the suite is green. Do not run the live model.

## What you should see when you are done

- Full suite: **963 tests, OK**.
- `/usr/bin/python3 -m app.eval --llm mock` on both packs: unchanged (organiser 11 of 18 matching, 11 of 18
  decided without a human, 0 round-one stops; synth 10 of 17, 10 of 17, 0). This session must not move any eval
  number. If one moves, stop and report it.
- Filing trip `T-RD0109` on the mock with a claim of 55.16 through `POST /api/disputes` gives a withheld case
  (held by the SGD 50 cap). `POST /api/review/<run_id>/decision` with `{"decision": "approve", "reviewer": "...",
  "reason": "..."}` then returns a party view whose message is
  `Decision: refund of SGD 55.16. Basis: What this policy covers; Every finding must rest on the Evidence Pack. A member of our team reviewed your case.`
  (the mock cites general rules; the real model cites the route rules),
  and `GET /api/demo/driver` shows that dispute as decided.

## Out of scope

The operator console (a later session). The Judge, every gate, the evidence layer, the eval harness, the policy,
the data packs. Driver filing. Any change to what the AI decides.
