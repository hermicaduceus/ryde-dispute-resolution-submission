# Publication substitutions (applied before the repository went public)

Before publication, one mechanical text replacement ran over every file in every commit of this
repository, these transcripts included, and over every commit message. It adds to the privacy edits
described in `README.md`:

| Original | Replaced with |
|---|---|
| the planning agent's name (two spellings) | `the planner` |
| the operator's initials | `the operator` |
| a second coding agent's product name | `another coding agent` |
| a reviewer model's family name and version | `a second-model` / `second-model` |
| that model's vendor | `the vendor` |
| the local home directory | `[USER_HOME]` |

All commits carry one team author identity. No message was paraphrased and no tool output was
rewritten to change what it reports. Folder names inside paths were left as they are, because the
unedited screenshots show them too. Screenshots were not edited. The platform usage export
(`evidence/2026-10-10_codebuddy-cli_47-usage-export-api-call-log.xlsx`) received the same
replacements inside the prompt text of its cells only; its 243 rows, 1,458 cells and every other
value are unchanged. A PowerPoint lock file committed by mistake was removed from history.

## Export checksums after publication

The 16 October metadata check found that some recorded export checksums no longer matched the
published transcript files. Publication substitutions changed transcript bytes after the earlier
exports; this refresh checks the shipped bytes without rewriting any conversation text.

`markdown_sha256`, `jsonl_sha256` and the native example's `sha256` describe the files now shipped.
Where an export digest changed, `previously_recorded_export_sha256` preserves the replaced value;
it is not the current published-file checksum. The original `source_sha256` values, source-log
inventories, counts and recorded review outcomes are unchanged. No claim is made that each old
export digest has been independently traced to a particular substitution.

`baseline_archive_source_sha256` in an additions manifest records the baseline-manifest input
used at that historical export. It is not the current archive-manifest checksum. Changing its
export-digest metadata does not change the source logs or extend an earlier content review.
