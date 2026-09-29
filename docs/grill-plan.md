# Post-Build Grill Session — Plan (agreed 2026-09-25)

A full grill session runs **after the MVP floor stands and before polish**:
demo path running end to end (intake → both advocates → Judge → case-file view,
both categories), then grill, then amendments, then polish.

## Why

Catch gaps while there is still time to fix them. The base being already built
means a surfaced gap costs an amendment, not a redesign.

## Scope and standard of attack

Two tiers, different bars:

1. **Unlocked surfaces first** (cheap to fix, grilled hard):
   - Demo-day rubric gaps — 40/100 points are story/design/presentation.
     README, docs/architecture.md, and the walkthrough get attacked as hard
     as code.
   - Failure surfaces — LLM returns malformed output; confidence threshold
     fires mid-demo; "what if the rider lies?" Live answers required.
   - Honesty surface — replay vs live demo labeling, evidence screenshots,
     the "built on CodeBuddy" claim held up to a skeptical judge.

2. **Locked decisions second** (grill with the concrete-harm bar):
   - For each locked decision in CODEBUDDY.md, the grill must name a
     **concrete harm** — a rubric line lost, a demo failure caused, a
     dishonesty risk, or a judge question it cannot survive.
   - "Concrete harm or it stands." No preference-based re-litigation
     ("would framework X have been nicer?").
   - Known open edge that MUST reach a ruling here: what happens the first
     time a real defect lives only in `app/` under the CodeBuddy-only rule.

## Method

Grill against the **running system**, not memory of it: the operator drives the demo,
the planner attacks it. Doubles as demo rehearsal.

## Amendment rule

If a locked decision falls, amend CODEBUDDY.md in the same session. The lock
is a decision record, not a shrine.