"""One-click launcher for the Ryde demo.

Double-clicked through start.command (macOS) or start.bat (Windows), or run by hand:

    python3 tools/launch.py [--ports FIRST-LAST]

The launcher picks the first free port in the range — reusing a Ryde demo that is
already running — then runs the EXISTING app.server entry point in this same process
with the mock provider, and opens the start page once the server answers. One process
is load-bearing: Ctrl+C reaches app.server's own KeyboardInterrupt handler, and
closing the terminal window (SIGHUP) ends the process and frees the port.

This is a helper for the demo, not part of the app: app/ and ui/ never import it.
"""

from __future__ import annotations

import argparse
import errno
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from typing import Optional, Tuple

#: Run as `python3 tools/launch.py`, sys.path[0] is tools/, so the repository root
#: goes in before app.server is imported. The launcher never re-implements server
#: startup; it calls the existing entry point.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import app.server as server  # noqa: E402 - sys.path is prepared just above

FIRST_PORT = 8000
LAST_PORT = 8010
START_PATH = "/start/"

#: How long one probe may wait for an answer: a listener that accepts the connection
#: but never speaks must not stall the launcher.
PROBE_TIMEOUT = 1.0
#: How long a refused loopback connect may take before it counts as busy. Windows
#: retries a refusal for a second or two, so a shorter wait would read every free
#: port as taken there.
CONNECT_TIMEOUT = 3.0
#: The browser waiter's polling cadence, and how long it waits for the server to
#: answer before printing the URL instead.
POLL_SECONDS = 0.1
READY_TIMEOUT = 30.0

#: The banner app/server.py sends. A 200 carrying it is the only proof that a port
#: serves this demo and not some other program.
SERVER_HEADER = "RydePartyServer/"

#: Every loopback probe goes through this opener, which ignores the user's proxy
#: settings: urllib honours http_proxy and the system proxy, and macOS's default
#: proxy exceptions do not include 127.0.0.1, so a configured proxy would hide a
#: running demo from the launcher.
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

RUNNING = "Ryde demo running at {url}"
STOP_HINT = "Close this window (or press Ctrl+C) to stop the demo."
ALREADY_RUNNING = "The Ryde demo is already running at {url}. Opening it in your browser."
NO_FREE_PORT = ("Ports {first} to {last} are all in use by other programs. "
                "Close one of them, then open this file again.")
OPEN_YOURSELF = "Could not open a browser. Open {url} yourself."
PORT_TAKEN = "Port {port} was taken just as the demo started. Open this file again."


def start_url(port: int) -> str:
    """The start page's URL on 127.0.0.1."""
    return "http://127.0.0.1:%d%s" % (port, START_PATH)


def server_argv(port: int) -> list:
    """The existing server's own arguments: the mock, and the chosen port."""
    return ["--llm", "mock", "--port", str(port)]


def _answer(url: str) -> Optional[Tuple[int, str]]:
    """(status, Server header) for a GET, or None when the port did not answer.

    Any failure to get an answer — refused, timed out, a listener that speaks
    something that is not HTTP — reads as None, never as a status.
    """
    try:
        with _opener.open(url, timeout=PROBE_TIMEOUT) as response:
            return response.status, response.headers.get("Server", "")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers.get("Server", "")
    except Exception:
        return None


def is_ryde_demo(port: int) -> bool:
    """True only when GET /start/ answers 200 with the Ryde server banner.

    Nothing listening, another program's 200, and the Ryde banner on a 404 are all
    False: only the two together prove this port serves the demo.
    """
    answer = _answer(start_url(port))
    return bool(answer and answer[0] == 200 and answer[1].startswith(SERVER_HEADER))


def _is_free(port: int) -> bool:
    """True when a TCP connect to 127.0.0.1:port is refused (nobody is listening)."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=CONNECT_TIMEOUT):
            return False
    except ConnectionRefusedError:
        return True
    except OSError:
        # Not a refusal — something is there, or the probe could not tell. Skipping
        # the port is the safe reading.
        return False


def pick_port(first: int, last: int) -> Tuple[Optional[int], bool]:
    """The first usable port in [first, last], and whether the demo already runs on it.

    Ports are walked in order. A port already serving the Ryde demo is reused. Any
    other listener — HTTP or one that never answers — is skipped. The first port
    whose TCP connect is refused is used. (None, False) when every port is taken.
    """
    for port in range(first, last + 1):
        if is_ryde_demo(port):
            return port, True
        if _is_free(port):
            return port, False
    return None, False


def _open(url: str) -> bool:
    """Open url in the default browser. False when the browser refused or raised."""
    try:
        return bool(webbrowser.open(url))
    except webbrowser.Error:
        return False


def open_when_ready(url: str, timeout: float = READY_TIMEOUT) -> None:
    """Open url in the browser once it answers 200, or print it when that fails.

    The server starts on the main thread after this waiter, so the page must not be
    opened before the port answers. A server that never answers, and a browser that
    refuses or raises, both print the URL so the demo is still reachable by hand.
    """
    deadline = time.monotonic() + timeout
    while True:
        answer = _answer(url)
        if answer is not None and answer[0] == 200:
            break
        if time.monotonic() >= deadline:
            print(OPEN_YOURSELF.format(url=url))
            return
        time.sleep(POLL_SECONDS)
    if not _open(url):
        print(OPEN_YOURSELF.format(url=url))


def _port_range(raw: str) -> Tuple[int, int]:
    """'FIRST-LAST' as argparse takes it, or exit 2."""
    first, sep, last = raw.partition("-")
    if sep != "-":
        raise argparse.ArgumentTypeError("ports must be FIRST-LAST, e.g. 8000-8010")
    try:
        first_port, last_port = int(first), int(last)
    except ValueError:
        raise argparse.ArgumentTypeError("ports must be FIRST-LAST, e.g. 8000-8010")
    if not 1 <= first_port <= last_port <= 65535:
        raise argparse.ArgumentTypeError("ports must be an increasing range within 1..65535")
    return first_port, last_port


def main(argv: Optional[list] = None) -> int:
    """Pick a port, open the start page, and run the existing server. Returns its code."""
    parser = argparse.ArgumentParser(
        prog="python3 tools/launch.py",
        description="Start the Ryde demo on the first free port and open the start page.",
    )
    parser.add_argument(
        "--ports",
        type=_port_range,
        default=(FIRST_PORT, LAST_PORT),
        metavar="FIRST-LAST",
        help="ports to try, in order (default: %(default)s)",
    )
    args = parser.parse_args(argv)
    first, last = args.ports

    port, already_running = pick_port(first, last)
    if port is None:
        print(NO_FREE_PORT.format(first=first, last=last))
        return 1

    url = start_url(port)
    if already_running:
        print(ALREADY_RUNNING.format(url=url))
        if not _open(url):
            print(OPEN_YOURSELF.format(url=url))
        return 0

    print(RUNNING.format(url=url))
    print(STOP_HINT)
    # The waiter must not run before the server, so it goes on a daemon thread and the
    # server keeps the main thread: Ctrl+C reaches app.server's own handler, and a
    # closed terminal window ends this one process and frees the port.
    threading.Thread(target=open_when_ready, args=(url,), daemon=True).start()
    try:
        return server.main(server_argv(port))
    except OSError as exc:
        # Two quick double-clicks can both pick the same free port; the loser's bind
        # fails with EADDRINUSE. That is a race, not a bug: say so in one line, and
        # the next double-click reuses the winner or takes the next free port.
        if exc.errno in (errno.EADDRINUSE, 10048):
            print(PORT_TAKEN.format(port=port))
            return 1
        raise


if __name__ == "__main__":
    sys.exit(main())
