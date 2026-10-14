# CodeBuddy conversation history

The top-level reading copies cover 7 selected real development sessions and 214 recorded user/assistant messages. These are exports of logs saved when the work occurred, not newly generated accounts of development.

The [baseline archive](archive/README.md) contains the 56 saved Ryde conversations exported and audited on 12 October: 990 message records and 8,220 tool-event records, including probes and interrupted sessions. Its GLM verdict is PASS_WITH_NOTES with the minor native-path finding corrected; its disclosed coverage limits remain below. **That audit applies to the baseline only, not whole-repository/publication clearance or newer additions.** The 11 one-sided/empty logs are listed in its unchanged manifest.

## Final-build additions, 14 October

The [later-history index](additions-20261014/README.md) adds 8 saved W43/W44/W47 conversations, 109 message records and 902 tool-event records. The baseline plus additions contains **64 distinct conversations, 1099 message records and 9122 tool-event records** at the 14 October export cutoff. The selected reading copies overlap the baseline and are not counted again.

**Addition status: independently reviewed on GLM 5.3, PASS_WITH_NOTES.** Earlier transcripts and manifests are unchanged. A later CodeBuddy session requires another inventory check. The old audit does not clear these additions; W6 publication and form placement remain separate.

## Start here

| Session | Recorded date | Messages | Reading copy |
|---|---|---|---|
| Initial three-agent pipeline build | 2026-09-21 | 30 | [2026-09-21_codebuddy-cli_01-core-pipeline.md](2026-09-21_codebuddy-cli_01-core-pipeline.md) |
| Party-facing forms and delivery | 2026-09-23 | 78 | [2026-09-23_codebuddy-cli_02-party-surface.md](2026-09-23_codebuddy-cli_02-party-surface.md) |
| Tencent Cloud ADP adapter | 2026-09-28 | 30 | [2026-09-28_codebuddy-cli_03-tencent-adp-adapter.md](2026-09-28_codebuddy-cli_03-tencent-adp-adapter.md) |
| ADP adapter hardening | 2026-09-29 | 12 | [2026-09-29_codebuddy-cli_04-adp-hardening.md](2026-09-29_codebuddy-cli_04-adp-hardening.md) |
| Policy-forbidden refund repair | 2026-10-03 | 20 | [2026-10-03_codebuddy-cli_05-refund-safety-repair.md](2026-10-03_codebuddy-cli_05-refund-safety-repair.md) |
| Party status and human-review backend | 2026-10-03 | 38 | [2026-10-03_codebuddy-cli_06-human-loop-backend.md](2026-10-03_codebuddy-cli_06-human-loop-backend.md) |
| Human-review console | 2026-10-04 | 6 | [2026-10-04_codebuddy-cli_07-human-review-console.md](2026-10-04_codebuddy-cli_07-human-review-console.md) |

## What each file contains

- Markdown is the reading copy. Included user/assistant messages are reproduced in full, in source order, with timestamps and source-record numbers. Stored user-role records include ordinary prompts, automatic notices and mixed carriers. Export labels classify the content rather than prove the identity of its author.
- Paired JSONL contains those messages and the recorded tool-call arguments/results. Reasoning, snapshots, automatic compaction summaries and tagged local-command display are omitted from the selected copies; command input and task notifications that survived the selection remain separately labelled. Non-text message blocks are represented structurally rather than invented. Outputs are preserved as recorded; if CodeBuddy stored a large result in a separate `tool-results` file, that external file is not bundled here.
- `manifest.json` gives original-log checksums, export checksums, exact inclusion counts and omissions. Original unsanitized logs remain outside this repository in the private CodeBuddy session store.
- The native ADP `.txt` example was produced by CodeBuddy itself using `/resume` and `/export`. It captures a rendered terminal view, including collapsed tool output, so it is a supplementary example rather than the authoritative complete log.

## Privacy edits and provenance

The exporter mechanically replaces the local home path with `[USER_HOME]`, local project-store prefixes with `[LOCAL_PROJECT]-`, email addresses with `[REDACTED_EMAIL]`, cloud account IDs with `[REDACTED_ACCOUNT_ID]`, credential-shaped values with `[REDACTED_SECRET]`, and named operator/planner/teammate references with generic roles. No message is paraphrased, corrected or rewritten to improve the development story. Checksums identify the original private logs, not the redacted derivatives.

This folder is a selected history, not every development session. Automatic compaction checkpoints are excluded because they duplicate and summarize previous material; original recorded messages before those checkpoints are retained. A native export may show only the active compacted view, while these mechanical exports read the full saved log. Assertions about tests or commits in historical messages remain the participants' claims. Later reviews and repairs may supersede them. In particular, the ADP development sessions do not claim to record the later successful live-call verification.

Screenshots in the parent evidence folder and the platform usage export are separate proof artifacts. These text exports do not replace the minimum screenshot requirement.

Publication status: locally prepared and privacy-filtered, but still subject to the final W6 whole-repository/publication review. Nothing here has been committed or pushed by the export step.

## Audit and presentation notes

- Additional privacy replacements mask lowercase OS username, macOS per-user temp roots, numeric CodeBuddy uid fragments and the export workspace. Original private logs are unchanged.
- Both selected and archive copies use the same content-aware label vocabulary. Machine summaries/notices, local command/skill expansions and provider errors are distinguished from ordinary recorded user-side messages. A mixed carrier is labelled as such without claiming who authored its trailing instructions.
- Each message is blockquoted; machine/XML blocks are fenced literally so tags or embedded headings cannot hide text or create false conversation boundaries. Nonprinting controls are shown as literal \uNNNN in Markdown; their original encoded values remain in JSONL.
- Automatic checkpoints quote earlier conversation and sometimes tool arguments. Those quotations are retained as machine text, not fresh human turns.
- External bg-task/tool-results files and binary attachments referenced by a record are not bundled. A dead historical path is not a working evidence link.
- Model/effort identifiers are retained deliberately: they are development provenance, not credentials. Old failures, denied tools, incorrect claims and superseded counts remain honest history.
- The initial readers covered all 56 conversations, with long automatic checkpoint middles skimmed in 8 sessions. The independent GLM reviewer then read all 9 checkpoint bodies from those 8 sessions in full. Conversation-message and checkpoint review is complete; tool arguments/results were pattern-scanned, not all semantically read line by line. A clear pattern scan is not proof of universal privacy.
- Reader classifications and recorded-outcome notes are review claims, not fresh test verification. Independent GLM review is complete. Its only minor finding was a wrapped export-workspace path in the supplementary native file; that path is now masked and its checksum updated.

The native terminal capture has one additional privacy replacement for a quoted export-workspace path split by terminal wrapping. Nothing else in that native screen text was rewritten. Original private logs remain unchanged.
