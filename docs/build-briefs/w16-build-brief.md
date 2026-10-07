# W16: driver-side filing build brief

## Deliverable and authority

Build the approved driver-filing form and role-aware intake/follow-ups, without changing rider behaviour or any money authority. the operator approved the exact wording and separate page. This is a local demo, not authentication. Exactly three agents still decide each in-scope dispute. Route deviation and no-show stay the only autonomous categories. Cleaning reports use existing zero-model support routing, not the withheld-case decision queue.

Work only in the launch worktree. Read CODEBUDDY.md, docs/statement-extract.md and this brief. Do not read the planning repository or any scratch reference. No reference implementation is supplied. Derive your independent implementation from this contract and tests. Do not commit, merge, push, regenerate data, edit memory files or use a paid provider to self-check. Stop and ask if a test or existing ruling conflicts.

## Preflight

Confirm branch w16-driver-intake, inspect current HEAD and git status, and list the allowed pre-staged acceptance/doc files. Application/UI must have no pre-existing changes. The base was main 71eb71a when the worktree was created; do not require a future literal HEAD hash. This tree intentionally starts RED with approved tests and future-state docs. Main/rehearsal stays untouched. Python backend is stdlib-only; use /usr/bin/python3 -B. Keep mock as configured provider default. Tests create isolated temporary outputs; use TMPDIR beneath the operator-specified scratch location, not a live runs/ folder. Ask for that scratch path if it is not supplied in the launch prompt.

The parent proved these tests on a disposable reference: 1073 passing. On the unimplemented baseline the new 29 methods produced 58 assertion failures and zero errors. Subtests contribute multiple failures. Behavioural rider controls passed. These are preparation measurements, not a guarantee that the independent build needs exactly the same lines.

## Write fence

Application/UI allowed files ONLY:

- app/schemas.py: driver labels/kinds, role selector, role-aware slot enumeration/rendering. Do not change message/ruling schemas.
- app/server.py: select validation questionnaire by category and canonical filer. Existing rider compatibility exports stay. No status/storage/account/answer/money/API changes.
- app/agents/base.py: pass filing role into offered-slot enumeration. No agent schema/call-order/retry changes.
- app/pipeline.py: use filing-role labels in blank-field fallback only. Keep ordering, caps, stop/answer gates.
- app/llm/mock.py: role-aware blank-key label filtering only. Solver/action/amount decisions stay byte-for-byte untouched.
- ui/party/party.js: shared role/table selection, driver category labels, matched rendering and payload selection, invalid explicit marker refusal.
- ui/party/driver-filing.html: new driver shell, approved notices, existing ids/style/script.
- ui/party/index.html: driver discovery link only.
- ui/party/driver.html: filing link and approved fixed-account/read-only explanation only. This remains the existing account page.

All other app/UI paths are frozen, especially app/agents/judge.py, app/dispute.py, app/evidence/, human-review code, real adapters/config, status pages/scripts, driver.js, CSS and operator UI. Policy/data/tools and existing fixtures are frozen.

Tests are read-only EXCEPT the two digest values for ui/party/party.js: PARTY_JS_SHA in tests/test_party_rebrand.py and the matching expected digest in ContractIntactTest.test_party_js_unchanged in tests/test_w12_demo_notice.py. Compute both from your independently shipped bytes ONLY after rider+driver behavioural tests pass. No other test edit is authorized. These two digest assertions are the sole parent-approved carve-out. Do not copy the digest from a reference or disable a freeze. The staged comments identify this as a builder digest rebaseline, not a second feature change.

README.md, docs/architecture.md and docs/prompts.md have parent-supplied narrow future-state amendments. Read them and implement the claims; do not edit them in this build. If they disagree with the approved contract, stop and ask. No other documentation or evidence writes without an operator follow-up.

The parent also stages `docs/build-briefs/w16-acceptance-manifest.json`. It lists the approved test/doc files and their pre-build SHA-256 hashes. Before final verification, every listed file except the two authorized digest files must still match its manifest hash. The two digest files may differ only at their one expected digest literal and the surrounding approved comment. Do not edit the manifest.

Approved tests staged before dispatch: tests/test_w16_driver_contract.py, tests/test_w16_driver_filing.py, tests/test_w16_driver_pages.py, tests/w16_support.py; narrow amendments to test_session_eight.py, test_party_form_ux.py, test_session_six_fixes.py, test_party_rebrand.py, test_w12_demo_notice.py and w23_support.py. They change driver contract expectations, role-scoped behavioural comparisons, driver fixtures and authorized digests. Existing money/corpus/notice assertions remain unchanged. Use the exact exported names and types required by the tests, including `intake_questions_for`, `DRIVER_INTAKE_QUESTIONS` as a dict of tuples, and `DRIVER_YES_NO_INTAKE_KEYS` as a frozenset. Preserve the legacy `QUESTIONNAIRES[state.category]` submit-path access used by the existing pin. The driver shell must use `<section id="form-steps" data-filed-by="driver">`, bare approved navigation links, the existing ids and shared deferred party script. These are test-shape constraints, not alternate implementation suggestions.

## Contract

### Page-role selection

Use the existing form machinery from a separate /party/driver-filing.html shell. Put data-filed-by="driver" on its existing #form-steps element and read that element's attribute once at boot. A missing attribute defaults to rider, preserving the existing rider shell and Node harnesses. Explicit literal rider or driver selects the matching questionnaire, category labels and POST filed_by. An explicit invalid value, including an empty string, must show the approved fixed error and allow no filing or trip request. Do not read a role from the URL, document.body or the fixed driver account. The attribute configures demo copy, not authentication. Keep driver.html as the read-only account.

## Frozen role-aware contract

### Python tables and selectors

Keep legacy `INTAKE_QUESTIONS`, `YES_NO_INTAKE_KEYS`, `FOLLOW_UP_QUESTION_BANK` and `server.QUESTIONNAIRES` as rider-compatible exports with their existing values. Add `DRIVER_INTAKE_QUESTIONS` and `DRIVER_YES_NO_INTAKE_KEYS`. Recommend one selector `intake_questions_for(category, filed_by="rider")` returning the ordered `(key, label)` tuples for the role and category, or `()` for unsupported/malformed arguments. Call it in validation, slot generation/rendering, mock blank-key lookup and pipeline fallback. Keep kind declarations cross-checked against the role-specific yes/no sets.

Recommend these driver keys, in this exact order. They make actor direction explicit. Only `safety_concern` is shared: its question is about the filer in either form, and `server.py:589-593` reads that key for queue priority. Renaming it would needlessly expand operator code.

| Category | Key | Kind | Exact approved label |
|---|---|---|---|
| `route_deviation` | `route_shown_to_driver` | open | What route did the app show you, and roughly how long was it? |
| `route_deviation` | `route_agreed_with_rider` | yes_no | Did you and the rider agree to take a different route? |
| `route_deviation` | `rider_requested_stop` | yes_no | Did the rider ask you to stop anywhere along the way? |
| `route_deviation` | `safety_concern` | yes_no | At any point were you worried for your safety? |
| `no_show_charge` | `driver_waiting_place` | open | Where did you wait, and for roughly how long? |
| `no_show_charge` | `driver_contacted_rider` | yes_no | Did you try to call or message the rider? |
| `no_show_charge` | `safety_concern` | yes_no | At any point were you worried for your safety? |

`property_damage_mess`, `safety_incident` and `other` keep no extra questionnaire keys. Required description and optional claim amount cover the cleaning report. Do not add an upload control or imply photographs will be analysed.

Shared legacy keys with swapped labels are smaller mechanically, but unsafe semantically. `asked_driver_to_stop` and `did_driver_contact_you` name specific actor directions; relabelling them would silently change their meanings in stored intake, prompt JSON and mock metadata. New driver keys keep those meanings visible without changing the generic parser or evidence layer. Even plausible shared keys such as `expected_route` and `where_were_you` can retain rider-oriented wording in an overlooked fallback. A distinct driver table makes a wrong-party slot easy to refuse.

### Filing wire and storage

Keep the endpoint and outer request shape:

```json
{
  "category": "no_show_charge",
  "filed_by": "driver",
  "trip_id": "T-NS0201",
  "description": "I waited at the pickup point. Please review the recorded fee.",
  "claim_amount_sgd": null,
  "answers": {
    "driver_waiting_place": "At the booked pickup point for about five and a half minutes.",
    "driver_contacted_rider": "Yes - I sent a message.",
    "safety_concern": "No"
  }
}
```

This is a proposed input example, not a saved response or a verified historical driver statement.

- Normalize `filed_by` exactly as today. Validation then selects keys by **role and category**. Driver keys on rider filing and rider-only keys on driver filing return 400 before creating a run or calling a model. Shared `safety_concern` is valid for both.
- Preserve rider key names, wording, accepted string semantics and normalization. Do not tighten rider yes/no validation, add answer-length limits, require optional answers or fix unrelated existing UX residue.
- Keep existing description/body/amount limits, category vocabulary and category/trip match guard. Out-of-scope categories still accept any sample trip. Unknown trip stays 404. All answer values stay strings; blank strings are allowed. Missing keys/absent answers remain optional and are not automatically filled with blanks.
- Store exact driver keys without translating to rider keys. Organiser records use `ryde_extensions.intake`; synth records use top-level `intake`. Keep `intake.form_answers` and `intake.filed_by` on the self-contained case file. Platform trip/chat/profile/fee data stays copied, not overwritten by form answers.
- Preserve the generic dispute prompt block's explicit `filed_by: driver`, exact keys and follow-up answers. Both advocates and Judge receive the same attributable submission. No claim becomes corroborated evidence merely because it is on the form.
- New HTTP driver filing should reject old rider-only keys rather than aliasing them. This intentionally tightens the formerly rider-shaped **driver** API, not the rider API. Existing saved driver runs are not rewritten. Their reference lookup and already-asked question replies continue against persisted question strings; round two parses generic intake and does not ask again. Old CLI records remain pass-through, with no new validation at `parse_dispute`.
- Five-key response stays `run_id`, `dispute_id`, `status`, `message`, `questions`. Existing statuses, fixed messages, notice proof and human-decision overlay stay unchanged.

### Slots and continuation

Change `follow_up_slot_ids(category, filed_by="rider")` to enumerate only renderable ids for that role. Rider default output remains bank ids followed by legacy form ids, in existing order. Driver output is **form ids only**, from the driver table in form order:

| Category | Exact driver slot ids |
|---|---|
| `route_deviation` | `form:route_shown_to_driver`, `form:route_agreed_with_rider`, `form:rider_requested_stop`, `form:safety_concern` |
| `no_show_charge` | `form:driver_waiting_place`, `form:driver_contacted_rider`, `form:safety_concern` |
| out of scope/unknown | none |

`render_follow_up_slot(category, slot_id, filed_by="rider")` resolves form ids against the selected role table. Refuse every rider bank id for a driver filing. Refuse wrong-role form ids, wrong-category form ids, unknown ids, missing/empty/non-string ids, non-string categories and invalid roles without raising a hashing/type error. Unknown or malformed enumeration arguments return `[]`; malformed rendering arguments return `None`. Normalize role only at established input boundaries, not differently in each selector. Exact canonical roles are the helper contract.

The offered list must equal the renderable list. `AdvocateAgent.user_prompt` passes `dispute.filed_by` into enumeration and rendering. Both advocates get the same offered questions for the **filer**, not separate question lists based on their own `party`. `AdvocateCase.from_payload` already carries the right filer to the renderer. Keep its raw-slot audit, bounded six-slot parsing, duplicate-sentence collapse and invalid-slot notes. A missing or null optional `follow_up_slots` field remains an empty list. A non-null malformed list container or non-string list member remains a contract error with W19 handling; an unknown string is dropped with a note. Do not add model-written driver questions.

Mock changes are confined to selecting labels for blank-key filtering. Keep its first-round-only, filing-advocate-only, three-blank-slot behaviour and money solver unchanged. Pipeline fallback uses the same role-selected labels, asks only present blank strings, in table order, and only when no safe rendered question survives. Keep normalized deduplication, filer-advocate-first question priority, final cap three and the one-round gate. An invalid slot with no blank valid field must not create an empty `needs_info` stop.

Keep the existing templates exactly. Every table row above therefore generates these exact question forms, with `<label>` replaced verbatim:

| Use | Exact copy, existing template retained |
|---|---|
| selected form slot | `About the form question "<label>": could you tell us a little more?` |
| blank-field fallback | `We didn't get an answer to "<label>". Could you tell us?` |

After a stop, the new filing page uses existing answer boxes and `POST /api/disputes/<run_id>/answers`. Status lookup by `dispute_id` is the reload recovery path. A round-two rerun keeps driver identity and driver intake, attaches replies in the correct record location, changes run id, keeps dispute id, bypasses another question round and still runs all existing Judge gates. Do not re-render old persisted questions from new labels when validating replies.

## Approved page copy

the operator approved all additions and replacements in this section. Existing rider category labels, questionnaire copy and status/decision constants are retained unchanged. The driver form keeps the existing shared controls and step wording unless listed below.

| Location | Exact copy |
|---|---|
| driver-filing document title | Ryde - file a driver trip dispute |
| driver-filing eyebrow | RYDE / DRIVER HELP |
| driver-filing H1 | File a driver trip dispute |
| driver-filing introduction | Tell us what happened on a trip from your side as the driver. Three quick steps. |
| driver-filing demo note | Demo filing: choose a sample trip and file from that trip's driver's perspective. This is not a signed-in account. |
| driver-filing account limitation | The driver demo account shows only trips for driver D-2009, including T-RD0109. A filing on another sample trip will not appear there. |
| driver-filing header and outcome recovery hint | Save your reference number. Use it on the status page to answer questions or check the outcome. Driver filings are not listed in the rider demo list. |
| driver-filing header and outcome status link | Look up your reference number |
| driver-filing header rider-help link | Go to rider help |
| driver-filing header account link | View the driver demo account |
| driver-filing category `route_deviation` | A question about the route I took |
| driver-filing category `no_show_charge` | A no-show or waiting fee |
| driver-filing category `property_damage_mess` | A cleaning fee or damage report |
| driver-filing category `safety_incident` | A safety incident |
| driver-filing category `other` | Something else |
| driver-filing amount helper, only on new HTML | An amount you enter is a request, not a payment. |
| new driver link in rider help | Filing as a driver? |
| new link in driver outcome account | File a driver trip dispute |
| driver outcome account hint replacing rider-only-filing sentence | This page is read-only. To file a driver dispute, use the driver filing page. |
| driver outcome account added boundary hint | This demo account is for driver D-2009. The filing page lets you choose other sample trips; those filings will not appear here. |
| invalid explicit page-role marker error | This filing page could not be loaded. Please return to the help page and try again. |

Navigation targets are `./driver-filing.html`, `./index.html`, `./driver.html` and `./status.html#reference-input` as appropriate. `reference-input` already exists; do not create a new status-page id or a query-prefill implementation.

New driver form otherwise uses the existing literals: `What went wrong?`, `Which trip?`, `Pick the trip this dispute is about.`, `Tell us more`, `What happened?`, `required`, `Describe it in your own words.`, `Amount you are asking for, in SGD`, `optional`, `0.00`, `Back`, `Continue`, `Send my dispute`, `Yes`, `No`, `Tell us more (optional)`, `Tell us more: <label>`, `Reference number:`, `Please answer each question below, then send your replies.`, `Send my answers`, `I have nothing more to add`, and the existing loading/validation/error/outcome headings. Existing `NEEDS_INFO_MESSAGE` contains an em dash; retain the approved constant, do not restyle it in W16.

No new decision copy is proposed. The standing-fee demonstration should still say `Decision: no action.` with existing safe Basis titles and the illustrative-run notice when applicable. Do not add "You have been paid", "Your earnings increased" or a driver-entitlement sentence. Under review and passed-to-support remain existing fixed messages.

## Deterministic money demonstration contract

These are acceptance fixtures, not claims about real-model results. Script model replies through a test LLM adapter and call the actual server/pipeline/Judge gates. Never alter the mock solver, labels or source data. Do not label scripted provider output `tencent` to hide the demo notice.

1. **Supported existing fee stands.** File driver no-show on T-NS0201 with complete proposed driver answers and no claim amount. Assert actual pack wait 5.5 minutes, distance 18.1 m and fee 6.61. Script advocates with no slots and Judge no action, amount 0, confidence 0.95, citations NS-2/NS-3 and real cancellation refs. Assert ruled/decided, no candidate, no payment amount in the decision line, recorded fee unchanged, no review item, and illustrative notice. The fee standing is a no-action finding, not a transfer to the driver. Optional neighbouring waiting-fee characterization may use T-NS0207, whose organiser record has waiting fee 5.00, but must not add entitlement logic or make that extra beat a requirement.
2. **New payment is held.** Same driver form/trip, complete answers, script compensation 0.50 at 0.95. This small amount avoids the cap being the reason for refusal. Assert no ruling, candidate compensation exactly 0.50, `held_by` includes NS-8, neutral under-review message, no candidate/amount/confidence/rule ID/reason leaked to party JSON or DOM, and the candidate remains readable in the operator case/queue. Repeat on **T-RD0103** with compensation 0.50 to prove driver identity does not bypass RD-4. Preparation computed its measured route deviation 6.0%, readable charged fare 11.69, fare difference 0.00 and no unreadable fare inputs. A scripted pipeline probe on this driver filing returned withheld with `gates_failed: ["RD-4"]` and candidate compensation 0.50. This establishes a sole-gate fixture without relying on its corpus label.
3. **Cleaning report uses support path.** File driver `property_damage_mess` on an available sample trip, description required, optional amount such as 25.00, answers `{}`. Use a spy that fails if any model call happens. Assert human_review/passed_to_support, category_as_submitted property_damage_mess, routed other, no pack or advocate cases/ruling/candidate, no uploads/image analysis, safe fixed support message, successful reference recovery. Assert no W23 withheld-queue item or human-decision workflow; do not broaden it.

## Verification and stop condition

Run /usr/bin/python3 -B -m unittest tests.test_w16_driver_contract tests.test_w16_driver_filing tests.test_w16_driver_pages, then /usr/bin/python3 -B -m unittest discover -s tests -t . with the provided scratch TMPDIR. Require all tests green, no skips, no new dependency. Before final report inspect git diff by file and ensure only the fence and two digest values moved. Report exact counts, paths and command results, not "done" without outputs.

Deterministic scripted acceptance must show NS-0201's supported existing fee standing via no action, new compensation held by NS-8/RD-4, and cleaning report routed without a model call. Do not change the mock solver/corpus for a nicer demonstration. Real Tencent outcomes, actual-browser checks, ported mutation proof and independent review belong to the operator after your build, not to this session's self-report.

Present a plan before editing and wait for the operator's approval. If a needed file is outside the fence, an API field is missing, or a test appears wrong, stop and name the exact conflict rather than widening scope. End with git status/diff and measured tests, with no commit or merge.
