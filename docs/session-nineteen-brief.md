# Session nineteen brief: two money gates, an eval that finishes the job, and a true README

Three things change in this session, all ruled by the operator on 2026-10-01.

1. **Two new gates in the Judge.** Both withhold a ruling for a human; neither ever changes
   what the Judge proposed.
   - **NS-6, contested no-show.** The driver marked a no-show, the rider says the driver was
     absent, and the driver's position at arrival was never recorded. Without that position
     the fee has no GPS proof, so the only ruling allowed through is a refund of exactly the
     fee, and only for a low fee and a clean rider record.
   - **RD-5, proven overcharge.** On a route case where the records prove the rider was
     overcharged by at least SGD 1.00, a ruling that refunds less than that is held.
2. **The evaluation harness answers round two.** Today a case that stops to ask the party is
   scored as a miss and never reaches the Judge. From now on the harness answers every
   question with "I have nothing more to add", runs round two, and scores the final ruling.
   It also reports how many cases were decided without a human, and can repeat each case to
   measure whether rulings stay the same.
3. **The README stops saying false things**, names both new gates, and gains a short "How this
   was built" section.

`docs/policy.md` already carries the new NS-6 and RD-5 text and the SGD 10 parameter. Read
both rules before writing the gates.

**Target:** three new test files (75 tests), currently RED, go green, and the full suite
(`/usr/bin/python3 -m unittest discover -s tests -t .`, 690 tests when done) is green:
`tests/test_w22_money_gates.py`, `tests/test_w22_eval_round_two.py`, `tests/test_w22_docs.py`.

**Do not edit anything under `tests/`, `tools/`, `data/` or `ui/`.** If a test looks wrong, stop
and ask. Two existing test files were updated for this session on purpose (listed at the end).

## The contract, file by file

### `app/agents/judge.py`: the two gates

New module constants and one public helper:

- `CONTESTED_NO_SHOW_AUTO_LIMIT_SGD = 10.00`
- `DE_MINIMIS_SGD = 1.00`
- `ns6_auto_refund_eligible(pack: EvidencePack) -> bool`: True only when **all** hold, and a
  missing figure always fails its condition:
  - `pack.cancellation.cancellation_fee_sgd` is recorded, above 0, and at most the limit
    (exactly 10.00 is allowed);
  - the rider profile exists and `fraud_flags` is recorded **and equal to 0**. `None` means
    unknown, and unknown is not clean;
  - `disputes_total` and `disputes_upheld` are both recorded, neither is negative, and upheld
    is not above total. Rejected = total minus upheld. Eligible when rejected is no more than
    half of total (exactly half is allowed). Zero past disputes is eligible.

The gates are appended to the existing `gate_failures` list in `Judge.run`, **after** ESC-2, in
this order: NS-6, then RD-5. The existing confidence, ESC-4 and ESC-2 checks do not change.

**NS-6** applies only when every one of these holds: the dispute's category is the no-show
category, the pack has a cancellation block, `driver_marked_no_show is True`,
`rider_claims_driver_absent is True`, and `driver_distance_from_pickup_m is None`. When it
applies:

- not eligible: withhold, whatever the ruling says;
- eligible: withhold unless the action is `refund` **and** the amount equals the fee to the
  cent (round both to 2 places). A refund above the fee is withheld too.

**RD-5** applies only when the category is route deviation, the pack has a fare block, and
`fare.difference_sgd` is recorded and at least `DE_MINIMIS_SGD`. When it applies, withhold
unless the action is `refund` and the amount, rounded to the cent, is at least the difference
rounded to the cent. Refunding more than the difference is allowed.

For both gates: the gate name in `gates_failed` is exactly `"NS-6"` or `"RD-5"`. The entry in
`gate_summaries` names the rule id and **contains no amount and no "SGD"**: the summary shows on
the operator's event strip, and the figures belong in the payload and the notes. The reason
text (which goes into the notes) may carry figures.

### `app/eval.py`: round two, autonomy, repeat

New module constants: `NOTHING_MORE_TO_ADD = "I have nothing more to add"` and
`MAX_REPEAT = 5`.

New public function `with_round_two_answers(record: dict, questions: list) -> dict`: returns a
**deep copy** of the raw record with one `{"question": q, "answer": NOTHING_MORE_TO_ADD}` per
question, in order. The answers go where the record's own shape carries them, exactly as
`app/server.py` attaches a party's answers: under `ryde_extensions.follow_up_answers` for an
organiser-shaped record (`app.dispute.is_organiser_record`), at the top level otherwise. The input
record must be left unchanged.

Running a case (inside `run_eval`):

1. Read the record file as JSON and run it through `parse_dispute` and `run_dispute`, writing the
   case file to the case's directory, exactly as today.
2. If the outcome is `needs_info`, build the answered record from that resolution's
   `questions_for_party`, run it again, and write that run to a `round-2/` folder inside the
   case's directory. Round one's files stay where they are.
3. Score the **final** resolution with `score_case`. Its `case_file` is the path of the final
   run, relative to `--out`: `<pack>/<id>/case_file.json`, or `<pack>/<id>/round-2/case_file.json`
   after a round two.
4. Any exception in either round is caught per case (as today) and scored with `score_error`.

`CaseScore` gains four fields (defaults in brackets), and `to_dict` emits all four:
`asked_in_round_one` (False), `decided_without_human` (False), `repeat_got` (None),
`consistent` (None). `score_case` sets `decided_without_human` to True only when the outcome is
`ruled`. A model failure, a run failure, a withheld ruling, `human_review` and `needs_info` are all
False.

`run_eval` gains `repeat: int = 1`. Refuse anything that is not a real int from 1 to `MAX_REPEAT`
(`bool` is not an int here) by raising `EvalError` **before** anything is created on disk. Each
case runs `repeat` times. Run 1 lives at `<pack>/<id>/`, run *n* at `<pack>/<id>/run-<n>/`. The
case's score **is run 1's**. When `repeat > 1`, `repeat_got` is the list of every run's `got`
text, and `consistent` is True only when every run's `got` is identical **and** no run is a
`model failed` or `run failed` (failing the same way twice is not a decision).

`EvalReport` gains `repeat: int = 1`, and `to_dict` emits `"repeat"`. `totals` gains three keys:
`decided_without_human`, `round_one_stops` (cases with `asked_in_round_one`), and `consistent` (the
count, or `None` when `repeat` is 1).

Headlines, in this order, in both the Markdown report and stdout:

```
Decisions matching the label: <n> of <cases>
Rulings citing every decisive rule: <n> of <applicable>
Decided without a human: <n> of <cases>
Stopped to ask the party in round one: <n> of <cases>
Same decision on all <repeat> runs: <n> of <cases>      (only when repeat > 1)
```

The Markdown table gains a last column, `Asked in round one`, holding `yes` or nothing. No
percentages anywhere, as today.

CLI: `--repeat N` (int, default 1). Out of range prints `error: ...` to stderr and exits 1 before
any case runs or any directory is created. Pass the value through to `run_eval`.

Keep `build_llm_client` and `resolve_pack_dir` imported at module level: tests patch them on the
module.

### Docs

- `README.md`:
  - Replace the status line with one that starts `**Status:` and says the system runs end to end
    on the real Tencent Cloud model (ADP), with the mock as the default for a fresh checkout.
  - Remove the word "skeleton" (the Run section's first sentence).
  - The gate paragraph in **Run** becomes "Five gates ... all five are enforced in Python",
    naming confidence, ESC-4, ESC-2, NS-6 and RD-5, and saying each withholds and none rewrites a
    ruling.
  - Add to **Run**: one sentence with `python3 -m app.eval`, `--llm tencent` and `--repeat 3`.
  - Delete the last line ("The demo walkthrough and its recording land once ...") and replace it
    with a new section, `## How this was built`: the code in `app/` and `ui/` was written in
    Tencent Cloud CodeBuddy; **a planning agent** wrote each session's brief and its failing tests
    first; CodeBuddy built until they passed; the result was re-checked by running it; the
    screenshots in `evidence/` record those sessions. **Never name the planning agent's tool or
    model**, in the README or anywhere else you write.
  - The Mermaid gate node becomes
    `J --> G{"Gates pass? Confidence, cap, measured deviation, NS-6, RD-5"}`.
- `docs/architecture.md`, **Gates enforced in code**: "Six gates" becomes "Eight gates", and two
  new table rows go after the ESC-2 row: an NS-6 row (`app/agents/judge.py`; names
  `driver_distance_from_pickup_m`, the SGD 10 limit, `fraud_flags` and the "no more than half
  rejected" condition) and an RD-5 row (`app/agents/judge.py`; names `fare.difference_sgd` and
  SGD 1.00). The same Mermaid gate node change as the README (a test keeps the two blocks
  identical).
- `docs/dataset.md`, `### Evaluation`: replace "Stopping to ask the party counts as a miss" with
  what happens now (round two answered with "I have nothing more to add", the final ruling scored,
  the stop counted on its own line), and add what "Decided without a human" and `--repeat N`
  ("Same decision on all N runs") mean. The subsection must stay at **15 non-blank lines or
  fewer** (an existing test counts them).

## Allowed files

`app/agents/judge.py`, `app/eval.py`, `README.md`, `docs/architecture.md`, `docs/dataset.md`.
Nothing else.

## Constraints

Standard library only. Python 3.9: no `match`, no `X | Y` unions. Run the full suite with
`/usr/bin/python3`, not a bare `python3`.

## Existing tests updated for this session (read, do not edit)

- `tests/test_eval_harness.py`: on the mock, RD-0106 is now `wrong outcome` (the RD-5 gate holds
  the mock's 0.66 refund; the label says refund 3.40), the totals gain the three new keys, and the
  JSON report gains `repeat` and the four new per-case fields.
- `tests/test_party_form_ux.py`: the frozen 35-run baseline now has RD-0106 `withheld` in both
  packs. No other case moves.

## What you should see on the mock when you are done

Organiser pack: 11 of 18 decisions matching, 14 of 18 decided without a human, 0 round-one
stops. Synth pack: 10 of 17, 13 of 17, 0. NS-0205 is a refund of 6.61 in both packs.

## Out of scope

The party page, the console and the server. The human decision step and the status page are the
next session's work. Do not run the live model: the operator runs the paid eval after review.
