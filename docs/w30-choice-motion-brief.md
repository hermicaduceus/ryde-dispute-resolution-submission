# W30 final quick fix: page-3 Yes/No hover lift

the operator asks for Yes/No buttons to have the same pop-up hover motion as category/trip option cards, both rider and driver filing pages. the operator explicitly waived GLM review for this follow-up; final visual check is theirs.

Edit ONLY ui/party/party.css. Add the existing .option-card transition verbatim to .choice-button. Add the existing 2px hover lift and token floating shadow to .choice-button:hover. Keep every original property, selector, selected appearance, colour, size, spacing, HTML and JavaScript unchanged. Add a choice-only prefers-reduced-motion: reduce media block that sets .choice-button transition:none and .choice-button:hover transform:none. Keep hover colour/shadow feedback without movement. Do not alter other controls' motion or add click/focus movement.

Read/Edit tools only; no shell, tests, fixtures, docs edits, commits or pushes. Parent owns the narrowly audited colour ledger addition and test-preservation carve-out. Tests tests/test_w30_choice_motion.py and tests/browser/w30_choice_motion.cjs proved against a deleted disposable reference: full suite 1164 OK, five declaration deletion mutants assertion-RED, browser verifies actual hover movement, both answers' exclusive selection and real keyboard focus. Implement the scoped CSS and stop.
