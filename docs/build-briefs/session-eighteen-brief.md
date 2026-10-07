# Session eighteen brief: a failed model call goes to a human, never to a guess

Today, when a live model call fails (a timeout, a rate limit, the Tencent firewall, an ADP
error, or a reply the code cannot read), the run raises, the server deletes the run directory
and answers HTTP 500 `{"error": "internal error"}`, and the party page shows the words
"internal error". The operator gets nothing: the case file is gone. The operator reproduced
this on the real server before writing this brief.

This session changes that. A failure that may clear is retried; when the model still cannot
answer, the case is escalated to a human exactly like a withheld ruling: the party sees the
neutral under-review message, and the case file is kept with a record of what failed.

**Target:** `tests/test_w19_model_failure.py` (new, currently RED) green, and the full suite
(`/usr/bin/python3 -m unittest discover -s tests -t .`) green.

**Do not edit anything under `tests/`, `tools/`, `data/` or `ui/`.** If a test looks wrong, stop
and ask. Four existing test files were updated for this session on purpose (listed at the end);
they describe the new behaviour and are part of the target.

## The rulings (operator, 2026-09-30)

1. **Reuse the `withheld` outcome** with `UNDER_REVIEW_MESSAGE`. No new outcome, no party-page
   change, no change to `party_view`.
2. **Keep the case file.** It carries everything done before the failure (the Evidence Pack,
   whichever advocate cases were made) plus a `model_failure` record.
3. **Only model failures escalate:** an `LLMError` from the call, or a reply that cannot be
   read or breaks the output contract. Any other exception (a `TypeError`, a `KeyError`) is a
   defect in our code and must still propagate.
4. **A failure on the round-two re-run escalates too**, and the answered claim is kept, so the
   run can never be ruled twice. The server's answers route needs no change for this: an
   escalation returns normally, so the claim is never released.
5. **Retry what may clear, never what cannot.**
   - A **transient** failure is retried up to **3 times**, waiting **2, then 5, then 10
     seconds**: four attempts in all.
   - A **permanent** failure is never retried.
   - A reply that **cannot be read** is asked again **once**.
   - A reply that **parsed** is final, whatever it says. A low confidence or an amount over the
     cap goes to a human through the existing gates; it is never sent back to the model.
   - Only the failing agent's call is repeated. An agent that already answered is not called
     again.
6. **Time budget: 120 seconds per case**, from a new `llm.case_budget_seconds` config key.
7. **The eval harness** scores an escalated-on-failure case `model failed`: its own reason,
   never a match, never `wrong outcome`. Any such case makes `python3 -m app.eval` exit 2.

## The contract, file by file

### `app/llm/base.py` and `app/llm/__init__.py`

- New `class LLMTransientError(LLMError)`, exported from `app.llm`.
- `LLMRequest` gains `timeout_seconds: Optional[float] = None`: the most this call may take.
  It must **not** enter `fingerprint()`.

### `app/llm/tencent.py`: classify every failure

| Failure | Raise |
|---|---|
| HTTP 429, or any HTTP 5xx **except** the firewall's 501 | `LLMTransientError` |
| Cannot reach the endpoint (`URLError`, `OSError`, a socket timeout) | `LLMTransientError` |
| The connection broke mid-read (`http.client.HTTPException`) | `LLMTransientError` |
| Reply too large, not UTF-8, no `response.completed` event, no reply message, empty reply | `LLMContractError` |
| The firewall (501 or the `waf-captcha` marker, at any status), any other 4xx, an ADP `error` event | plain `LLMError` |

- Redaction in `complete()` must **keep the class**: re-raise `type(exc)(redacted message)`.
- The call's timeout is the configured `timeout_seconds`, or, when `request.timeout_seconds`
  is set, `max(1.0, min(configured, request.timeout_seconds))`.
- Update the module docstring: the "no retry loop" sentence is no longer true (the loop lives
  in the agent layer). Keep "no fallback to the mock".

### `app/agents/base.py`: the retry loop

Module constants: `RETRY_DELAYS_SECONDS = (2.0, 5.0, 10.0)`, `CONTRACT_REASKS = 1`, and a floor
of **5 seconds**: no call is started, and no retry wait is begun, unless at least 5 seconds of
the case's budget would be left for the call itself.

`RetryPolicy`, a frozen dataclass exported from `app.agents`:
`delays_seconds=RETRY_DELAYS_SECONDS`, `contract_reasks=CONTRACT_REASKS`,
`budget_seconds: Optional[float] = None` (None = no limit), `clock=None`, `sleep=None`. When
`clock`/`sleep` are None, use `time.monotonic`/`time.sleep`, **looked up at call time** (a test
patches `time.sleep`). `start()` returns a per-case budget object.

`ModelFailure(AgentError)`, exported from `app.agents`, carries `agent`, `kind`, `attempts`,
`message`, and `to_dict()` returning exactly those four keys. `kind` is one of
`"transient"`, `"permanent"`, `"unreadable reply"`, `"time budget"`.

`BaseAgent.__init__` takes an optional per-case budget (default: an unlimited one). `_ask`
becomes the loop, and building the typed result (`AdvocateCase.from_payload`,
`JudgeRuling.from_payload`) moves **inside** it, so a `ContractError` is re-asked like a parse
failure. Per attempt:

1. If the budget cannot cover a call, raise `ModelFailure(kind="time budget")`, with
   `attempts` = attempts made so far (0 if none).
2. Build the request with `timeout_seconds` = the budget's remaining seconds (None if unlimited),
   call the model, parse, build. Success returns.
3. `LLMContractError` or `ContractError`: if the re-ask is used up, raise
   `ModelFailure(kind="unreadable reply")`; otherwise log the retry and try again at once.
4. `LLMTransientError`: if the three retries are used up, raise
   `ModelFailure(kind="transient")`. If the budget cannot cover the next wait plus a call,
   raise `ModelFailure(kind="time budget")`. Otherwise log the retry, wait, try again.
5. Any other `LLMError`: raise `ModelFailure(kind="permanent")`.

The re-ask counter and the transient counter are separate. Each retry emits
`llm.call_retried`, from the agent's name to the agent's name, with a summary naming the
agent's role title, and a payload holding the failed attempt number, the kind, the message and
the wait. `ModelFailure` messages carry the (already redacted) adapter message; raise them
`from None`.

### `app/events.py`

`EventType.LLM_CALL_RETRIED = "llm.call_retried"` and
`EventType.DISPUTE_ESCALATED_ON_MODEL_FAILURE = "dispute.escalated_on_model_failure"`.

### `app/pipeline.py` and `app/schemas.py`

- `run_dispute(..., retry_policy=None)`. Start one budget per case and hand it to all three
  agents.
- Catch `ModelFailure` around the advocates and around the Judge (not around anything else),
  and escalate: emit `dispute.escalated_on_model_failure` (system to `human_review`), then
  `party.notified`, then complete the run as usual (`run.completed`, events snapshot).
- The resolution: outcome `withheld`, `UNDER_REVIEW_MESSAGE`, `escalated_for_human_review=True`,
  `ruling` and `withheld_candidate` both None, the extra notes the Judge would have carried,
  and one note that names the failing agent and the kind.
- The case file keeps the Evidence Pack and each advocate case that exists (None for one that
  never answered).
- `Resolution` gains `model_failure: Optional[Dict] = None`, always serialised (None when absent).

### `app/config.py` and `app/config.json`

`llm.case_budget_seconds: 120` in the JSON, with a line in `_readme`. `LLMSettings` gains
`case_budget_seconds: float` (default 120.0 when the key is absent). A value that is not a
positive number (0, negative, a string, a bool, null) raises `ConfigError`.

### `app/server.py`, `app/cli.py`, `app/eval.py`

Each passes `retry_policy=RetryPolicy(budget_seconds=<configured budget>)` to `run_dispute`.
The tests patch each module's `load_config` and `run_dispute`, so call them by those
module-level names. The server reads the budget **once**, in `make_server`, onto its state.

- **CLI:** a model failure is a completed run: exit 0, write the case file, and in the
  RESOLUTION block print a line naming the agent, the kind, the attempt count and the message.
- **Eval:** `REASONS` gains `"model failed"` between `"asked the party"` and `"run failed"`.
  `score_case`: a resolution whose `model_failure` is not None scores `model failed`,
  `decision_match` False, `error` = the failure's message. Its case file is written and its
  path recorded like any completed case. Exit 2 when any case is `model failed` or `run failed`.

### Docs

- `docs/architecture.md`
  - **LLM provider** section: add a paragraph stating the retry rules, with these exact
    strings: `2, 5 and 10 seconds`, `120 seconds`, `` `llm.case_budget_seconds` ``,
    `` `dispute.escalated_on_model_failure` ``, `` `llm.call_retried` ``, `` `model_failure` ``,
    "asked again once" and "never asked again".
  - Remove the sentence "Any failure raises an error".
  - **Four outcomes** table: the `withheld` row names the model failure.
  - **Limits**: remove the bullet "A failed model call is an error, not a referral". Replace it
    with one bullet saying the party waits while retries run, and is not notified later.
  - **Diagram**: add the edge `J -- "Model could not answer" --> H`.
- `README.md`: the same edge in its Mermaid block (a test keeps the two blocks identical).
  Nothing else in the README changes.
- `docs/dataset.md`, `### Evaluation`: one sentence saying a case the model could not answer is
  scored `model failed`, never a match, and makes the command exit 2. Keep the subsection at 15
  non-blank lines or fewer.

## Allowed files

`app/llm/base.py`, `app/llm/__init__.py`, `app/llm/tencent.py`, `app/agents/base.py`,
`app/agents/__init__.py`, `app/agents/judge.py`, `app/events.py`, `app/pipeline.py`,
`app/schemas.py`, `app/config.py`, `app/config.json`, `app/server.py`, `app/cli.py`,
`app/eval.py`, `docs/architecture.md`, `docs/dataset.md`, `README.md`. Nothing else.

## Constraints

Standard library only. Python 3.9: no `match`, no `X | Y` unions. No test may wait in real
time, so every wait goes through the policy's `sleep`.

## Existing tests updated for this session (read, do not edit)

- `tests/test_pipeline.py`: `ContractFailureTest` now expects escalation, not a raised
  `AgentError`, plus a new pin that our own `TypeError` still raises.
- `tests/test_adp_adapter.py`: the firewall, string-amount and `StringAmountRulingTest` pins now
  expect escalation; the guarantees (never retried, never converted) are unchanged.
- `tests/test_adp_hardening.py`: the CLI key-leak pin now expects exit 0 and the cause in the
  case file and on stdout, still with no key anywhere.
- `tests/test_eval_harness.py`: the new reason, and the outage case scored `model failed`.
- `tests/test_architecture_doc.py`: unchanged, but it now requires the two new event types in
  the doc.

## Out of scope

The operator console (`ui/app.js`) is unchanged: it shows a model-failure case as a withheld
case with no candidate, and its notes explain why. Background processing (answering the party
later, instead of inside the filing request) is a separate item.
