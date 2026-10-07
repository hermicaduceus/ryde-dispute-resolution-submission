# Session ten brief: W12 — a demo notice on party decisions made without a real LLM

Deliverable: when a ruled case's LLM record does not PROVE the real provider, the
party view's decided message must lead with a fixed demo notice. RED acceptance tests
are already committed at `tests/test_w12_demo_notice.py` (commit a9a9e85); your job is
to make them green without breaking any existing test.

## The problem

The mock provider (`app/llm/mock.py`) prefixes its free-text fields with "MOCK", but the
party decision message is built in code from action + amount + rule titles
(`party_message_for_ruling` in `app/schemas.py`), so on a mock run the party page reads
"Decision: refund of SGD 5.81. Basis: ..." with no marker. A filmed mock ruling is
indistinguishable from a live-model ruling. W12 fixes this on the party view only.

## Exact requirements

1. Add a fixed constant `DEMO_NOTICE_MESSAGE` in `app/schemas.py`. It must:
   - be a non-blank string;
   - pass `is_party_safe` (no ai/agent/advocate/judge/confidence/withheld/escalate/model
     stems, no rule-id-shaped tokens);
   - contain the word "demo" (lowercase check in the tests);
   - state in plain party language that this decision came from an illustrative run and
     is not a live review. Suggested wording (you may improve it, keeping the word
     "demo" and the party-safe constraints): "Demo notice: this decision was produced by
     an illustrative run and is not a live review. "
2. In `party_view` (`app/server.py`): when the view's status is "decided", prepend
   `DEMO_NOTICE_MESSAGE` to the message UNLESS the ruling's LLM record proves the real
   provider. Proving means ALL of: `resolution.ruling.llm` is a non-array dict whose
   `"provider"` value is exactly the string "tencent". Everything else — missing record,
   `"mock"`, arrays, empty objects, wrong type, inexact strings like "Tencent" or
   " tencent" — shows the notice. Fail closed: the burden of proof is on the record.
3. Only the "decided" status gets the notice. "under_review", "passed_to_support" and
   "needs_info" views show exactly what they show today (their canonical constants).
4. The five-key party view contract is unchanged: run_id, dispute_id, status, message,
   questions — the notice rides the message value, no new key.
5. `ui/party/party.js` must remain byte-identical (a test pins its SHA-256). No HTML,
   CSS or JS changes are needed and none are wanted.
6. Update `docs/architecture.md` honestly: the "llm provider" section and the "what the
   parties see" section currently say the party decision message carries no marker. They
   must now describe the demo notice: it appears on decided views whenever the ruling's
   LLM record does not prove the tencent provider, and a proven real-provider decision
   shows no notice. The doc test greps for the phrase "demo notice".

## Constraints (standing project rules)

- Plain stdlib only; match the existing code style exactly (this file set uses no
  type-checker hints beyond what exists).
- The guard must be a SHAPE check, not a type check: `isinstance(llm, dict)` excludes
  arrays in Python, but the field inside can still be a list or dict — probe the tests'
  WRONG_LLM_SHAPES list; every one of them must show the notice.
- A fix is not done until a test fails when the fix is reverted — the committed RED file
  is that pin; do not weaken or edit `tests/test_w12_demo_notice.py`. You are also
  barred from editing any file under `tests/` (build-lane fence).
- All 392 existing tests must stay green; the full suite is 405 with the new file.
- Do not change `app/llm/mock.py`, `app/pipeline.py`, `app/agents/`, `data/`, or
  `docs/policy.md`: the change lives in `app/schemas.py` (the constant) and
  `app/server.py` (the prepend) plus the two doc sections.

## Verification (run these yourself before declaring done)

- `python3 -m unittest tests.test_w12_demo_notice -v` → 13 tests, all green.
- `python3 -m unittest discover -s tests -t .` → 405 tests, all green.
- Confirm the notice appears on the party page: `python3 -m app.server`, open
  http://127.0.0.1:8000/party/, file the route-deviation dispute for any trip, and read
  the decision screen: the demo notice must be the first text above the decision.