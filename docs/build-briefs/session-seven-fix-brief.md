# Build session seven — fix brief: architecture document, review round

**Target:** `tests/test_architecture_doc.py` now carries six more tests (class
`ReviewRoundPins`) that fail on the current doc. Make them pass **without editing any test**,
keep the full suite green, and correct every item below. Edit only `docs/architecture.md`
and `README.md`. Nothing under `app/`, `ui/`, `data/`, `tests/` or `tools/`.

Every item was reproduced against the code before it was written here.

## Items that change the diagram (both copies stay byte-identical)

1. **A withheld ruling goes to a human.** The Judge marks a withheld case for human review
   (`app/agents/judge.py:231-240`, `escalated_for_human_review=True`). Add an edge from the
   Withheld node to the Human review node, labelled "Candidate ruling queued". Pinned by
   `test_withheld_ruling_reaches_human_review_in_the_diagram`.
2. **The dataset pack feeds the server, not the form.** The server reads pack records to
   serve `/api/trips` and to build each filing's platform evidence (`app/server.py`); the
   form only calls the server. Replace the Dataset pack → Rider intake form edge with
   Dataset pack → Server. Pinned by `test_dataset_pack_feeds_the_server_not_the_form`.
3. **The command-line runner is a second way in.** `app/cli.py:82-84` resolves a dispute id
   straight from the pack. Add a "Command-line runner" node fed by the Dataset pack, feeding
   the category check. Pinned by `test_diagram_shows_the_command_line_runner`.
4. **The console reads the case file, not the log file.** `ui/app.js` renders the `events`
   array embedded in `case_file.json` and opens payloads from run files the operator attaches;
   it never reads `events.jsonl` and never calls the server. Label the Event log → Operator
   console edge "Embedded in the case file", and fix the sentence under `## Diagram` that says
   the console reads the event log.

Layout hint: declare the Dataset pack node BEFORE the Rider intake form node so their edges do
not cross at the top.

## Items in the prose

5. **README: three gates, not two.** `README.md` near line 106 says "Two gates stand between a
   ruling and the parties" and names only confidence and ESC-4. The Judge enforces a third,
   ESC-2 (`app/agents/judge.py:174-190`). Say three and name ESC-2, and add
   `python3 -m app.cli --pack ryde-synth-v1 --dispute RD-0108` as the ESC-2 example beside the
   existing RD-0109 line. Pinned by `test_readme_names_all_three_judge_gates`.
6. **README agent table: advocates do not gather evidence.** The pack is computed before any
   agent runs and agents may only cite it (`app/agents/base.py:28-34`, HARD_RULES). Change both
   advocate rows to "Builds the rider's (driver's) case from the Evidence Pack and the policy".
   Pinned by `test_readme_advocates_do_not_gather_evidence`.
7. **The word check is the gate for questions, not a backstop.** Rewrite the last sentences of
   `## What the parties see` and the matching `## Limits` bullet. The decision **message** is
   composed in code from structured fields, so nothing model-written reaches it. Follow-up
   **questions** are written by the advocates' model (`app/agents/base.py:198-201`); the word
   check (`is_party_safe`, applied in `app/pipeline.py` `_questions_for_party` and again in
   `party_view`) is what stops an unsafe one, and when none survive the pipeline falls back to
   plain template questions built from the form's own labels. State plainly that the word list
   is incomplete, so for questions it is a real but imperfect filter.
8. **The `advocate.follow_up_requested` event is not filtered.** Lifecycle step 6 says the event
   is emitted "only for questions that pass the party-safety check". False: `app/agents/base.py:
   270-283` records the advocate's raw questions. The check runs later, on the list sent to the
   party. Say that the event records what the advocate asked, and the party receives only the
   questions that pass the check.
9. **`needs_info` questions may come from the pipeline, not the advocates.** When no safe
   advocate question survives but a form answer was left blank, `_questions_for_party`
   (`app/pipeline.py:328-336`) builds template questions itself. Fix the `needs_info` row in
   `## The four outcomes` and lifecycle step 7 to say so.
10. **Web runs write more files, and there is a round-two route.** Under `## Observability`, add
    that a run filed through the server also writes `dispute.json` (the record the pipeline ran
    on) and that an answered run gains `answered.json`. Under `## What the parties see` (or
    Components), name the round-two route `POST /api/disputes/<run_id>/answers`. Pinned by
    `test_names_the_web_run_files_and_the_answers_route`.
11. **Add a sixth gate: answer once.** The answers route claims a run atomically with
    `O_CREAT | O_EXCL` before re-running it (`app/server.py:659-668`), so a `needs_info` run can
    be answered exactly once and cannot produce two rulings. Add it to `## Gates enforced in
    code` with its file, and change "Five gates" to "Six gates" in that section.
12. **Preconditions are prose, not machine-checked.** `## Policy and dataset packs` says the
    rules carry "machine-checkable preconditions". `app/policy.py:23-24`: evaluating them "is a
    later capability; nothing here interprets policy." Say the preconditions are written
    against pack fields in plain language and are not evaluated by code yet; add one line to
    `## Limits`.
13. **Citing an unknown rule ID is recorded, not blocked.** "agents may cite only IDs the loader
    found" implies enforcement. In fact an unknown ID is recorded under the ruling's
    `validation.unknown_rule_ids` with a note, the ruling still issues, and the unknown ID
    never reaches the party message because only known rule titles are looked up. Say that.
14. **Numbers: the pack and the party's own claim.** The Overview and lifecycle step 4 say the
    pack is the only source of numbers. The agents are also shown the party's claimed amount
    (`amount_claimed_sgd`, `app/agents/base.py:53`). Say that every computed figure comes from
    the pack and the only other number the agents see is the amount the party asked for.
15. **A missing trip or cancellation record aborts the run.** The Evidence layer row says a
    missing input "becomes a null with a note, never a guess". True inside a record, but a
    route case with no trip or a no-show with no cancellation record raises
    `EvidenceInputError` (`app/evidence/compute.py:749-758`) and no pack is built. Say both.
16. **Mock marking, stated precisely.** "every string it returns is `MOCK`-prefixed" is false:
    actions, rule IDs and evidence refs are not. The free-text fields (claim summaries,
    arguments, the Judge's explanation) carry the prefix, and the party decision message, which
    is composed in code, carries none. Say that, in the Components row and in
    `## LLM provider`.
17. **Same content, not the same file.** `## LLM provider` says the same dispute "always produces
    the same case file". The run id and event timestamps differ per run; the decisions and
    every computed figure are the same. Say that.
18. **The decision message, precisely.** In `## What the parties see`, add: a no-action ruling
    carries no amount, at most three rule titles are shown, and escalation (ESC) rules are
    never listed.

## Rules

- Read the cited lines before rewriting each item. Every sentence must stay true of HEAD.
- Do not edit anything under `app/`, `ui/`, `data/`, `tests/` or `tools/`.
- Keep the Mermaid block byte-identical between `docs/architecture.md` and `README.md`.
- No internal labels: no item numbers from this brief in the doc.
- Commit once for the diagram (items 1-4), once for the doc prose (7-18) and once for the
  README prose (5-6), each with the suite result in the message.

## Done means

```bash
python3 -m unittest discover -s tests -t .      # 345 tests, OK
```
