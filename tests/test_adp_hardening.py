"""Session fourteen fix round: the gpt-5.6-sol review findings. RED until the build lane ships it.

A cross-family review of the ADP adapter (build 2a4534b) found nine real defects, each
reproduced by the operator before this file was written. One class per finding:

- S14-001 an HTTP error body that echoes an AppKey reached CLI stderr through
  LLMError -> AgentError -> the CLI's error line;
- S14-002 SSE framed with CRLF (or bare CR) line endings was rejected;
- S14-003 a reply split across several reply messages kept only the last one;
- S14-004 a connection that broke mid-read escaped as http.client.IncompleteRead;
- S14-005 the whole response was read into memory with no size limit;
- S14-006 docs/tencent-endpoint-acquisition.md still said the endpoint was blocked;
- S14-007 invalid UTF-8 was silently replaced and could reach a ruling;
- S14-009 five regressions left the suite green: no pacing lock, generic error text, a
  contradicting doc sentence, dropped request headers, a dropped timeout;
- S14-010 the README said every mock string carries the MOCK prefix.

No test touches the network. Keys used here are test strings, never real ones.
"""

from __future__ import annotations

import contextlib
import http.client
import io
import json
import os
import re
import tempfile
import threading
import time
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from app.agents import AgentError
from app.llm import LLMError, LLMRequest

from .support import ROUTE_DEVIATION, run_fixture
from .test_adp_adapter import (
    ENV_VARS,
    FIREWALL_FIXTURE,
    KEYS,
    REPLY_FIXTURE,
    _client,
    _completed_only,
    _http_error,
    _patched,
    _request,
    _settings,
    _sse_reply,
    _tencent,
    _Transport,
)

ROOT = Path(__file__).resolve().parent.parent
SECRET = "SECRET-APPKEY-DO-NOT-LEAK-0123456789"
SECRET_KEYS = {"rider_advocate": SECRET, "driver_advocate": "driver-secret-x", "judge": "judge-secret-y"}


class _SizedResponse:
    """A response that honours read(amt) like http.client.HTTPResponse and records the sizes asked."""

    def __init__(self, body: bytes, status: int = 200, fail=None):
        self._body = body
        self.status = status
        self.fail = fail
        self.read_sizes = []

    def read(self, amt=None):
        self.read_sizes.append(amt)
        if self.fail is not None:
            raise self.fail
        if amt is None or amt < 0:
            return self._body
        return self._body[:amt]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _raises(answer, keys=None):
    """Run one call against `answer`; return the LLMError text. Any other exception fails the test."""
    transport = _Transport(answer) if not isinstance(answer, _SizedResponse) else None
    opener = transport if transport is not None else (lambda request, timeout=None: answer)
    client = _client(app_keys=dict(keys or KEYS))
    with _patched(opener):
        try:
            client.complete(_request(agent="rider_advocate"))
        except LLMError as exc:
            return str(exc)
    raise AssertionError("expected LLMError")


# --------------------------------------------------------------------------- S14-001


class SecretRedactionTest(unittest.TestCase):
    def test_an_http_error_body_never_reaches_the_message(self):
        body = '{"error": "invalid AppKey: %s", "detail": "BODY-MARKER"}' % SECRET
        message = _raises(_http_error(400, body), keys=SECRET_KEYS)
        self.assertNotIn(SECRET, message)
        self.assertNotIn("BODY-MARKER", message, "no part of an error body may be copied into the message")
        self.assertIn("400", message, "the status code is the cause and must stay")

    def test_every_configured_key_is_redacted_from_any_llm_error(self):
        # An ADP error event whose Message echoes each key: the code stays, the keys go.
        for agent, key in SECRET_KEYS.items():
            with self.subTest(agent=agent):
                event = {"Type": "error", "Error": {"Code": 4505004, "Message": "App key %s invalid" % key}}
                message = _raises("event: error\ndata: %s\n\n" % json.dumps(event), keys=SECRET_KEYS)
                for secret in SECRET_KEYS.values():
                    self.assertNotIn(secret, message)
                self.assertIn("4505004", message)

    def test_a_printed_traceback_carries_no_key(self):
        # Anything that prints the traceback must not surface an unredacted inner error.
        import traceback

        event = {"Type": "error", "Error": {"Code": 4505004, "Message": "App key %s invalid" % SECRET}}
        cases = [_http_error(400, "echo %s" % SECRET), "event: error\ndata: %s\n\n" % json.dumps(event)]
        for answer in cases:
            with self.subTest(answer=type(answer).__name__):
                transport = _Transport(answer)
                with _patched(transport):
                    try:
                        _client(app_keys=dict(SECRET_KEYS)).complete(_request(agent="rider_advocate"))
                    except LLMError as exc:
                        printed = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
                        self.assertNotIn(SECRET, printed)
                    else:
                        self.fail("expected LLMError")

    def test_the_cli_never_prints_a_key(self):
        from app import cli

        env = {ENV_VARS[agent]: key for agent, key in SECRET_KEYS.items()}
        stderr, stdout = io.StringIO(), io.StringIO()
        transport = _Transport(_http_error(400, '{"error": "invalid AppKey: %s"}' % SECRET))
        with tempfile.TemporaryDirectory() as out, mock.patch.dict(os.environ, env), _patched(transport), \
                contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(stdout):
            code = cli.main(["--llm", "tencent", "--dispute", "RD-0101", "--out", out, "--run-id", "leak-probe"])
            written = "".join(p.read_text(errors="ignore") for p in Path(out).rglob("*") if p.is_file())
        # W19: the failed call escalates the case, so the run completes and writes a case
        # file that now carries the cause. The key must reach none of it.
        self.assertEqual(code, 0)
        self.assertIn("model_failure", written)
        for secret in SECRET_KEYS.values():
            self.assertNotIn(secret, stderr.getvalue())
            self.assertNotIn(secret, stdout.getvalue())
            self.assertNotIn(secret, written)
        self.assertIn("HTTP 400", stdout.getvalue(), "the operator still needs the cause")
        self.assertIn("HTTP 400", written, "the reviewer still needs the cause")


# --------------------------------------------------------------------------- S14-002


class LineEndingTest(unittest.TestCase):
    def test_crlf_and_cr_framed_streams_parse_to_the_same_answer(self):
        lf = REPLY_FIXTURE.read_text(encoding="utf-8")
        for name, body in (("crlf", lf.replace("\n", "\r\n")), ("cr", lf.replace("\n", "\r"))):
            with self.subTest(ending=name):
                transport = _Transport(body)
                with _patched(transport):
                    result = _client().complete(_request())
                self.assertEqual(result.text, '{"role": "judge", "amount": 1.5}')

    def test_a_crlf_error_event_still_raises_with_its_code(self):
        event = {"Type": "error", "Error": {"Code": 4505004, "Message": "App key invalid"}}
        message = _raises("event: error\r\ndata: %s\r\n\r\n" % json.dumps(event))
        self.assertIn("4505004", message)


# --------------------------------------------------------------------------- S14-003


class MultipleReplyTest(unittest.TestCase):
    def test_reply_messages_are_joined_in_order(self):
        body = _completed_only({
            "Status": "success",
            "Messages": [
                {"Type": "reply", "Contents": [{"Type": "text", "Text": '{"action":'}]},
                {"Type": "question", "Contents": [{"Type": "text", "Text": "NOT-A-REPLY"}]},
                {"Type": "reply", "Contents": [{"Type": "text", "Text": ' "no action"}'}]},
            ],
        })
        transport = _Transport(body)
        with _patched(transport):
            result = _client().complete(_request())
        self.assertEqual(result.text, '{"action": "no action"}')


# --------------------------------------------------------------------------- S14-004, 005, 007


class TransportFailureTest(unittest.TestCase):
    def test_a_connection_that_breaks_mid_read_raises_llm_error(self):
        for failure in (
            http.client.IncompleteRead(b"partial", 100),
            http.client.RemoteDisconnected("closed"),
            ConnectionResetError("reset"),
            TimeoutError("timed out"),
        ):
            with self.subTest(failure=type(failure).__name__):
                message = _raises(_SizedResponse(b"", fail=failure))
                self.assertNotIn("partial", message, "partial bytes may carry sensitive text")

    def test_the_body_is_read_with_a_bound(self):
        response = _SizedResponse(REPLY_FIXTURE.read_bytes())
        with _patched(lambda request, timeout=None: response):
            _client().complete(_request())
        limit = _tencent().MAX_RESPONSE_BYTES
        self.assertEqual(response.read_sizes, [limit + 1])

    def test_the_limit_leaves_room_for_a_real_reply_and_refuses_more(self):
        limit = _tencent().MAX_RESPONSE_BYTES
        self.assertGreaterEqual(limit, 1024 * 1024, "a live Judge reply measured 89 KB; keep a wide margin")
        self.assertLessEqual(limit, 16 * 1024 * 1024)
        message = _raises(_SizedResponse(b"x" * (limit + 1)))
        self.assertIn("too large", message)

    def test_a_reply_at_the_limit_is_not_refused_for_size(self):
        limit = _tencent().MAX_RESPONSE_BYTES
        padding = "x" * (limit - len(REPLY_FIXTURE.read_bytes()) - 1)
        body = (REPLY_FIXTURE.read_text(encoding="utf-8") + ": " + padding)[:limit]
        self.assertLessEqual(len(body.encode("utf-8")), limit)
        transport = _Transport(body)
        with _patched(transport):
            result = _client().complete(_request())
        self.assertEqual(result.text, '{"role": "judge", "amount": 1.5}')

    def test_an_http_error_body_is_read_with_a_bound(self):
        sizes = []

        class _Body(io.BytesIO):
            def read(self, amt=None):
                sizes.append(amt)
                return super().read(amt)

        error = urllib.error.HTTPError("u", 500, "err", {}, _Body(b"server error"))
        _raises(error)
        self.assertEqual(sizes, [_tencent().MAX_RESPONSE_BYTES + 1])

    def test_invalid_utf8_raises_instead_of_being_replaced(self):
        raw = _sse_reply('{"explanation": "cafe"}').encode("utf-8").replace(b"cafe", b"caf\xff")
        message = _raises(_SizedResponse(raw))
        self.assertIn("UTF-8", message)


# --------------------------------------------------------------------------- S14-009


class RequestContractTest(unittest.TestCase):
    def test_headers_and_timeout_are_sent(self):
        seen = {}

        def opener(request, timeout=None):
            seen["headers"] = {k.lower(): v for k, v in request.header_items()}
            seen["timeout"] = timeout
            return _SizedResponse(REPLY_FIXTURE.read_bytes())

        with _patched(opener):
            _client().complete(_request())
        self.assertEqual(seen["headers"].get("content-type"), "application/json")
        self.assertEqual(seen["headers"].get("accept"), "text/event-stream")
        self.assertEqual(seen["timeout"], _settings().timeout_seconds)

    def test_each_failure_names_its_cause(self):
        cases = [
            (_http_error(429, "slow down"), "HTTP 429"),
            (_http_error(500, "boom"), "HTTP 500"),
            (_http_error(501, FIREWALL_FIXTURE.read_text(encoding="utf-8")), "firewall"),
            (urllib.error.URLError(ConnectionRefusedError("refused")), "cannot reach"),
            (_SizedResponse(b"", fail=http.client.IncompleteRead(b"", 5)), "IncompleteRead"),
        ]
        for answer, needle in cases:
            with self.subTest(needle=needle):
                self.assertIn(needle, _raises(answer))


class ConcurrentPacingTest(unittest.TestCase):
    def test_concurrent_calls_on_one_client_are_spaced(self):
        # ThreadingHTTPServer shares one client across request threads.
        starts = []
        lock = threading.Lock()

        def opener(request, timeout=None):
            with lock:
                starts.append(time.monotonic())
            return _SizedResponse(REPLY_FIXTURE.read_bytes())

        client = _client(min_interval_seconds=0.15)
        barrier = threading.Barrier(4)
        errors = []

        def worker():
            try:
                barrier.wait()
                client.complete(_request())
            except Exception as exc:  # noqa: BLE001 - reported below
                errors.append(exc)

        with _patched(opener):
            threads = [threading.Thread(target=worker) for _ in range(4)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(10)
        self.assertEqual(errors, [])
        starts.sort()
        gaps = [b - a for a, b in zip(starts, starts[1:])]
        self.assertEqual(len(gaps), 3)
        self.assertGreaterEqual(min(gaps), 0.14, "calls started %s apart" % [round(g, 3) for g in gaps])


# --------------------------------------------------------------------------- S14-006, 010, docs


def _current_docs():
    """Every judge-facing document. Session briefs are dated work records and are excluded."""
    paths = [ROOT / "README.md", ROOT / "CODEBUDDY.md", ROOT / "CLAUDE.md"]
    paths += [p for p in sorted((ROOT / "docs").glob("*.md")) if not p.name.startswith("session-")]
    return [p for p in paths if p.exists()]


class DocsTruthTest(unittest.TestCase):
    STALE = re.compile(
        r"BLOCKED on an API key|TENCENT_LLM_API_KEY|TENCENT_LLM_ENDPOINT|not pinned yet"
        r"|has not been called|never been called|only mock calls|every mock string"
        r"|endpoint is unverified|UNVERIFIED against a live call|No real LLM calls",
        re.IGNORECASE,
    )

    def test_the_superseded_acquisition_note_is_gone(self):
        self.assertFalse((ROOT / "docs" / "tencent-endpoint-acquisition.md").exists())

    def test_no_current_doc_says_the_model_is_unreachable_or_mock_only(self):
        self.assertGreater(len(_current_docs()), 5, "the scan must cover the doc set")
        hits = []
        for path in _current_docs():
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if self.STALE.search(line):
                    hits.append("%s:%d: %s" % (path.relative_to(ROOT), number, line.strip()))
        self.assertEqual(hits, [])

    def test_the_readme_limits_the_mock_prefix_to_free_text(self):
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        start = text.index("**Mock by default.**")
        paragraph = text[start:text.index("\n\n", start)]
        self.assertIn("free-text", paragraph)
        self.assertIn("MOCK", paragraph)
        self.assertRegex(paragraph, r"actions?, amounts?, rule IDs")

    def test_the_readme_prefix_claim_matches_a_real_mock_run(self):
        # The claim above must be true of the mock: free text prefixed, structured fields not.
        with tempfile.TemporaryDirectory() as tmp:
            case = run_fixture(ROUTE_DEVIATION, Path(tmp) / "run")
        ruling = case.resolution["ruling"]
        self.assertTrue(ruling["explanation"].startswith("MOCK"))
        self.assertFalse(str(ruling["action"]).startswith("MOCK"))


if __name__ == "__main__":
    unittest.main()
