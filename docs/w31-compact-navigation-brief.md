# W31 compact consistent filing navigation
the operator approved fixing rider/driver consistency: compact wrapped vertical gap, rider middle dot, smaller labels on BOTH filing pages. Headless CodeBuddy flash/max. Only ui/party/index.html, ui/party/driver-filing.html, ui/party/party.css. No JS, console CSS, wording/destination changes, settings, commits/push/memory/test edits.

1. Rider HTML: replace ONLY the two adjacent navigation p elements with one `<p class="party-nav">`, retaining exact two anchors/destinations and inserting ` · ` between them. No other HTML bytes change.
2. Driver HTML: add `class="party-nav"` to the existing header navigation p holding its three anchors and dots. No other HTML bytes change.
3. Replace ONLY the final rider-specific paragraph rule and its explanatory comment in party.css with shared rules:
`.party-header > .party-nav { display:flex; flex-wrap:wrap; align-items:center; gap:0.5rem; margin:1rem 0; }`
`.party-header > .party-nav a { font-size:0.9rem; }`
Keep all existing pill styling, min44px tap targets, focus/hover, driver flex rule and forms intact. Shared p removes doubled paragraph margins. 0.9rem = 14.4px at default root, like the driver helper above. Do not apply smaller text to status/account links or controls.

Parent owns authorized HTML frozen-hash updates only after verifying all non-navigation HTML byte-identical. Exact CSS exclusions updated, new immutable nav tests RED (5 methods, 3 assertion failures). Parent verifies real geometry/fonts/dots, tests, and ledger. No Bash needed. Read back and report.
