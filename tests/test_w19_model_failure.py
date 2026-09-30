"""W19 acceptance target: a failed model call goes to a human, never to a guess.

RED until the build lane ships session eighteen. the operator's rulings, 2026-09-30:

1. The escalation reuses the existing `withheld` outcome and the neutral under-review
   message. No new outcome, no party-page change.
2. The case file is KEPT, carrying the failure (agent, kind, attempts, redacted cause).
3. Only model failures escalate: a failed call, or a reply that cannot be read. A defect
   in our own code still fails loudly.
4. A failure on the round-two re-run escalates too, and the answered claim is kept, so
   the run can never be ruled twice.
5. Retry what may clear, never what cannot:
   - a transient failure (timeout, dropped connection, HTTP 429, HTTP 5xx other than the
     firewall's 501) is retried up to 3 times, after 2, 5 and 10 seconds;
   - a permanent failure (the firewall, any other 4xx, an ADP error event) is never retried;
   - a reply that cannot be read is asked again ONCE;
   - a reply that parsed is final, whatever it says: no re-asking for a better verdict;
   - only the failed agent's call is repeated, never an agent that already answered.
6. Time budget: 120 seconds per case (option A), from app/config.json. A retry that the
   budget cannot cover is not attempted, and each call's timeout is cut to what is left.
7. The eval harness scores these cases "model failed", its own reason, never a match
   and never "wrong outcome", and any such case makes `python3 -m app.eval` exit 2.

No test sleeps in real time and none touches the network.
"""

from __future__ import annotations

import io
import json
import re
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from app.events import EventLog
from app.llm import LLMContractError, LLMError, LLMResponse, MockLLMClient
from app.pipeline import run_dispute
from app.schemas import UNDER_REVIEW_MESSAGE

from .support import ROUTE_DEVIATION, load_fixture_dispute, load_fixture_policy
from .test_adp_adapter import FIREWALL_FIXTURE, REPLY_FIXTURE, _client, _http_error, _patched, _request

ROOT = Path(__file__).resolve().parent.parent


def _w19():
    """The new names, imported late so every test fails on its own, not at import."""
    from app.agents import ModelFailure, RetryPolicy
    from app.agents import base as agent_base
    from app.llm import LLMTransientError

    return ModelFailure, RetryPolicy, LLMTransientError, agent_base


class _Clock:
    """A fake monotonic clock. sleep() advances it; a call can cost time too."""

    def __init__(self):
        self.now = 0.0
        self.slept = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


class _Plan(MockLLMClient):
    """The mock, except each agent follows a script of failures before answering.

    A script entry is an exception to raise, or a string to return as the raw reply.
    When an agent's script runs out it answers like the mock. `cost` advances the fake
    clock by that many seconds per call.
    """

    def __init__(self, plan, clock=None, cost=0.0, **kwargs):
        super().__init__(**kwargs)
        self.plan = {agent: list(steps) for agent, steps in plan.items()}
        self.clock = clock
        self.cost = cost
        self.requests = []

    def complete(self, request):
        self.requests.append(request)
        if self.clock is not None:
            self.clock.now += self.cost
        steps = self.plan.get(request.agent)
        if steps:
            step = steps.pop(0)
            if isinstance(step, BaseException):
                raise step
            return LLMResponse(text=step, provider="mock", model="scripted")
        return super().complete(request)

    def agents(self):
        return [r.agent for r in self.requests]


def _config_with_budget(seconds):
    """A load_config stand-in: the real config, with the case budget replaced."""
    import dataclasses

    from app.config import load_config

    real = load_config()
    patched = dataclasses.replace(real, llm=dataclasses.replace(real.llm, case_budget_seconds=seconds))
    return lambda *args, **kwargs: patched


def _run(test, llm, *, clock=None, budget=None, **policy_kwargs):
    _, RetryPolicy, _, _ = _w19()
    clock = clock or _Clock()
    tmp = tempfile.TemporaryDirectory()
    test.addCleanup(tmp.cleanup)
    run_dir = Path(tmp.name) / "run"
    case_file = run_dispute(
        dispute=load_fixture_dispute(ROUTE_DEVIATION),
        llm=llm,
        policy=load_fixture_policy(),
        events=EventLog(run_dir, "w19"),
        confidence_threshold=0.65,
        retry_policy=RetryPolicy(budget_seconds=budget, clock=clock, sleep=clock.sleep, **policy_kwargs),
    )
    return case_file.to_dict(), clock, run_dir


def _transient(text="HTTP 503"):
    return _w19()[2]("ADP call failed: %s" % text)


# ------------------------------------------------------------ 1-2: escalate and keep


class EscalationShapeTest(unittest.TestCase):
    def _escalated(self):
        llm = _Plan({"judge": [LLMError("ADP returned error 4505004: App key invalid")]})
        return _run(self, llm)

    def test_the_outcome_is_withheld_with_the_neutral_message(self):
        case, _, _ = self._escalated()
        resolution = case["resolution"]
        self.assertEqual("withheld", resolution["outcome"])
        self.assertEqual(UNDER_REVIEW_MESSAGE, resolution["party_message"])
        self.assertTrue(resolution["escalated_for_human_review"])
        self.assertFalse(resolution["delivered_to_parties"])
        self.assertIsNone(resolution["ruling"])
        self.assertIsNone(resolution["withheld_candidate"], "the Judge never answered: no candidate exists")

    def test_the_failure_is_recorded_for_the_reviewer(self):
        case, _, _ = self._escalated()
        failure = case["resolution"]["model_failure"]
        self.assertIsInstance(failure, dict)
        self.assertEqual({"agent", "kind", "attempts", "message"}, set(failure))
        self.assertEqual(("judge", "permanent", 1), (failure["agent"], failure["kind"], failure["attempts"]))
        self.assertIn("4505004", failure["message"])
        self.assertTrue(any("judge" in note and "permanent" in note for note in case["resolution"]["notes"]),
                        case["resolution"]["notes"])

    def test_the_work_done_before_the_failure_is_kept(self):
        case, _, _ = self._escalated()
        self.assertIsNotNone(case["evidence_pack"])
        self.assertIsNotNone(case["claims"]["rider"], "the rider advocate answered; its case must survive")
        self.assertIsNotNone(case["claims"]["driver"])

    def test_an_advocate_failure_keeps_what_existed_and_nothing_more(self):
        llm = _Plan({"driver_advocate": [LLMError("the Tencent web firewall blocked the request (HTTP 501)")]})
        case, _, _ = _run(self, llm)
        self.assertIsNotNone(case["claims"]["rider"])
        self.assertIsNone(case["claims"]["driver"])
        self.assertEqual("driver_advocate", case["resolution"]["model_failure"]["agent"])
        self.assertEqual(["rider_advocate", "driver_advocate"], llm.agents(), "the Judge must not run")

    def test_the_event_log_records_the_escalation_and_completes(self):
        _, _, run_dir = self._escalated()
        types = [e["type"] for e in EventLog.read_events(run_dir)]
        self.assertIn("dispute.escalated_on_model_failure", types)
        escalation = types.index("dispute.escalated_on_model_failure")
        self.assertEqual(["party.notified", "run.completed"], types[escalation + 1:])
        event = next(e for e in EventLog.read_events(run_dir) if e["type"] == "dispute.escalated_on_model_failure")
        self.assertEqual(("system", "human_review"), (event["from"], event["to"]))

    def test_a_normal_run_carries_a_null_model_failure(self):
        case, _, _ = _run(self, _Plan({}))
        self.assertEqual("ruled", case["resolution"]["outcome"])
        self.assertIn("model_failure", case["resolution"], "the key is always serialised")
        self.assertIsNone(case["resolution"]["model_failure"])


# --------------------------------------------------------------- 3: scope of escalation


class OnlyModelFailuresEscalateTest(unittest.TestCase):
    def test_a_defect_in_our_code_is_not_escalated(self):
        for exc in (TypeError("our bug"), KeyError("missing"), AttributeError("x")):
            with self.subTest(kind=type(exc).__name__):
                with self.assertRaises(type(exc)):
                    _run(self, _Plan({"judge": [exc]}))

    def test_the_model_failure_is_an_agent_error(self):
        ModelFailure, _, _, _ = _w19()
        from app.agents import AgentError

        self.assertTrue(issubclass(ModelFailure, AgentError))


# ------------------------------------------------------------------- 5: retry rules


class TransientRetryTest(unittest.TestCase):
    def test_three_retries_with_growing_waits_then_success(self):
        llm = _Plan({"judge": [_transient(), _transient(), _transient()]})
        case, clock, _ = _run(self, llm)
        self.assertEqual("ruled", case["resolution"]["outcome"])
        self.assertIsNone(case["resolution"]["model_failure"])
        self.assertEqual([2.0, 5.0, 10.0], clock.slept)
        self.assertEqual(["rider_advocate", "driver_advocate"] + ["judge"] * 4, llm.agents())

    def test_the_fourth_failure_escalates(self):
        llm = _Plan({"judge": [_transient("HTTP 429")] * 5})
        case, clock, _ = _run(self, llm)
        failure = case["resolution"]["model_failure"]
        self.assertEqual(("judge", "transient", 4), (failure["agent"], failure["kind"], failure["attempts"]))
        self.assertEqual([2.0, 5.0, 10.0], clock.slept)
        self.assertEqual(4, llm.agents().count("judge"), "four attempts in all, never a fifth")

    def test_only_the_failed_agent_is_called_again(self):
        llm = _Plan({"driver_advocate": [_transient(), _transient()]})
        case, _, _ = _run(self, llm)
        self.assertEqual("ruled", case["resolution"]["outcome"])
        self.assertEqual(["rider_advocate", "driver_advocate", "driver_advocate", "driver_advocate", "judge"],
                         llm.agents())

    def test_each_retry_is_logged(self):
        llm = _Plan({"judge": [_transient(), _transient()]})
        _, _, run_dir = _run(self, llm)
        retries = [e for e in EventLog.read_events(run_dir) if e["type"] == "llm.call_retried"]
        self.assertEqual(2, len(retries))
        self.assertEqual(["judge", "judge"], [e["from"] for e in retries])
        self.assertTrue(all("judge" in e["summary"].lower() for e in retries), [e["summary"] for e in retries])

    def test_the_default_waits_are_the_ruled_ones(self):
        _, RetryPolicy, _, agent_base = _w19()
        self.assertEqual((2.0, 5.0, 10.0), tuple(agent_base.RETRY_DELAYS_SECONDS))
        self.assertEqual((2.0, 5.0, 10.0), tuple(RetryPolicy().delays_seconds))
        self.assertEqual(1, agent_base.CONTRACT_REASKS)
        self.assertEqual(1, RetryPolicy().contract_reasks)

    def test_the_real_sleep_is_used_when_no_clock_is_injected(self):
        # The default policy must actually wait; a no-op sleep would retry in a hot loop.
        _, RetryPolicy, _, _ = _w19()
        llm = _Plan({"judge": [_transient()]})
        with mock.patch("time.sleep") as slept:
            tmp = tempfile.TemporaryDirectory()
            self.addCleanup(tmp.cleanup)
            run_dispute(dispute=load_fixture_dispute(ROUTE_DEVIATION), llm=llm, policy=load_fixture_policy(),
                        events=EventLog(Path(tmp.name) / "r", "r"), confidence_threshold=0.65,
                        retry_policy=RetryPolicy())
        self.assertEqual([mock.call(2.0)], slept.call_args_list)


class PermanentFailureTest(unittest.TestCase):
    def test_a_permanent_failure_is_never_retried(self):
        for message in ("the Tencent web firewall blocked the request (HTTP 501)",
                        "ADP call failed: HTTP 400", "ADP returned error 4505004: App key invalid"):
            with self.subTest(message=message):
                llm = _Plan({"judge": [LLMError(message)]})
                case, clock, _ = _run(self, llm)
                self.assertEqual(1, llm.agents().count("judge"))
                self.assertEqual([], clock.slept)
                self.assertEqual("permanent", case["resolution"]["model_failure"]["kind"])


class UnreadableReplyTest(unittest.TestCase):
    def test_an_unreadable_reply_is_asked_again_once_and_can_recover(self):
        llm = _Plan({"judge": ["this is not JSON"]})
        case, clock, _ = _run(self, llm)
        self.assertEqual("ruled", case["resolution"]["outcome"])
        self.assertEqual(2, llm.agents().count("judge"))
        self.assertEqual([], clock.slept, "a re-ask is not a wait")

    def test_a_second_unreadable_reply_escalates(self):
        llm = _Plan({"judge": ["not JSON", "still not JSON", "never asked"]})
        case, _, _ = _run(self, llm)
        failure = case["resolution"]["model_failure"]
        self.assertEqual(("judge", "unreadable reply", 2), (failure["agent"], failure["kind"], failure["attempts"]))
        self.assertEqual(2, llm.agents().count("judge"))

    def test_a_contract_breach_counts_as_unreadable(self):
        bad = json.dumps({"action": "partial refund", "recommended_amount_sgd": 1.0, "confidence": 0.9,
                          "explanation": "x", "cited_rule_ids": ["RD-1"]})
        llm = _Plan({"judge": [bad, bad]})
        case, _, _ = _run(self, llm)
        self.assertEqual("unreadable reply", case["resolution"]["model_failure"]["kind"])
        self.assertIsNone(case["resolution"]["ruling"])

    def test_an_adapter_contract_error_counts_as_unreadable(self):
        llm = _Plan({"rider_advocate": [LLMContractError("ADP reply is empty"), LLMContractError("ADP reply is empty")]})
        case, clock, _ = _run(self, llm)
        self.assertEqual(("rider_advocate", "unreadable reply", 2),
                         tuple(case["resolution"]["model_failure"][k] for k in ("agent", "kind", "attempts")))
        self.assertEqual([], clock.slept)

    def test_the_two_counters_are_separate(self):
        # One re-ask for the unreadable reply does not use up a transient retry.
        llm = _Plan({"judge": ["not JSON", _transient(), _transient(), _transient()]})
        case, clock, _ = _run(self, llm)
        self.assertEqual("ruled", case["resolution"]["outcome"])
        self.assertEqual([2.0, 5.0, 10.0], clock.slept)


class NoVerdictShoppingTest(unittest.TestCase):
    def test_a_low_confidence_ruling_is_never_asked_again(self):
        llm = _Plan({}, judge_confidence=0.10)
        case, clock, _ = _run(self, llm)
        self.assertEqual("withheld", case["resolution"]["outcome"])
        self.assertIsNotNone(case["resolution"]["withheld_candidate"], "a gate withheld it, the model answered")
        self.assertIsNone(case["resolution"]["model_failure"], "a low confidence is not a model failure")
        self.assertEqual(1, llm.agents().count("judge"))
        self.assertEqual([], clock.slept)

    def test_a_ruling_over_the_cap_is_never_asked_again(self):
        big = json.dumps({"action": "refund", "recommended_amount_sgd": 80.0, "confidence": 0.95,
                          "explanation": "x", "cited_rule_ids": ["RD-1"], "cited_evidence_refs": []})
        llm = _Plan({"judge": [big]})
        case, _, _ = _run(self, llm)
        self.assertEqual("withheld", case["resolution"]["outcome"])
        self.assertIsNone(case["resolution"]["model_failure"])
        self.assertEqual(1, llm.agents().count("judge"))


# -------------------------------------------------------------------- 6: time budget


class TimeBudgetTest(unittest.TestCase):
    def test_config_carries_the_ruled_budget(self):
        from app.config import load_config

        config = json.loads((ROOT / "app" / "config.json").read_text(encoding="utf-8"))
        self.assertEqual(120, config["llm"]["case_budget_seconds"])
        self.assertEqual(120.0, load_config().llm.case_budget_seconds)

    def test_config_rejects_a_bad_budget(self):
        from app.config import ConfigError, load_config

        base = json.loads((ROOT / "app" / "config.json").read_text(encoding="utf-8"))
        for bad in (0, -5, "120", True, None):
            with self.subTest(value=bad):
                data = json.loads(json.dumps(base))
                data["llm"]["case_budget_seconds"] = bad
                with tempfile.TemporaryDirectory() as tmp:
                    path = Path(tmp) / "config.json"
                    path.write_text(json.dumps(data), encoding="utf-8")
                    with self.assertRaises(ConfigError):
                        load_config(path)

    def test_a_retry_the_budget_cannot_cover_is_not_attempted(self):
        # Each call costs 54 s on the fake clock, budget 60: after the first failure 6 s are
        # left. That covers a call (5 s floor) but not the 2 s wait plus a call, so the
        # retry must be refused BEFORE waiting. Ignoring the wait would sleep, then give up.
        clock = _Clock()
        llm = _Plan({"rider_advocate": [_transient()] * 4}, clock=clock, cost=54.0)
        case, clock, _ = _run(self, llm, clock=clock, budget=60)
        failure = case["resolution"]["model_failure"]
        self.assertEqual(("rider_advocate", "time budget", 1),
                         (failure["agent"], failure["kind"], failure["attempts"]))
        self.assertEqual([], clock.slept, "no wait the budget cannot cover")
        self.assertEqual(1, len(llm.requests))

    def test_a_call_is_not_started_once_the_budget_is_spent(self):
        clock = _Clock()
        llm = _Plan({}, clock=clock, cost=45.0)
        case, _, _ = _run(self, llm, clock=clock, budget=93)
        # rider 45 s, driver 90 s, then 3 s left, under the 5 s floor: the Judge is not started.
        self.assertEqual(["rider_advocate", "driver_advocate"], llm.agents())
        self.assertEqual(("judge", "time budget", 0),
                         tuple(case["resolution"]["model_failure"][k] for k in ("agent", "kind", "attempts")))

    def test_each_call_is_told_what_is_left(self):
        clock = _Clock()
        llm = _Plan({}, clock=clock, cost=10.0)
        _run(self, llm, clock=clock, budget=120)
        self.assertEqual([120.0, 110.0, 100.0], [r.timeout_seconds for r in llm.requests])

    def test_no_budget_means_no_timeout_override(self):
        llm = _Plan({})
        _run(self, llm)
        self.assertEqual([None, None, None], [r.timeout_seconds for r in llm.requests])

    def test_the_timeout_is_not_part_of_the_fingerprint(self):
        from app.llm import LLMRequest

        a = LLMRequest(agent="judge", system_prompt="s", user_prompt="u", timeout_seconds=100.0)
        b = LLMRequest(agent="judge", system_prompt="s", user_prompt="u", timeout_seconds=12.0)
        self.assertEqual(a.fingerprint(), b.fingerprint())


# -------------------------------------------------------- the adapter's classification


class AdapterClassificationTest(unittest.TestCase):
    def _error(self, answer):
        from .test_adp_adapter import _Transport

        transport = _Transport(answer) if not callable(answer) else answer
        with _patched(transport):
            try:
                _client().complete(_request(agent="judge"))
            except LLMError as exc:
                return exc
        self.fail("expected LLMError")

    def test_transient_failures(self):
        import http.client

        from .test_adp_hardening import _SizedResponse

        LLMTransientError = _w19()[2]
        cases = {
            "429": _http_error(429, "slow down"),
            "500": _http_error(500, "boom"),
            "502": _http_error(502, "bad gateway"),
            "503": _http_error(503, "unavailable"),
            "refused": urllib.error.URLError(ConnectionRefusedError("refused")),
            "timeout": urllib.error.URLError(TimeoutError("timed out")),
            "socket timeout": TimeoutError("timed out"),
        }
        for name, answer in cases.items():
            with self.subTest(case=name):
                self.assertIsInstance(self._error(answer), LLMTransientError)
        broken = _SizedResponse(b"", fail=http.client.IncompleteRead(b"", 5))
        with _patched(lambda request, timeout=None: broken):
            with self.assertRaises(LLMTransientError):
                _client().complete(_request())

    def test_permanent_failures_are_not_transient(self):
        LLMTransientError = _w19()[2]
        event = {"Type": "error", "Error": {"Code": 4505004, "Message": "App key invalid"}}
        cases = {
            "firewall 501": _http_error(501, FIREWALL_FIXTURE.read_text(encoding="utf-8")),
            "400": _http_error(400, "bad"),
            "401": _http_error(401, "no"),
            "404": _http_error(404, "gone"),
            "adp error event": "event: error\ndata: %s\n\n" % json.dumps(event),
        }
        for name, answer in cases.items():
            with self.subTest(case=name):
                exc = self._error(answer)
                self.assertNotIsInstance(exc, LLMTransientError)
                self.assertNotIsInstance(exc, LLMContractError)

    def test_a_firewall_page_behind_a_200_is_permanent(self):
        LLMTransientError = _w19()[2]
        exc = self._error(FIREWALL_FIXTURE.read_text(encoding="utf-8"))
        self.assertNotIsInstance(exc, (LLMTransientError, LLMContractError))

    def test_unreadable_replies_are_contract_errors(self):
        from .test_adp_adapter import _completed_only

        cases = {
            "no completed event": "event: done\ndata: [DONE]\n\n",
            "no reply message": _completed_only({"Messages": []}),
            "empty reply": _completed_only({"Messages": [{"Type": "reply", "Contents": [{"Type": "text", "Text": "  "}]}]}),
        }
        for name, answer in cases.items():
            with self.subTest(case=name):
                self.assertIsInstance(self._error(answer), LLMContractError)

    def test_invalid_utf8_and_oversize_are_contract_errors(self):
        from .test_adp_hardening import _SizedResponse

        tencent = __import__("app.llm.tencent", fromlist=["MAX_RESPONSE_BYTES"])
        for name, body in (("utf8", b"\xff\xfe data"), ("size", b"x" * (tencent.MAX_RESPONSE_BYTES + 1))):
            with self.subTest(case=name):
                with _patched(lambda request, timeout=None, b=body: _SizedResponse(b)):
                    with self.assertRaises(LLMContractError):
                        _client().complete(_request())

    def test_redaction_keeps_the_class(self):
        # The adapter redacts every message; the class must survive or retries break.
        LLMTransientError = _w19()[2]
        from .test_adp_hardening import SECRET, SECRET_KEYS

        from .test_adp_adapter import _Transport

        with _patched(_Transport(_http_error(503, "echo %s" % SECRET))):
            try:
                _client(app_keys=dict(SECRET_KEYS)).complete(_request(agent="rider_advocate"))
            except LLMError as exc:
                self.assertIsInstance(exc, LLMTransientError)
                self.assertNotIn(SECRET, str(exc))
            else:
                self.fail("expected LLMError")

    def test_the_timeout_follows_the_budget(self):
        seen = []

        class _Resp(io.BytesIO):
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def answer(request, timeout=None):
            seen.append(timeout)
            return _Resp(REPLY_FIXTURE.read_bytes())

        from app.llm import LLMRequest

        with _patched(answer):
            client = _client()
            client.complete(LLMRequest(agent="judge", system_prompt="s", user_prompt="u", timeout_seconds=12.5))
            client.complete(LLMRequest(agent="judge", system_prompt="s", user_prompt="u", timeout_seconds=500.0))
            client.complete(LLMRequest(agent="judge", system_prompt="s", user_prompt="u"))
            client.complete(LLMRequest(agent="judge", system_prompt="s", user_prompt="u", timeout_seconds=0.2))
        configured = float(client.settings.timeout_seconds)
        self.assertEqual([12.5, configured, configured, 1.0], seen)


# ------------------------------------------------------------ server: the party's view


class _Server:
    def __init__(self, llm):
        from app.server import make_server

        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)
        self.httpd = make_server(port=0, out_dir=self.out, llm=llm)
        self.base = "http://127.0.0.1:%d" % self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.tmp.cleanup()

    def json(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as err:
            return err.code, json.loads(err.read() or b"null")


def _filing(trip_id, answers=None):
    return {
        "category": "route_deviation", "filed_by": "rider", "trip_id": trip_id,
        "description": "He went a long way round.", "claim_amount_sgd": 5.81,
        "answers": answers if answers is not None else {
            "expected_route": "Expressway, about 6.4 km.", "was_route_agreed": "No",
            "asked_driver_to_stop": "No", "safety_concern": "No",
        },
    }


class _AlwaysFails(MockLLMClient):
    """Every call to one agent fails permanently; the rest answer like the mock."""

    def __init__(self, agent, **kwargs):
        super().__init__(**kwargs)
        self.agent = agent
        self.armed = True

    def complete(self, request):
        if self.armed and request.agent == self.agent:
            raise LLMError("the Tencent web firewall blocked the request (HTTP 501)")
        return super().complete(request)


class ServerEscalationTest(unittest.TestCase):
    def test_the_party_gets_the_neutral_message_not_an_error(self):
        server = _Server(_AlwaysFails("judge"))
        try:
            _, trips = server.json("GET", "/api/trips?category=route_deviation")
            status, view = server.json("POST", "/api/disputes", _filing(trips["trips"][0]["trip_id"]))
            self.assertEqual(200, status, view)
            self.assertEqual(["dispute_id", "message", "questions", "run_id", "status"], sorted(view))
            self.assertEqual("under_review", view["status"])
            self.assertEqual(UNDER_REVIEW_MESSAGE, view["message"])
            self.assertEqual([], view["questions"])
            blob = json.dumps(view).lower()
            for leak in ("firewall", "501", "model", "judge", "attempt", "error"):
                self.assertNotIn(leak, blob)
            run_dir = server.out / view["run_id"]
            case = json.loads((run_dir / "case_file.json").read_text(encoding="utf-8"))
            self.assertEqual("permanent", case["resolution"]["model_failure"]["kind"])
            self.assertTrue((run_dir / "dispute.json").exists(), "the reviewer needs the record that ran")
        finally:
            server.close()

    def test_a_round_two_failure_escalates_and_keeps_the_claim(self):
        llm = _AlwaysFails("judge")
        llm.armed = False
        server = _Server(llm)
        try:
            _, trips = server.json("GET", "/api/trips?category=route_deviation")
            answers = _filing("x")["answers"]
            answers["expected_route"] = ""
            _, first = server.json("POST", "/api/disputes", _filing(trips["trips"][0]["trip_id"], answers=answers))
            self.assertEqual("needs_info", first["status"], first)
            reply = {"answers": [{"question": q, "answer": "The expressway."} for q in first["questions"]]}
            llm.armed = True
            status, second = server.json("POST", "/api/disputes/%s/answers" % first["run_id"], reply)
            self.assertEqual(200, status, second)
            self.assertEqual("under_review", second["status"])
            self.assertEqual(UNDER_REVIEW_MESSAGE, second["message"])
            llm.armed = False
            status, _ = server.json("POST", "/api/disputes/%s/answers" % first["run_id"], reply)
            self.assertEqual(409, status, "the escalated run was answered; it must never be ruled twice")
            self.assertEqual(2, len([p for p in server.out.iterdir() if p.is_dir()]))
        finally:
            server.close()

    def test_the_server_applies_the_configured_budget(self):
        # 77 s, not the shipped 120: a hard-coded default must not pass for the config.
        from app import server as server_module

        captured = []
        original = server_module.run_dispute

        def spy(**kwargs):
            captured.append(kwargs.get("retry_policy"))
            return original(**kwargs)

        with mock.patch.object(server_module, "load_config", _config_with_budget(77.0)):
            s = _Server(MockLLMClient())
        try:
            with mock.patch.object(server_module, "run_dispute", spy):
                _, trips = s.json("GET", "/api/trips?category=route_deviation")
                s.json("POST", "/api/disputes", _filing(trips["trips"][0]["trip_id"]))
        finally:
            s.close()
        self.assertEqual(1, len(captured))
        self.assertEqual(77.0, getattr(captured[0], "budget_seconds", None))


# --------------------------------------------------------------------- CLI and eval


class CliAndEvalTest(unittest.TestCase):
    def test_the_cli_reports_the_escalation_and_exits_zero(self):
        import contextlib

        from app import cli

        stdout, stderr = io.StringIO(), io.StringIO()
        with tempfile.TemporaryDirectory() as out, \
                mock.patch.object(cli, "build_llm_client", lambda *a, **k: _AlwaysFails("judge")), \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = cli.main(["--llm", "mock", "--dispute", "RD-0101", "--out", out, "--run-id", "w19"])
            written = (Path(out) / "w19" / "case_file.json").exists()
        self.assertEqual(0, code, stderr.getvalue())
        self.assertTrue(written)
        text = stdout.getvalue()
        self.assertIn("outcome:  withheld", text)
        self.assertRegex(text, r"(?i)judge.*permanent.*1 attempt")
        self.assertIn("firewall", text)

    def test_the_cli_and_eval_pass_the_configured_budget(self):
        # Behaviour, not source: spy on the pipeline call each entry point makes.
        import contextlib

        import app.cli as cli
        import app.eval as ev

        for module, argv in ((cli, ["--llm", "mock", "--dispute", "RD-0101", "--run-id", "b"]),
                             (ev, ["--llm", "mock", "--pack", "organiser-style-v1"])):
            with self.subTest(module=module.__name__):
                captured = []
                original = module.run_dispute

                def spy(original=original, captured=captured, **kwargs):
                    captured.append(kwargs.get("retry_policy"))
                    return original(**kwargs)

                with tempfile.TemporaryDirectory() as out, \
                        mock.patch.object(module, "load_config", _config_with_budget(77.0)), \
                        mock.patch.object(module, "run_dispute", spy), \
                        contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    module.main(argv + ["--out", out])
                self.assertTrue(captured)
                self.assertEqual({77.0}, {getattr(p, "budget_seconds", None) for p in captured})

    def test_score_case_names_the_model_failure(self):
        from app.eval import score_case

        label = {"dispute_id": "RD-0101", "expected_outcome": "escalated", "expected_action": None,
                 "expected_amount_sgd": None, "decisive_rule_ids": ["RD-1"]}
        resolution = {"outcome": "withheld", "ruling": None, "withheld_candidate": None,
                      "model_failure": {"agent": "judge", "kind": "transient", "attempts": 4,
                                        "message": "ADP call failed: HTTP 503"}}
        got = score_case(label, resolution)
        # Even where the label says escalated, an outage is not a correct escalation.
        self.assertEqual(("model failed", False, None), (got.reason, got.decision_match, got.grounded))
        self.assertIn("HTTP 503", got.error or "")

    def test_a_gate_withheld_case_is_still_scored_normally(self):
        from app.eval import score_case

        label = {"dispute_id": "RD-0109", "expected_outcome": "escalated", "expected_action": None,
                 "expected_amount_sgd": None, "decisive_rule_ids": ["ESC-4"]}
        resolution = {"outcome": "withheld", "ruling": None, "model_failure": None,
                      "withheld_candidate": {"action": "refund", "recommended_amount_sgd": 55.16, "cited_rule_ids": []}}
        self.assertEqual("match", score_case(label, resolution).reason)

    def test_the_reason_list_places_model_failed_before_run_failed(self):
        from app.eval import REASONS

        self.assertEqual(["match", "wrong outcome", "wrong action", "wrong amount", "asked the party",
                          "model failed", "run failed"], list(REASONS))


# --------------------------------------------------------------------------- docs


class DocsTest(unittest.TestCase):
    def _arch(self):
        return (ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")

    def test_the_old_limit_is_gone(self):
        text = self._arch()
        self.assertNotIn("A failed model call is an error, not a referral", text)
        self.assertNotIn("generic error", text)
        self.assertNotRegex(text, r"Any failure raises an\s+error")

    def test_the_architecture_doc_states_the_retry_rules(self):
        text = self._arch()
        section = text[text.index("## LLM provider"):text.index("## Limits")]
        for needle in ("2, 5 and 10 seconds", "120 seconds", "`llm.case_budget_seconds`",
                       "`dispute.escalated_on_model_failure`", "`llm.call_retried`", "`model_failure`"):
            self.assertIn(needle, section)
        self.assertRegex(section, r"(?i)asked again once")
        self.assertRegex(section, r"(?i)never asked again")

    def test_the_outcome_table_names_the_model_failure(self):
        text = self._arch()
        row = next(line for line in text.splitlines() if line.startswith("| `withheld` |"))
        self.assertRegex(row, r"(?i)model")

    def test_the_diagram_routes_a_model_failure_to_human_review(self):
        block = re.search(r"```mermaid\n(.*?)```", self._arch(), re.DOTALL).group(1)
        self.assertRegex(block, r'-- "Model could not answer" --> H\b')

    def test_the_dataset_doc_explains_model_failed(self):
        text = (ROOT / "docs" / "dataset.md").read_text(encoding="utf-8")
        section = text[text.index("### Evaluation"):text.index("## Known limitations")]
        self.assertIn("model failed", section)
        self.assertLessEqual(len([l for l in section.splitlines() if l.strip()]), 15)


if __name__ == "__main__":
    unittest.main()
