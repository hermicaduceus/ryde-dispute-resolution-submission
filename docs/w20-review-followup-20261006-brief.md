# W20 review follow-up, 2026-10-06

## Ruled scope

the operator chose: fix F2 trip restoration and both test gaps F3/F4, tidy F6 into an assertion; accept the rare-control-whitespace F1 as residue. F5 stays current different-trip-clears behaviour. W32 is complete and unchanged. No broad cleanup, no server grammar change, no whitespace alignment.

Starting merged build `680835ddf8c3453fa39c5d252d46527a73136182` already has the three W20 units. This follow-up only repairs remembered trip restoration across failed or invalidated reloads. The planner has already strengthened the parent-owned acceptance tests for F3/F4/F6; do not edit those tests.

## Acceptance

- Both roles and both categories: fill all details, Back starts a fresh trip GET which fails; trip Back then Continue retries a successful GET still listing A. Restore A, enabled Continue, all controls, description, amount, and serialized trip A without re-clicking.
- The same holds if trip Back abandons a pending details-Back GET, followed by retry.
- If a newer retry succeeds with A and an older response arrives with only B, keep the newer A and its draft. Preserve every W30 epoch check and no late scroll.
- Never select an unavailable trip when the current returned list omits it. Category/different-trip changes still clear question answers. Same-trip click preserves them. Continue must only use a trip from the current successful list.
- F3 delimiter/start-prefix near misses are refused under the existing exact grammar.
- F4 repeated Back/Continue WITHOUT trip re-click keeps the complete draft and serialized trip ID.
- F6 a mistakenly added follow-up cap fails the test assertion, not an uncaught error. Do not add a follow-up cap.

Parent-owned tests: `tests/test_w20_reload_restore.py`, `tests/w20_reload_support.py`, `tests/test_w20_back_state.py`, `tests/test_w20_intake_validation.py`. Instrumentation extends the existing fake DOM with deterministic failed/pending trip GETs. Parent also owns independent browser and mutation gates.

## Existing proof

Focused acceptance on unchanged runtime: 18 tests, 12 assertion failures, zero errors, all failed/pending reload restoration.

A disposable scratch reference passes the FULL 1189-test suite. Six unique deliberate defects all fail only assertions: S11 delimiter loosened (20 failures), S12 unanchored grammar (40), U13 visual-only selection (16), S15 forbidden reply cap (1), whole F2 selection fix reverted (12), stale-success epoch guard removed (4). The reference is deleted before this dispatch. Implement independently; the reference source is not your brief.

## Exact write allowance

- `ui/party/party.js`: minimal remembered-trip restoration repair and a short accurate comment if needed. Preserve unrelated bytes and all existing state/reset/request safety contracts.
- Only the party.js SHA values in `tests/test_party_rebrand.py`, `tests/test_w12_demo_notice.py`, `tests/test_w15_feedback.py`, `tests/test_w15_layout.py`. All four exceptions previously approved by the operator; replace only that SHA and preserve every assertion and other hash.

NO other writes: all app Python, Judge, prompts, UI styles/HTML, acceptance/support tests, settings, memory, generated output, documentation are immutable to this builder. Do not add constants that need unrelated changes. Commit exactly your allowed files on this branch. The planner owns merge and review.

No secrets, live APIs/network, installs, delegation or bypass permissions. Preserve deny/ask rules. Reuse the existing named CodeBuddy session, flash max, explicit process-local permissions. Test command: `env -u PYTHONPATH /usr/bin/python3 -m unittest discover -s tests -t .`. Stop with a precise blocker if the contract cannot be met. Full GREEN expected on this prepared baseline, not sibling RED.
