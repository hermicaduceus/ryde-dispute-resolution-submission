# Evidence plan (§8 proof of product usage)

The competition's rule 8 is a scoring gate: without proof of CodeBuddy/WorkBuddy usage the
project is **not scored at all**. Evidence accumulates as work happens; it cannot be
reconstructed later.

## Rules

1. **Screenshots are the proof.** Take a screenshot of the real chat interaction whenever one
   happens: prompt visible, tool's response visible. The minimum bar is three CodeBuddy/WorkBuddy
   chat screenshots; the habit targets one per working session.
2. **Naming:** `YYYY-MM-DD_<tool>_<topic>.png` — tool is `codebuddy-cli`, `codebuddy-ide`,
   `workbuddy` or `miora`; topic is short and deliverable-anchored, e.g.
   `2026-09-22_codebuddy-cli_evidence-pack.png`.
3. **Store in `evidence/`** (this folder), moved in the same working session it was taken. At
   submission, this folder sorted by name is the evidence exhibit.
4. **CLI transcripts are the backstop**, not the primary proof: CodeBuddy CLI sessions write
   transcripts automatically to `~/.codebuddy/projects/`. Curated excerpts may be added as
   supplementary proof late in the build.
5. **Prompts target named deliverables.** Development prompts name the file, test or deploy they
   are for; no exploratory filler in the evidence pile.

## Session-end checklist

- [ ] Screenshot(s) from this session in `evidence/`, correctly named
- [ ] Anything notable about how the tools behaved is noted in `docs/tool-experiences.md`