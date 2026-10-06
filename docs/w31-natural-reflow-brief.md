# W31 queue natural-reflow repair
the operator authorized content-driven progressive field wrapping instead of a 1000px whole-row switch. Explicitly waived another GLM review for this small change. Parent still runs regression/browser checks. Continue headless flash/max. Only ui/styles.css edit; no HTML/JS/party.css/text/tests/ledger/settings/commits/push/memory edits.

Replace ONLY the final W31 follow-up @media(max-width:1000px) block and its comment with these all-width rules. Keep the original base queue grid untouched but override its display with a more specific selector, preserving frozen colour/spacing rules. This intentionally supersedes the previous desktop grid layout requirement, not its visual styling.
- `.queue-list > .queue-row`: display:flex; flex-wrap:wrap. Retain existing gap/alignment/padding/border.
- `.queue-row > span`: flex:1 1 140px; min-width:0; max-width:100%. Each field keeps a readable basis and wraps to a new line as container space runs out.
- `.queue-row > .queue-safety`: flex:0 1 auto; overflow-wrap:anywhere. Inherit span max-width and min-width. Compact badge, not an empty fixed column.
- `.queue-row > .queue-open`: flex:0 0 auto; min-height:44px; max-width:100%. Button may move to next line but never be squeezed/cropped.
- `.queue-open-status`: flex:1 0 100%. Add this property to its existing rule; preserve role/empty hiding/error styling and existing grid-column declaration harmless in flex layout. Status always gets its own full-width line when populated.
No breakpoint, no transition animation, no overflow:hidden, no sorting/reordering of fields. Rider header already wraps naturally, leave alone. Parent adjusted responsive tests to new contract and confirmed RED (2 assertions), authorized exact new CSS selector exclusions in W15 preservation. Parent will run tests and real geometry sweeps. Read back and report exact diff.
