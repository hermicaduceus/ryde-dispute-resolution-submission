"""W34 acceptance: one-click launcher, start page and the demo switch bar.

Contract: docs/build-briefs/w34-launcher-brief.md. Written RED-first by the planner; the
builder makes this file green without editing it.

What is pinned, by area:
  * app/server.py gains `--port` (default 8000, 1..65535) and nothing else changes before
    `def parse_args(`.
  * tools/launch.py: picks a port (8000-8010), reuses a demo already running, opens the
    browser on /start/ only once the server answers, and runs the EXISTING app.server
    entry point in the same process with `--llm mock`. One process, so closing the window
    (SIGHUP) or Ctrl+C (SIGINT) frees the port.
  * start.command / start.bat: find Python 3.9+, print one plain line when it is missing,
    and run tools/launch.py from the repository folder.
  * ui/start/index.html: the start page, two links, no script.
  * The switch bar on the five existing pages: three relative links, one current marker,
    and nothing else changed in those pages (the bar lines and one stylesheet line removed
    restore the exact pre-W34 bytes).

Preservation pins that already pass before the build: FROZEN_W34, the server prefix and
the <head> line on every page. They are here so the build cannot quietly break them.
"""
from __future__ import annotations

import contextlib
import errno
import hashlib
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
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import List, Optional, Tuple
from unittest import mock
from urllib.parse import urljoin, urlsplit

REPO = Path(__file__).resolve().parents[1]
UI = REPO / "ui"
LAUNCH_PY = REPO / "tools" / "launch.py"
START_COMMAND = REPO / "start.command"
START_BAT = REPO / "start.bat"
START_PAGE = UI / "start" / "index.html"
SWITCH_CSS = UI / "switch-bar.css"

MISSING_PYTHON = ("Python 3.9 or newer is needed to run the Ryde demo. Install it from "
                  "https://www.python.org/downloads/ and then open this file again.")
VERSION_CHECK = "sys.version_info >= (3, 9)"

START_TITLE = "Ryde dispute resolution demo"
#: W47 (2026-10-14): one provider-neutral sentence replaced the mock-only wording. The
#: start page now describes the two launchers, not the current mode (the live launcher
#: proves its provider itself).
START_INTRO = ("Runs on your computer with sample trips. The standard launcher uses an "
               "illustrative mock; the live launcher uses Tencent AI and needs private "
               "access keys.")
START_LINKS = [
    ("../party/", "File a dispute As a rider or a driver, on a sample trip"),
    ("../", "Operator console The review queue, human decisions and every case file"),
]

BAR_LABEL = "Demo pages"
BAR_TEXTS = ["Start", "File a dispute", "Operator console"]
BAR_PATHS = ["/start/", "/party/", "/"]
# (file, URL it is served at, the link that carries aria-current, its value)
PAGES = [
    ("ui/index.html", "/", "Operator console", "page"),
    ("ui/party/index.html", "/party/", "File a dispute", "page"),
    ("ui/party/driver-filing.html", "/party/driver-filing.html", "File a dispute", "true"),
    ("ui/party/status.html", "/party/status.html", "File a dispute", "true"),
    ("ui/party/driver.html", "/party/driver.html", "File a dispute", "true"),
]
# sha256 of each page at e13cbe5, before W34.
ORIGINAL_PAGE_SHA = {
    # W35 (2026-10-08): ui/party/index.html, driver-filing.html and status.html released;
    # W35 adds the step 3 summary, the pending-send status line and the status-page regions
    # (tests/test_w35_P.py pins that markup).
    "ui/party/driver.html": "63b9c366f12477a9002c006fea71199f9e57e8e311d3170b55d54c671717454d",
}
# Everything W34 must not touch, hashed at e13cbe5: app/ except server.py, every existing
# ui/ script and stylesheet, the policy.
# W43 SHOULD (2026-10-13) re-baselined app/agents/judge.py, app/cli.py and app/events.py:
# that lane's three fixes edit them (tests/test_w43_should_*.py pin the new behaviour).
FROZEN_W34 = {
    "app/__init__.py": "e5d96ec8d046c894e767773130c01354dde14ecfbcef9fc58db7af36a8e17e25",
    "app/agents/__init__.py": "3880e0f6bddf40af77c0c8fc224cde247c7b98e617aff17d0336d2eda1d2dd0b",
    "app/agents/base.py": "a0398140287d42673034e09ea8438129793c6492b6d1745d4509d3f0cae34fd5",
    "app/agents/driver_advocate.py": "b104c5afce054f7f2fb7cedec55ae80c04defb015e9cfdff7e7fc8a185cbd117",
    "app/agents/judge.py": "b898210d816188397577f8be3a9f26fa4b32843f319958b3ab619e9b583c0379",
    "app/agents/rider_advocate.py": "0b782098a399861315be03768f88cc6b821a43556a5fd278c0b6b5e27c03281d",
    "app/cli.py": "96f789a7e7e17d048e9529ca0ee9705b6efe508335ec964fccac28661a9ee70f",
    "app/config.json": "9bad3dfc71d7e81db50801e25171099e272f1ad94ff44fdd2721f3e040532bbc",
    "app/config.py": "ac535e02781cabc7e4d189769876efd4c4d2c71330a1aacf7092e9183bbc90cb",
    "app/dispute.py": "1705daa66a897b7f4c265a506b592d153a8888e8ebf112e57631007cd31bae8c",
    "app/eval.py": "e426be975cc900f83a467cc93524c9c10380625ee00adcafe5b4e06903883ff1",
    "app/events.py": "35ee2887e05bf41be1c7bdedf5355c4f6153d149ca3f20819646fc4811817209",
    "app/evidence/__init__.py": "befc73254285cb0e6fb5039b5bd7c96cf321430e643a9295022ce17f34e3e6c4",
    "app/evidence/compute.py": "7875ef3282371575a3092eb9746c08d2ebca0d919af3a16a9fb77e958c73d559",
    "app/evidence/schema.py": "c43dde67551b751c98383700b98d0c305c9a970031e109713108430044ca59f3",
    # W35 R2 lane K released app/human_review.py (tests/test_w35_r2_K.py pins the rest of the module).
    "app/llm/__init__.py": "014cc053124a4bf057bba9c3f2760c83eae0f37f3a7ac729d8e782db34c258ac",
    "app/llm/base.py": "dda8c03d2a79d37ac68d1a4f848937533af9a49f982d2bb26535d8269cf1aae4",
    "app/llm/mock.py": "37777c29c01460750df771d446b673ddb00245356e5a4f4568d069aa3a05d496",
    "app/llm/tencent.py": "fc1d122fce5bb4b73827786598a8825432b80faf33c7e88278d977f2c732a851",
    "app/pipeline.py": "1725249bde875d9d3b317e5b414d35042756bd85f8cfab8b2baee5664386f0f0",
    "app/policy.py": "0d2899305cf68260f3748fa030f304183edcbb8a44fddeaedda7ed3bdd00c4e5",
    "app/prompt_view.py": "3b8472f60e51f99b98a1f96f4ba4fe403986701a3ad3bf74c23a73325db985f6",
    "app/schemas.py": "371334cabd7a75f23dd2f6cb353adccfef48b16fb0197befe5e80e6b33360ce5",
    "docs/policy.md": "d6a3e63c4da7223af1e05e96f6e58982af2b9f2a3253348f79b8fd6aa2a3408e",
    "ui/party/driver.js": "fff0dd47777ed9b872fa51deb51171a844f6b827e3c58d4ba90302cf0cbe70ff",
    # W35 (2026-10-08): ui/party/party.css and ui/party/party.js released (tests/test_w35_P.py).
    # Step-1 targeting round (2026-10-15): ui/party/status.js released for the ?dispute=
    # focus param (tests/test_step1_dispute_target.py pins the new behaviour).
    "ui/party/status.js": "fc62509fb8b4f5a2507a0a05620657016b3dc68859ab6badde9e5683549e4931",
}
# W35 lane C released ui/app.js and ui/styles.css above, SERVER_PREFIX_SHA, and ui/index.html's
# ORIGINAL_PAGE_SHA entry: that round edits all four (tests/test_w35_C.py pins the new behaviour).


# ---------------------------------------------------------------- helpers


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_bytes(tc: unittest.TestCase, path: Path) -> bytes:
    if not path.is_file():
        tc.fail("%s is missing" % path.relative_to(REPO))
    return path.read_bytes()


def _read_text(tc: unittest.TestCase, path: Path) -> str:
    return _read_bytes(tc, path).decode("utf-8")


def _attr(tc: unittest.TestCase, obj, name: str):
    if not hasattr(obj, name):
        tc.fail("%r has no attribute %s" % (obj, name))
    return getattr(obj, name)


def _load_launch(tc: unittest.TestCase):
    if not LAUNCH_PY.is_file():
        tc.fail("tools/launch.py is missing")
    spec = importlib.util.spec_from_file_location("w34_launch_under_test", LAUNCH_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


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
    """A base port b such that b .. b+n-1 are all free right now."""
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


def _get(url: str, timeout: float = 5.0) -> Tuple[int, str, bytes]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status, resp.headers.get("Server", ""), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers.get("Server", ""), b""


class _Fake(BaseHTTPRequestHandler):
    status = 200
    server_version = "OtherServer/1.0"

    def do_GET(self):  # noqa: N802
        body = b"<!doctype html><title>other</title>"
        self.send_response(self.status)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def _fake_server(tc: unittest.TestCase, port: int, status: int = 200,
                 version: str = "OtherServer/1.0") -> None:
    handler = type("FakeHandler", (_Fake,), {"status": status, "server_version": version})
    httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    tc.addCleanup(httpd.server_close)
    tc.addCleanup(httpd.shutdown)


def _silent_listener(tc: unittest.TestCase, port: int) -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", port))
    sock.listen(8)
    tc.addCleanup(sock.close)


def _ryde_server(tc: unittest.TestCase, port: int = 0) -> int:
    from app.server import make_server
    from app.llm import build_llm_client
    out = Path(tempfile.mkdtemp(prefix="w34-runs-"))
    tc.addCleanup(shutil.rmtree, out, True)
    httpd = make_server(port, out_dir=out, llm=build_llm_client("mock"))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    tc.addCleanup(httpd.server_close)
    tc.addCleanup(httpd.shutdown)
    return httpd.server_address[1]


class _Tags(HTMLParser):
    """Every start tag in document order, with attrs, plus the text inside each <a>."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags: List[Tuple[str, dict]] = []
        self.anchors: List[dict] = []  # {"attrs", "text", "in_nav", "nav_index"}
        self.navs: List[dict] = []
        self.body_children: List[str] = []
        self._depth_in_body: Optional[int] = None
        self._depth = 0
        self._anchor: Optional[dict] = None
        self._nav_depth: Optional[int] = None
        self.title_text = ""
        self._in_title = False
        self.h1_text = ""
        self._in_h1 = False
        self.p_texts: List[str] = []
        self._p: Optional[List[str]] = None

    VOID = {"meta", "link", "br", "img", "input", "hr", "source", "area", "base", "col",
            "embed", "track", "wbr"}

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        self.tags.append((tag, a))
        if self._depth_in_body is not None and self._depth == self._depth_in_body:
            self.body_children.append(tag)
        if tag == "body":
            self._depth_in_body = self._depth + 1
        if tag == "nav":
            self.navs.append({"attrs": a, "anchors": []})
            self._nav_depth = self._depth + 1
        if tag == "a":
            self._anchor = {"attrs": a, "text": [], "in_nav": self._nav_depth is not None}
        if tag == "title":
            self._in_title = True
        if tag == "h1":
            self._in_h1 = True
        if tag == "p":
            self._p = []
        if tag not in self.VOID:
            self._depth += 1

    def handle_endtag(self, tag):
        if tag not in self.VOID:
            self._depth -= 1
        if tag == "a" and self._anchor is not None:
            self._anchor["text"] = " ".join(" ".join(self._anchor["text"]).split())
            self.anchors.append(self._anchor)
            if self._anchor["in_nav"] and self.navs:
                self.navs[-1]["anchors"].append(self._anchor)
            self._anchor = None
        if tag == "nav":
            self._nav_depth = None
        if tag == "title":
            self._in_title = False
        if tag == "h1":
            self._in_h1 = False
        if tag == "p" and self._p is not None:
            self.p_texts.append(" ".join(" ".join(self._p).split()))
            self._p = None

    def handle_data(self, data):
        if self._anchor is not None:
            self._anchor["text"].append(data)
        if self._in_title:
            self.title_text += data
        if self._in_h1:
            self.h1_text += data
        if self._p is not None:
            self._p.append(data)


def _parse(text: str) -> _Tags:
    parser = _Tags()
    parser.feed(text)
    parser.close()
    return parser


def _strip_css_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _strip_bat_comments(text: str) -> str:
    keep = []
    for line in text.splitlines():
        s = line.strip().lower()
        if s.startswith("rem ") or s == "rem" or s.startswith("::"):
            continue
        keep.append(line)
    return "\n".join(keep)


def _strip_sh_comments(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


# ---------------------------------------------------------------- app/server.py --port


class ServerPort(unittest.TestCase):

    def test_default_port_is_still_8000(self):
        from app import server
        self.assertEqual(8000, server.DEFAULT_PORT)
        args = server.parse_args([])
        self.assertEqual(8000, getattr(args, "port", None), "--port defaults to DEFAULT_PORT")

    def test_port_accepts_its_bounds(self):
        from app import server
        for raw, want in (("1", 1), ("8005", 8005), ("65535", 65535)):
            with self.subTest(raw=raw):
                try:
                    with contextlib.redirect_stderr(io.StringIO()):
                        args = server.parse_args(["--port", raw])
                except SystemExit:
                    self.fail("--port %s was refused" % raw)
                self.assertEqual(want, getattr(args, "port", None))

    def test_port_refuses_out_of_range_and_non_numbers(self):
        from app import server
        for raw in ("0", "65536", "-1", "abc", "80.5", ""):
            with self.subTest(raw=raw):
                with contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit):
                        server.parse_args(["--port", raw])

    def test_main_binds_the_port_it_is_given(self):
        port = _free_run(1)
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        proc = subprocess.Popen(
            [sys.executable, "-m", "app.server", "--llm", "mock", "--port", str(port)],
            cwd=str(REPO), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            deadline = time.time() + 20
            status = None
            while time.time() < deadline:
                if proc.poll() is not None:
                    break
                try:
                    status = _get("http://127.0.0.1:%d/" % port, timeout=1)[0]
                    break
                except OSError:
                    time.sleep(0.2)
            if status is None:
                proc.kill()
                out, err = proc.communicate(timeout=10)
                self.fail("server did not answer on --port %d: %s" % (port, err.decode()[-400:]))
            self.assertEqual(200, status)
        finally:
            if proc.poll() is None:
                proc.send_signal(signal.SIGINT)
            out, _err = proc.communicate(timeout=15)
        self.assertIn("http://127.0.0.1:%d/" % port, out.decode())


# ---------------------------------------------------------------- W34 fix round (review findings)


PORT_TAKEN = "Port {port} was taken just as the demo started. Open this file again."
README_REUSE = ("If you already started the demo yourself, the launcher reuses that copy "
                "as it is.")
PROXY_ENV_KEYS = ("http_proxy", "HTTP_PROXY", "https_proxy", "HTTPS_PROXY",
                  "all_proxy", "ALL_PROXY", "no_proxy", "NO_PROXY")


class FixRound(unittest.TestCase):
    """Review findings on 49ce669, each reproduced before it was pinned."""

    def setUp(self):
        self.launch = _load_launch(self)

    def _probe_through_proxy(self, code: str) -> subprocess.CompletedProcess:
        # A fresh process, because urllib caches its global opener on first use: an
        # in-process check could pass on an opener built before the proxy was set.
        demo = _ryde_server(self)
        proxy = _free_run(1)
        _fake_server(self, proxy, 403, "CorporateProxy/1.0")
        env = {k: v for k, v in os.environ.items() if k not in PROXY_ENV_KEYS}
        env.pop("PYTHONPATH", None)
        env["http_proxy"] = env["HTTP_PROXY"] = "http://127.0.0.1:%d" % proxy
        script = ("import sys\nsys.path.insert(0, %r)\nimport launch\n" % str(LAUNCH_PY.parent)) + \
            code.replace("PORT", str(demo))
        return subprocess.run([sys.executable, "-c", script], cwd=str(REPO), env=env,
                              capture_output=True, text=True, timeout=30)

    def test_a_configured_http_proxy_never_hides_the_running_demo(self):
        proc = self._probe_through_proxy("print(launch.is_ryde_demo(PORT))\n")
        self.assertEqual(0, proc.returncode, proc.stderr)
        self.assertEqual("True", proc.stdout.strip(),
                         "loopback probes go direct, not through the user's proxy")

    def test_a_configured_http_proxy_never_blocks_the_browser(self):
        proc = self._probe_through_proxy(
            "launch.webbrowser.open = lambda url, *a, **k: print('OPENED ' + url) or True\n"
            "launch.open_when_ready(launch.start_url(PORT), timeout=5)\n")
        self.assertEqual(0, proc.returncode, proc.stderr)
        lines = proc.stdout.strip().splitlines()
        self.assertEqual(1, len(lines), "opens once and prints nothing else: %r" % lines)
        self.assertRegex(lines[0], r"^OPENED http://127\.0\.0\.1:\d+/start/$")

    def test_a_port_taken_before_the_bind_prints_a_plain_line_not_a_traceback(self):
        port = _free_run(1)
        squatter = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        squatter.bind(("127.0.0.1", port))
        squatter.listen(1)
        self.addCleanup(squatter.close)
        out = io.StringIO()
        with mock.patch.object(self.launch, "pick_port", return_value=(port, False)), \
                mock.patch.object(self.launch, "open_when_ready", lambda *a, **k: None), \
                contextlib.redirect_stdout(out):
            try:
                code = self.launch.main([])
            except BaseException as exc:  # noqa: BLE001 - the window would show this
                self.fail("a bind failure escaped as %s: %s" % (type(exc).__name__, exc))
        self.assertEqual(1, code)
        self.assertIn(PORT_TAKEN.format(port=port), out.getvalue().splitlines())
        self.assertEqual(PORT_TAKEN, _attr(self, self.launch, "PORT_TAKEN"))

    def test_other_server_failures_still_surface(self):
        # Only the bind race is turned into a plain line; a real bug must stay visible.
        with mock.patch.object(self.launch, "pick_port", return_value=(_free_run(1), False)), \
                mock.patch.object(self.launch, "open_when_ready", lambda *a, **k: None), \
                mock.patch.object(self.launch.server, "main", side_effect=RuntimeError("boom")), \
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(RuntimeError):
                self.launch.main([])
        # An OSError that is not the bind race (here: permission denied) is a real fault,
        # not "port taken", and must not be reworded into one.
        with mock.patch.object(self.launch, "pick_port", return_value=(_free_run(1), False)), \
                mock.patch.object(self.launch, "open_when_ready", lambda *a, **k: None), \
                mock.patch.object(self.launch.server, "main",
                                  side_effect=OSError(errno.EACCES, "Permission denied")), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            with self.assertRaises(OSError):
                self.launch.main([])
        self.assertNotIn("was taken", out.getvalue())

    def test_readme_says_a_running_copy_is_reused_as_it_is(self):
        text = _read_text(self, REPO / "README.md")
        start = text.find("## Run")
        self.assertGreaterEqual(start, 0, "README has a ## Run section")
        end = text.find("\n## ", start + 1)
        section = text[start:end if end > 0 else len(text)]
        self.assertIn(README_REUSE, " ".join(section.split()),
                      "the Run section warns that an already-running copy is reused unchanged")

    def _pick_one(self, connect):
        port = _free_run(1)
        with mock.patch.object(self.launch, "is_ryde_demo", return_value=False), \
                mock.patch.object(self.launch.socket, "create_connection", connect):
            return port, self.launch.pick_port(port, port)

    def test_a_slow_refusal_still_reads_as_a_free_port(self):
        # Windows retries a refused loopback connect for about a second or two before it
        # reports the refusal; that port is free, not busy.
        def slow_refusal(address, timeout=None, *a, **k):
            if timeout is not None and timeout < 2.5:
                raise socket.timeout("timed out before the refusal arrived")
            time.sleep(1.5)
            raise ConnectionRefusedError(61, "Connection refused")
        port, picked = self._pick_one(slow_refusal)
        self.assertEqual((port, False), picked)

    def test_a_connect_that_times_out_is_not_a_free_port(self):
        def timeout(address, timeout=None, *a, **k):
            raise socket.timeout("timed out")
        _, picked = self._pick_one(timeout)
        self.assertEqual((None, False), picked, "a port that never answers is skipped")


# ---------------------------------------------------------------- tools/launch.py, in process


class LaunchModule(unittest.TestCase):

    def setUp(self):
        self.launch = _load_launch(self)

    def test_constants_and_start_url(self):
        self.assertEqual(8000, _attr(self, self.launch, "FIRST_PORT"))
        self.assertEqual(8010, _attr(self, self.launch, "LAST_PORT"))
        self.assertEqual("/start/", _attr(self, self.launch, "START_PATH"))
        self.assertEqual("http://127.0.0.1:8003/start/", _attr(self, self.launch, "start_url")(8003))

    def test_message_constants_are_exact(self):
        L = self.launch
        self.assertEqual("Ryde demo running at {url}", _attr(self, L, "RUNNING"))
        self.assertEqual("Close this window (or press Ctrl+C) to stop the demo.",
                         _attr(self, L, "STOP_HINT"))
        self.assertEqual("The Ryde demo is already running at {url}. Opening it in your browser.",
                         _attr(self, L, "ALREADY_RUNNING"))
        self.assertEqual("Ports {first} to {last} are all in use by other programs. "
                         "Close one of them, then open this file again.",
                         _attr(self, L, "NO_FREE_PORT"))
        self.assertEqual("Could not open a browser. Open {url} yourself.",
                         _attr(self, L, "OPEN_YOURSELF"))

    def test_server_argv_forces_the_mock_and_the_port(self):
        self.assertEqual(["--llm", "mock", "--port", "8003"],
                         _attr(self, self.launch, "server_argv")(8003))

    def test_is_ryde_demo_needs_a_200_start_page_and_the_ryde_server_header(self):
        is_demo = _attr(self, self.launch, "is_ryde_demo")
        base = _free_run(3)
        _fake_server(self, base, 200, "OtherServer/1.0")
        _fake_server(self, base + 1, 404, "RydePartyServer/1.0")
        ryde = _ryde_server(self, base + 2)
        self.assertFalse(is_demo(base), "a 200 from another program is not the demo")
        self.assertFalse(is_demo(base + 1), "the Ryde header on a 404 is not a running demo")
        self.assertTrue(is_demo(ryde))
        self.assertFalse(is_demo(_free_run(1)), "nothing listening is not the demo")

    def test_pick_port_returns_the_first_port_when_all_are_free(self):
        pick = _attr(self, self.launch, "pick_port")
        base = _free_run(3)
        self.assertEqual((base, False), pick(base, base + 2))

    def test_pick_port_skips_another_programs_http_server(self):
        pick = _attr(self, self.launch, "pick_port")
        base = _free_run(3)
        _fake_server(self, base, 200, "OtherServer/1.0")
        self.assertEqual((base + 1, False), pick(base, base + 2))

    def test_pick_port_skips_a_listener_that_never_answers_quickly(self):
        pick = _attr(self, self.launch, "pick_port")
        base = _free_run(3)
        _silent_listener(self, base)
        started = time.time()
        self.assertEqual((base + 1, False), pick(base, base + 2))
        self.assertLess(time.time() - started, 5.0, "a silent port must not stall the launcher")

    def test_pick_port_reuses_a_running_demo(self):
        pick = _attr(self, self.launch, "pick_port")
        base = _free_run(3)
        _ryde_server(self, base)
        self.assertEqual((base, True), pick(base, base + 2))

    def test_pick_port_reuses_a_demo_behind_another_program(self):
        pick = _attr(self, self.launch, "pick_port")
        base = _free_run(3)
        _fake_server(self, base, 200, "OtherServer/1.0")
        _ryde_server(self, base + 1)
        self.assertEqual((base + 1, True), pick(base, base + 2))

    def test_pick_port_none_when_every_port_is_taken_by_others(self):
        pick = _attr(self, self.launch, "pick_port")
        base = _free_run(2)
        _fake_server(self, base, 200, "OtherServer/1.0")
        _silent_listener(self, base + 1)
        self.assertEqual((None, False), pick(base, base + 1))

    def _run_main(self, argv, server_main=None, opener=None, browser_open=None):
        L = self.launch
        calls = {"server": [], "opener": [], "browser": []}
        opened = threading.Event()

        def fake_server_main(args=None):
            calls["server"].append(list(args) if args is not None else None)
            return 0

        def fake_opener(url, *a, **k):
            calls["opener"].append(url)
            opened.set()

        def fake_browser(url, *a, **k):
            calls["browser"].append(url)
            return True

        server_mod = _attr(self, L, "server")
        out = io.StringIO()
        with mock.patch.object(server_mod, "main", server_main or fake_server_main), \
                mock.patch.object(L, "open_when_ready", opener or fake_opener), \
                mock.patch.object(_attr(self, L, "webbrowser"), "open", browser_open or fake_browser), \
                contextlib.redirect_stdout(out):
            rc = _attr(self, L, "main")(argv)
        opened.wait(3)
        return rc, out.getvalue().splitlines(), calls

    def test_main_runs_the_existing_server_entry_with_the_mock_on_the_picked_port(self):
        port = _free_run(1)
        rc, lines, calls = self._run_main(["--ports", "%d-%d" % (port, port)])
        self.assertEqual(0, rc)
        self.assertEqual([["--llm", "mock", "--port", str(port)]], calls["server"])
        url = "http://127.0.0.1:%d/start/" % port
        self.assertEqual([url], calls["opener"], "the browser opener gets the start page URL")
        self.assertIn("Ryde demo running at %s" % url, lines)
        self.assertIn("Close this window (or press Ctrl+C) to stop the demo.", lines)

    def test_a_stuck_browser_waiter_never_keeps_the_process_alive(self):
        # The waiter runs beside the server; when the server returns, the process ends
        # even if the waiter is still polling (a daemon thread).
        _load_launch(self)
        script = (
            "import sys, time\n"
            "sys.path.insert(0, %r)\n"
            "import launch\n"
            "launch.pick_port = lambda first, last: (%d, False)\n"
            "launch.open_when_ready = lambda *a, **k: time.sleep(60)\n"
            "launch.server.main = lambda argv: 0\n"
            "sys.exit(launch.main([]))\n"
        ) % (str(LAUNCH_PY.parent), _free_run(1))
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        started = time.time()
        try:
            proc = subprocess.run([sys.executable, "-c", script], cwd=str(REPO), env=env,
                                  capture_output=True, text=True, timeout=20)
        except subprocess.TimeoutExpired:
            self.fail("the process waited for the browser thread after the server returned")
        self.assertEqual(0, proc.returncode, proc.stderr)
        self.assertLess(time.time() - started, 15)

    def test_main_returns_the_server_exit_code(self):
        port = _free_run(1)
        rc, _lines, _calls = self._run_main(["--ports", "%d-%d" % (port, port)],
                                            server_main=lambda args=None: 3)
        self.assertEqual(3, rc)

    def test_main_defaults_to_ports_8000_to_8010(self):
        L = self.launch
        seen = []

        def fake_pick(first, last):
            seen.append((first, last))
            return (None, False)

        with mock.patch.object(L, "pick_port", fake_pick):
            rc, lines, calls = self._run_main([])
        self.assertEqual([(8000, 8010)], seen)
        self.assertEqual(1, rc)
        self.assertIn("Ports 8000 to 8010 are all in use by other programs. "
                      "Close one of them, then open this file again.", lines)
        self.assertEqual([], calls["server"])

    def test_main_reuses_a_running_demo_without_starting_a_server(self):
        base = _free_run(1)
        _ryde_server(self, base)
        rc, lines, calls = self._run_main(["--ports", "%d-%d" % (base, base)])
        url = "http://127.0.0.1:%d/start/" % base
        self.assertEqual(0, rc)
        self.assertEqual([], calls["server"], "no second server")
        self.assertEqual([url], calls["browser"], "opens the running demo directly")
        self.assertIn("The Ryde demo is already running at %s. Opening it in your browser." % url,
                      lines)

    def test_main_stops_with_a_plain_line_when_no_port_is_free(self):
        base = _free_run(2)
        _fake_server(self, base, 200, "OtherServer/1.0")
        _fake_server(self, base + 1, 200, "OtherServer/1.0")
        rc, lines, calls = self._run_main(["--ports", "%d-%d" % (base, base + 1)])
        self.assertEqual(1, rc)
        self.assertEqual(["Ports %d to %d are all in use by other programs. "
                          "Close one of them, then open this file again." % (base, base + 1)],
                         lines)
        self.assertEqual([], calls["server"])
        self.assertEqual([], calls["browser"])

    def test_open_when_ready_waits_for_the_server_then_opens_the_browser_once(self):
        L = self.launch
        port = _free_run(1)
        url = "http://127.0.0.1:%d/start/" % port
        seen = []

        def browser(target, *a, **k):
            try:
                status = _get(target, timeout=3)[0]
            except OSError:
                status = "refused"  # opened before the server answered
            seen.append((target, status))
            return True

        starter = threading.Timer(0.8, lambda: _ryde_server(self, port))
        starter.start()
        self.addCleanup(starter.cancel)
        out = io.StringIO()
        with mock.patch.object(_attr(self, L, "webbrowser"), "open", browser), \
                contextlib.redirect_stdout(out):
            _attr(self, L, "open_when_ready")(url, timeout=15)
        self.assertEqual([(url, 200)], seen, "opened once, after the start page answered 200")
        self.assertEqual("", out.getvalue())

    def test_open_when_ready_prints_the_url_when_the_server_never_answers(self):
        L = self.launch
        port = _free_run(1)
        url = "http://127.0.0.1:%d/start/" % port
        seen = []
        out = io.StringIO()
        started = time.time()
        with mock.patch.object(_attr(self, L, "webbrowser"), "open",
                               lambda u, *a, **k: seen.append(u) or True), \
                contextlib.redirect_stdout(out):
            _attr(self, L, "open_when_ready")(url, timeout=0.6)
        self.assertLess(time.time() - started, 4.0)
        self.assertEqual([], seen)
        self.assertEqual(["Could not open a browser. Open %s yourself." % url],
                         out.getvalue().splitlines())

    def test_open_when_ready_prints_the_url_when_the_browser_fails(self):
        L = self.launch
        port = _ryde_server(self)
        url = "http://127.0.0.1:%d/start/" % port
        wb = _attr(self, L, "webbrowser")

        def refuse(u, *a, **k):
            return False

        def explode(u, *a, **k):
            raise wb.Error("no browser")

        for opener in (refuse, explode):
            with self.subTest(opener=opener.__name__):
                out = io.StringIO()
                with mock.patch.object(wb, "open", opener), contextlib.redirect_stdout(out):
                    _attr(self, L, "open_when_ready")(url, timeout=10)
                self.assertEqual(["Could not open a browser. Open %s yourself." % url],
                                 out.getvalue().splitlines())


# ---------------------------------------------------------------- tools/launch.py, real process


RECORDER = r'''
import sys, urllib.request, urllib.error
url = sys.argv[1]
try:
    status = urllib.request.urlopen(url, timeout=5).status
except urllib.error.HTTPError as exc:
    status = exc.code
except Exception as exc:
    status = "ERR"
with open(sys.argv[2], "a") as fh:
    fh.write("%s %s\n" % (url, status))
'''


@unittest.skipUnless(os.name == "posix", "signals and BROWSER recorder are POSIX here")
class LaunchProcess(unittest.TestCase):
    """The launcher as the wrappers run it: a real process, a real server, a fake browser."""

    def _start(self):
        if not LAUNCH_PY.is_file():
            self.fail("tools/launch.py is missing")
        tmp = Path(tempfile.mkdtemp(prefix="w34-launch-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        recorder = tmp / "recorder.py"
        recorder.write_text(RECORDER, encoding="utf-8")
        record = tmp / "opened.txt"
        port = _free_run(1)
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        # webbrowser replaces EVERY "%s" in BROWSER with the URL, so the record path is literal.
        env["BROWSER"] = "%s %s %%s %s" % (sys.executable, recorder, record)
        proc = subprocess.Popen(
            [sys.executable, str(LAUNCH_PY), "--ports", "%d-%d" % (port, port)],
            cwd=str(tmp), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.addCleanup(lambda: proc.poll() is None and proc.kill())
        deadline = time.time() + 30
        while time.time() < deadline and proc.poll() is None:
            if record.is_file() and record.read_text().strip():
                break
            time.sleep(0.2)
        if proc.poll() is not None:
            out, err = proc.communicate(timeout=10)
            self.fail("launcher exited early (%s): %s %s" % (proc.returncode, out.decode()[-300:],
                                                             err.decode()[-600:]))
        self.assertTrue(record.is_file(), "the launcher opened no browser")
        return proc, port, record

    def test_opens_the_start_page_once_it_answers_and_serves_both_pages(self):
        proc, port, record = self._start()
        url = "http://127.0.0.1:%d/start/" % port
        time.sleep(0.5)
        self.assertEqual(["%s 200" % url], record.read_text().splitlines())
        for path in ("/party/", "/"):
            self.assertEqual(200, _get("http://127.0.0.1:%d%s" % (port, path))[0])
        proc.send_signal(signal.SIGINT)
        out, _err = proc.communicate(timeout=15)
        lines = out.decode().splitlines()
        self.assertIn("Ryde demo running at %s" % url, lines)
        self.assertIn("Close this window (or press Ctrl+C) to stop the demo.", lines)
        self.assertIn("  llm provider: mock", lines, "the existing server entry ran on the mock")

    def test_closing_the_window_sighup_frees_the_port(self):
        proc, port, _record = self._start()
        proc.send_signal(signal.SIGHUP)
        try:
            proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            self.fail("SIGHUP did not stop the launcher")
        time.sleep(0.3)
        self.assertTrue(_refused(port), "nothing may keep serving after the window closes")

    def test_ctrl_c_stops_cleanly_and_frees_the_port(self):
        proc, port, _record = self._start()
        proc.send_signal(signal.SIGINT)
        try:
            proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            self.fail("Ctrl+C did not stop the launcher")
        self.assertEqual(0, proc.returncode)
        time.sleep(0.3)
        self.assertTrue(_refused(port))


# ---------------------------------------------------------------- wrappers


FAKE_PYTHON = '''#!/bin/bash
printf '%s|%s\\n' "$PWD" "$*" >> "$W34_RECORD"
if [ "$1" = "-c" ]; then exit "${W34_VERSION_RC:-0}"; fi
exit 0
'''


@unittest.skipUnless(sys.platform == "darwin" or os.name == "posix", "runs start.command under bash")
class StartCommand(unittest.TestCase):

    def test_is_an_executable_bash_script_with_unix_line_endings(self):
        data = _read_bytes(self, START_COMMAND)
        self.assertTrue(data.startswith(b"#!/bin/bash\n"), "first line is #!/bin/bash")
        self.assertNotIn(b"\r", data)
        mode = START_COMMAND.stat().st_mode
        self.assertTrue(mode & stat.S_IXUSR and mode & stat.S_IXGRP and mode & stat.S_IXOTH,
                        "start.command is executable (chmod 755) so a double-click runs it")
        if (REPO / ".git").exists():
            listed = subprocess.run(["git", "ls-files", "-s", "start.command"], cwd=str(REPO),
                                    capture_output=True, text=True).stdout
            if listed:
                self.assertTrue(listed.startswith("100755 "), "git records the executable bit")

    def _run(self, version_rc: Optional[int]):
        tmp = Path(tempfile.mkdtemp(prefix="w34-cmd-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        bindir = tmp / "bin"
        bindir.mkdir()
        record = tmp / "calls.txt"
        if version_rc is not None:
            fake = bindir / "python3"
            fake.write_text(FAKE_PYTHON, encoding="utf-8")
            fake.chmod(0o755)
            path = "%s:/usr/bin:/bin" % bindir
        else:
            for tool in ("dirname", "basename", "env", "cat", "uname"):
                src = shutil.which(tool, path="/usr/bin:/bin")
                if src:
                    os.symlink(src, bindir / tool)
            path = str(bindir)
        env = {"PATH": path, "HOME": str(tmp), "W34_RECORD": str(record),
               "W34_VERSION_RC": str(version_rc if version_rc is not None else 0)}
        _read_bytes(self, START_COMMAND)
        proc = subprocess.run(["/bin/bash", str(START_COMMAND)], cwd=str(tmp), env=env,
                              stdin=subprocess.DEVNULL, capture_output=True, text=True,
                              timeout=30)
        calls = record.read_text().splitlines() if record.is_file() else []
        return proc, calls

    def test_runs_launch_py_from_the_repository_folder_after_the_version_check(self):
        proc, calls = self._run(version_rc=0)
        self.assertEqual(0, proc.returncode, proc.stderr)
        self.assertGreaterEqual(len(calls), 2, calls)
        here, args = calls[-1].split("|", 1)
        self.assertEqual(os.path.realpath(REPO), os.path.realpath(here),
                         "launch.py runs from the repository folder, whatever the caller's folder")
        self.assertEqual("tools/launch.py", args)
        checks = [c for c in calls[:-1] if c.split("|", 1)[1].startswith("-c ")]
        self.assertTrue(checks and all(VERSION_CHECK in c for c in checks), calls)

    def test_an_old_python_prints_the_plain_message_and_stops(self):
        proc, calls = self._run(version_rc=1)
        self.assertNotEqual(0, proc.returncode)
        self.assertIn(MISSING_PYTHON, proc.stdout.splitlines())
        self.assertFalse([c for c in calls if "tools/launch.py" in c], "launch.py never runs")

    def test_no_python_at_all_prints_the_plain_message_and_stops(self):
        proc, calls = self._run(version_rc=None)
        self.assertNotEqual(0, proc.returncode)
        self.assertIn(MISSING_PYTHON, proc.stdout.splitlines())
        self.assertEqual([], calls)

    def test_an_old_python_keeps_the_window_open_until_a_key_is_pressed(self):
        # A double-clicked window that closes at once hides the message; the script waits.
        tmp = Path(tempfile.mkdtemp(prefix="w34-key-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        (tmp / "bin").mkdir()
        fake = tmp / "bin" / "python3"
        fake.write_text(FAKE_PYTHON, encoding="utf-8")
        fake.chmod(0o755)
        env = {"PATH": "%s:/usr/bin:/bin" % (tmp / "bin"), "HOME": str(tmp),
               "W34_RECORD": str(tmp / "calls.txt"), "W34_VERSION_RC": "1"}
        _read_bytes(self, START_COMMAND)
        proc = subprocess.Popen(["/bin/bash", str(START_COMMAND)], cwd=str(tmp), env=env,
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
        self.addCleanup(lambda: proc.poll() is None and proc.kill())
        time.sleep(1.5)
        self.assertIsNone(proc.poll(), "the window waits for a key after the message")
        out, _ = proc.communicate(input=b"x", timeout=10)
        self.assertNotEqual(0, proc.returncode)
        self.assertIn(MISSING_PYTHON, out.decode("utf-8").splitlines())

    def test_hands_over_with_exec_so_the_window_owns_one_process(self):
        body = _strip_sh_comments(_read_text(self, START_COMMAND))
        self.assertRegex(body, r'(?m)^\s*exec\s+(python3|"?\$\{?[A-Za-z_]+\}?"?)\s+tools/launch\.py\s*$')


class StartBat(unittest.TestCase):

    def test_uses_windows_line_endings_throughout(self):
        data = _read_bytes(self, START_BAT)
        self.assertGreater(data.count(b"\r\n"), 5)
        self.assertEqual(data.count(b"\n"), data.count(b"\r\n"), "every line ends CRLF")

    def test_gitattributes_keeps_bat_bytes_unconverted(self):
        text = _read_text(self, REPO / ".gitattributes")
        self.assertIn("*.bat -text", [line.strip() for line in text.splitlines()])

    def test_contract_lines(self):
        body = _strip_bat_comments(_read_bytes(self, START_BAT).decode("utf-8"))
        lines = [line.strip() for line in body.splitlines() if line.strip()]
        self.assertEqual("@echo off", lines[0].lower())
        self.assertIn('cd /d "%~dp0"', body)
        self.assertRegex(body, r"(?m)^\s*py -3 -c \"[^\"]*" + re.escape(VERSION_CHECK))
        self.assertRegex(body, r"(?m)^\s*python -c \"[^\"]*" + re.escape(VERSION_CHECK))
        self.assertLess(body.index("py -3 -c"), body.index("python -c"), "py -3 is tried first")
        literal = re.search(r"(?im)^\s*echo\s+" + re.escape(MISSING_PYTHON) + r"\s*$", body)
        via_var = re.search(r'(?im)^\s*set\s+"(\w+)=' + re.escape(MISSING_PYTHON) + r'"\s*$', body)
        if via_var:
            self.assertRegex(body, r"(?im)^\s*echo\s+%" + via_var.group(1) + r"%\s*$",
                             "the variable holding the sentence is echoed")
        self.assertTrue(literal or via_var, "start.bat prints the exact missing-Python sentence")
        self.assertRegex(body, r"(?m)tools\\launch\.py")

    # Each pause is pinned on its own path, so one can never satisfy the other: a
    # whole-file search for "pause" passed with either of the two removed.
    def _lines(self):
        body = _strip_bat_comments(_read_bytes(self, START_BAT).decode("utf-8"))
        return [line.strip() for line in body.splitlines() if line.strip()]

    def _block_pauses_before_exit(self, lines, start):
        """True when, from lines[start] onward, a pause comes before the next exit."""
        for line in lines[start:]:
            low = line.lower()
            if low == "pause":
                return True
            if low.startswith("exit") or low.startswith("goto ") or low.startswith(":"):
                return False
        return False

    def test_the_missing_python_message_is_followed_by_a_pause(self):
        lines = self._lines()
        echo = [i for i, line in enumerate(lines)
                if line.lower().startswith("echo ") and (MISSING_PYTHON in line or
                re.fullmatch(r"(?i)echo\s+%\w+%", line))]
        self.assertEqual(1, len(echo), "one line prints the missing-Python sentence")
        self.assertTrue(self._block_pauses_before_exit(lines, echo[0] + 1),
                        "a pause follows the message before the script exits")

    def test_a_failed_launch_pauses_so_the_window_does_not_vanish(self):
        lines = self._lines()
        runs = [i for i, line in enumerate(lines) if re.search(r"tools\\launch\.py", line)]
        self.assertTrue(runs, "start.bat runs tools\\launch.py")
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


class StartPage(unittest.TestCase):

    def test_static_contract(self):
        text = _read_text(self, START_PAGE)
        self.assertIn("<head>", [line.strip() for line in text.splitlines()],
                      "a <head> line of its own (the replay exporter inserts after it)")
        page = _parse(text)
        self.assertEqual(START_TITLE, page.title_text.strip())
        self.assertEqual(START_TITLE, " ".join(page.h1_text.split()))
        self.assertIn(START_INTRO, page.p_texts)
        self.assertEqual(START_LINKS, [(a["attrs"].get("href"), a["text"]) for a in page.anchors],
                         "exactly two links, in this order, with this text")
        self.assertNotIn("script", [t for t, _ in page.tags], "the start page runs no script")
        self.assertIn(("meta", {"name": "viewport",
                                "content": "width=device-width, initial-scale=1"}), page.tags)

    def test_local_stylesheets_exist(self):
        page = _parse(_read_text(self, START_PAGE))
        local = [a["href"] for t, a in page.tags
                 if t == "link" and a.get("rel") == "stylesheet" and "://" not in a.get("href", "")]
        self.assertTrue(local, "the start page has its own stylesheet")
        for href in local:
            target = urlsplit(urljoin("http://h/start/", href)).path
            self.assertTrue((UI / target.lstrip("/")).is_file(), href)

    def test_served_and_both_links_land(self):
        port = _ryde_server(self)
        base = "http://127.0.0.1:%d/start/" % port
        status, server_header, body = _get(base)
        self.assertEqual(200, status)
        self.assertTrue(server_header.startswith("RydePartyServer/"))
        self.assertIn(START_TITLE.encode(), body)
        for href, _ in START_LINKS:
            with self.subTest(href=href):
                target = urljoin(base, href)
                self.assertEqual(200, _get(target)[0], target)
        self.assertEqual(["/party/", "/"],
                         [urlsplit(urljoin(base, h)).path for h, _ in START_LINKS])


# ---------------------------------------------------------------- switch bar


class SwitchBar(unittest.TestCase):

    def _page(self, rel):
        return _read_text(self, REPO / rel)

    def test_each_page_has_one_bar_with_three_relative_links(self):
        for rel, url, _current, _value in PAGES:
            with self.subTest(page=rel):
                page = _parse(self._page(rel))
                bars = [n for n in page.navs if "switch-bar" in n["attrs"].get("class", "").split()]
                self.assertEqual(1, len(bars), "exactly one switch bar")
                self.assertEqual(1, len(page.navs), "no other nav added")
                bar = bars[0]
                self.assertEqual(BAR_LABEL, bar["attrs"].get("aria-label"))
                self.assertEqual(BAR_TEXTS, [a["text"] for a in bar["anchors"]])
                hrefs = [a["attrs"].get("href", "") for a in bar["anchors"]]
                for href in hrefs:
                    self.assertFalse(href.startswith("/") or "://" in href,
                                     "relative link (the replay copy serves ui/ under a subpath): %s"
                                     % href)
                self.assertEqual(BAR_PATHS, [urlsplit(urljoin("http://h" + url, h)).path
                                             for h in hrefs])

    def test_exactly_one_current_marker_on_the_right_link(self):
        for rel, _url, current, value in PAGES:
            with self.subTest(page=rel):
                page = _parse(self._page(rel))
                bar = [n for n in page.navs if "switch-bar" in n["attrs"].get("class", "").split()]
                self.assertTrue(bar, "no switch bar")
                marked = [(a["text"], a["attrs"].get("aria-current"))
                          for a in bar[0]["anchors"] if "aria-current" in a["attrs"]]
                self.assertEqual([(current, value)], marked)

    def test_bar_is_the_first_thing_in_the_body(self):
        for rel, *_ in PAGES:
            with self.subTest(page=rel):
                page = _parse(self._page(rel))
                self.assertTrue(page.body_children, "no body content")
                self.assertEqual("nav", page.body_children[0])

    def test_each_page_links_the_shared_bar_stylesheet(self):
        for rel, url, *_ in PAGES:
            with self.subTest(page=rel):
                page = _parse(self._page(rel))
                hrefs = [a.get("href", "") for t, a in page.tags
                         if t == "link" and a.get("rel") == "stylesheet"
                         and a.get("href", "").endswith("switch-bar.css")]
                self.assertEqual(1, len(hrefs))
                self.assertFalse(hrefs[0].startswith("/"))
                self.assertEqual("/switch-bar.css", urlsplit(urljoin("http://h" + url, hrefs[0])).path)
        self.assertTrue(SWITCH_CSS.is_file())

    def test_removing_the_bar_and_its_stylesheet_line_restores_the_page_exactly(self):
        for rel, *_ in PAGES:
            if rel not in ORIGINAL_PAGE_SHA:
                continue  # released by W35 (see ORIGINAL_PAGE_SHA)
            with self.subTest(page=rel):
                lines = (REPO / rel).read_bytes().split(b"\n")
                start = [i for i, line in enumerate(lines) if b'<nav class="switch-bar"' in line]
                self.assertEqual(1, len(start), 'one line opens <nav class="switch-bar"')
                end = next((i for i in range(start[0], len(lines)) if b"</nav>" in lines[i]), None)
                self.assertIsNotNone(end, "the bar closes with </nav>")
                css = [i for i, line in enumerate(lines) if b"switch-bar.css" in line]
                self.assertEqual(1, len(css), "one line links switch-bar.css")
                drop = set(range(start[0], end + 1)) | set(css)
                kept = b"\n".join(line for i, line in enumerate(lines) if i not in drop)
                if rel not in ORIGINAL_PAGE_SHA:
                    continue  # W35 lane C released ui/index.html (the console page changes)
                self.assertEqual(ORIGINAL_PAGE_SHA[rel], _sha(kept),
                                 "the bar and its stylesheet line are the ONLY change to %s" % rel)

    def test_bar_stylesheet_never_pins_the_bar(self):
        css = _strip_css_comments(_read_text(self, SWITCH_CSS))
        self.assertIn(".switch-bar", css)
        self.assertNotRegex(css.lower(), r"position\s*:\s*(sticky|fixed)",
                            "the bar scrolls away; a pinned bar fights the filing frame")

    def test_every_link_in_every_bar_lands_on_the_running_server(self):
        port = _ryde_server(self)
        for rel, url, *_ in PAGES:
            with self.subTest(page=rel):
                base = "http://127.0.0.1:%d%s" % (port, url)
                status, _hdr, body = _get(base)
                self.assertEqual(200, status)
                bar = [n for n in _parse(body.decode("utf-8")).navs
                       if "switch-bar" in n["attrs"].get("class", "").split()]
                self.assertTrue(bar, "served page carries the bar")
                for a in bar[0]["anchors"]:
                    self.assertEqual(200, _get(urljoin(base, a["attrs"]["href"]))[0])


# ---------------------------------------------------------------- freeze, replay, README


class Preservation(unittest.TestCase):

    def test_nothing_else_in_app_ui_scripts_styles_or_policy_moved(self):
        actual = {rel: _sha((REPO / rel).read_bytes()) for rel in FROZEN_W34}
        self.assertEqual(FROZEN_W34, actual)

    def test_no_new_script_or_existing_stylesheet_in_ui(self):
        scripts = sorted(str(p.relative_to(REPO)) for p in UI.rglob("*.js"))
        self.assertEqual(["ui/app.js", "ui/party/driver.js", "ui/party/party.js",
                          "ui/party/status.js"], scripts)

    def test_every_page_keeps_a_head_line_for_the_replay_exporter(self):
        for path in sorted(UI.rglob("*.html")):
            with self.subTest(page=str(path.relative_to(REPO))):
                lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()]
                self.assertIn("<head>", lines)


class ReadmeRun(unittest.TestCase):

    def test_run_section_names_the_launchers_and_keeps_the_manual_command(self):
        text = _read_text(self, REPO / "README.md")
        match = re.search(r"(?ms)^## Run\n(.*?)(?=^## |\Z)", text)
        self.assertIsNotNone(match, "README has a ## Run section")
        run = match.group(1)
        for needle in ("start.command", "start.bat", "/start/", "Python 3.9",
                       "Open Anyway", "Run anyway", "python3 -m app.server",
                       "http://127.0.0.1:8000/party/"):
            with self.subTest(needle=needle):
                self.assertIn(needle, run)
        if "start.command" not in run or "python3 -m app.server" not in run:
            return
        self.assertLess(run.index("start.command"), run.index("python3 -m app.server"),
                        "the one-click route comes first, the manual command stays as fallback")


if __name__ == "__main__":
    unittest.main()
