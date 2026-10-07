# W15 action-bar repair, the operator approved 2026-10-06

The GLM review endorsed all three feedback fixes. A separate W15-original regression remains: sticky .step-actions cover category options on mobile AND desktop. the operator approved normal-flow action bars at all widths, then verification and re-review. This supersedes the original sticky-action requirement in docs/build-briefs/w15-brief.md. The three endorsed feedback changes remain untouched.

## Exact implementation scope

Allowed UI write: ui/party/party.css only.

- In the existing .step-actions block replace position: sticky with position: static.
- Remove bottom: 0. No media-query exception, added override or fixed/absolute positioning.
- Leave display, justification, gap, margins, padding, card background, top border, radius and all buttons unchanged.
- The top file comment may be corrected from sticky to normal-flow. No unrelated formatting.
- tests/fixtures/colour_ledger.json may be regenerated ONLY through /usr/bin/python3 tools/colour_ledger.py --write if line-number movement requires it.

No HTML, JS, copy, console CSS, app, data, tools, test-source or docs edits. the planner already updated the governing brief and tests under the operator's explicit approval. No commit, push, stash, reset or branch switch. Preserve all existing uncommitted W15 and feedback changes.

## RED-first gates already prepared

- tests.test_w15_layout: sticky requirement replaced with the approved static/no-bottom requirement. Retains all action-bar surface assertions.
- tests.test_w15_feedback: adds the all-width cascade assertion; preservation hash excludes ONLY approved .step-actions position/bottom in addition to original feedback rules. All other CSS, HTML and JS freezes stay unchanged. No whole-file rebaseline.
- Combined focused suite: 27 methods, 2 assertion failures, zero errors on the actual current sticky implementation.
- tests/browser/w15_actions.cjs: actual geometry, option-center hit testing and direct initial pointer clicks. Both rider and driver, six sizes each, category/trip/details intermediate states. Browser RED on the actual sticky implementation is an overlap assertion, not a missing symbol or test crash.
- Tests were proven satisfiable in a disposable reference: focused and full suite GREEN, real-browser 12 views / 36 stages GREEN. The reference does not cross into this repo.

## Run these commands

/usr/bin/python3 -B -m unittest tests.test_w15_layout tests.test_w15_feedback -q
/usr/bin/python3 tools/colour_ledger.py --write
/usr/bin/python3 -B -m unittest discover -s tests -t . -q
git diff --check

Expected full suite: 1104 OK. the planner runs independent real-browser verification and the shipped-code mutation battery. Do NOT read outside the repo or run a browser yourself.

the operator has already approved this exact two-declaration repair. Make it, run the checks and report exact diff/files/results. No need for another plan gate. Do not commit.
