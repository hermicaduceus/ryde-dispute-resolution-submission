"""W27 replay shim: routing, refusals, banner and snapshot persistence, driven in Node.

tests/browser/w27_replay_shim.cjs loads the EXPORTED replay/replay-shim.js (the file the
exporter wrote, placeholders filled) into a fresh vm context per page and reports what each
fetch returned and what the banner says; this file asserts on that report.
Contract: docs/build-briefs/w27-replay-export-brief.md.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

from tests import w27_replay_support as w27

DRIVER = w27.REPO / "tests" / "browser" / "w27_replay_shim.cjs"


def _drive(site: Path, scenarios):
    """The driver's report, or {'harness_error': ...}. Never raises, so a broken shim or a
    missing export reads as a failed assertion in the tests, not as a test error."""
    node = shutil.which("node")
    if not node:
        return {"harness_error": "node is required for the W27 shim tests"}
    spec = w27.scratch_dir() / "scenarios.json"
    spec.write_text(json.dumps(scenarios), encoding="utf-8")
    try:
        result = subprocess.run([node, str(DRIVER), str(site), str(spec)], capture_output=True,
                                text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return {"harness_error": "driver timed out"}
    if result.returncode != 0:
        return {"harness_error": result.stderr[-3000:]}
    return json.loads(result.stdout)


def _sentence(snapshot: str, prefix: str = "") -> str:
    return prefix + w27.BANNER_SENTENCE % (w27.RECORDED_ON, snapshot)


def _body_file(site: Path, label: str, key: str) -> str:
    entries = w27.manifest(site, label)
    if key not in entries:
        raise AssertionError("%r is not in the %s manifest" % (key, label))
    return (site / "replay" / "data" / label / entries[key]).read_text(encoding="utf-8")


def _decode(body):
    """A response body as JSON; a body that is not JSON fails the test instead of erroring."""
    try:
        return json.loads(body)
    except (TypeError, ValueError):
        raise AssertionError("response body is not JSON: %r" % (body,))


def _decision_site(decision: str, amount):
    """HAND-MADE SHAPE: a copy of the mock export whose recorded after-snapshot decision is
    replaced, because the fixture records only an approval. Only the recorded body changes."""
    site = w27.scratch_dir() / "site"
    shutil.copytree(w27.mock_export()["out"], site)
    key = "GET /api/review/%s/case" % w27.fixture()["rd_run"]
    path = site / "replay" / "data" / "after" / w27.manifest(site, "after").get(key, "missing.json")
    if not path.is_file():
        raise AssertionError("the after snapshot has no recorded %s" % key)
    body = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(body.get("human_decision"), dict):
        raise AssertionError("the after snapshot's case body carries no recorded decision")
    body["human_decision"]["decision"] = decision
    body["human_decision"]["amount_sgd"] = amount
    path.write_text(json.dumps(body), encoding="utf-8")
    return site


class ReplayShim(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.export = w27.mock_export()
        cls.fx = w27.fixture()
        cls.site = cls.export["out"]
        rd, ns = cls.fx["rd_run"], cls.fx["ns_run"]
        payloads = w27.payload_names(cls.fx["after"] / rd)
        cls.after_only = [n for n in payloads if n not in w27.payload_names(cls.fx["before"] / rd)]
        decision_payload = cls.after_only[0] if cls.after_only else "missing.json"
        cls.decision_payload = decision_payload
        post = {"method": "POST", "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"decision": "approve", "reviewer": "x", "reason": "y"})}
        cls.calls_after = [
            {"input": "/api/demo/rider", "init": {"method": "GET"}},
            {"input": "/api/review/%s/case" % rd},
            {"input": "/api/trips?category=other", "init": {"method": "GET"}},
            {"input": "/api/review/%s/payloads/%s" % (rd, decision_payload), "init": {"method": "GET"}},
            {"input": "/api/review/NOPE-RUN/case", "init": {"method": "GET"}},
            {"input": "/api/demo/rider?extra=1", "init": {"method": "GET"}},
            {"input": "/api/not-a-route"},
            {"input": "/api/review/%s/decision" % rd, "init": post},
            {"input": "/api/disputes", "init": post},
            {"input": "/api/disputes/%s/answers" % rd, "init": post},
            {"input": "/api/review/%s/decision" % ns, "init": post},
            {"input": "/replay/data/after/manifest.json", "init": {"method": "GET"}},
            {"input": "/api/review/%s/case" % rd, "init": {"method": "PUT", "body": "{}"}},
            {"input": "/api/disputes", "init": {"method": "post", "body": "{}"}},
        ]
        cls.calls_before = [
            {"input": "/api/review/queue", "init": {"method": "GET"}},
            {"input": "/api/review/%s/payloads/%s" % (rd, decision_payload), "init": {"method": "GET"}},
            {"input": "/api/review/%s/decision" % rd, "init": post},
        ]
        queue = [{"input": "/api/review/queue", "init": {"method": "GET"}}]
        cls.scenarios = [
            {"name": "after", "pages": [{"url": "/party/status.html?snapshot=after", "calls": cls.calls_after}]},
            {"name": "before", "pages": [{"url": "/index.html?snapshot=before&run=%s" % rd, "calls": cls.calls_before}]},
            {"name": "storage", "pages": [
                {"url": "/index.html?snapshot=before&run=%s" % rd, "calls": []},
                {"url": "/party/status.html", "calls": queue},
                {"url": "/party/driver.html?snapshot=after", "calls": []},
                {"url": "/party/index.html", "calls": queue},
                {"url": "/party/status.html?snapshot=sideways", "calls": []},
            ]},
            {"name": "fresh", "pages": [{"url": "/party/status.html", "calls": queue}]},
            {"name": "fresh-invalid", "pages": [{"url": "/party/status.html?snapshot=nonsense", "calls": []}]},
        ]
        cls.report = _drive(cls.site, cls.scenarios) if cls.export["code"] == 0 else {
            "harness_error": "the mock export failed: " + cls.export["stderr"][-2000:]}

    # ------------------------------------------------------------------ helpers

    def page(self, scenario, index=0):
        self.assertNotIn("harness_error", self.report, self.report.get("harness_error"))
        page = self.report["scenarios"][scenario][index]
        self.assertEqual(page["errors"], [], page["errors"])
        return page

    def response(self, page, index):
        entry = page["responses"][index]
        self.assertIsNone(entry["error"], entry["error"])
        return entry["status"], entry["body"]

    def assertBanner(self, page, snapshot, prefix=w27.MOCK_PREFIX):
        banner = page["banner"]
        self.assertEqual(banner["count"], 1, "exactly one #replay-banner")
        self.assertTrue(banner["isFirstChild"], "the banner is the first child of <body>")
        self.assertEqual((banner["tag"], banner["role"]), ("DIV", "note"))
        self.assertEqual(banner["textBefore"].strip(), _sentence(snapshot, prefix))
        self.assertEqual(banner["textAfter"].strip(), "")
        self.assertEqual(banner["switchCount"], 1)
        self.assertIsNotNone(banner["link"], "#replay-switch must sit inside #replay-banner")
        other = "after" if snapshot == "before" else "before"
        self.assertEqual(banner["link"]["tag"], "A")
        self.assertEqual(banner["link"]["text"].strip(), "Show %s the decision" % other)
        # Walkthrough round (2026-10-15): one click home from every page.
        self.assertIsNotNone(banner["back"], "#replay-back must sit inside #replay-banner")
        self.assertEqual((banner["back"]["tag"], banner["back"]["href"]), ("A", "/replay/"))
        self.assertEqual(banner["back"]["text"].strip(), "Back to the steps")
        return banner["link"]["href"]

    def assertSwitchHref(self, href, path, query):
        parts = urlsplit(href)
        self.assertIn(parts.netloc, ("", "replay.test"))
        self.assertEqual(parts.path, path)
        self.assertEqual(sorted(parse_qsl(parts.query)), sorted(query))

    # ------------------------------------------------------------------ routing

    def test_recorded_gets_answer_200_with_the_recorded_body(self):
        page = self.page("after")
        rd = self.fx["rd_run"]
        keys = ["GET /api/demo/rider", "GET /api/review/%s/case" % rd, "GET /api/trips?category=other",
                "GET /api/review/%s/payloads/%s" % (rd, self.decision_payload)]
        self.assertTrue(self.after_only, "test premise: the decision adds a payload to after/")
        for index, key in enumerate(keys):
            with self.subTest(key=key):
                self.assertEqual(self.response(page, index), (200, _body_file(self.site, "after", key)))

    def test_snapshot_selects_the_recorded_data(self):
        page = self.page("before")
        before_queue = _body_file(self.site, "before", "GET /api/review/queue")
        self.assertNotEqual(before_queue, _body_file(self.site, "after", "GET /api/review/queue"))
        self.assertEqual(self.response(page, 0), (200, before_queue))
        status, body = self.response(page, 1)
        self.assertEqual((status, _decode(body)), (404, w27.NOT_IN_REPLAY))

    def test_unknown_api_gets_answer_404_not_in_this_replay(self):
        page = self.page("after")
        for index in (4, 5, 6):
            with self.subTest(call=self.calls_after[index]["input"]):
                status, body = self.response(page, index)
                self.assertEqual((status, _decode(body)), (404, w27.NOT_IN_REPLAY))

    def test_decision_post_is_refused_with_the_recorded_decision(self):
        expected = w27.DECISION_REFUSAL % "approve, SGD 55.16"
        for scenario, index in (("after", 7), ("before", 2)):
            with self.subTest(snapshot=scenario):
                status, body = self.response(self.page(scenario), index)
                self.assertEqual((status, _decode(body)), (403, {"error": expected}))

    def test_other_writes_are_refused_with_the_guided_walkthrough_sentence(self):
        page = self.page("after")
        for index in (8, 9, 10, 12, 13):
            with self.subTest(call=self.calls_after[index]):
                status, body = self.response(page, index)
                self.assertEqual((status, _decode(body)), (403, {"error": w27.GENERIC_REFUSAL}))

    def test_no_api_request_reaches_the_network_and_static_passes_through(self):
        page = self.page("after")
        self.assertEqual([n for n in page["network"] if n["url"].startswith("/api/")], [])
        status, body = self.response(page, 11)
        self.assertEqual(status, 200)
        self.assertEqual(_decode(body), w27.manifest(self.site, "after"))
        self.assertIn({"method": "GET", "url": "/replay/data/after/manifest.json"}, page["network"])
        before = self.page("before")
        self.assertEqual([n for n in before["network"] if n["url"].startswith("/api/")], [])

    # ------------------------------------------------------------------ banner

    def test_banner_after_the_decision(self):
        href = self.assertBanner(self.page("after"), "after")
        self.assertSwitchHref(href, "/party/status.html", [("snapshot", "before")])

    def test_banner_before_the_decision_keeps_other_parameters(self):
        href = self.assertBanner(self.page("before"), "before")
        self.assertSwitchHref(href, "/index.html", [("snapshot", "after"), ("run", self.fx["rd_run"])])

    def test_snapshot_persists_across_in_site_navigation(self):
        expected = ["before", "before", "after", "after", "after"]
        for index, snapshot in enumerate(expected):
            with self.subTest(page=self.scenarios[2]["pages"][index]["url"]):
                self.assertBanner(self.page("storage", index), snapshot)
        self.assertEqual(self.response(self.page("storage", 1), 0),
                         (200, _body_file(self.site, "before", "GET /api/review/queue")))
        self.assertEqual(self.response(self.page("storage", 3), 0),
                         (200, _body_file(self.site, "after", "GET /api/review/queue")))

    def test_default_snapshot_is_after(self):
        page = self.page("fresh")
        href = self.assertBanner(page, "after")
        self.assertSwitchHref(href, "/party/status.html", [("snapshot", "before")])
        self.assertEqual(self.response(page, 0), (200, _body_file(self.site, "after", "GET /api/review/queue")))
        self.assertBanner(self.page("fresh-invalid"), "after")

    def test_shim_is_plain_es5(self):
        self.assertEqual(self.export["code"], 0, self.export["stderr"][-2000:])
        source = w27.strip_js_comments((self.site / "replay" / "replay-shim.js").read_text(encoding="utf-8"))
        self.assertNotIn("=>", source)
        self.assertNotIn("`", source)
        self.assertNotRegex(source, r"\b(let|const|class|async|await)\b")


class ReplayShimVariants(unittest.TestCase):
    """Banner without the mock prefix, and the decision sentence for change and reject."""

    def test_real_provider_banner_has_no_test_prefix(self):
        fx = w27.copy_fixture({run: "tencent" for run in w27.fixture()["runs"]})
        site = w27.scratch_dir() / "site"
        code, _stdout, stderr = w27.run_cli(w27.export_args(fx, site, allow_mock=False))
        self.assertEqual(code, 0, stderr[-2000:])
        report = _drive(site, [{"name": "live", "pages": [
            {"url": "/party/status.html?snapshot=before", "calls": []},
            {"url": "/index.html?snapshot=after", "calls": []},
        ]}])
        self.assertNotIn("harness_error", report, report.get("harness_error"))
        for index, snapshot in enumerate(("before", "after")):
            page = report["scenarios"]["live"][index]
            self.assertEqual(page["errors"], [])
            self.assertEqual(page["banner"]["count"], 1)
            self.assertEqual(page["banner"]["textBefore"].strip(), _sentence(snapshot))

    def test_decision_sentence_for_change_and_reject(self):
        export = w27.mock_export()
        self.assertEqual(export["code"], 0, export["stderr"][-2000:])
        rd = w27.fixture()["rd_run"]
        post = {"method": "POST", "body": "{}"}
        for decision, amount, chose in (("change", 40, "change, SGD 40.00"), ("reject", None, "reject")):
            with self.subTest(decision=decision):
                report = _drive(_decision_site(decision, amount), [{"name": "d", "pages": [
                    {"url": "/index.html?snapshot=before&run=%s" % rd,
                     "calls": [{"input": "/api/review/%s/decision" % rd, "init": post}]}]}])
                self.assertNotIn("harness_error", report, report.get("harness_error"))
                page = report["scenarios"]["d"][0]
                self.assertEqual(page["errors"], [])
                entry = page["responses"][0]
                self.assertIsNone(entry["error"])
                self.assertEqual((entry["status"], _decode(entry["body"])),
                                 (403, {"error": w27.DECISION_REFUSAL % chose}))


if __name__ == "__main__":
    unittest.main()
