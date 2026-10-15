"""W27 static replay exporter: CLI end to end, manifest coverage, copies, refusals, secret scan.

Runs tools/export_replay.py against a fixture the real pipeline produced on the mock (see
tests/w27_replay_support.py). Contract: docs/build-briefs/w27-replay-export-brief.md.
"""

from __future__ import annotations

import json
import re
import shutil
import unittest
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

from tests import w27_replay_support as w27


def _out_dir() -> Path:
    return w27.scratch_dir() / "site"


class _Landing(HTMLParser):
    """title text, and every <ol> as a list of <li> items, each a list of (href, text) links."""

    def __init__(self):
        super().__init__()
        self.title, self.lists = "", []
        self._in_title = False
        self._ol_depth = 0
        self._li = None
        self._a = None

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self._in_title = True
        elif tag == "ol":
            self._ol_depth += 1
            self.lists.append([])
        elif tag == "li" and self._ol_depth:
            self._li = []
            self.lists[-1].append(self._li)
        elif tag == "a" and self._li is not None:
            self._a = [dict(attrs).get("href"), ""]
            self._li.append(self._a)

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        elif tag == "ol":
            self._ol_depth -= 1
        elif tag == "li":
            self._li = None
        elif tag == "a":
            self._a = None

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        if self._a is not None:
            self._a[1] += data


class ExportEndToEnd(unittest.TestCase):
    """One --allow-mock export of the mock fixture through the real CLI."""

    @classmethod
    def setUpClass(cls):
        cls.fx = w27.fixture()
        cls.inputs_before = {label: w27.tree(cls.fx[label]) for label in w27.LABELS}
        cls.out = _out_dir()
        cls.code, cls.stdout, cls.stderr = w27.run_cli(w27.export_args(cls.fx, cls.out))
        cls.inputs_after = {label: w27.tree(cls.fx[label]) for label in w27.LABELS}

    def test_export_succeeds_with_a_missing_secrets_file(self):
        # export_args points --secrets-file at a file that does not exist: no secrets to check.
        self.assertEqual(self.code, 0, self.stderr[-2000:])
        for rel in ("replay/index.html", "replay/replay-shim.js", "replay/data/before/manifest.json",
                    "replay/data/after/manifest.json", "index.html", "party/status.html"):
            self.assertTrue((self.out / rel).is_file(), rel)

    def test_manifest_covers_exactly_the_required_urls(self):
        self.assertEqual(self.code, 0, self.stderr[-2000:])
        for label in w27.LABELS:
            with self.subTest(label=label):
                expected = set(w27.required_keys(self.fx, label)) | set(w27.optional_keys_live(self.fx, label))
                actual = set(w27.manifest(self.out, label))
                self.assertEqual(sorted(expected - actual), [], "missing from the %s manifest" % label)
                self.assertEqual(sorted(actual - expected), [], "unexpected in the %s manifest" % label)

    def test_every_category_the_party_pages_offer_is_recorded(self):
        self.assertEqual(self.code, 0, self.stderr[-2000:])
        party_js = (w27.UI_DIR / "party" / "party.js").read_text(encoding="utf-8")
        offered = []
        for value in re.findall(r'\{\s*id:\s*"([a-z_]+)",\s*label:', party_js):
            if value not in offered:
                offered.append(value)
        self.assertEqual(offered, w27.CATEGORIES, "the party pages' category list moved; update the fixture table")
        for label in w27.LABELS:
            keys = w27.manifest(self.out, label)
            for category in offered:
                self.assertIn("GET /api/trips?category=%s" % category, keys)

    def test_manifest_values_are_numbered_files_and_nothing_else(self):
        self.assertEqual(self.code, 0, self.stderr[-2000:])
        for label in w27.LABELS:
            with self.subTest(label=label):
                values = list(w27.manifest(self.out, label).values())
                for value in values:
                    self.assertRegex(value, r"^[0-9]{4}\.json$")
                self.assertEqual(len(values), len(set(values)), "two keys share one body file")
                data_dir = self.out / "replay" / "data" / label
                self.assertEqual(sorted(p.name for p in data_dir.iterdir()),
                                 sorted(values + ["manifest.json"]))

    def test_recorded_bodies_equal_the_real_server(self):
        self.assertEqual(self.code, 0, self.stderr[-2000:])
        for label in w27.LABELS:
            live = w27.LiveServer(self.fx[label])
            try:
                for key in w27.manifest(self.out, label):
                    with self.subTest(label=label, key=key):
                        status, body = live.get(key[len("GET "):])
                        self.assertEqual(status, 200)
                        self.assertEqual(w27.without_waiting(w27.recorded(self.out, label, key)),
                                         w27.without_waiting(body))
            finally:
                live.close()

    def test_before_and_after_are_the_right_snapshots(self):
        self.assertEqual(self.code, 0, self.stderr[-2000:])
        rd = self.fx["rd_run"]
        key = "GET /api/review/%s/case" % rd
        self.assertIsNone(w27.recorded(self.out, "before", key)["human_decision"])
        decision = w27.recorded(self.out, "after", key)["human_decision"]
        self.assertEqual((decision["decision"], decision["amount_sgd"]), ("approve", 55.16))
        before_queue = [c["run_id"] for c in w27.recorded(self.out, "before", "GET /api/review/queue")["cases"]]
        after_queue = [c["run_id"] for c in w27.recorded(self.out, "after", "GET /api/review/queue")["cases"]]
        self.assertEqual((before_queue, after_queue), ([rd], []))

    def test_ui_copied_byte_identical_except_one_shim_line_after_head(self):
        self.assertEqual(self.code, 0, self.stderr[-2000:])
        sources = [p for p in sorted(w27.UI_DIR.rglob("*")) if p.is_file()]
        self.assertTrue(any(p.suffix == ".html" for p in sources))
        for src in sources:
            rel = src.relative_to(w27.UI_DIR).as_posix()
            with self.subTest(file=rel):
                copied = (self.out / rel).read_bytes()
                original = src.read_bytes()
                if src.suffix != ".html":
                    self.assertEqual(copied, original)
                    continue
                old = original.decode("utf-8").splitlines(keepends=True)
                new = copied.decode("utf-8").splitlines(keepends=True)
                self.assertEqual(len(new), len(old) + 1, "exactly one added line")
                head = next(i for i, line in enumerate(old) if line.strip() == "<head>")
                self.assertEqual(new[:head + 1], old[:head + 1])
                self.assertEqual(new[head + 1].strip(), w27.SHIM_TAG)
                self.assertTrue(new[head + 1].endswith("\n"))
                self.assertEqual(new[head + 2:], old[head + 1:])
                self.assertEqual(copied.decode("utf-8").count("replay-shim.js"), 1)

    def test_no_stray_files_in_the_output(self):
        self.assertEqual(self.code, 0, self.stderr[-2000:])
        ui = {p.relative_to(w27.UI_DIR).as_posix() for p in w27.UI_DIR.rglob("*") if p.is_file()}
        data = set()
        for label in w27.LABELS:
            data.add("replay/data/%s/manifest.json" % label)
            data.update("replay/data/%s/%s" % (label, name) for name in w27.manifest(self.out, label).values())
        expected = ui | data | {"replay/index.html", "replay/replay-shim.js"}
        self.assertEqual(sorted(set(w27.files(self.out)) ^ expected), [])

    def test_landing_page_title_and_four_steps(self):
        self.assertEqual(self.code, 0, self.stderr[-2000:])
        html = (self.out / "replay" / "index.html").read_text(encoding="utf-8")
        page = _Landing()
        page.feed(html)
        self.assertEqual(page.title.strip(), w27.LANDING_TITLE)
        self.assertEqual(len(page.lists), 1, "one numbered list of steps")
        steps = page.lists[0]
        self.assertEqual(len(steps), 5)
        expected = [(href % {"rd": self.fx["rd_run"], "ns": self.fx["ns_dispute"],
                             "rd_dispute": self.fx["rd_dispute"]}, text)
                    for text, href in w27.LANDING_STEPS]
        actual = []
        for item in steps:
            self.assertEqual(len(item), 1, "one link per step")
            actual.append((item[0][0], " ".join(item[0][1].split())))
        self.assertEqual(actual, expected)
        self.assertIn(w27.RECORDED_ON, html)
        self.assertNotIn("{{", html)

    def test_shim_placeholders_are_filled(self):
        self.assertEqual(self.code, 0, self.stderr[-2000:])
        shim = (self.out / "replay" / "replay-shim.js").read_text(encoding="utf-8")
        self.assertNotIn("{{", shim)
        self.assertNotIn("}}", shim)

    def test_inputs_are_never_modified(self):
        self.assertEqual(self.code, 0, self.stderr[-2000:])
        self.assertEqual(self.inputs_after, self.inputs_before)


class ExportRefusals(unittest.TestCase):
    """Every refusal exits 2 with an export_replay: line and leaves nothing in --out."""

    def assertRefused(self, code, stderr, out):
        self.assertEqual(code, 2, stderr[-2000:])
        self.assertTrue(w27.refusal_lines(stderr), "no export_replay: line on stderr")
        self.assertTrue(w27.is_empty_or_absent(out), w27.files(out) if Path(out).exists() else out)

    def test_mock_runs_refused_without_allow_mock(self):
        fx = w27.fixture()
        hashes = {label: w27.tree(fx[label]) for label in w27.LABELS}
        out = _out_dir()
        code, _stdout, stderr = w27.run_cli(w27.export_args(fx, out, allow_mock=False))
        self.assertRefused(code, stderr, out)
        self.assertTrue(any(run in line for line in w27.refusal_lines(stderr) for run in fx["runs"]),
                        "the refusal must name the mock run")
        self.assertEqual({label: w27.tree(fx[label]) for label in w27.LABELS}, hashes)

    def test_mock_refusal_names_the_mock_run(self):
        # Only RD-0109 still says mock; NS-0202 is rewritten to the real provider.
        fx = w27.copy_fixture({w27.fixture()["ns_run"]: "tencent"})
        out = _out_dir()
        code, _stdout, stderr = w27.run_cli(w27.export_args(fx, out, allow_mock=False))
        self.assertRefused(code, stderr, out)
        lines = " ".join(w27.refusal_lines(stderr))
        self.assertIn(fx["rd_run"], lines)
        self.assertNotIn(fx["ns_run"], lines)

    def test_real_provider_runs_export_without_allow_mock(self):
        fx = w27.copy_fixture({run: "tencent" for run in w27.fixture()["runs"]})
        out = _out_dir()
        code, _stdout, stderr = w27.run_cli(w27.export_args(fx, out, allow_mock=False))
        self.assertEqual(code, 0, stderr[-2000:])
        self.assertTrue((out / "replay" / "data" / "after" / "manifest.json").is_file())

    def test_recorded_on_must_be_an_iso_date(self):
        fx = w27.fixture()
        for bad in ("2026-02-30", "2026-10-6", "20261006", "06-10-2026", "2026/10/06", "",
                    "2026-10-06T00:00", " 2026-10-06"):
            with self.subTest(recorded_on=bad):
                out = _out_dir()
                code, _stdout, stderr = w27.run_cli(w27.export_args(fx, out, recorded_on=bad))
                self.assertRefused(code, stderr, out)

    def test_non_empty_out_refused_and_left_alone(self):
        fx = w27.fixture()
        out = _out_dir()
        out.mkdir(parents=True)
        (out / "keep.txt").write_bytes(b"operator file\n")
        code, _stdout, stderr = w27.run_cli(w27.export_args(fx, out))
        self.assertEqual(code, 2, stderr[-2000:])
        self.assertTrue(w27.refusal_lines(stderr))
        self.assertEqual(w27.files(out), ["keep.txt"])
        self.assertEqual((out / "keep.txt").read_bytes(), b"operator file\n")

    def test_existing_empty_out_is_accepted(self):
        fx = w27.fixture()
        out = _out_dir()
        out.mkdir(parents=True)
        code, _stdout, stderr = w27.run_cli(w27.export_args(fx, out))
        self.assertEqual(code, 0, stderr[-2000:])
        self.assertTrue((out / "replay" / "index.html").is_file())

    def test_export_needs_exactly_one_rd0109_run(self):
        # HAND-MADE SHAPE: the NS-0202 run alone, so the landing page has no run to link.
        fx = dict(w27.fixture())
        root = w27.scratch_dir()
        for label in w27.LABELS:
            shutil.copytree(Path(fx[label]) / fx["ns_run"], root / label / fx["ns_run"])
            fx[label] = root / label
        out = _out_dir()
        code, _stdout, stderr = w27.run_cli(w27.export_args(fx, out))
        self.assertRefused(code, stderr, out)


class SecretScan(unittest.TestCase):
    """Values of length >= 8 from --secrets-file (KEY=VALUE, read like app.config.load_env_file)
    found in ANY output file refuse the export; the message names the file, never the value."""

    @classmethod
    def setUpClass(cls):
        cls.clean = w27.mock_export()

    def _holders(self, value):
        out = self.clean["out"]
        return [rel for rel in w27.files(out) if value.encode("utf-8") in (out / rel).read_bytes()]

    def _export_with(self, lines):
        secrets = w27.scratch_dir() / "secrets.env"
        secrets.write_text("\n".join(lines) + "\n", encoding="utf-8")
        out = _out_dir()
        code, stdout, stderr = w27.run_cli(w27.export_args(w27.fixture(), out, secrets=secrets))
        return out, code, stdout, stderr

    def _assert_refused_naming(self, value, holders, lines):
        self.assertEqual(self.clean["code"], 0, self.clean["stderr"][-2000:])
        self.assertTrue(holders, "test premise: %r must occur in a clean export" % value)
        out, code, stdout, stderr = self._export_with(lines)
        self.assertEqual(code, 2, stderr[-2000:])
        self.assertTrue(w27.is_empty_or_absent(out))
        named = " ".join(w27.refusal_lines(stderr))
        self.assertTrue(any(rel in named for rel in holders), (named, holders))
        self.assertNotIn(value, stdout + stderr)

    def test_secret_in_a_recorded_body(self):
        holders = self._holders(w27.REVIEW_REASON)
        self.assertTrue(all(rel.startswith("replay/data/after/") for rel in holders), holders)
        self._assert_refused_naming(w27.REVIEW_REASON, holders,
                                    ["# a comment line", "EMPTY=", "REVIEW=%s" % w27.REVIEW_REASON])

    def test_secret_in_a_copied_ui_file(self):
        value = "Review request failed."
        self._assert_refused_naming(value, self._holders(value), ["UI_TEXT=%s" % value])

    def test_secret_in_the_landing_page(self):
        value = w27.LANDING_TITLE
        holders = self._holders(value)
        self.assertEqual(holders, ["replay/index.html"])
        self._assert_refused_naming(value, holders, ['TITLE="%s"' % value])

    def test_values_shorter_than_eight_are_ignored(self):
        self.assertEqual(self.clean["code"], 0, self.clean["stderr"][-2000:])
        self.assertTrue(self._holders("Decisio"), "test premise: the 7-character value occurs")
        out, code, _stdout, stderr = self._export_with(["SHORT=Decisio"])
        self.assertEqual(code, 0, stderr[-2000:])
        self.assertTrue((out / "replay" / "index.html").is_file())

    def test_value_of_exactly_eight_is_checked(self):
        self._assert_refused_naming("Decision", self._holders("Decision"), ["EIGHT=Decision"])


class ExportServerContract(unittest.TestCase):
    """The exporter drives the real app.server: temp copy, port 0, a model client that refuses."""

    @classmethod
    def setUpClass(cls):
        cls.fx = w27.fixture()

    def test_real_server_on_a_temp_copy_with_a_refusing_model(self):
        from app.llm.base import LLMRequest

        out = _out_dir()
        code, _stdout, stderr, calls = w27.run_inprocess(w27.export_args(self.fx, out))
        self.assertEqual(code, 0, stderr[-2000:])
        self.assertEqual(len(calls), 2, "one server per snapshot")
        inputs = [Path(self.fx[label]).resolve() for label in w27.LABELS]
        for call in calls:
            self.assertEqual(call["port"], 0)
            self.assertIsNotNone(call["out_dir"], "the server must be given the temp copy")
            served = Path(call["out_dir"]).resolve()
            for folder in inputs:
                self.assertNotEqual(served, folder)
                self.assertFalse(served.is_relative_to(folder))
            self.assertIsNotNone(call["llm"])
            for agent in ("rider_advocate", "driver_advocate", "judge"):
                with self.assertRaises(Exception):
                    call["llm"].complete(LLMRequest(agent=agent, system_prompt="s", user_prompt="u"))

    def _required_targets(self):
        rd = self.fx["rd_run"]
        return ["/api/review/queue", "/api/review/overrides", "/api/demo/rider", "/api/demo/driver",
                "/api/trips?category=other", "/api/trips?category=route_deviation",
                "/api/disputes/%s" % self.fx["rd_dispute"], "/api/review/%s/case" % rd,
                "/api/review/%s/payloads/0001-run-started.json" % rd]

    def test_a_required_url_that_is_not_200_refuses_naming_it(self):
        for status in (404, 500):
            for target in self._required_targets():
                with self.subTest(target=target, status=status):
                    out = _out_dir()
                    code, _stdout, stderr, _calls = w27.run_inprocess(
                        w27.export_args(self.fx, out),
                        override=lambda t, target=target, status=status: (status, {"error": "x"}) if t == target else None,
                    )
                    self.assertEqual(code, 2, stderr[-2000:])
                    self.assertTrue(any(target in line for line in w27.refusal_lines(stderr)), stderr[-2000:])
                    self.assertTrue(w27.is_empty_or_absent(out))

    def test_optional_prompts_404_is_omitted(self):
        out = _out_dir()
        code, _stdout, stderr, _calls = w27.run_inprocess(
            w27.export_args(self.fx, out),
            override=lambda t: (404, {"error": "not found"}) if t.endswith("/prompts") else None,
        )
        self.assertEqual(code, 0, stderr[-2000:])
        for label in w27.LABELS:
            self.assertEqual([k for k in w27.manifest(out, label) if k.endswith("/prompts")], [])

    def test_optional_prompts_other_failure_refuses_naming_it(self):
        target = "/api/review/%s/prompts" % self.fx["ns_run"]
        out = _out_dir()
        code, _stdout, stderr, _calls = w27.run_inprocess(
            w27.export_args(self.fx, out),
            override=lambda t: (500, {"error": "internal error"}) if t == target else
            ((404, {"error": "not found"}) if t.endswith("/prompts") else None),
        )
        self.assertEqual(code, 2, stderr[-2000:])
        self.assertTrue(any(target in line for line in w27.refusal_lines(stderr)), stderr[-2000:])
        self.assertTrue(w27.is_empty_or_absent(out))

    def test_optional_prompts_200_is_recorded(self):
        def answer(t):
            match = re.fullmatch(r"/api/review/([^/]+)/prompts", t)
            if match:
                return 200, {"run_id": match.group(1), "agents": [{"agent": "judge"}]}
            return None

        out = _out_dir()
        code, _stdout, stderr, _calls = w27.run_inprocess(w27.export_args(self.fx, out), override=answer)
        self.assertEqual(code, 0, stderr[-2000:])
        for label in w27.LABELS:
            for run in self.fx["runs"]:
                key = "GET /api/review/%s/prompts" % run
                self.assertEqual(w27.recorded(out, label, key), {"run_id": run, "agents": [{"agent": "judge"}]})


class ReplayDoc(unittest.TestCase):
    def test_docs_replay_explains_recording_day(self):
        path = w27.REPO / "docs" / "replay.md"
        self.assertTrue(path.is_file(), "docs/replay.md is a W27 deliverable")
        text = path.read_text(encoding="utf-8")
        for needle in ("tools/export_replay.py", "--before", "--after", "--recorded-on", "--out",
                       "--allow-mock", "--secrets-file", "replay/index.html", "NS-0202", "RD-0109"):
            self.assertIn(needle, text)
        self.assertRegex(text, r"(?im)^#+ .*recording day")


if __name__ == "__main__":
    unittest.main()
