"""W47 A acceptance: the separate LIVE launcher, its Windows/macOS wrappers and the one
provider-neutral start-page sentence.

Written RED-first by the planner. On the unmodified baseline every "behaviour" test fails
for the intended reason (tools/launch_live.py, start-live.bat and start-live.command do
not exist; the start page still carries the old mock-only sentence). The builder makes
this file green without editing it.

W47 R2 (this revision) adds the parent-reproduced guard pins:
  * the endpoint is pinned to the one reviewed ADP URL and SET explicitly before
    construction, so neither a stale inherited TENCENT_ADP_ENDPOINT nor a stray legacy
    .env can redirect the calls (EndpointPin);
  * the sidecar is read at one boundary: invalid UTF-8 and read errors are fixed plain
    refusals, and a malformed or duplicated assignment is refused before the app's parser
    is trusted with values (SidecarReadBoundary, SidecarValidation);
  * a constructor failure never echoes the Tencent client's own message, which can quote
    the endpoint that carries an app key (StartupErrorRedaction).
A guard that is absent from the implementation is a FAILURE via _guard below, never an
AttributeError ERROR, so the pre-fix run reports the missing behaviour directly.

What is pinned, by area:
  * tools/launch_live.py: a SEPARATE helper beside tools/launch.py. It always requests the
    Tencent provider explicitly, binds its OWN server on an explicit port (default 8030,
    outside the mock range) and NEVER reuses a running listener, proves in-process that the
    provider is Tencent before opening the page, and reads a dedicated sidecar whose role
    keys override any stale inherited environment.
  * Credentials never touch the command line or an error: values are never printed; only
    variable NAMES are ever named. An unexpected variable name in the sidecar is refused.
  * start-live.bat / start-live.command: find Python 3.9+, print one plain line when it is
    missing, run tools/launch_live.py from the package folder; CRLF for the .bat,
    executable mode and exec for the .command.
  * ui/start/index.html: exactly one p carries the new provider-neutral sentence, and the
    old mock-only sentence is gone.

The Windows wrapper's real cmd.exe execution is NOT available on macOS, so this file pins
its structure, quoting and CRLF bytes only; it does not claim a Windows run. The browser
probe lives in tests/browser/w47_live_launcher.cjs and is parent-owned and unexecuted here.
"""
from __future__ import annotations

import contextlib
import errno
import importlib.util
import io
import os
import re
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
LAUNCH_LIVE_PY = REPO / "tools" / "launch_live.py"
LAUNCH_MOCK_PY = REPO / "tools" / "launch.py"
START_LIVE_COMMAND = REPO / "start-live.command"
START_LIVE_BAT = REPO / "start-live.bat"
START_PAGE = REPO / "ui" / "start" / "index.html"

#: The single provider-neutral sentence that replaces the mock-only one on the start page.
START_INTRO = ("Runs on your computer with sample trips. The standard launcher uses an "
               "illustrative mock; the live launcher uses Tencent AI and needs private "
               "access keys.")
OLD_INTRO = ("Runs on your computer with sample trips. The AI is a stand-in (mock), "
             "so no key is needed.")

MISSING_PYTHON = ("Python 3.9 or newer is needed to run the Ryde live demo. Install it from "
                  "https://www.python.org/downloads/ and then open this file again.")
VERSION_CHECK = "sys.version_info >= (3, 9)"

ROLE_KEYS = ("TENCENT_ADP_RIDER_APP_KEY", "TENCENT_ADP_DRIVER_APP_KEY",
             "TENCENT_ADP_JUDGE_APP_KEY")
ENDPOINT_VAR = "TENCENT_ADP_ENDPOINT"
ALLOWED = frozenset(ROLE_KEYS + (ENDPOINT_VAR,))
LIVE_PORT = 8030

#: The one reviewed Tencent Cloud ADP URL this helper may call, and the value shipped in
#: app/config.json's llm.endpoint.
REVIEWED_ENDPOINT = "https://wss.lke.tencentcloud.com/adp/v2/chat"

#: Conspicuously fake values. They are never real keys and must never appear in output.
FAKE_RIDER = "FAKE-w47-rider-0000000000000001"
FAKE_DRIVER = "FAKE-w47-driver-0000000000000002"
FAKE_JUDGE = "FAKE-w47-judge-0000000000000003"


# ---------------------------------------------------------------- helpers


def _read_bytes(tc: unittest.TestCase, path: Path) -> bytes:
    if not path.is_file():
        tc.fail("%s is missing" % path.relative_to(REPO))
    return path.read_bytes()


def _read_text(tc: unittest.TestCase, path: Path) -> str:
    return _read_bytes(tc, path).decode("utf-8")


def _load_live(tc: unittest.TestCase):
    if not LAUNCH_LIVE_PY.is_file():
        tc.fail("tools/launch_live.py is missing")
    spec = importlib.util.spec_from_file_location("w47_live_under_test", LAUNCH_LIVE_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def _guard(tc: unittest.TestCase, module, name: str):
    """Return module.<name>, or FAIL cleanly when the guard is absent.

    The pre-fix implementation does not define these R2 attributes at all; a missing guard
    must read as a behavioural failure, never as an AttributeError that the runner counts
    as an ERROR.
    """
    if not hasattr(module, name):
        tc.fail("tools/launch_live.py defines no %s: the W47 R2 guard is missing" % name)
    return getattr(module, name)


def _port_free(port: int) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def _free_run(n: int) -> int:
    import random
    rng = random.Random()
    for _ in range(400):
        base = rng.randrange(20000, 60000)
        if all(_port_free(base + i) for i in range(n)):
            return base
    raise AssertionError("no free run of %d ports found" % n)


def _refused(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return False
    except OSError:
        return True


def _get(url: str, timeout: float = 5.0):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status, resp.headers.get("Server", ""), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers.get("Server", ""), b""


def _sidecar(tc: unittest.TestCase, lines, prefix: str = "w47-creds-") -> Path:
    d = Path(tempfile.mkdtemp(prefix=prefix))
    tc.addCleanup(shutil.rmtree, d, True)
    path = d / ".env.live"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _sidecar_raw(tc: unittest.TestCase, data: bytes, prefix: str = "w47-rawcreds-") -> Path:
    d = Path(tempfile.mkdtemp(prefix=prefix))
    tc.addCleanup(shutil.rmtree, d, True)
    path = d / ".env.live"
    path.write_bytes(data)
    return path


def _legacy_env(tc: unittest.TestCase, lines):
    """A fake, unrelated repo-root .env for one test only, removed on cleanup. It is a
    scratch fixture: no real .env is ever read, and the launcher must not let this file
    redirect its endpoint."""
    path = REPO / ".env"
    tc.assertFalse(path.exists(), "the scratch tree must not already carry a .env")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tc.addCleanup(lambda: path.exists() and path.unlink())
    return path


def _expect_credential_error(tc: unittest.TestCase, module, path):
    """Call module.parse_credentials and return its CredentialError text, converting any
    OTHER exception into a test failure: a guard must refuse plainly, never escape as a
    decode or read error."""
    try:
        values = module.parse_credentials(path)
    except module.CredentialError as exc:
        return str(exc)
    except Exception as exc:  # noqa: BLE001 - the point is to fail, not to re-raise
        tc.fail("parse_credentials raised %s, not CredentialError" % type(exc).__name__)
    tc.fail("parse_credentials accepted %s" % path)
    return ""  # unreachable; keeps the type checker quiet


def _run_both(tc: unittest.TestCase, module, argv, make_server):
    """Run module.main with a make_server that raises, capturing stdout AND stderr."""
    out, err = io.StringIO(), io.StringIO()
    with mock.patch.object(module.server, "make_server", make_server), \
            mock.patch.object(module, "open_when_ready", lambda *a: None), \
            contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = module.main(argv)
    return rc, out.getvalue(), err.getvalue()


def _valid_lines():
    return ["%s=%s" % (ROLE_KEYS[0], FAKE_RIDER),
            "%s=%s" % (ROLE_KEYS[1], FAKE_DRIVER),
            "%s=%s" % (ROLE_KEYS[2], FAKE_JUDGE)]


class _FakeHTTPD:
    """A stand-in for the ThreadingHTTPServer make_server returns, with the state the
    launcher reads back for its provider proof."""

    def __init__(self, port: int, provider: str = "tencent"):
        self.server_address = ("127.0.0.1", port)
        self.ryde_state = SimpleNamespace(llm=SimpleNamespace(provider_name=provider))
        self.closed = False
        self.served = False

    def serve_forever(self):  # noqa: N802
        self.served = True

    def server_close(self):  # noqa: N802
        self.closed = True


def _run_main(tc, module, argv, *, httpd=None, make_server=None, opener_recorder=None):
    """Run module.main with make_server patched. Returns (rc, lines, calls, httpd)."""
    calls = {"make_server": [], "opener": [], "endpoint_env": []}
    if httpd is None:
        httpd = _FakeHTTPD(LIVE_PORT)
    holder = {"httpd": httpd}

    def fake_make_server(port, **kwargs):
        calls["make_server"].append((port, kwargs))
        # The endpoint the launcher deliberately SET in this process at construction time:
        # it must be the reviewed URL, never a stale inherited value or a legacy .env.
        calls["endpoint_env"].append(os.environ.get(ENDPOINT_VAR))
        httpd.server_address = ("127.0.0.1", port)  # report the port we were asked to bind
        holder["httpd"] = httpd
        return httpd

    def fake_opener(url, *a, **k):
        calls["opener"].append(url)
        if opener_recorder is not None:
            opener_recorder.append(url)

    out = io.StringIO()
    with mock.patch.object(module.server, "make_server", make_server or fake_make_server), \
            mock.patch.object(module, "open_when_ready", fake_opener), \
            contextlib.redirect_stdout(out):
        rc = module.main(argv)
    return rc, out.getvalue().splitlines(), calls, holder["httpd"]


# ---------------------------------------------------------------- module contract


class ModuleContract(unittest.TestCase):

    def setUp(self):
        self.m = _load_live(self)

    def test_it_is_a_separate_helper_beside_the_mock_launcher(self):
        self.assertTrue(LAUNCH_LIVE_PY.is_file())
        self.assertTrue(LAUNCH_MOCK_PY.is_file(), "the mock launcher still exists, unchanged")
        self.assertNotEqual(LAUNCH_LIVE_PY, LAUNCH_MOCK_PY)

    def test_default_port_is_8030_outside_the_mock_range(self):
        self.assertEqual(LIVE_PORT, self.m.LIVE_PORT)
        self.assertNotIn(self.m.LIVE_PORT, range(8000, 8011),
                         "the live port is outside the mock launcher's range")

    def test_start_path_is_the_party_page_not_the_start_page(self):
        self.assertEqual("/party/", self.m.PARTY_PATH)
        self.assertNotEqual(getattr(self.m, "START_PATH", None), self.m.PARTY_PATH)

    def test_the_provider_is_named_tencent(self):
        self.assertEqual("tencent", self.m.PROVIDER)

    def test_only_the_three_keys_and_an_endpoint_may_be_set(self):
        self.assertEqual(ALLOWED, set(self.m.ALLOWED_ENV_VARS))
        self.assertEqual(set(ROLE_KEYS), set(self.m.ROLE_KEY_ENV_VARS))
        self.assertEqual(ENDPOINT_VAR, self.m.ENDPOINT_ENV_VAR)

    def test_credentials_path_defaults_to_env_live_at_the_package_root(self):
        self.assertEqual(REPO / ".env.live",
                         self.m.credentials_path(REPO, None))

    def test_credentials_path_honours_an_explicit_override(self):
        explicit = Path("/tmp/elsewhere/.env.live")
        self.assertEqual(explicit, self.m.credentials_path(REPO, explicit))


# ---------------------------------------------------------------- credentials parsing


class CredentialsParse(unittest.TestCase):

    def setUp(self):
        self.m = _load_live(self)

    def test_reads_the_app_env_dialect_export_and_quotes(self):
        path = _sidecar(self, ["export %s='%s'" % (ROLE_KEYS[0], FAKE_RIDER),
                               '# a comment',
                               '%s="%s"' % (ROLE_KEYS[1], FAKE_DRIVER),
                               "%s=%s" % (ROLE_KEYS[2], FAKE_JUDGE)])
        values = self.m.parse_credentials(path)
        self.assertEqual(FAKE_RIDER, values[ROLE_KEYS[0]])
        self.assertEqual(FAKE_DRIVER, values[ROLE_KEYS[1]])
        self.assertEqual(FAKE_JUDGE, values[ROLE_KEYS[2]])

    def test_rejects_an_unexpected_variable_name(self):
        path = _sidecar(self, _valid_lines() + ["PATH=/bin/evil"])
        with self.assertRaises(self.m.CredentialError) as cm:
            self.m.parse_credentials(path)
        self.assertIn("PATH", str(cm.exception))
        self.assertNotIn(FAKE_RIDER, str(cm.exception))

    def test_does_not_name_values_in_the_unexpected_name_error(self):
        path = _sidecar(self, _valid_lines() + ["SOME_SECRET=%s" % FAKE_RIDER])
        with self.assertRaises(self.m.CredentialError) as cm:
            self.m.parse_credentials(path)
        self.assertNotIn(FAKE_RIDER, str(cm.exception))

    def test_missing_role_keys_flags_blank_and_placeholder(self):
        values = {ROLE_KEYS[0]: FAKE_RIDER, ROLE_KEYS[1]: "   ",
                  ROLE_KEYS[2]: "your-key-here"}
        self.assertEqual([ROLE_KEYS[1], ROLE_KEYS[2]], self.m.missing_role_keys(values))

    def test_all_three_real_shaped_keys_are_accepted(self):
        values = dict(zip(ROLE_KEYS, (FAKE_RIDER, FAKE_DRIVER, FAKE_JUDGE)))
        self.assertEqual([], self.m.missing_role_keys(values))

    def test_only_the_reviewed_endpoint_passes_as_an_override(self):
        # W47 R2: the optional endpoint override must be the one reviewed URL. This fixture
        # used to assert that an arbitrary endpoint (https://real.example/x) was ACCEPTED;
        # that is now invalid by design (the endpoint carries all three app keys), so the
        # expectation is inverted. The refusal path is pinned in EndpointPin below.
        endpoint_is_bad = _guard(self, self.m, "endpoint_is_bad")
        self.assertTrue(endpoint_is_bad({ENDPOINT_VAR: "todo"}))
        self.assertTrue(endpoint_is_bad({ENDPOINT_VAR: "https://real.example/x"}))
        self.assertFalse(endpoint_is_bad({ENDPOINT_VAR: REVIEWED_ENDPOINT}))
        self.assertFalse(endpoint_is_bad({}), "an absent endpoint is fine")


# ---------------------------------------------------------------- precedence


class SidecarPrecedence(unittest.TestCase):

    def setUp(self):
        self.m = _load_live(self)

    def test_apply_overrides_a_stale_inherited_key(self):
        stale = {ROLE_KEYS[0]: "FAKE-stale-key", ROLE_KEYS[1]: "FAKE-stale-key",
                 ROLE_KEYS[2]: "FAKE-stale-key"}
        values = dict(zip(ROLE_KEYS, (FAKE_RIDER, FAKE_DRIVER, FAKE_JUDGE)))
        with mock.patch.dict(os.environ, stale, clear=False):
            self.m.apply_credentials(values)
            self.assertEqual(FAKE_RIDER, os.environ[ROLE_KEYS[0]])
            self.assertEqual(FAKE_DRIVER, os.environ[ROLE_KEYS[1]])
            self.assertEqual(FAKE_JUDGE, os.environ[ROLE_KEYS[2]])

    def test_a_missing_key_in_the_sidecar_cannot_leave_a_stale_one_standing(self):
        # Only two role keys supplied: the third must NOT survive from the environment.
        stale = {ROLE_KEYS[2]: "FAKE-stale-third"}
        values = {ROLE_KEYS[0]: FAKE_RIDER, ROLE_KEYS[1]: FAKE_DRIVER}
        with mock.patch.dict(os.environ, stale, clear=False):
            self.assertEqual("FAKE-stale-third", os.environ[ROLE_KEYS[2]])
            self.m.apply_credentials(values)
            self.assertNotIn(ROLE_KEYS[2], os.environ,
                             "a stale third key is not left for the client to pick up")

    def test_apply_writes_only_allowed_names(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.m.apply_credentials({ROLE_KEYS[0]: FAKE_RIDER, "PATH": "/evil"})
            self.assertEqual(FAKE_RIDER, os.environ[ROLE_KEYS[0]])
            self.assertNotIn("PATH", os.environ)


# ---------------------------------------------------------------- endpoint pin


class EndpointPin(unittest.TestCase):
    """The endpoint carries all three app keys, so this helper may call only one reviewed
    URL; an invalid override or a shipped config that differs is refused before any bind
    or browser."""

    def setUp(self):
        self.m = _load_live(self)

    def test_malformed_endpoint_urls_are_plain_refusals(self):
        for value in ("https://[", "https://[invalid", "https://[::1"):
            with self.subTest(endpoint=value):
                creds = _sidecar(self, _valid_lines() + ["%s=%s" % (ENDPOINT_VAR, value)])
                try:
                    rc, lines, calls, _httpd = _run_main(
                        self, self.m, ["--credentials", str(creds)]
                    )
                except Exception as exc:
                    self.fail("malformed endpoint raised %s instead of a plain refusal" %
                              type(exc).__name__)
                self.assertEqual(1, rc)
                self.assertEqual([], calls["make_server"])
                self.assertNotIn(value, "\n".join(lines))

    def test_the_reviewed_endpoint_is_the_shipped_tencent_adp_url(self):
        self.assertEqual(REVIEWED_ENDPOINT, _guard(self, self.m, "REVIEWED_ENDPOINT"))

    def test_only_the_reviewed_endpoint_is_a_valid_override(self):
        endpoint_is_bad = _guard(self, self.m, "endpoint_is_bad")
        self.assertTrue(endpoint_is_bad({ENDPOINT_VAR: "todo"}))
        self.assertTrue(endpoint_is_bad({ENDPOINT_VAR: ""}))
        self.assertTrue(endpoint_is_bad({ENDPOINT_VAR: "https://evil.example/adp/v2/chat"}))
        self.assertFalse(endpoint_is_bad({ENDPOINT_VAR: REVIEWED_ENDPOINT}))
        self.assertFalse(endpoint_is_bad({}))

    def test_the_shipped_config_endpoint_is_the_same_reviewed_url(self):
        ok = _guard(self, self.m, "shipped_endpoint_ok")
        endpoint = _guard(self, self.m, "shipped_endpoint")
        self.assertTrue(ok())
        self.assertEqual(REVIEWED_ENDPOINT, endpoint())

    def test_a_different_shipped_config_endpoint_is_refused(self):
        ok = _guard(self, self.m, "shipped_endpoint_ok")
        _guard(self, self.m, "load_config")
        other = SimpleNamespace(llm=SimpleNamespace(endpoint="https://evil.example/adp/v2/chat"))
        with mock.patch.object(self.m, "load_config", lambda: other):
            self.assertFalse(ok())
        good = SimpleNamespace(llm=SimpleNamespace(endpoint=REVIEWED_ENDPOINT))
        with mock.patch.object(self.m, "load_config", lambda: good):
            self.assertTrue(ok())

    def test_a_config_that_will_not_load_is_refused_not_raised(self):
        ok = _guard(self, self.m, "shipped_endpoint_ok")
        config_error = _guard(self, self.m, "ConfigError")
        _guard(self, self.m, "load_config")
        with mock.patch.object(self.m, "load_config", side_effect=config_error("boom")):
            try:
                result = ok()
            except Exception as exc:  # noqa: BLE001
                self.fail("shipped_endpoint_ok raised %s" % type(exc).__name__)
        self.assertFalse(result)

    def test_each_invalid_endpoint_is_refused_before_any_bind_or_browser(self):
        bad_endpoints = [
            "http://wss.lke.tencentcloud.com/adp/v2/chat",              # scheme downgrade
            "https://evil.example/adp/v2/chat",                         # alternate host
            "https://wss.lke.tencentcloud.com.evil.example/adp/v2/chat",
            "https://wss.lke.tencentcloud.com.evil.example:443/adp/v2/chat",
            "https://user:pass@wss.lke.tencentcloud.com/adp/v2/chat",   # userinfo
            "https://wss.lke.tencentcloud.com:8443/adp/v2/chat",        # alternate port
            "https://wss.lke.tencentcloud.com/adp/v2/chat?x=1",         # query
            "https://wss.lke.tencentcloud.com/adp/v2/chat#frag",        # fragment
            "https://wss.lke.tencentcloud.com/adp/v2/chat/",            # path variant
            "https://wss.lke.tencentcloud.com/adp/v1/chat",
            "TODO-pin-FAKE-endpoint-0000000000000000",
            "",
        ]
        for value in bad_endpoints:
            with self.subTest(endpoint=value):
                creds = _sidecar(self, _valid_lines() + ["%s=%s" % (ENDPOINT_VAR, value)])
                opener = []
                rc, lines, calls, _httpd = _run_main(
                    self, self.m, ["--credentials", str(creds)], opener_recorder=opener)
                self.assertEqual(1, rc, "an invalid endpoint must be refused")
                self.assertEqual([], calls["make_server"],
                                 "refusal must happen before the provider is constructed")
                self.assertEqual([], opener, "the page is never opened on an invalid endpoint")
                blob = "\n".join(lines)
                self.assertIn(ENDPOINT_VAR, blob)
                if value:
                    self.assertNotIn(value, blob, "the endpoint value is never echoed")

    def test_a_sidecar_endpoint_equal_to_the_reviewed_url_is_accepted_and_pinned(self):
        creds = _sidecar(self, _valid_lines() + ["%s=%s" % (ENDPOINT_VAR, REVIEWED_ENDPOINT)])
        rc, _lines, calls, _httpd = _run_main(self, self.m, ["--credentials", str(creds)])
        self.assertEqual(0, rc)
        self.assertEqual([REVIEWED_ENDPOINT], calls["endpoint_env"])

    def test_the_endpoint_is_pinned_despite_stale_env_and_a_legacy_dotenv(self):
        # No endpoint in the selected sidecar, a stale inherited value AND an unrelated fake
        # repo-root .env: none of them may reach construction.
        creds = _sidecar(self, _valid_lines())
        _legacy_env(self, ["%s=https://legacy.invalid/adp" % ENDPOINT_VAR,
                           "%s=FAKE-legacy-rider-0000000000000009" % ROLE_KEYS[0]])
        stale = {ENDPOINT_VAR: "https://stale.invalid/adp"}
        with mock.patch.dict(os.environ, stale, clear=False):
            rc, _lines, calls, _httpd = _run_main(self, self.m, ["--credentials", str(creds)])
            self.assertEqual(0, rc)
            self.assertEqual([REVIEWED_ENDPOINT], calls["endpoint_env"],
                             "the reviewed endpoint is set explicitly before construction")

    def test_main_refuses_when_the_shipped_config_endpoint_is_not_reviewed(self):
        _guard(self, self.m, "shipped_endpoint_ok")
        creds = _sidecar(self, _valid_lines())
        opener = []
        with mock.patch.object(self.m, "shipped_endpoint_ok", lambda: False):
            rc, lines, calls, _httpd = _run_main(
                self, self.m, ["--credentials", str(creds)], opener_recorder=opener)
        self.assertEqual(1, rc)
        self.assertEqual([], calls["make_server"])
        self.assertEqual([], opener)
        self.assertIn("app/config.json", "\n".join(lines))


# ---------------------------------------------------------------- sidecar validation


class SidecarValidation(unittest.TestCase):
    """The strict pre-check refuses lines the app's minimal parser would ignore or
    overwrite; malformed text is never echoed."""

    def setUp(self):
        self.m = _load_live(self)

    def test_a_valid_sidecar_still_parses(self):
        path = _sidecar(self, _valid_lines())
        values = self.m.parse_credentials(path)
        self.assertEqual(FAKE_RIDER, values[ROLE_KEYS[0]])

    def test_a_line_without_an_assignment_is_refused_without_echoing_it(self):
        path = _sidecar(self, _valid_lines() + ["this line is not an assignment"])
        message = _expect_credential_error(self, self.m, path)
        self.assertNotIn("this line is not an assignment", message)

    def test_a_malformed_name_is_a_bad_line_not_an_unknown_name(self):
        path = _sidecar(self, _valid_lines() + ["=oops"])
        message = _expect_credential_error(self, self.m, path)
        self.assertIn("line 4", message, "the malformed line is named by number")

    def test_a_duplicate_role_key_is_refused(self):
        path = _sidecar(self, _valid_lines() + ["%s=FAKE-second-rider" % ROLE_KEYS[0]])
        message = _expect_credential_error(self, self.m, path)
        self.assertIn(ROLE_KEYS[0], message)
        self.assertNotIn("FAKE-second-rider", message)

    def test_a_duplicate_endpoint_is_refused(self):
        path = _sidecar(self, _valid_lines() + ["%s=%s" % (ENDPOINT_VAR, REVIEWED_ENDPOINT)] * 2)
        message = _expect_credential_error(self, self.m, path)
        self.assertIn(ENDPOINT_VAR, message)

    def test_a_malformed_sidecar_stops_before_any_bind(self):
        path = _sidecar(self, _valid_lines() + ["nonsense"])
        opener = []
        rc, lines, calls, _httpd = _run_main(
            self, self.m, ["--credentials", str(path)], opener_recorder=opener)
        self.assertEqual(1, rc)
        self.assertEqual([], calls["make_server"])
        self.assertEqual([], opener)
        self.assertNotIn("nonsense", "\n".join(lines))


# ---------------------------------------------------------------- read boundary


class SidecarReadBoundary(unittest.TestCase):
    """An unreadable or non-UTF-8 sidecar is a fixed plain refusal, never a traceback and
    never echoed content."""

    def setUp(self):
        self.m = _load_live(self)

    def test_invalid_utf8_is_a_plain_refusal_not_a_traceback(self):
        path = _sidecar_raw(self, b"\xff\xfe\x00")
        message = _expect_credential_error(self, self.m, path)
        self.assertIn(".env.live", message)
        self.assertNotIn("Traceback", message)

    def test_invalid_utf8_through_main_refuses_before_any_bind(self):
        path = _sidecar_raw(self, b"\xff\xfe\x00")
        opener = []
        try:
            rc, lines, calls, _httpd = _run_main(
                self, self.m, ["--credentials", str(path)], opener_recorder=opener)
        except Exception as exc:  # noqa: BLE001
            self.fail("main raised %s instead of a plain refusal" % type(exc).__name__)
        self.assertEqual(1, rc)
        self.assertEqual([], calls["make_server"])
        self.assertEqual([], opener)
        self.assertNotIn("Traceback", "\n".join(lines))

    def test_a_read_error_is_a_plain_refusal(self):
        directory = Path(tempfile.mkdtemp(prefix="w47-dircreds-"))
        self.addCleanup(shutil.rmtree, directory, True)
        message = _expect_credential_error(self, self.m, directory)
        self.assertIn("could not be read", message)

    def test_a_permission_error_is_a_plain_refusal(self):
        directory = Path(tempfile.mkdtemp(prefix="w47-permcreds-"))
        self.addCleanup(shutil.rmtree, directory, True)
        path = directory / ".env.live"
        path.write_text("X=1\n", encoding="utf-8")
        os.chmod(str(path), 0)
        self.addCleanup(os.chmod, str(path), 0o600)
        if os.access(str(path), os.R_OK):
            self.skipTest("the file is still readable (running as root?)")
        _expect_credential_error(self, self.m, path)


# ---------------------------------------------------------------- startup redaction


class StartupErrorRedaction(unittest.TestCase):
    """A constructor failure must never print the Tencent client's own message: it can
    quote the endpoint, which carries an app key. The launcher prints one fixed line."""

    def setUp(self):
        self.m = _load_live(self)

    def test_the_startup_line_is_fixed_and_carries_no_placeholder(self):
        literal = _guard(self, self.m, "START_FAILED")
        self.assertNotIn("{", literal, "the startup line must be fixed, not a template")

    def test_each_fake_key_in_a_constructor_error_is_never_echoed(self):
        for key in (FAKE_RIDER, FAKE_DRIVER, FAKE_JUDGE):
            with self.subTest(key=key):
                creds = _sidecar(self, _valid_lines())

                def boom(port, **kwargs):
                    raise self.m.LLMError(
                        "llm.endpoint is not set ('https://wss.lke.tencentcloud.com/adp/"
                        "v2/chat/" + key + "'); key=" + key)

                rc, out, err = _run_both(self, self.m, ["--credentials", str(creds)], boom)
                blob = out + err
                self.assertEqual(1, rc)
                self.assertNotIn(key, blob, "no constructor text reaches stdout/stderr")
                self.assertNotIn("Traceback", blob)
                self.assertIn("could not start", out)

    def test_a_sidecar_endpoint_carrying_a_key_is_refused_without_echoing_it(self):
        # The parent-reproduced family: TENCENT_ADP_ENDPOINT=TODO-pin-<fake key>.
        fake = FAKE_RIDER
        creds = _sidecar(self, _valid_lines() + ["%s=TODO-pin-%s" % (ENDPOINT_VAR, fake)])
        opener = []
        rc, lines, calls, _httpd = _run_main(
            self, self.m, ["--credentials", str(creds)], opener_recorder=opener)
        blob = "\n".join(lines)
        self.assertEqual(1, rc)
        self.assertEqual([], calls["make_server"], "refused before provider construction")
        self.assertEqual([], opener)
        self.assertNotIn(fake, blob)
        self.assertIn(ENDPOINT_VAR, blob)


# ---------------------------------------------------------------- main, no server


class MainSelection(unittest.TestCase):

    def setUp(self):
        self.m = _load_live(self)

    def _valid_sidecar(self):
        return _sidecar(self, _valid_lines())

    def test_requests_tencent_explicitly_and_never_the_config_provider(self):
        creds = self._valid_sidecar()
        rc, _lines, calls, _httpd = _run_main(self, self.m, ["--credentials", str(creds)])
        self.assertEqual(1, len(calls["make_server"]), "the server is built exactly once")
        _port, kwargs = calls["make_server"][0]
        self.assertEqual("tencent", kwargs.get("provider"),
                         "the provider is passed explicitly, not left to app/config.json")
        self.assertNotIn("llm", kwargs, "an llm= would bypass the provider proof")

    def test_default_port_is_8030_and_an_explicit_port_is_honoured(self):
        creds = self._valid_sidecar()
        _rc, _lines, calls, _httpd = _run_main(self, self.m, ["--credentials", str(creds)])
        self.assertEqual(LIVE_PORT, calls["make_server"][0][0])
        want = _free_run(1)
        _rc, _lines, calls, _httpd = _run_main(
            self, self.m, ["--credentials", str(creds), "--port", str(want)])
        self.assertEqual(want, calls["make_server"][0][0])

    def test_opens_the_party_page_not_the_start_page(self):
        creds = self._valid_sidecar()
        rc, _lines, calls, _httpd = _run_main(
            self, self.m, ["--credentials", str(creds), "--port", "8031"])
        self.assertEqual(0, rc)
        self.assertEqual(["http://127.0.0.1:8031/party/"], calls["opener"])
        self.assertNotIn("/start/", calls["opener"][0])

    def test_prints_the_console_and_status_urls(self):
        creds = self._valid_sidecar()
        rc, lines, _calls, _httpd = _run_main(
            self, self.m, ["--credentials", str(creds), "--port", "8032"])
        self.assertEqual(0, rc)
        blob = "\n".join(lines)
        self.assertIn("http://127.0.0.1:8032/party/", blob)
        self.assertIn("http://127.0.0.1:8032/", blob)
        self.assertIn("http://127.0.0.1:8032/party/status.html", blob)
        self.assertIn("tencent", blob)

    def test_refuses_a_provider_that_is_not_tencent(self):
        creds = self._valid_sidecar()
        fake = _FakeHTTPD(8030, provider="mock")
        opener = []
        rc, lines, calls, httpd = _run_main(
            self, self.m, ["--credentials", str(creds)], httpd=fake,
            opener_recorder=opener)
        self.assertEqual(1, rc, "a non-Tencent provider is a refusal, not a fallback")
        self.assertIn("tencent", "\n".join(lines).lower())
        self.assertEqual([], opener, "the page is never opened on the wrong provider")
        self.assertTrue(fake.closed, "the refused server is closed")

    def test_missing_credentials_file_is_a_plain_refusal_before_any_bind(self):
        missing = REPO / "no-such-sidecar.env.live"
        rc, lines, calls, _httpd = _run_main(
            self, self.m, ["--credentials", str(missing)])
        self.assertEqual(1, rc)
        self.assertEqual([], calls["make_server"], "nothing binds without credentials")
        self.assertEqual(1, len(lines))
        self.assertIn(".env.live", lines[0])

    def test_an_unexpected_variable_name_stops_before_any_bind(self):
        path = _sidecar(self, _valid_lines() + ["AWS_SECRET_ACCESS_KEY=whatever"])
        rc, lines, calls, _httpd = _run_main(self, self.m, ["--credentials", str(path)])
        self.assertEqual(1, rc)
        self.assertEqual([], calls["make_server"])
        self.assertIn("AWS_SECRET_ACCESS_KEY", "\n".join(lines))

    def test_a_missing_role_key_stops_and_names_only_the_variable(self):
        path = _sidecar(self, _valid_lines()[:2])  # judge key absent
        rc, lines, calls, _httpd = _run_main(self, self.m, ["--credentials", str(path)])
        self.assertEqual(1, rc)
        self.assertEqual([], calls["make_server"])
        blob = "\n".join(lines)
        self.assertIn(ROLE_KEYS[2], blob)
        self.assertNotIn(FAKE_RIDER, blob)
        self.assertNotIn(FAKE_DRIVER, blob)

    def test_a_placeholder_endpoint_override_stops_before_any_bind(self):
        path = _sidecar(self, _valid_lines() + ["%s=todo" % ENDPOINT_VAR])
        rc, lines, calls, _httpd = _run_main(self, self.m, ["--credentials", str(path)])
        self.assertEqual(1, rc)
        self.assertEqual([], calls["make_server"])
        self.assertIn(ENDPOINT_VAR, "\n".join(lines))

    def test_no_error_path_ever_prints_a_credential_value(self):
        sentinel = "FAKE-secret-sentinel-DO-NOT-PRINT-9x8y7z"
        cases = {
            "unknown-name": _valid_lines() + ["LEAK=%s" % sentinel],
            "missing-key": ["%s=%s" % (ROLE_KEYS[0], sentinel)],
            "bad-endpoint": _valid_lines() + ["%s=%s" % (ENDPOINT_VAR, "<placeholder>")],
        }
        for name, lines in cases.items():
            with self.subTest(case=name):
                path = _sidecar(self, lines)
                _rc, out_lines, _calls, _httpd = _run_main(
                    self, self.m, ["--credentials", str(path)])
                self.assertNotIn(sentinel, "\n".join(out_lines))


# ---------------------------------------------------------------- live subprocess


def _child_env(tc):
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    for key in ROLE_KEYS + (ENDPOINT_VAR,):
        env.pop(key, None)
    env["BROWSER"] = "/usr/bin/true"  # never launch a real browser from a test
    return env


class LiveSubprocess(unittest.TestCase):
    """Runs the real helper in a child process against the real app.server entry point,
    with a fake-shaped sidecar and no network: binding and serving are exercised, no ADP
    call is ever made because nothing files a dispute."""

    def _start(self, argv):
        env = _child_env(self)
        proc = subprocess.Popen(
            [sys.executable, "-B", str(LAUNCH_LIVE_PY)] + argv,
            cwd=str(REPO), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(lambda: proc.poll() is None and proc.kill())
        return proc

    def _wait_ready(self, proc, port):
        deadline = time.time() + 20
        while time.time() < deadline:
            if proc.poll() is not None:
                return False
            try:
                if _get("http://127.0.0.1:%d/party/" % port, timeout=1)[0] == 200:
                    return True
            except OSError:
                time.sleep(0.2)
        return False

    def test_binds_its_own_server_proves_tencent_and_stops_on_sigint(self):
        creds = _sidecar(self, _valid_lines())
        port = _free_run(1)
        proc = self._start(["--credentials", str(creds), "--port", str(port)])
        self.assertTrue(self._wait_ready(proc, port), "the live server never answered")
        status, server_header, body = _get("http://127.0.0.1:%d/party/" % port)
        self.assertEqual(200, status)
        self.assertTrue(server_header.startswith("RydePartyServer/"),
                        "the launcher bound the real Ryde server")
        proc.send_signal(signal.SIGINT)
        try:
            out, err = proc.communicate(timeout=15)
        except subprocess.TimeoutExpired:
            self.fail("Ctrl+C did not stop the live launcher")
        self.assertEqual(0, proc.returncode, err[-400:])
        self.assertIn("http://127.0.0.1:%d/party/" % port, out)
        self.assertIn("/party/status.html", out)
        self.assertIn("tencent", out)
        time.sleep(0.3)
        self.assertTrue(_refused(port), "Ctrl+C freed the port")

    def test_an_occupied_port_is_a_plain_refusal_not_a_mock_tab(self):
        creds = _sidecar(self, _valid_lines())
        port = _free_run(1)
        squatter = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        squatter.bind(("127.0.0.1", port))
        squatter.listen(1)
        self.addCleanup(squatter.close)
        proc = self._start(["--credentials", str(creds), "--port", str(port)])
        out, err = proc.communicate(timeout=20)
        self.assertEqual(1, proc.returncode, err[-400:])
        self.assertIn("already in use", out)
        self.assertNotIn("Traceback", err)

    def test_never_reuses_a_running_ryde_demo_on_the_port(self):
        # A mock Ryde demo answers with the banner the old launcher would reuse.
        from app.server import make_server
        from app.llm import build_llm_client
        out_dir = Path(tempfile.mkdtemp(prefix="w47-runs-"))
        self.addCleanup(shutil.rmtree, out_dir, True)
        port = _free_run(1)
        httpd = make_server(port, out_dir=out_dir, llm=build_llm_client("mock"))
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        creds = _sidecar(self, _valid_lines())
        proc = self._start(["--credentials", str(creds), "--port", str(port)])
        out, err = proc.communicate(timeout=20)
        self.assertEqual(1, proc.returncode, "the live launcher must refuse, not reuse")
        self.assertIn("already in use", out)


# ---------------------------------------------------------------- wrappers


FAKE_PYTHON = '''#!/bin/bash
printf '%s|%s\\n' "$PWD" "$*" >> "$W47_RECORD"
if [ "$1" = "-c" ]; then exit "${W47_VERSION_RC:-0}"; fi
exit 0
'''


@unittest.skipUnless(os.name == "posix", "runs start-live.command under bash")
class StartLiveCommand(unittest.TestCase):

    def test_is_an_executable_bash_script_with_unix_line_endings(self):
        data = _read_bytes(self, START_LIVE_COMMAND)
        self.assertTrue(data.startswith(b"#!/bin/bash\n"), "first line is #!/bin/bash")
        self.assertNotIn(b"\r", data)
        mode = START_LIVE_COMMAND.stat().st_mode
        self.assertTrue(mode & stat.S_IXUSR and mode & stat.S_IXGRP and mode & stat.S_IXOTH,
                        "start-live.command is executable (chmod 755)")

    def _run(self):
        tmp = Path(tempfile.mkdtemp(prefix="w47-cmd-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        bindir = tmp / "bin"
        bindir.mkdir()
        record = tmp / "calls.txt"
        fake = bindir / "python3"
        fake.write_text(FAKE_PYTHON, encoding="utf-8")
        fake.chmod(0o755)
        env = {"PATH": "%s:/usr/bin:/bin" % bindir, "HOME": str(tmp),
               "W47_RECORD": str(record), "W47_VERSION_RC": "0"}
        _read_bytes(self, START_LIVE_COMMAND)
        proc = subprocess.run(["/bin/bash", str(START_LIVE_COMMAND)], cwd=str(tmp), env=env,
                              stdin=subprocess.DEVNULL, capture_output=True, text=True,
                              timeout=30)
        calls = record.read_text().splitlines() if record.is_file() else []
        return proc, calls

    def test_runs_launch_live_py_from_the_package_folder_after_the_version_check(self):
        proc, calls = self._run()
        self.assertEqual(0, proc.returncode, proc.stderr)
        self.assertGreaterEqual(len(calls), 2, calls)
        here, args = calls[-1].split("|", 1)
        self.assertEqual(os.path.realpath(REPO), os.path.realpath(here))
        self.assertEqual("tools/launch_live.py", args)
        checks = [c for c in calls[:-1] if c.split("|", 1)[1].startswith("-c ")]
        self.assertTrue(checks and all(VERSION_CHECK in c for c in checks), calls)

    def test_hands_over_with_exec_so_the_window_owns_one_process(self):
        body = "\n".join(line for line in _read_text(self, START_LIVE_COMMAND).splitlines()
                         if not line.lstrip().startswith("#"))
        self.assertRegex(body,
                         r'(?m)^\s*exec\s+(python3|"?\$\{?[A-Za-z_]+\}?"?)\s+tools/launch_live\.py\s+"\$@"\s*$')
        self.assertNotRegex(body, r'(?m)^\s*exec\s*\(\s*\)',
                            "the wrapper must not replace the shell exec builtin")


class StartLiveBat(unittest.TestCase):
    """Structure, quoting and CRLF only: cmd.exe is not run here (no Windows)."""

    def test_uses_windows_line_endings_throughout(self):
        data = _read_bytes(self, START_LIVE_BAT)
        self.assertGreater(data.count(b"\r\n"), 5)
        self.assertEqual(data.count(b"\n"), data.count(b"\r\n"), "every line ends CRLF")

    def _lines(self):
        body = _read_text(self, START_LIVE_BAT)
        keep = []
        for line in body.splitlines():
            s = line.strip().lower()
            if s.startswith("rem ") or s == "rem" or s.startswith("::"):
                continue
            if line.strip():
                keep.append(line.strip())
        return keep

    def test_contract_lines_and_quoting(self):
        body = _read_text(self, START_LIVE_BAT)
        stripped = "\n".join(self._lines())
        self.assertEqual("@echo off", stripped.splitlines()[0].lower())
        # Quoting pin: the script changes to its own folder with the driver quoted, so a
        # path with spaces (a ZIP extracted to "My Folder") still works.
        self.assertIn('cd /d "%~dp0"', stripped)
        self.assertRegex(stripped, r"(?m)^\s*py -3 -c \"[^\"]*" + re.escape(VERSION_CHECK))
        self.assertRegex(stripped, r"(?m)^\s*python -c \"[^\"]*" + re.escape(VERSION_CHECK))
        self.assertLess(stripped.index("py -3 -c"), stripped.index("python -c"),
                        "py -3 is tried first")
        self.assertIn("tools\\launch_live.py", stripped)

    def test_prints_the_exact_missing_python_sentence(self):
        stripped = "\n".join(self._lines())
        literal = re.search(r"(?im)^\s*echo\s+" + re.escape(MISSING_PYTHON) + r"\s*$", stripped)
        via_var = re.search(r'(?im)^\s*set\s+"(\w+)=' + re.escape(MISSING_PYTHON) + r'"\s*$',
                            stripped)
        if via_var:
            self.assertRegex(stripped, r"(?im)^\s*echo\s+%" + via_var.group(1) + r"%\s*$")
        self.assertTrue(literal or via_var, "start-live.bat prints the exact sentence")

    def _block_pauses_before_exit(self, lines, start):
        for line in lines[start:]:
            low = line.lower()
            if low == "pause":
                return True
            if low.startswith("exit") or low.startswith("goto ") or low.startswith(":"):
                return False
        return False

    def test_a_failed_launch_pauses_so_the_window_does_not_vanish(self):
        lines = self._lines()
        runs = [i for i, line in enumerate(lines) if re.search(r"tools\\launch_live\.py", line)]
        self.assertTrue(runs, "start-live.bat runs tools\\launch_live.py")
        after = lines[runs[-1] + 1:]
        self.assertTrue(after, "something handles the launcher's exit code")
        first = after[0].lower()
        direct = re.fullmatch(r"if\s+(errorlevel\s+1|%errorlevel%\s+neq\s+0)\s+pause", first)
        jump = re.fullmatch(r"if\s+(errorlevel\s+1|%errorlevel%\s+neq\s+0)\s+goto\s+:?(\w+)", first)
        if direct:
            return
        self.assertTrue(jump, "the line after the launch checks its exit code: %r" % after[0])
        label = [i for i, line in enumerate(lines) if line.lower() == ":" + jump.group(2).lower()]
        self.assertEqual(1, len(label), "the failure label exists once")
        self.assertTrue(self._block_pauses_before_exit(lines, label[0] + 1),
                        "the failure path pauses before it exits")


# ---------------------------------------------------------------- start page


class StartPageIntro(unittest.TestCase):

    def test_the_neutral_sentence_is_present_and_the_mock_only_one_is_gone(self):
        text = _read_text(self, START_PAGE)
        self.assertIn(START_INTRO, text, "the provider-neutral sentence is on the start page")
        self.assertNotIn(OLD_INTRO, text, "the mock-only sentence is gone")

    def test_it_is_one_sentence_in_one_paragraph(self):
        text = _read_text(self, START_PAGE)
        intro_ps = re.findall(r'<p class="intro">(.*?)</p>', text, flags=re.S)
        self.assertEqual(1, len(intro_ps), "exactly one intro paragraph")
        self.assertEqual(START_INTRO, " ".join(intro_ps[0].split()))


if __name__ == "__main__":
    unittest.main()
