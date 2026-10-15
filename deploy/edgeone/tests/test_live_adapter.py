"""Tests for the live EdgeOne adapter (cloud-functions/api/[[default]].py).

The provider seam (_make_llm) is replaced by the keyless mock, so no test spends credits. Each
test gets its own runtime root (cases + limit counts) and a fresh server.

The adapter runs inside an assembled bundle (it imports app/ from beside itself), so with no
RYDE_LIVE_SITE the bundle is built from this repository by deploy/edgeone/package.py into a
temporary folder. Point RYDE_LIVE_SITE at an unpacked deploy zip to test that instead.

    cd deploy/edgeone/tests && python3 -m unittest test_live_adapter -v
"""
import importlib.util
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

if os.environ.get("RYDE_LIVE_SITE"):
    SITE = Path(os.environ["RYDE_LIVE_SITE"])
else:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import package

    _BUILD = tempfile.TemporaryDirectory(prefix="ryde-edgeone-site-")
    SITE = package.build(Path(_BUILD.name) / "site")
ENTRY = SITE / "cloud-functions" / "api" / "[[default]].py"

NS_BODY = {
    "category": "no_show_charge", "filed_by": "rider", "trip_id": "T-NS0202",
    "description": "I was at the pickup point the whole time and was charged anyway.",
    "claim_amount_sgd": 5,
    "answers": {"where_were_you": "At the pickup point", "did_driver_contact_you": "No",
                "safety_concern": "No", "rider_claims_driver_absent": "Yes"},
}
BLANK_ROUTE_BODY = {
    "category": "route_deviation", "filed_by": "rider", "trip_id": "T-RD0101",
    "description": "The ride went a different way.", "claim_amount_sgd": None,
    "answers": {"expected_route": "", "was_route_agreed": "", "asked_driver_to_stop": "",
                "safety_concern": ""},
}
OTHER_BODY = {
    "category": "other", "filed_by": "rider", "trip_id": "T-NS0202",
    "description": "Something else happened.", "claim_amount_sgd": None, "answers": {},
}


def load_adapter():
    spec = importlib.util.spec_from_file_location("live_entry_%d" % id(object()), ENTRY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AdapterCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.m = load_adapter()
        self.m.RUNTIME_ROOT = Path(self.tmp.name)
        from app.llm import build_llm_client
        self.m._make_llm = lambda config: build_llm_client("mock")
        self.clock = [1_760_500_000.0]  # 2025-10-15 ~11:46 SGT; tests move it explicitly
        self.m._now = lambda: self.clock[0]
        self.inflight = [0]
        self.idle = threading.Event()
        self.idle.set()
        lock = threading.Lock()
        test = self

        class Tracked(self.m.handler):
            def setup(self):
                with lock:
                    test.inflight[0] += 1
                    test.idle.clear()
                super().setup()

            def finish(self):
                try:
                    super().finish()
                finally:
                    with lock:
                        test.inflight[0] -= 1
                        if test.inflight[0] == 0:
                            test.idle.set()

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Tracked)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.base = "http://127.0.0.1:%d" % self.httpd.server_address[1]

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.tmp.cleanup()

    def call(self, path, body=None, visitor="203.0.113.1", raw=None, extra=None):
        data = raw if raw is not None else (None if body is None else json.dumps(body).encode())
        req = urllib.request.Request(self.base + path, data=data,
                                     headers={"Content-Type": "application/json",
                                              "Eo-Connecting-Ip": visitor, **(extra or {})})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status, json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode())

    def counts(self):
        # The refund for a refused filing runs after the response is written, so wait until
        # the server has finished every request it accepted before reading the file.
        self.assertTrue(self.idle.wait(5), "server still busy")
        p = Path(self.tmp.name) / "limits.json"
        return json.loads(p.read_text()) if p.exists() else {}


class ProviderAndBudget(AdapterCase):
    def test_live_provider_and_budget(self):
        self.assertEqual(self.m.LIVE_PROVIDER, "tencent")
        self.assertEqual(self.m.CASE_BUDGET_SECONDS, 100)
        self.call("/api/review/runs")
        self.assertEqual(self.m._SHIM.ryde_state.case_budget_seconds, 100)

    def test_real_seam_builds_tencent_from_env_keys(self):
        m = load_adapter()
        m.RUNTIME_ROOT = Path(self.tmp.name) / "seam"
        names = ("TENCENT_ADP_RIDER_APP_KEY", "TENCENT_ADP_DRIVER_APP_KEY", "TENCENT_ADP_JUDGE_APP_KEY")
        saved = {n: os.environ.get(n) for n in names}
        try:
            for n in names:
                os.environ[n] = "test-placeholder-" + n
            state = m._build_state()
            self.assertEqual(state.llm.provider_name, "tencent")
        finally:
            for n, v in saved.items():
                if v is None:
                    os.environ.pop(n, None)
                else:
                    os.environ[n] = v

    def test_missing_keys_answer_503_then_recover(self):
        def boom(config):
            raise RuntimeError("missing keys")
        self.m._make_llm = boom
        status, body = self.call("/api/trips?category=no_show_charge&filed_by=rider")
        self.assertEqual(status, 503)
        self.assertEqual(body["error"], self.m.NOT_CONFIGURED_MESSAGE)
        status, body = self.call("/api/disputes", NS_BODY)
        self.assertEqual(status, 503)
        self.assertEqual(self.counts(), {}, "a refused-before-limit filing must not be counted")
        from app.llm import build_llm_client
        self.m._make_llm = lambda config: build_llm_client("mock")
        status, _ = self.call("/api/trips?category=no_show_charge&filed_by=rider")
        self.assertEqual(status, 200)

    def test_case_file_records_repo_relative_policy(self):
        status, body = self.call("/api/disputes", NS_BODY)
        self.assertEqual(status, 200)
        case = json.loads((Path(self.tmp.name) / "runs" / body["run_id"] / "case_file.json").read_text())
        self.assertEqual(case["policy"]["source_path"], "docs/policy.md")


class VisitorLimit(AdapterCase):
    def test_eleventh_filing_in_an_hour_is_refused_with_message(self):
        for i in range(10):
            status, _ = self.call("/api/disputes", NS_BODY)
            self.assertEqual(status, 200, "filing %d" % (i + 1))
        status, body = self.call("/api/disputes", NS_BODY)
        self.assertEqual(status, 429)
        self.assertEqual(body, {"error": self.m.VISITOR_LIMIT_MESSAGE})
        self.assertIn("10 live filings per hour", body["error"])
        self.assertEqual(self.counts()["daily"], 10)

    def test_other_visitor_unaffected(self):
        for _ in range(10):
            self.call("/api/disputes", NS_BODY, visitor="203.0.113.1")
        status, _ = self.call("/api/disputes", NS_BODY, visitor="203.0.113.2")
        self.assertEqual(status, 200)

    def test_window_rolls_after_an_hour(self):
        for _ in range(10):
            self.call("/api/disputes", NS_BODY)
        self.clock[0] += 3599
        self.assertEqual(self.call("/api/disputes", NS_BODY)[0], 429)
        self.clock[0] += 2  # first stamps now 3601 s old
        self.assertEqual(self.call("/api/disputes", NS_BODY)[0], 200)

    def test_spoofable_headers_do_not_mint_new_visitors(self):
        for i in range(10):
            self.call("/api/disputes", NS_BODY, visitor="198.51.100.7",
                      extra={"X-Forwarded-For": "10.0.0.%d" % i, "EO-Client-IP": "10.1.0.%d" % i,
                             "X-Real-IP": "10.2.0.%d" % i})
        status, _ = self.call("/api/disputes", NS_BODY, visitor="198.51.100.7",
                              extra={"X-Forwarded-For": "192.0.2.99", "EO-Client-IP": "192.0.2.98"})
        self.assertEqual(status, 429)
        self.assertEqual(list(self.counts()["visitors"]), ["198.51.100.7"])

    def test_missing_trusted_header_shares_one_strict_bucket(self):
        for i in range(10):
            self.call("/api/disputes", NS_BODY, visitor="", extra={"X-Forwarded-For": "10.0.0.%d" % i})
        self.assertEqual(self.call("/api/disputes", NS_BODY, visitor="",
                                   extra={"X-Forwarded-For": "10.0.9.9"})[0], 429)
        self.assertEqual(list(self.counts()["visitors"]), ["unknown"])


class DailyLimit(AdapterCase):
    def test_daily_total_refused_with_message_and_resets_next_sgt_day(self):
        self.m.DAILY_LIMIT = 3
        for i, v in enumerate(["a", "b", "c"]):
            self.assertEqual(self.call("/api/disputes", NS_BODY, visitor=v)[0], 200)
        status, body = self.call("/api/disputes", NS_BODY, visitor="d")
        self.assertEqual(status, 429)
        self.assertEqual(body, {"error": self.m.DAILY_LIMIT_MESSAGE})
        self.assertIn("midnight Singapore time", body["error"])
        # 1_760_500_000 is 11:46:40 SGT; +12h14m lands at 00:00:40 SGT the next day
        self.clock[0] += 12 * 3600 + 14 * 60
        self.assertEqual(self.call("/api/disputes", NS_BODY, visitor="d")[0], 200)
        self.assertEqual(self.counts()["daily"], 1)

    def test_day_boundary_is_singapore_midnight_not_utc(self):
        self.m.DAILY_LIMIT = 1
        self.assertEqual(self.call("/api/disputes", NS_BODY, visitor="a")[0], 200)
        self.clock[0] += 12 * 3600  # 23:46 SGT same day (UTC date has not changed either way)
        self.assertEqual(self.call("/api/disputes", NS_BODY, visitor="b")[0], 429)
        self.clock[0] += 14 * 60  # 00:00:40 SGT next day, still 16:00 UTC same UTC day
        self.assertEqual(self.call("/api/disputes", NS_BODY, visitor="b")[0], 200)


class WhatCounts(AdapterCase):
    def test_out_of_scope_report_not_counted(self):
        status, body = self.call("/api/disputes", OTHER_BODY)
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "passed_to_support")
        self.assertEqual(self.counts(), {})

    def test_refused_filing_gives_slot_back(self):
        bad = dict(NS_BODY, trip_id="T-RD0101")  # category/trip mismatch -> app answers 400
        status, _ = self.call("/api/disputes", bad)
        self.assertEqual(status, 400)
        self.assertEqual(self.counts()["daily"], 0)
        self.assertEqual(self.counts()["visitors"].get("203.0.113.1", []), [])

    def test_follow_up_answers_never_limited(self):
        status, body = self.call("/api/disputes", BLANK_ROUTE_BODY)
        self.assertEqual((status, body["status"]), (200, "needs_info"))
        for _ in range(9):
            self.call("/api/disputes", NS_BODY)
        self.assertEqual(self.call("/api/disputes", NS_BODY)[0], 429)
        # A stray category in the answers body must not make the reply look like a new filing.
        answers = {"category": "route_deviation",
                   "answers": [{"question": q, "answer": "We agreed nothing; the app showed the expressway."}
                               for q in body["questions"]]}
        status, out = self.call("/api/disputes/%s/answers" % body["run_id"], answers)
        self.assertEqual(status, 200)
        self.assertEqual(self.counts()["daily"], 10)

    def test_console_and_reads_never_limited(self):
        self.m.DAILY_LIMIT = 0
        for path in ("/api/review/runs", "/api/review/queue", "/api/demo/rider",
                     "/api/trips?category=route_deviation&filed_by=rider"):
            self.assertEqual(self.call(path)[0], 200, path)

    def test_malformed_body_reaches_app_and_is_not_counted(self):
        status, _ = self.call("/api/disputes", raw=b"{not json")
        self.assertEqual(status, 400)
        self.assertEqual(self.counts(), {})

    def test_corrupt_counts_file_recovers(self):
        (Path(self.tmp.name) / "limits.json").write_text("[1,2,3]")
        self.assertEqual(self.call("/api/disputes", NS_BODY)[0], 200)
        self.assertEqual(self.counts()["daily"], 1)


class Concurrency(AdapterCase):
    def test_parallel_filings_never_exceed_the_daily_limit(self):
        self.m.DAILY_LIMIT = 5
        results = []

        def go(i):
            results.append(self.call("/api/disputes", NS_BODY, visitor="v%d" % i)[0])

        threads = [threading.Thread(target=go, args=(i,)) for i in range(12)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(results.count(200), 5)
        self.assertEqual(results.count(429), 7)
        self.assertEqual(self.counts()["daily"], 5)


def raw_post(base, target, body, visitor="203.0.113.1"):
    """Send a request-target exactly as given (urllib would drop a fragment)."""
    import socket
    from urllib.parse import urlsplit as _u
    port = _u(base).port
    data = json.dumps(body).encode()
    sock = socket.create_connection(("127.0.0.1", port))
    sock.sendall(("POST %s HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\n"
                  "Eo-Connecting-Ip: %s\r\nContent-Length: %d\r\nConnection: close\r\n\r\n"
                  % (target, visitor, len(data))).encode() + data)
    out = b""
    while True:
        chunk = sock.recv(65536)
        if not chunk:
            break
        out += chunk
    sock.close()
    head, _, rest = out.partition(b"\r\n\r\n")
    return int(head.split()[1]), json.loads(rest or b"{}")


class ReviewFindings(AdapterCase):
    """Pins for the glm-5.3 review round (F1 fragment, F2 midnight, F3 bound, F4 prefix, F7 log)."""

    def test_f1_fragment_or_query_cannot_dodge_the_limit(self):
        for target in ["/api/disputes#x", "/api/disputes?x=1", "/api/disputes?a#b"] * 3 + ["/api/disputes#y"]:
            self.assertEqual(raw_post(self.base, target, NS_BODY)[0], 200, target)
        status, body = raw_post(self.base, "/api/disputes#z", NS_BODY)
        self.assertEqual((status, body), (429, {"error": self.m.VISITOR_LIMIT_MESSAGE}))
        self.assertEqual(self.counts()["daily"], 10)

    def test_f2_rolling_hour_survives_singapore_midnight(self):
        self.clock[0] = 1_760_543_700.0  # 23:55 SGT
        for _ in range(10):
            self.assertEqual(self.call("/api/disputes", NS_BODY)[0], 200)
        self.clock[0] += 11 * 60  # 00:06 SGT, next day
        status, body = self.call("/api/disputes", NS_BODY)
        self.assertEqual((status, body.get("error")), (429, self.m.VISITOR_LIMIT_MESSAGE))
        self.assertEqual(self.counts()["daily"], 0, "the daily total itself did reset")
        self.assertEqual(self.call("/api/disputes", NS_BODY, visitor="198.51.100.20")[0], 200)
        self.clock[0] += 3600  # past the hour since 23:55
        self.assertEqual(self.call("/api/disputes", NS_BODY)[0], 200)

    def test_f3_a_case_can_be_answered_once_by_anyone_then_never_again(self):
        status, body = self.call("/api/disputes", BLANK_ROUTE_BODY, visitor="198.51.100.1")
        self.assertEqual(body["status"], "needs_info")
        answers = {"answers": [{"question": q, "answer": "No change was agreed."} for q in body["questions"]]}
        self.assertEqual(self.call("/api/disputes/%s/answers" % body["run_id"], answers,
                                   visitor="198.51.100.2")[0], 200)
        self.assertEqual(self.call("/api/disputes/%s/answers" % body["run_id"], answers,
                                   visitor="198.51.100.3")[0], 409)

    def test_f4_platform_stripped_prefix_is_restored_and_still_limited(self):
        for _ in range(10):
            self.assertEqual(raw_post(self.base, "/disputes", NS_BODY)[0], 200)
        self.assertEqual(raw_post(self.base, "/disputes", NS_BODY)[0], 429)
        self.assertEqual(raw_post(self.base, "/review/runs", {})[0], 404)  # POST on a GET route

    def test_f7_build_failure_is_logged_without_values(self):
        import contextlib
        import io as _io

        def boom(config):
            raise RuntimeError("missing ADP app key(s): TENCENT_ADP_JUDGE_APP_KEY")
        self.m._make_llm = boom
        err = _io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(self.call("/api/review/runs")[0], 503)
        self.assertIn("state not ready: RuntimeError: missing ADP app key(s): TENCENT_ADP_JUDGE_APP_KEY",
                      err.getvalue())


if __name__ == "__main__":
    unittest.main()
