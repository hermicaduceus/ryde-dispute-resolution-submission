"""W35 round 2, lane S: the status page's lookup controls can never be covered or unreachable.

REVIEW finding 1: the fixed status frame (ui/switch-bar.css, min-height 654px) let the lookup
section shrink below its own title, field, error line and button, so "My disputes" painted over
Check status. In an exported replay the banner above the bar made it worse. The contract:

  * the lookup box never shrinks; a lookup RESULT is its own block under it and is the part that
    gives up room (down to 5rem, scrolling inside its own window);
  * if the floors (header 4.5rem, lookup box, result 5rem, list 8rem) do not fit, the shell
    scrolls: never overflow:hidden with a control off screen;
  * the list still scrolls inside its own region and never moves the lookup box; no fades.

The geometry is a real-browser contract (tests/browser/w35_r2_S.cjs, live and an exported mock
replay, widths 320/360/390/1280, heights around the threshold, seven lookup states, a hit test
with the pointer parked away because a hover raises the filtered button above its neighbours).
The markup order is pinned here so a run without a browser still sees it.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading
import unittest
from functools import partial
from html.parser import HTMLParser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from tests.w23_b2_support import NODE
from tests.w23_support import Server

REPO = Path(__file__).resolve().parent.parent
PARTY = REPO / "ui" / "party"
BROWSER_DIR = REPO / "tests" / "browser"


class _Doc(HTMLParser):
    """Minimal element tree: (tag, attrs, children)."""

    VOID = {"meta", "link", "input", "br", "img"}

    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.root = ("#root", {}, [])
        self.stack = [self.root]
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        node = (tag, dict(attrs), [])
        self.stack[-1][2].append(node)
        if tag not in self.VOID:
            self.stack.append(node)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break


def _walk(node):
    yield node
    for child in node[2]:
        yield from _walk(child)


def _cls(node):
    return node[1].get("class", "").split()


class StatusMarkupOrder(unittest.TestCase):

    def setUp(self):
        self.doc = _Doc((PARTY / "status.html").read_text(encoding="utf-8")).root
        mains = [n for n in _walk(self.doc) if n[0] == "main"]
        self.assertEqual(1, len(mains))
        self.main = mains[0]

    def test_the_result_block_is_its_own_child_of_the_shell_between_the_lookup_box_and_the_list(self):
        kids = [(n[0], n[1].get("id"), _cls(n)) for n in self.main[2]]
        self.assertEqual(
            [("header", None, ["party-header"]),
             ("section", None, ["step", "status-lookup"]),
             ("div", "lookup-result", []),
             ("section", None, ["step", "status-list"])], kids,
            "the result must not live inside the lookup box: a shrinking box is what covered the button")

    def test_the_lookup_box_keeps_exactly_its_controls(self):
        lookup = next(n for n in self.main[2] if "status-lookup" in _cls(n))
        self.assertEqual(["h2", "div", "p", "div"], [n[0] for n in lookup[2]])
        ids = [n[1].get("id") for n in _walk(lookup) if n[1].get("id")]
        self.assertEqual(["reference-input", "reference-error", "reference-check"], ids)
        self.assertFalse([n for n in _walk(lookup) if n[1].get("id") == "lookup-result"])

    def test_the_result_block_starts_empty(self):
        found = [n for n in self.main[2] if n[1].get("id") == "lookup-result"]
        self.assertEqual(1, len(found), "one result block, a direct child of the shell")
        self.assertEqual([], found[0][2], "an empty result block takes no room (display:none while :empty)")


def _browser_env():
    return os.environ.get("PUPPETEER_MODULE") and os.environ.get("BROWSER_EXECUTABLE")


def _run_node(args, env_extra=None, timeout=900):
    env = dict(os.environ)
    env.update(env_extra or {})
    return subprocess.run([NODE, str(BROWSER_DIR / "w35_r2_S.cjs")] + args, env=env, capture_output=True,
                          text=True, timeout=timeout)


def _message(data, result):
    shown = "\n".join((data.get("violations") or [])[:25])
    return (data.get("error") or shown or result.stderr)[-4000:]


@unittest.skipUnless(_browser_env(), "PUPPETEER_MODULE and BROWSER_EXECUTABLE are not set")
class RealBrowserStatusLayout(unittest.TestCase):
    """tests/browser/w35_r2_S.cjs: live status page and exported replay."""

    def _report(self):
        report = Path(tempfile.mkdtemp(prefix="w35s-")) / "report.json"
        self.addCleanup(shutil.rmtree, report.parent, True)
        return report

    def _check(self, target, base):
        report = self._report()
        result = _run_node([target, base, str(report)])
        data = json.loads(report.read_text()) if report.is_file() else {}
        self.assertEqual(0, result.returncode, _message(data, result))
        self.assertTrue(data.get("passed"), _message(data, result))
        self.assertGreaterEqual(len(data.get("views", [])), 31, "the whole viewport matrix ran")

    def test_the_live_status_page_never_covers_or_loses_a_lookup_control(self):
        server = Server()
        self.addCleanup(server.close)
        self._check("live", server.base)

    def test_the_exported_replay_status_page_never_covers_or_loses_a_lookup_control(self):
        from tests import w27_replay_support as w27

        export = w27.mock_export()
        self.assertEqual(0, export["code"], export["stderr"][-2000:])

        class Quiet(SimpleHTTPRequestHandler):
            def log_message(self, *args):
                pass

        httpd = ThreadingHTTPServer(("127.0.0.1", 0), partial(Quiet, directory=str(export["out"])))
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        self._check("replay", "http://127.0.0.1:%d" % httpd.server_address[1])


if __name__ == "__main__":
    unittest.main()
