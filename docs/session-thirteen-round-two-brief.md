# Session thirteen, round two — colour means status, nothing else

Round one (W18 token pass) is on disk and uncommitted. the operator reviewed it live and ruled
(2026-09-27): **colour only where it carries meaning**. Anything that is just "which side"
or "a number" or "a label" is neutral. The four failing tests in
`tests/test_console_rebrand.py` pin this. Do not edit tests.

## The colour map this round enforces

| Colour | Meaning | Where it stays |
|---|---|---|
| Green | Delivered to the parties | ruled card, ruled badge, and the party message **only inside `.outcome-ruled`** |
| Amber | Withheld / human-only | withheld card + badge, the withheld party message, the human-only region, the `judge.ruling_withheld` event row, the null-citation chip |
| Blue | Routed (human review, waiting on the party) | as today |
| Red | Error | as today |
| Pink | Ryde brand chrome | loader, section numbers, markers, citation chips, event log, focus ring |

Everything else is neutral: `--ink`, `--muted`, `--faint`, `--line`, `--panel`, `--canvas`.

## Changes, all in `ui/styles.css`

1. **Advocate cards, both sides identical and neutral.**
   - `.claim-card`: `border-top` uses `var(--line)`, not the accent.
   - `.claim-card-header`: background `var(--panel)`.
   - `.claim-driver` and `.claim-driver .claim-card-header`: remove every colour, background
     and border declaration (deleting the rules outright is fine). The driver must not look
     different from the rider, and amber on the driver reads as a warning about the driver.
2. **The rider's quote** `.claim-text`: neutral (`--canvas` background, `--ink` rule on the left).
3. **Money amounts** are not deliveries. `.info-row.highlight dd`,
   `.request-grid .info-row.highlight dd`, `.resolution-metrics .info-row.highlight dd`:
   `--ink`, keep the weight.
4. **Missing data is information, not an alarm.** `.evidence-field.has-null`,
   `.field-value.is-null`, `.evidence-note`, `.note-label`: neutral (grey wash, muted text).
   Drop the brown/amber hex literals (`#77511e`, `#f0d9b4`).
5. **Expected absence** `.deliberate-empty`, `.deliberate-empty h3`, `.deliberate-empty p`:
   neutral, same treatment.
6. **Policy rules are not deliveries.** `.policy-item`: neutral chip. `.citation-policy` and
   `.citation-policy:hover`: remove their green, so a policy citation inherits the pink
   `.citation` chip like every other citation.
7. **The party message box.** Base `.party-message` and `.party-message-label` become neutral.
   Add two rules that restore green on the delivered case only:
   ```css
   .outcome-ruled .party-message { background: var(--green-wash); border-color: #b9d9c5; border-left-color: var(--green); }
   .outcome-ruled .party-message-label { color: var(--green); }
   ```
   The existing `.party-facing-region .party-message*` rules stay amber (withheld). The
   human-review and waiting cards then show a neutral message box, and their blue badge
   carries the meaning.

## Trap: duplicate selectors

`.note-label` and `.party-message-label` each appear in **two** rules (a shared typography
rule near the top, and a specific rule further down). The tests read every rule with that
selector. Fix the one that carries the colour; do not leave a coloured copy behind.

## Prohibitions (unchanged from round one)

`ui/app.js` byte-identical; no id, copy, layout or HTML changes; only `ui/styles.css` changes
this round; no test edits; do not commit.

## Acceptance

`python3 -m unittest discover -s tests -t .` → **437 OK** (currently 4 failing on purpose).
If a test cannot be satisfied or this brief conflicts with the repo, stop and report.
