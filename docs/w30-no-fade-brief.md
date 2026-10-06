# W30 final visual comment: remove trip-list fade

the operator's marked comment requests removal of the shade at the bottom of the trip list. Partial cards and the scrollbar already indicate more content. This supersedes the older fade requirement only.

Edit ONLY `ui/party/party.css`: delete the `background` declaration carrying both gradients inside `#step-trip #trip-options`. Delete the obsolete gradient explanation from that rule's preceding comment. Do not add replacement decoration or change another property/selector. Preserve every other CSS byte outside that deletion/comment. No HTML/JS/layout/button/spacing changes, no tests/fixtures/docs edits, no commits/pushes.

Read/Edit tools only. Parent updated the no-fade pins and verified a deleted scratch reference with the full 1160-test suite. Parent owns colour-ledger removal, tests, browser/pixel checks and proof. Do the scoped edit and stop, no shell or extra exploration required.
