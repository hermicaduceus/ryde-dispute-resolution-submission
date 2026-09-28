"""The Tencent Cloud ADP adapter (session fourteen). RED until the build lane ships it.

Every ruling so far came from the mock. The real model is now reachable through Tencent
Cloud ADP: three published agent apps (Rider Advocate, Driver Advocate, Judge), one
AppKey each, called over HTTP. A scratch probe on 2026-09-28 proved the route end to end
and found what the adapter must handle. Each class below pins one of those findings:

- the reply is Server-Sent Events; the answer lives in the response.completed event;
- ADP reports errors as an error event inside an HTTP 200;
- Tencent's web firewall answers HTTP 501 with a captcha page when a prompt mixes
  backticks and ASCII brackets, and the fix is to drop backticks and send full-width
  brackets;
- the free plan allows 10 calls a minute;
- a model can return an amount as a string, and the contract must reject it, never
  convert it (operator ruling 2026-09-28).

The three fixtures under tests/fixtures/adp/ are real captures from the live endpoint
on 2026-09-28, with trace ids, record-id suffixes, the avatar URL and the app's role
card removed. No test here touches the network: every test replaces urlopen.
"""

from __future__ import annotations

import io
import json
import os
import re
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from app.agents import AgentError
from app.config import load_config
from app.llm import LLMError, LLMRequest

from .support import ROUTE_DEVIATION, ScriptedLLM, run_fixture
from .test_pipeline import DRIVER_CASE, RIDER_CASE

ROOT = Path(__file__).resolve().parent.parent
ADP_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "adp"
REPLY_FIXTURE = ADP_FIXTURES / "adp_sse_reply.txt"
ERROR_FIXTURE = ADP_FIXTURES / "adp_sse_error.txt"
FIREWALL_FIXTURE = ADP_FIXTURES / "adp_firewall_501.html"

ADP_ENDPOINT = "https://wss.lke.tencentcloud.com/adp/v2/chat"
KEYS = {
    "rider_advocate": "rider-app-key-for-tests",
    "driver_advocate": "driver-app-key-for-tests",
    "judge": "judge-app-key-for-tests",
}
ENV_VARS = {
    "rider_advocate": "TENCENT_ADP_RIDER_APP_KEY",
    "driver_advocate": "TENCENT_ADP_DRIVER_APP_KEY",
    "judge": "TENCENT_ADP_JUDGE_APP_KEY",
}
FIREWALL_CHARS = "`()<>;|$"
FULL_WIDTH = {
    "(": "\uff08",
    ")": "\uff09",
    "<": "\uff1c",
    ">": "\uff1e",
    ";": "\uff1b",
    "|": "\uff5c",
    "$": "\uff04",
}
JUDGE_RULING = {
    "action": "refund",
    "recommended_amount_sgd": 4.87,
    "confidence": 0.9,
    "explanation": "The route ran longer than the estimate, so RD-1 applies.",
    "cited_rule_ids": ["RD-1"],
    "cited_evidence_refs": ["route.deviation_km"],
}


# --------------------------------------------------------------------------- helpers


def _tencent():
    import app.llm.tencent as tencent

    return tencent


def _settings():
    return load_config().llm


def _client(**kwargs):
    kwargs.setdefault("app_keys", dict(KEYS))
    kwargs.setdefault("min_interval_seconds", 0)
    return _tencent().TencentLLMClient(_settings(), **kwargs)


def _sse_reply(text: str) -> str:
    """A live-shaped SSE stream whose reply is `text`, built from the real capture."""
    template = REPLY_FIXTURE.read_text(encoding="utf-8")
    original = '{"role": "judge", "amount": 1.5}'
    return template.replace(json.dumps(original)[1:-1], json.dumps(text)[1:-1])


def _completed_only(response) -> str:
    """An SSE stream carrying one response.completed event with `response` as its body."""
    event = {"Type": "response.completed", "Response": response}
    return "event: response.completed\ndata: %s\n\nevent: done\ndata: [DONE]\n\n" % json.dumps(event)


class _FakeResponse:
    def __init__(self, body: str, status: int = 200):
        self._body = body.encode("utf-8")
        self.status = status

    def read(self, amt=None):
        # Mirrors http.client.HTTPResponse.read: a bounded read returns at most amt bytes.
        if amt is None or amt < 0:
            return self._body
        return self._body[:amt]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _Transport:
    """Replaces urlopen. Records every request; answers from a function or a fixed body."""

    def __init__(self, answer):
        self.answer = answer
        self.requests = []

    def __call__(self, request, timeout=None):
        self.requests.append(request)
        body = json.loads(request.data.decode("utf-8"))
        result = self.answer(body) if callable(self.answer) else self.answer
        if isinstance(result, BaseException):
            raise result
        return _FakeResponse(result)

    def bodies(self):
        return [json.loads(r.data.decode("utf-8")) for r in self.requests]


def _http_error(code: int, body: str):
    return urllib.error.HTTPError(ADP_ENDPOINT, code, "error", {}, io.BytesIO(body.encode("utf-8")))


def _request(agent="judge", system="system text", user="user text"):
    return LLMRequest(agent=agent, system_prompt=system, user_prompt=user)


def _patched(transport):
    return mock.patch("app.llm.tencent.urllib.request.urlopen", transport)


# --------------------------------------------------------------------------- config


class ConfigurationTest(unittest.TestCase):
    def test_each_missing_key_is_named_and_the_client_refuses_to_build(self):
        for agent, var in ENV_VARS.items():
            keys = dict(KEYS)
            keys[agent] = ""
            with self.assertRaises(LLMError) as ctx:
                _client(app_keys=keys)
            self.assertIn(var, str(ctx.exception))

    def test_keys_are_read_from_the_environment_one_per_agent(self):
        env = {ENV_VARS[agent]: key for agent, key in KEYS.items()}
        with mock.patch.dict(os.environ, env):
            client = _tencent().TencentLLMClient(_settings(), min_interval_seconds=0)
        transport = _Transport(_sse_reply("{}"))
        with _patched(transport):
            for agent in KEYS:
                client.complete(_request(agent=agent))
        self.assertEqual([b["AppKey"] for b in transport.bodies()], [KEYS[a] for a in KEYS])

    def test_a_placeholder_endpoint_is_refused(self):
        settings = _settings()
        placeholder = type(settings)(**{**settings.__dict__, "endpoint": "https://TODO-pin.example/v1"})
        with mock.patch("app.llm.tencent.read_secret", return_value=None):
            with self.assertRaises(LLMError):
                _tencent().TencentLLMClient(placeholder, app_keys=dict(KEYS))

    def test_config_points_at_adp_and_keeps_mock_as_the_default(self):
        config = json.loads((ROOT / "app" / "config.json").read_text(encoding="utf-8"))
        self.assertEqual(config["llm"]["provider"], "mock")
        self.assertEqual(config["llm"]["endpoint"], ADP_ENDPOINT)
        self.assertNotIn("TODO-pin", json.dumps(config))

    def test_env_template_names_the_three_keys_blank(self):
        lines = (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
        assignments = {}
        for line in lines:
            match = re.match(r"^([A-Z_]+)=(.*)$", line.strip())
            if match:
                assignments[match.group(1)] = match.group(2)
        for var in ENV_VARS.values():
            self.assertIn(var, assignments)
            self.assertEqual(assignments[var], "", "%s must be blank in the committed template" % var)
        self.assertNotIn("TENCENT_LLM_API_KEY", assignments)


# --------------------------------------------------------------------------- request


class RequestTest(unittest.TestCase):
    def setUp(self):
        self.transport = _Transport(_sse_reply("{}"))

    def _send(self, request):
        with _patched(self.transport):
            _client().complete(request)
        return self.transport.requests[-1], self.transport.bodies()[-1]

    def test_the_body_matches_the_adp_protocol(self):
        http_request, body = self._send(_request(agent="rider_advocate"))
        self.assertEqual(http_request.get_method(), "POST")
        self.assertEqual(http_request.full_url, ADP_ENDPOINT)
        self.assertEqual(body["AppKey"], KEYS["rider_advocate"])
        self.assertEqual(body["Stream"], "disable")
        self.assertIs(body["Incremental"], False)
        self.assertTrue(body["VisitorId"])
        self.assertTrue(body["RequestId"])
        self.assertEqual(len(body["Contents"]), 1)
        self.assertEqual(body["Contents"][0]["Type"], "text")
        headers = {k.lower() for k in http_request.headers}
        self.assertNotIn("authorization", headers, "the AppKey travels in the body only")

    def test_every_agent_calls_its_own_app(self):
        with _patched(self.transport):
            client = _client()
            for agent in ("judge", "rider_advocate", "driver_advocate"):
                client.complete(_request(agent=agent))
        self.assertEqual(
            [b["AppKey"] for b in self.transport.bodies()],
            [KEYS["judge"], KEYS["rider_advocate"], KEYS["driver_advocate"]],
        )

    def test_an_unknown_agent_is_refused_without_a_call(self):
        with _patched(self.transport):
            with self.assertRaises(LLMError):
                _client().complete(_request(agent="mediator"))
        self.assertEqual(self.transport.requests, [])

    def test_every_call_opens_a_fresh_conversation(self):
        with _patched(self.transport):
            client = _client()
            client.complete(_request())
            client.complete(_request())
        ids = [b["ConversationId"] for b in self.transport.bodies()]
        self.assertEqual(len(set(ids)), 2, "a reused ConversationId leaks context between calls")

    def test_both_prompts_are_sent_in_one_message(self):
        _, body = self._send(_request(system="ROLE-MARKER-ALPHA", user="CASE-MARKER-BETA"))
        text = body["Contents"][0]["Text"]
        self.assertIn("ROLE-MARKER-ALPHA", text)
        self.assertIn("CASE-MARKER-BETA", text)
        self.assertLess(text.index("ROLE-MARKER-ALPHA"), text.index("CASE-MARKER-BETA"))

    def test_the_whole_prompt_is_cleaned_for_the_firewall(self):
        dirty = "rule `RD-1` (see <a>; x | y costs $5)"
        _, body = self._send(_request(system="SYS " + dirty, user="USR " + dirty))
        text = body["Contents"][0]["Text"]
        for char in FIREWALL_CHARS:
            self.assertNotIn(char, text, "%r reached the firewall" % char)
        # The model must still see every bracket, in full-width form, in both prompts.
        cleaned = "rule RD-1 \uff08see \uff1ca\uff1e\uff1b x \uff5c y costs \uff045\uff09"
        self.assertEqual(text.count("SYS " + cleaned), 1)
        self.assertEqual(text.count("USR " + cleaned), 1)

    def test_the_cleaning_table_maps_each_character(self):
        clean = _tencent().clean_for_firewall
        self.assertEqual(clean("`"), "")
        for ascii_char, full in FULL_WIDTH.items():
            self.assertEqual(clean(ascii_char), full, ascii_char)
        self.assertEqual(clean("SGD 5.81, RD-1: \"quoted\" [x] {y}"), "SGD 5.81, RD-1: \"quoted\" [x] {y}")

    def test_the_real_policy_leaves_no_firewall_characters(self):
        policy = (ROOT / "docs" / "policy.md").read_text(encoding="utf-8")
        self.assertTrue(any(c in policy for c in FIREWALL_CHARS), "precondition: the policy has them")
        cleaned = _tencent().clean_for_firewall(policy)
        self.assertEqual([c for c in FIREWALL_CHARS if c in cleaned], [])


# --------------------------------------------------------------------------- response


class ResponseTest(unittest.TestCase):
    def _complete(self, answer, agent="judge"):
        transport = _Transport(answer)
        with _patched(transport):
            result = _client().complete(_request(agent=agent))
        return result, transport

    def _fails(self, answer):
        transport = _Transport(answer)
        with _patched(transport):
            with self.assertRaises(LLMError) as ctx:
                _client().complete(_request())
        self.assertEqual(len(transport.requests), 1, "a failed call must never be retried")
        return str(ctx.exception)

    def test_the_real_reply_capture_parses_to_the_answer_text(self):
        result, _ = self._complete(REPLY_FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(result.text, '{"role": "judge", "amount": 1.5}')
        self.assertEqual(result.provider, "tencent")
        self.assertEqual(result.model, _settings().model)
        self.assertEqual(result.usage.get("total_tokens"), 249)

    def test_the_answer_comes_from_response_completed_not_earlier_events(self):
        body = REPLY_FIXTURE.read_text(encoding="utf-8")
        cut = body.index("event: response.completed")
        message = self._fails(body[:cut])
        self.assertIn("response.completed", message)

    def test_an_error_event_inside_http_200_raises_with_its_code(self):
        message = self._fails(ERROR_FIXTURE.read_text(encoding="utf-8"))
        self.assertIn("4505004", message)

    def test_the_real_firewall_block_raises_once(self):
        message = self._fails(_http_error(501, FIREWALL_FIXTURE.read_text(encoding="utf-8")))
        self.assertIn("firewall", message.lower())

    def test_a_firewall_page_under_any_status_raises(self):
        message = self._fails(FIREWALL_FIXTURE.read_text(encoding="utf-8"))
        self.assertIn("firewall", message.lower())

    def test_other_http_errors_and_network_failures_raise_once(self):
        for failure in (
            _http_error(429, '{"message": "rate limited"}'),
            _http_error(500, "server error"),
            urllib.error.URLError("no route to host"),
        ):
            with self.subTest(failure=repr(failure)):
                self._fails(failure)

    def test_an_empty_reply_raises(self):
        self._fails(_sse_reply(""))
        self._fails(_sse_reply("   "))

    def test_every_malformed_completed_shape_raises_llm_error(self):
        wrong_shapes = [
            None,
            [],
            [1, 2],
            {},
            "text",
            0,
            {"Messages": None},
            {"Messages": {}},
            {"Messages": []},
            {"Messages": [None, "x", 3]},
            {"Messages": [{"Type": "question", "Contents": [{"Type": "text", "Text": "{}"}]}]},
            {"Messages": [{"Type": "reply"}]},
            {"Messages": [{"Type": "reply", "Contents": {}}]},
            {"Messages": [{"Type": "reply", "Contents": "{}"}]},
            {"Messages": [{"Type": "reply", "Contents": [{"Type": "text", "Text": 5}]}]},
            {"Messages": [{"Type": "reply", "Contents": [{"Type": "text", "Text": ["{}"]}]}]},
        ]
        for shape in wrong_shapes:
            with self.subTest(shape=shape):
                self._fails(_completed_only(shape))

    def test_a_malformed_error_event_still_raises_llm_error(self):
        for error in (None, [], "boom", {"Code": None}):
            with self.subTest(error=error):
                event = {"Type": "error", "Error": error}
                self._fails("event: error\ndata: %s\n\n" % json.dumps(event))


# --------------------------------------------------------------------------- pacing


class PacingTest(unittest.TestCase):
    def test_the_interval_respects_ten_calls_a_minute(self):
        self.assertGreaterEqual(_tencent().MIN_CALL_INTERVAL_SECONDS, 6.0)

    def test_the_default_client_uses_the_module_interval(self):
        client = _tencent().TencentLLMClient(_settings(), app_keys=dict(KEYS))
        self.assertEqual(client.min_interval_seconds, _tencent().MIN_CALL_INTERVAL_SECONDS)

    def test_back_to_back_calls_are_spaced_and_a_failed_call_counts(self):
        clock = [1000.0]
        sleeps = []

        def fake_sleep(seconds):
            sleeps.append(seconds)
            clock[0] += seconds

        answers = iter([_http_error(501, FIREWALL_FIXTURE.read_text(encoding="utf-8")), _sse_reply("{}")])
        transport = _Transport(lambda body: next(answers))
        with _patched(transport), \
                mock.patch("app.llm.tencent.time.monotonic", lambda: clock[0]), \
                mock.patch("app.llm.tencent.time.sleep", fake_sleep):
            client = _client(min_interval_seconds=6.5)
            with self.assertRaises(LLMError):
                client.complete(_request())
            self.assertEqual(sleeps, [], "the first call must not wait")
            clock[0] += 2.0
            client.complete(_request())
        self.assertEqual(len(sleeps), 1)
        self.assertAlmostEqual(sleeps[0], 4.5, places=3)

    def test_a_call_after_the_interval_does_not_wait(self):
        clock = [1000.0]
        sleeps = []
        transport = _Transport(_sse_reply("{}"))
        with _patched(transport), \
                mock.patch("app.llm.tencent.time.monotonic", lambda: clock[0]), \
                mock.patch("app.llm.tencent.time.sleep", sleeps.append):
            client = _client(min_interval_seconds=6.5)
            client.complete(_request())
            clock[0] += 7.0
            client.complete(_request())
        self.assertEqual(sleeps, [])


# --------------------------------------------------------------------------- pipeline


class PipelineThroughAdapterTest(unittest.TestCase):
    """The full pipeline on the adapter, with the network replaced."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.run_dir = Path(self._tmp.name) / "run"

    def tearDown(self):
        self._tmp.cleanup()

    def _by_key(self, judge=JUDGE_RULING, rider=RIDER_CASE, driver=DRIVER_CASE):
        replies = {KEYS["rider_advocate"]: rider, KEYS["driver_advocate"]: driver, KEYS["judge"]: judge}

        def answer(body):
            return _sse_reply(json.dumps(replies[body["AppKey"]]))

        return answer

    def test_a_real_provider_ruling_reaches_the_party_without_the_demo_notice(self):
        from app.schemas import DEMO_NOTICE_MESSAGE
        from app.server import party_view

        transport = _Transport(self._by_key())
        with _patched(transport):
            case_file = run_fixture(ROUTE_DEVIATION, self.run_dir, llm=_client())
        resolution = case_file.resolution
        self.assertEqual(resolution["outcome"], "ruled")
        self.assertEqual(resolution["ruling"]["llm"]["provider"], "tencent")
        self.assertEqual(
            sorted(b["AppKey"] for b in transport.bodies()),
            sorted(KEYS.values()),
            "each agent must have called its own app exactly once",
        )
        view = party_view(case_file.to_dict())
        self.assertEqual(view["status"], "decided")
        self.assertNotIn(DEMO_NOTICE_MESSAGE.strip(), view["message"])
        self.assertIn("4.87", view["message"])

    def test_a_blocked_call_stops_the_run_with_no_mock_fallback(self):
        transport = _Transport(_http_error(501, FIREWALL_FIXTURE.read_text(encoding="utf-8")))
        with _patched(transport):
            with self.assertRaises(AgentError) as ctx:
                run_fixture(ROUTE_DEVIATION, self.run_dir, llm=_client())
        self.assertIn("firewall", str(ctx.exception).lower())
        self.assertEqual(len(transport.requests), 1, "the run must stop at the first failure")

    def test_a_string_amount_from_the_judge_is_rejected_not_converted(self):
        judge = dict(JUDGE_RULING, recommended_amount_sgd="4.87")
        transport = _Transport(self._by_key(judge=judge))
        with _patched(transport):
            with self.assertRaises(AgentError):
                run_fixture(ROUTE_DEVIATION, self.run_dir, llm=_client())

    def test_a_string_amount_from_an_advocate_is_rejected_not_converted(self):
        driver = dict(DRIVER_CASE, requested_amount_sgd="0.00")
        transport = _Transport(self._by_key(driver=driver))
        with _patched(transport):
            with self.assertRaises(AgentError):
                run_fixture(ROUTE_DEVIATION, self.run_dir, llm=_client())


class StringAmountRulingTest(unittest.TestCase):
    """Operator ruling 2026-09-28: a string amount fails the run. Green on arrival.

    This pins the contract validator independently of the adapter, so a later change
    that "helpfully" converts "4.87" to 4.87 turns the suite red.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.run_dir = Path(self._tmp.name) / "run"

    def tearDown(self):
        self._tmp.cleanup()

    def test_string_amounts_and_confidence_are_rejected(self):
        cases = {
            "judge amount": {"judge": dict(JUDGE_RULING, recommended_amount_sgd="4.87")},
            "judge confidence": {"judge": dict(JUDGE_RULING, confidence="0.9")},
            "rider amount": {"rider_advocate": dict(RIDER_CASE, requested_amount_sgd="4.87")},
            "driver amount": {"driver_advocate": dict(DRIVER_CASE, requested_amount_sgd="0.00")},
        }
        for name, override in cases.items():
            with self.subTest(case=name):
                scripted = {"rider_advocate": RIDER_CASE, "driver_advocate": DRIVER_CASE, "judge": JUDGE_RULING}
                scripted.update(override)
                with self.assertRaises(AgentError):
                    run_fixture(ROUTE_DEVIATION, self.run_dir / name.replace(" ", "-"), llm=ScriptedLLM(scripted))


# --------------------------------------------------------------------------- server


class ServerFlagTest(unittest.TestCase):
    def test_the_flag_parses_and_defaults_to_config(self):
        from app.server import parse_args

        self.assertIsNone(parse_args([]).llm)
        self.assertEqual(parse_args(["--llm", "tencent"]).llm, "tencent")
        self.assertEqual(parse_args(["--llm", "mock"]).llm, "mock")
        with mock.patch("sys.stderr", io.StringIO()):
            with self.assertRaises(SystemExit):
                parse_args(["--llm", "openai"])

    def test_main_hands_the_flag_to_make_server(self):
        import app.server as server

        class _Httpd:
            server_address = ("127.0.0.1", 8000)
            ryde_state = mock.Mock()

            def serve_forever(self):
                raise KeyboardInterrupt

            def server_close(self):
                pass

        with mock.patch.object(server, "make_server", return_value=_Httpd()) as made, \
                mock.patch("sys.stdout", io.StringIO()):
            server.main(["--llm", "tencent"])
        self.assertEqual(made.call_args.kwargs.get("provider"), "tencent")

    def test_tencent_without_keys_fails_before_the_server_binds(self):
        from app.server import make_server

        with mock.patch("app.llm.tencent.read_secret", return_value=None), \
                mock.patch("app.server.ThreadingHTTPServer") as bound:
            with self.assertRaises(LLMError):
                make_server(0, provider="tencent")
        bound.assert_not_called()

    def test_the_provider_argument_selects_the_client(self):
        from app.server import make_server

        env = {ENV_VARS[agent]: key for agent, key in KEYS.items()}
        with mock.patch.dict(os.environ, env):
            httpd = make_server(0, provider="tencent")
        try:
            self.assertEqual(httpd.ryde_state.llm.provider_name, "tencent")
        finally:
            httpd.server_close()
        httpd = make_server(0, provider="mock")
        try:
            self.assertEqual(httpd.ryde_state.llm.provider_name, "mock")
        finally:
            httpd.server_close()
        httpd = make_server(0)
        try:
            self.assertEqual(httpd.ryde_state.llm.provider_name, "mock", "config default stays mock")
        finally:
            httpd.server_close()


# --------------------------------------------------------------------------- docs


class DocsHonestyTest(unittest.TestCase):
    STALE = (
        "not pinned yet",
        "has not been called",
        "never called",
        "No real LLM calls",
        "TENCENT_LLM_API_KEY",
        "TODO(",
        "UNVERIFIED",
    )

    def test_no_file_still_says_the_endpoint_is_unpinned(self):
        for rel in ("docs/architecture.md", "README.md", "app/llm/tencent.py", "app/llm/__init__.py", "app/config.json"):
            text = (ROOT / rel).read_text(encoding="utf-8")
            with self.subTest(file=rel):
                self.assertEqual([s for s in self.STALE if s in text], [])

    def test_the_architecture_doc_describes_the_adapter(self):
        text = (ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")
        start = text.index("## LLM provider")
        section = text[start:text.index("\n## ", start + 1)]
        for needle in ("ADP", "firewall", "6.5", "--llm tencent"):
            self.assertIn(needle, section)

    def test_the_readme_says_how_to_run_the_real_model(self):
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("--llm tencent", text)
        self.assertIn(".env.example", text)


if __name__ == "__main__":
    unittest.main()
