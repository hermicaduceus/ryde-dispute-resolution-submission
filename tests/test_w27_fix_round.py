"""W27 fix round: the review findings on the static replay exporter, pinned RED-first.

M1  the mock refusal fails open on an unreadable provider and reads only the first run.started;
M3  --out inside an input (--before, --after, the repo's ui/ or tools/replay/), and
    --before == --after, are accepted;
m1  the landing page's step texts are fixed claims instead of the saved runs' facts;
M2  the secret scan matches raw UTF-8 only, so an escaped secret ships;
m2  the shim lets the bare '/api' path reach the network.

Contract: docs/build-briefs/w27-fix-brief.md. Every hand-made shape below is a copy of the fixture with one
labelled edit; the shared fixture itself is never touched.
"""

from __future__ import annotations

import html
import json
import os
import re
import shutil
import subprocess
import unittest
import urllib.parse
import uuid
from html.parser import HTMLParser
from pathlib import Path
from unittest import mock

from tests import w27_replay_support as w27

UNREADABLE = ("export_replay: the model provider of run(s) %s could not be read; "
              "pass --allow-mock to export a test replay")
MOCK_LINE = ("export_replay: run(s) %s were recorded with the mock model; "
             "pass --allow-mock to export a test replay")
SECRET_LINE = "export_replay: refusing to publish: a value from --secrets-file occurs in "
RUN_STARTED_PAYLOAD = "0001-run-started.json"
STEP_HREFS = ["/party/status.html?snapshot=after&dispute=%(ns)s",
              "/party/status.html?snapshot=before&dispute=%(rd_dispute)s",
              "/index.html?snapshot=before&run=%(rd)s",
              "/index.html?snapshot=after&run=%(rd)s", "/party/status.html?snapshot=after"]
STEP_4 = "What the rider sees"
SHIM_DRIVER = w27.REPO / "tests" / "browser" / "w27_replay_shim.cjs"


# ------------------------------------------------------------------ helpers


def _runs():
    return w27.fixture()["runs"]


def _tencent():
    """HAND-MADE SHAPE (support's copy_fixture): every run.started payload names tencent."""
    return w27.copy_fixture({run: "tencent" for run in _runs()})


def _run_dir(fx, label, which):
    return Path(fx[label]) / fx[which + "_run"]


def _edit_json(path, edit):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    result = edit(data)
    Path(path).write_text(json.dumps(data if result is None else result, indent=2) + "\n", encoding="utf-8")


def _edit_run_started(run_dir, edit):
    """edit(event) -> the new event dict, or None to drop it; other lines are kept verbatim."""
    path = Path(run_dir) / "events.jsonl"
    out, seen = [], 0
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            out.append(line)
            continue
        if isinstance(event, dict) and event.get("type") == "run.started":
            seen += 1
            new = edit(dict(event))
            if new is not None:
                out.append(json.dumps(new))
            continue
        out.append(line)
    if not seen:
        raise AssertionError("test premise: %s has no run.started event" % path)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def _add_run_started(run_dir, payload_ref, payload=None):
    """Append a second run.started event (a copy of the first), optionally writing its payload."""
    run_dir = Path(run_dir)
    path = run_dir / "events.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    first = next((json.loads(l) for l in lines if '"run.started"' in l), None)
    if first is None:
        raise AssertionError("test premise: %s has no run.started event" % path)
    second = dict(first)
    second["payload_ref"] = payload_ref
    lines.append(json.dumps(second))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if payload is not None:
        (run_dir / payload_ref).write_text(json.dumps(payload), encoding="utf-8")


def _args(before, after, out, *, allow_mock, secrets=None):
    args = ["--before", str(before), "--after", str(after), "--recorded-on", w27.RECORDED_ON,
            "--out", str(out)]
    if allow_mock:
        args.append("--allow-mock")
    args += ["--secrets-file", str(secrets if secrets is not None else w27.scratch_dir() / "no-such.env")]
    return args


def _export(fx, *, allow_mock=False, out=None, before=None, after=None, secrets=None):
    out = Path(out) if out is not None else w27.scratch_dir() / "site"
    code, stdout, stderr = w27.run_cli(_args(before or fx["before"], after or fx["after"], out,
                                             allow_mock=allow_mock, secrets=secrets))
    return {"code": code, "stdout": stdout, "stderr": stderr, "out": out}


def _read(path):
    path = Path(path)
    if not path.is_file():
        raise AssertionError("%s was not written" % path)
    return path.read_text(encoding="utf-8")


class _Steps(HTMLParser):
    """Every <ol> as a list of <li>, each a list of [href, text] links (text unescaped)."""

    def __init__(self):
        super().__init__()
        self.lists, self._li, self._a, self._depth = [], None, None, 0

    def handle_starttag(self, tag, attrs):
        if tag == "ol":
            self._depth += 1
            self.lists.append([])
        elif tag == "li" and self._depth:
            self._li = []
            self.lists[-1].append(self._li)
        elif tag == "a" and self._li is not None:
            self._a = [dict(attrs).get("href"), ""]
            self._li.append(self._a)

    def handle_endtag(self, tag):
        if tag == "ol":
            self._depth -= 1
        elif tag == "li":
            self._li = None
        elif tag == "a":
            self._a = None

    def handle_data(self, data):
        if self._a is not None:
            self._a[1] += data


def _steps(out):
    page = _Steps()
    page.feed(_read(Path(out) / "replay" / "index.html"))
    if len(page.lists) != 1:
        raise AssertionError("expected one <ol> on the landing page, found %d" % len(page.lists))
    steps = []
    for item in page.lists[0]:
        if len(item) != 1:
            raise AssertionError("expected one link per step, got %r" % (item,))
        steps.append((item[0][0], " ".join(item[0][1].split())))
    return steps


def _expected_steps(fx, texts, waiting=None):
    hrefs = [href % {"rd": fx["rd_run"], "ns": fx["ns_dispute"], "rd_dispute": fx["rd_dispute"]}
             if "%(" in href else href for href in STEP_HREFS]
    if waiting is None:
        waiting = w27.WAITING_STEP
    return list(zip(hrefs, [texts[0], waiting, texts[1], texts[2]] + [STEP_4]))


class _Raw:
    """A body the stubbed server sends verbatim, so a test can plant exact bytes."""

    def __init__(self, data):
        self.data = data


def _export_planting(target, data, secrets_lines):
    """In-process export (support's run_inprocess) with `target` answered by the bytes `data`."""
    from app import server

    real_send = server.RydeRequestHandler._send_json

    def send(self, status, payload):
        if isinstance(payload, _Raw):
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload.data)))
            self.end_headers()
            self.wfile.write(payload.data)
            return None
        return real_send(self, status, payload)

    secrets = w27.scratch_dir() / "secrets.env"
    secrets.write_text("\n".join(secrets_lines) + "\n", encoding="utf-8")
    out = w27.scratch_dir() / "site"
    fx = w27.fixture()
    with mock.patch.object(server.RydeRequestHandler, "_send_json", send):
        code, stdout, stderr, _calls = w27.run_inprocess(
            _args(fx["before"], fx["after"], out, allow_mock=True, secrets=secrets),
            override=lambda t: (200, _Raw(data)) if t == target else None,
        )
    return {"code": code, "stdout": stdout, "stderr": stderr, "out": out}


def _drive(site, scenarios):
    """The Node shim driver's report, or {'harness_error': ...}; never raises."""
    node = shutil.which("node")
    if not node:
        return {"harness_error": "node is required for the W27 shim tests"}
    spec = w27.scratch_dir() / "scenarios.json"
    spec.write_text(json.dumps(scenarios), encoding="utf-8")
    try:
        result = subprocess.run([node, str(SHIM_DRIVER), str(site), str(spec)], capture_output=True,
                                text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return {"harness_error": "driver timed out"}
    if result.returncode != 0:
        return {"harness_error": result.stderr[-3000:]}
    return json.loads(result.stdout)


class _Base(unittest.TestCase):

    def snapshot_trees(self, fx):
        return {label: w27.tree(fx[label]) for label in w27.LABELS}

    def assertRefusedWith(self, result, line, fx=None, trees=None):
        """Exit 2, exactly the one expected export_replay: line, --out empty, inputs unchanged."""
        self.assertEqual(result["code"], 2, result["stderr"][-2000:])
        self.assertEqual(w27.refusal_lines(result["stderr"]), [line])
        self.assertTrue(w27.is_empty_or_absent(result["out"]), result["out"])
        if fx is not None:
            self.assertEqual(self.snapshot_trees(fx), trees)

    def assertRefused(self, result):
        self.assertEqual(result["code"], 2, result["stderr"][-2000:])
        self.assertEqual(len(w27.refusal_lines(result["stderr"])), 1, result["stderr"][-2000:])
        self.assertTrue(w27.is_empty_or_absent(result["out"]),
                        w27.files(result["out"]) if Path(result["out"]).exists() else result["out"])

    def assertExported(self, result):
        self.assertEqual(result["code"], 0, result["stderr"][-2000:])
        self.assertTrue((Path(result["out"]) / "replay" / "index.html").is_file())

    def shim_text(self, result):
        return _read(Path(result["out"]) / "replay" / "replay-shim.js")


# ------------------------------------------------------------------ M1: the provider gate


class ProviderGate(_Base):
    """Without --allow-mock: every run.started of every replayed run in both snapshots is read;
    a mock one refuses (existing line), an unreadable one refuses (new line)."""

    def _unreadable(self, label, which, edit):
        fx = _tencent()
        edit(fx, _run_dir(fx, label, which))
        trees = self.snapshot_trees(fx)
        result = _export(fx)
        self.assertRefusedWith(result, UNREADABLE % fx[which + "_run"], fx, trees)

    def test_no_events_file(self):
        self._unreadable("after", "rd", lambda fx, run: (run / "events.jsonl").unlink())

    def test_events_file_is_a_directory(self):
        def edit(fx, run):
            (run / "events.jsonl").unlink()
            (run / "events.jsonl").mkdir()
        self._unreadable("before", "ns", edit)

    def test_no_run_started_event(self):
        self._unreadable("before", "rd", lambda fx, run: _edit_run_started(run, lambda e: None))

    def test_run_started_line_is_invalid_json(self):
        # Invalid lines are skipped as before, so the run is left with no readable run.started.
        def edit(fx, run):
            path = run / "events.jsonl"
            lines = path.read_text(encoding="utf-8").splitlines()
            lines = [l[:-3] if '"run.started"' in l else l for l in lines]
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        self._unreadable("after", "ns", edit)

    def test_payload_ref_missing(self):
        def drop(event):
            event.pop("payload_ref", None)
            return event
        self._unreadable("before", "ns", lambda fx, run: _edit_run_started(run, drop))

    def test_payload_ref_not_a_string(self):
        self._unreadable("after", "rd", lambda fx, run: _edit_run_started(
            run, lambda e: dict(e, payload_ref=7)))

    def test_payload_ref_empty(self):
        self._unreadable("before", "rd", lambda fx, run: _edit_run_started(
            run, lambda e: dict(e, payload_ref="")))

    def test_payload_ref_escapes_the_run_dir_relative(self):
        # Points at the OTHER run's readable tencent payload: readable, but not this run's.
        def edit(fx, run):
            ref = "../%s/payloads/%s" % (fx["rd_run"], RUN_STARTED_PAYLOAD)
            self.assertTrue((run / ref).is_file(), "test premise: the escaping target exists")
            _edit_run_started(run, lambda e: dict(e, payload_ref=ref))
        self._unreadable("after", "ns", edit)

    def test_payload_ref_absolute_outside(self):
        def edit(fx, run):
            outside = Path(fx["root"]) / "outside-run-started.json"
            outside.write_text(json.dumps({"llm_provider": "tencent"}), encoding="utf-8")
            _edit_run_started(run, lambda e: dict(e, payload_ref=str(outside)))
        self._unreadable("before", "ns", edit)

    def test_payload_ref_symlink_escapes_the_run_dir(self):
        def edit(fx, run):
            outside = Path(fx["root"]) / "outside-run-started.json"
            outside.write_text(json.dumps({"llm_provider": "tencent"}), encoding="utf-8")
            link = run / "payloads" / "0099-linked.json"
            os.symlink(str(outside), str(link))
            _edit_run_started(run, lambda e: dict(e, payload_ref="payloads/0099-linked.json"))
        self._unreadable("after", "rd", edit)

    def test_payload_file_missing(self):
        self._unreadable("after", "rd", lambda fx, run: _edit_run_started(
            run, lambda e: dict(e, payload_ref="payloads/9999-missing.json")))

    def test_payload_is_not_an_object(self):
        self._unreadable("before", "rd", lambda fx, run: (run / "payloads" / RUN_STARTED_PAYLOAD)
                         .write_text("[\"tencent\"]\n", encoding="utf-8"))

    def test_payload_is_not_json(self):
        self._unreadable("after", "ns", lambda fx, run: (run / "payloads" / RUN_STARTED_PAYLOAD)
                         .write_text("{\"llm_provider\": \"tencent\"\n", encoding="utf-8"))

    def test_llm_provider_missing(self):
        self._unreadable("before", "ns", lambda fx, run: _edit_json(
            run / "payloads" / RUN_STARTED_PAYLOAD, lambda d: d.pop("llm_provider")))

    def test_llm_provider_not_a_string(self):
        for value in (7, None, ["tencent"]):
            with self.subTest(llm_provider=value):
                self._unreadable("after", "rd", lambda fx, run, value=value: _edit_json(
                    run / "payloads" / RUN_STARTED_PAYLOAD, lambda d: d.update(llm_provider=value)))

    def test_llm_provider_empty(self):
        self._unreadable("before", "rd", lambda fx, run: _edit_json(
            run / "payloads" / RUN_STARTED_PAYLOAD, lambda d: d.update(llm_provider="")))

    def test_a_later_run_started_that_cannot_be_read(self):
        # The first run.started says tencent; a second one points at a missing payload.
        self._unreadable("after", "rd", lambda fx, run: _add_run_started(run, "payloads/9998-gone.json"))

    def test_two_unreadable_runs_are_named_sorted(self):
        fx = _tencent()
        (_run_dir(fx, "before", "rd") / "events.jsonl").unlink()
        (_run_dir(fx, "after", "ns") / "events.jsonl").unlink()
        trees = self.snapshot_trees(fx)
        self.assertRefusedWith(_export(fx), UNREADABLE % ", ".join(sorted(_runs())), fx, trees)

    def test_a_later_run_started_saying_mock_refuses_naming_the_run(self):
        fx = _tencent()
        _add_run_started(_run_dir(fx, "after", "ns"), "payloads/0098-run-started-again.json",
                         {"llm_provider": "mock"})
        trees = self.snapshot_trees(fx)
        self.assertRefusedWith(_export(fx), MOCK_LINE % fx["ns_run"], fx, trees)

    def test_mock_in_the_after_snapshot_only(self):
        fx = _tencent()
        _edit_json(_run_dir(fx, "after", "rd") / "payloads" / RUN_STARTED_PAYLOAD,
                   lambda d: d.update(llm_provider="mock"))
        trees = self.snapshot_trees(fx)
        self.assertRefusedWith(_export(fx), MOCK_LINE % fx["rd_run"], fx, trees)

    def test_allow_mock_exports_an_unreadable_provider_as_a_test_replay(self):
        fx = _tencent()
        (_run_dir(fx, "before", "rd") / "events.jsonl").unlink()
        _edit_json(_run_dir(fx, "after", "ns") / "payloads" / RUN_STARTED_PAYLOAD,
                   lambda d: d.pop("llm_provider"))
        result = _export(fx, allow_mock=True)
        self.assertExported(result)
        self.assertIn('"%s"' % w27.MOCK_PREFIX, self.shim_text(result))

    def test_tencent_runs_with_a_second_tencent_run_started_still_export(self):
        fx = _tencent()
        for label in w27.LABELS:
            _add_run_started(_run_dir(fx, label, "rd"), "payloads/0097-run-started-again.json",
                             {"llm_provider": "tencent"})
        result = _export(fx)
        self.assertExported(result)
        self.assertNotIn(w27.MOCK_PREFIX, self.shim_text(result))


# ------------------------------------------------------------------ M3: path refusals


class PathRefusals(_Base):
    """--out may not equal or sit inside --before, --after, the repo's ui/ or tools/replay/;
    --before and --after may not resolve to the same folder. Refused before anything is written."""

    def _probe(self, parent):
        """A fresh, absent folder name under a repo directory, removed again whatever happens."""
        probe = Path(parent) / ("w27-fix-probe-%s" % uuid.uuid4().hex[:12])
        self.assertFalse(probe.exists())
        self.addCleanup(shutil.rmtree, str(probe), True)
        return probe

    def test_out_equals_before(self):
        fx = w27.copy_fixture()
        trees = self.snapshot_trees(fx)
        result = _export(fx, allow_mock=True, out=fx["before"])
        self.assertEqual(result["code"], 2, result["stderr"][-2000:])
        self.assertEqual(len(w27.refusal_lines(result["stderr"])), 1)
        self.assertEqual(self.snapshot_trees(fx), trees)

    def test_out_inside_before(self):
        fx = w27.copy_fixture()
        trees = self.snapshot_trees(fx)
        out = Path(fx["before"]) / "site"
        result = _export(fx, allow_mock=True, out=out)
        self.assertRefused(result)
        self.assertFalse(out.exists())
        self.assertEqual(self.snapshot_trees(fx), trees)

    def test_out_inside_after_through_a_symlink(self):
        fx = w27.copy_fixture()
        alias = Path(fx["root"]) / "after-alias"
        os.symlink(str(fx["after"]), str(alias))
        trees = self.snapshot_trees(fx)
        out = alias / "nested" / "site"
        result = _export(fx, allow_mock=True, out=out)
        self.assertRefused(result)
        self.assertFalse((Path(fx["after"]) / "nested").exists())
        self.assertEqual(self.snapshot_trees(fx), trees)

    def test_out_inside_the_repo_ui_folder(self):
        fx = w27.fixture()
        probe = self._probe(w27.UI_DIR)
        ui_before = w27.tree(w27.UI_DIR)
        # Relative to the exporter's cwd (the repo root), so only a resolved path catches it.
        result = _export(fx, allow_mock=True, out=Path("ui") / probe.name / "site")
        result["out"] = probe / "site"
        self.assertRefused(result)
        self.assertFalse(probe.exists(), "nothing may be created inside ui/")
        self.assertEqual(w27.tree(w27.UI_DIR), ui_before)

    def test_out_inside_the_repo_tools_replay_folder(self):
        fx = w27.fixture()
        replay = w27.REPO / "tools" / "replay"
        probe = self._probe(replay)
        replay_before = w27.tree(replay)
        # Spelled through app/.., so only a resolved path shows it is inside tools/replay/.
        out = w27.REPO / "app" / ".." / "tools" / "replay" / probe.name
        result = _export(fx, allow_mock=True, out=out)
        result["out"] = probe
        self.assertRefused(result)
        self.assertFalse(probe.exists(), "nothing may be created inside tools/replay/")
        self.assertEqual(w27.tree(replay), replay_before)

    def test_before_equals_after(self):
        fx = w27.copy_fixture()
        trees = self.snapshot_trees(fx)
        result = _export(fx, allow_mock=True, before=fx["before"], after=fx["before"])
        self.assertRefused(result)
        self.assertEqual(self.snapshot_trees(fx), trees)

    def test_before_equals_after_through_a_symlink(self):
        fx = w27.copy_fixture()
        alias = Path(fx["root"]) / "before-alias"
        os.symlink(str(fx["before"]), str(alias))
        trees = self.snapshot_trees(fx)
        result = _export(fx, allow_mock=True, before=fx["before"], after=alias)
        self.assertRefused(result)
        self.assertEqual(self.snapshot_trees(fx), trees)

    def test_a_missing_out_beside_the_inputs_still_exports(self):
        # A sibling whose NAME starts with the input's name is not inside it.
        fx = w27.copy_fixture()
        trees = self.snapshot_trees(fx)
        result = _export(fx, allow_mock=True, out=Path(fx["root"]) / (Path(fx["before"]).name + "-site"))
        self.assertExported(result)
        self.assertEqual(self.snapshot_trees(fx), trees)


# ------------------------------------------------------------------ m1: landing steps from data


def _ns_case(fx, label):
    return _run_dir(fx, label, "ns") / "case_file.json"


def _rd_case(fx, label):
    return _run_dir(fx, label, "rd") / "case_file.json"


def _set_decision(fx, label, which, record):
    """HAND-MADE SHAPE: write a human_decision.json the server's load_decision accepts."""
    run = _run_dir(fx, label, which)
    base = {"schema_version": "1.0", "run_id": run.name, "dispute_id": "PF-HANDMADE",
            "reviewer": w27.REVIEWER, "reason": "hand-made decision", "proposed": None,
            "decided_at": "2026-10-06T00:00:00+00:00"}
    base.update(record)
    (run / "human_decision.json").write_text(json.dumps(base, indent=2) + "\n", encoding="utf-8")


def _resolution(path, **changes):
    def edit(case):
        case["resolution"].update(changes)
    _edit_json(path, edit)


def _ruling(path, field, **changes):
    def edit(case):
        if not isinstance(case["resolution"].get(field), dict):
            raise AssertionError("test premise: %s has no resolution.%s object" % (path, field))
        case["resolution"][field].update(changes)
    _edit_json(path, edit)


class LandingSteps(_Base):
    """Steps 1-3 state what the saved runs recorded; step 4, the links and the title do not move."""

    def assertSteps(self, result, fx, texts, waiting=None):
        self.assertExported(result)
        self.assertEqual(_steps(result["out"]), _expected_steps(fx, texts, waiting=waiting))

    def test_the_mock_fixture(self):
        export = w27.mock_export()
        self.assertEqual(export["code"], 0, export["stderr"][-2000:])
        self.assertEqual(_steps(export["out"]), _expected_steps(export["fx"], [
            "A no-show case the AI decided alone: no action",
            "A detour case the AI held for a human: it proposed refund SGD 55.16",
            "The human approved: refund SGD 55.16",
        ]))

    def test_change_decision_and_an_undelivered_no_show_and_a_ruled_detour(self):
        # HAND-MADE SHAPE: the human changed the proposal to SGD 40; NS-0202 was not delivered;
        # RD-0109's before snapshot reads ruled.
        fx = w27.copy_fixture()
        _set_decision(fx, "after", "rd", {"decision": "change", "action": "refund", "amount_sgd": 40})
        _resolution(_ns_case(fx, "after"), delivered_to_parties=False)
        _resolution(_rd_case(fx, "before"), outcome="ruled")
        self.assertSteps(_export(fx, allow_mock=True), fx, [
            "A no-show case: ruled",
            "A detour case: ruled",
            "The human changed it to: refund SGD 40.00",
        ], waiting="The rider's view of the detour case: decided")

    def test_an_approval_states_the_decision_record_not_the_proposal(self):
        # HAND-MADE SHAPE (planner, fix-round tightening 2026-10-07): the approval's own amount
        # differs from the held proposal (SGD 55.16), so step 3 must read the decision record.
        # On genuine data the two are equal, which is why a proposal-sourced phrase survived.
        fx = w27.copy_fixture()
        _set_decision(fx, "after", "rd", {"decision": "approve", "action": "refund", "amount_sgd": 30})
        self.assertSteps(_export(fx, allow_mock=True), fx, [
            "A no-show case the AI decided alone: no action",
            "A detour case the AI held for a human: it proposed refund SGD 55.16",
            "The human approved: refund SGD 30.00",
        ])

    def test_reject_decision_and_a_withheld_no_show_and_a_decided_detour_before(self):
        # HAND-MADE SHAPE: the human rejected; NS-0202 reads withheld; RD-0109 already carries a
        # decision in the before snapshot.
        fx = w27.copy_fixture()
        _set_decision(fx, "after", "rd", {"decision": "reject", "action": "no action", "amount_sgd": 0.0})
        _resolution(_ns_case(fx, "after"), outcome="withheld")
        _set_decision(fx, "before", "rd", {"decision": "approve", "action": "refund", "amount_sgd": 55.16})
        self.assertSteps(_export(fx, allow_mock=True), fx, [
            "A no-show case: withheld",
            "A detour case: withheld",
            "The human rejected it: no action",
        ], waiting="The rider's view of the detour case: decided")

    def test_no_decision_recorded_and_a_no_show_with_a_human_decision(self):
        # HAND-MADE SHAPE: the after snapshot is a separate copy of before (no decision); NS-0202
        # carries a human decision record.
        fx = w27.copy_fixture()
        shutil.rmtree(fx["after"])
        shutil.copytree(fx["before"], fx["after"])
        _set_decision(fx, "after", "ns", {"decision": "approve", "action": "no action", "amount_sgd": 0.0})
        self.assertSteps(_export(fx, allow_mock=True), fx, [
            "A no-show case: ruled",
            "A detour case the AI held for a human: it proposed refund SGD 55.16",
            "No human decision was recorded",
        ])

    def test_a_refund_no_show_and_a_decision_the_server_ignores(self):
        # HAND-MADE SHAPE: NS-0202 ruled a SGD 6.6 refund (amount not already in two-decimal form);
        # RD-0109's decision record has a non-numeric amount, so the server shows no decision.
        fx = w27.copy_fixture()
        _ruling(_ns_case(fx, "after"), "ruling", action="refund", recommended_amount_sgd=6.6)
        _edit_json(_run_dir(fx, "after", "rd") / "human_decision.json",
                   lambda d: d.update(amount_sgd="abc"))
        self.assertSteps(_export(fx, allow_mock=True), fx, [
            "A no-show case the AI decided alone: refund SGD 6.60",
            "A detour case the AI held for a human: it proposed refund SGD 55.16",
            "No human decision was recorded",
        ])

    def test_actions_without_an_amount_and_a_change_to_no_action(self):
        # HAND-MADE SHAPE: NS-0202's ruling and RD-0109's held proposal carry no amount; the human
        # changed the proposal to no action.
        fx = w27.copy_fixture()
        _ruling(_ns_case(fx, "after"), "ruling", action="compensation", recommended_amount_sgd=None)
        _ruling(_rd_case(fx, "before"), "withheld_candidate", action="compensation",
                recommended_amount_sgd=None)
        _set_decision(fx, "after", "rd", {"decision": "change", "action": "no action", "amount_sgd": 0.0})
        self.assertSteps(_export(fx, allow_mock=True), fx, [
            "A no-show case the AI decided alone: compensation",
            "A detour case the AI held for a human: it proposed compensation",
            "The human changed it to: no action",
        ])

    def test_inserted_values_are_html_escaped(self):
        # HAND-MADE SHAPE: an action and an outcome carrying HTML-special characters.
        action, outcome = '<b>"R&D"</b>', "held & 'waiting'"
        fx = w27.copy_fixture()
        _ruling(_ns_case(fx, "after"), "ruling", action=action, recommended_amount_sgd=1)
        _resolution(_rd_case(fx, "before"), outcome=outcome)
        result = _export(fx, allow_mock=True)
        self.assertSteps(result, fx, [
            "A no-show case the AI decided alone: %s SGD 1.00" % action,
            "A detour case: %s" % outcome,
            "The human approved: refund SGD 55.16",
        ])
        page = _read(Path(result["out"]) / "replay" / "index.html")
        self.assertIn(html.escape(action), page)
        self.assertIn(html.escape(outcome), page)
        self.assertNotIn("<b>", page)

    def _ns_refused(self, edit):
        fx = w27.copy_fixture()
        edit(fx)
        self.assertRefused(_export(fx, allow_mock=True))

    def test_ns0202_missing_from_a_snapshot_is_refused(self):
        self._ns_refused(lambda fx: shutil.rmtree(_run_dir(fx, "before", "ns")))

    def test_two_ns0202_runs_in_a_snapshot_are_refused(self):
        self._ns_refused(lambda fx: shutil.copytree(_run_dir(fx, "after", "ns"),
                                                    Path(fx["after"]) / (fx["ns_run"] + "-copy")))

    def test_different_ns0202_runs_are_refused(self):
        self._ns_refused(lambda fx: os.rename(_run_dir(fx, "after", "ns"),
                                              Path(fx["after"]) / (fx["ns_run"] + "-renamed")))


# ------------------------------------------------------------------ M2: secret encodings


class SecretEncodings(_Base):
    """A secret refuses in every form it can ship in: raw, JSON-escaped (ASCII and not),
    HTML-escaped and percent-encoded. The message is the existing one and carries no form."""

    def assertSecretRefused(self, result, value, where):
        self.assertEqual(result["code"], 2, result["stderr"][-2000:])
        lines = w27.refusal_lines(result["stderr"])
        self.assertEqual(len(lines), 1, result["stderr"][-2000:])
        self.assertTrue(lines[0].startswith(SECRET_LINE), lines[0])
        self.assertRegex(lines[0][len(SECRET_LINE):], where)
        self.assertTrue(w27.is_empty_or_absent(result["out"]))
        forms = {value, json.dumps(value)[1:-1], json.dumps(value, ensure_ascii=False)[1:-1],
                 html.escape(value), urllib.parse.quote(value, safe="")}
        for form in forms:
            self.assertNotIn(form, result["stdout"] + result["stderr"])

    def _reason_export(self, value):
        """HAND-MADE SHAPE: RD-0109's recorded decision reason is the secret value."""
        fx = w27.copy_fixture()
        _edit_json(_run_dir(fx, "after", "rd") / "human_decision.json", lambda d: d.update(reason=value))
        secrets = Path(fx["root"]) / "secrets.env"
        secrets.write_text("KEY=%s\n" % value, encoding="utf-8")
        return _export(fx, allow_mock=True, secrets=secrets)

    def test_non_ascii_secret_in_a_recorded_body(self):
        self.assertSecretRefused(self._reason_export("cl\u00e9-secr\u00e8te-2026"), "cl\u00e9-secr\u00e8te-2026",
                                 r"^replay/data/after/\d{4}\.json$")

    def test_secret_with_a_double_quote_in_a_recorded_body(self):
        self.assertSecretRefused(self._reason_export('pass"word-2026'), 'pass"word-2026',
                                 r"^replay/data/after/\d{4}\.json$")

    def test_secret_with_a_backslash_in_a_recorded_body(self):
        self.assertSecretRefused(self._reason_export("back\\slash-2026"), "back\\slash-2026",
                                 r"^replay/data/after/\d{4}\.json$")

    def _planted(self, value, form):
        forms = [value, json.dumps(value)[1:-1], json.dumps(value, ensure_ascii=False)[1:-1],
                 html.escape(value), urllib.parse.quote(value, safe="")]
        self.assertIn(form, forms)
        self.assertEqual([f for f in set(forms) if f != form and f in form], [],
                         "test premise: the planted form holds no OTHER needle form")
        data = b'{"note": "' + form.encode("utf-8") + b'"}'
        return _export_planting("/api/demo/driver", data, ["KEY=%s" % value])

    def test_planted_raw_form(self):
        # A double quote makes every escaped form differ from the raw one.
        value = 'pass"word-2026'
        result = self._planted(value, value)
        self.assertSecretRefused(result, value, r"^replay/data/(before|after)/\d{4}\.json$")

    def test_planted_json_ascii_escaped_form(self):
        value = 'cl\u00e9"secret-2026'
        result = self._planted(value, json.dumps(value)[1:-1])
        self.assertSecretRefused(result, value, r"^replay/data/(before|after)/\d{4}\.json$")

    def test_planted_json_unicode_form(self):
        value = 'cl\u00e9"secret-2026'
        result = self._planted(value, json.dumps(value, ensure_ascii=False)[1:-1])
        self.assertSecretRefused(result, value, r"^replay/data/(before|after)/\d{4}\.json$")

    def test_planted_html_escaped_form(self):
        value = "R&D<key>-2026"
        result = self._planted(value, html.escape(value))
        self.assertSecretRefused(result, value, r"^replay/data/(before|after)/\d{4}\.json$")

    def test_planted_percent_encoded_form(self):
        value = "path/to key-2026"
        result = self._planted(value, urllib.parse.quote(value, safe=""))
        self.assertSecretRefused(result, value, r"^replay/data/(before|after)/\d{4}\.json$")

    def test_a_planted_unrelated_body_still_exports(self):
        # The stub plants bytes that hold no form of the secret: the export must succeed, so the
        # four planted refusals above are about the form, not the stub.
        result = _export_planting("/api/demo/driver", b'{"note": "nothing secret here"}',
                                  ["KEY=path/to key-2026"])
        self.assertExported(result)


# ------------------------------------------------------------------ m2: the shim's '/api' root


class ShimApiRoot(_Base):
    """Pathname exactly '/api' or under '/api/' is the shim's; everything else passes through."""

    @classmethod
    def setUpClass(cls):
        cls.export = w27.mock_export()
        calls = [
            {"input": "/api", "init": {"method": "GET"}},
            {"input": "/api", "init": {"method": "POST", "body": "{}"}},
            {"input": "/api?x=1"},
            {"input": "/api", "init": {"method": "PUT", "body": "{}"}},
            {"input": "/apiary.json", "init": {"method": "GET"}},
            {"input": "/api/demo/rider", "init": {"method": "GET"}},
        ]
        cls.report = _drive(cls.export["out"], [{"name": "p", "pages": [
            {"url": "/party/status.html?snapshot=after", "calls": calls}]}]) if cls.export["code"] == 0 \
            else {"harness_error": "the mock export failed: " + cls.export["stderr"][-2000:]}

    def page(self):
        self.assertNotIn("harness_error", self.report, self.report.get("harness_error"))
        page = self.report["scenarios"]["p"][0]
        self.assertEqual(page["errors"], [])
        return page

    def response(self, index):
        entry = self.page()["responses"][index]
        self.assertIsNone(entry["error"], entry["error"])
        try:
            body = json.loads(entry["body"])
        except (TypeError, ValueError):
            body = entry["body"]
        return entry["status"], body

    def test_get_api_root_is_not_in_this_replay(self):
        self.assertEqual(self.response(0), (404, w27.NOT_IN_REPLAY))
        self.assertEqual(self.response(2), (404, w27.NOT_IN_REPLAY))

    def test_writes_to_api_root_are_refused(self):
        for index in (1, 3):
            with self.subTest(call=index):
                self.assertEqual(self.response(index), (403, {"error": w27.GENERIC_REFUSAL}))

    def test_api_root_never_reaches_the_network(self):
        hits = [n for n in self.page()["network"] if re.match(r"^/api(/|\?|$)", n["url"])]
        self.assertEqual(hits, [])

    def test_a_path_that_only_starts_with_api_passes_through(self):
        self.assertIn({"method": "GET", "url": "/apiary.json"}, self.page()["network"])
        self.assertEqual(self.response(4)[0], 404)
        status, body = self.response(5)
        self.assertEqual(status, 200)
        self.assertEqual(body, w27.recorded(self.export["out"], "after", "GET /api/demo/rider"))


class ReplayDocFixRound(unittest.TestCase):
    """docs/replay.md documents the new refusal and the data-built steps (contract strings)."""

    def test_docs_replay_names_the_new_refusal_and_step_texts(self):
        text = _read(w27.REPO / "docs" / "replay.md")
        for needle in ("could not be read", "T-NS0202", "No human decision was recorded"):
            self.assertIn(needle, text)

    def test_docs_replay_quotes_the_unreadable_provider_refusal_in_full(self):
        # Planner tightening 2026-10-07: "could not be read" also appears in the prose, so the
        # refusal line itself is pinned verbatim, on a line of its own.
        text = _read(w27.REPO / "docs" / "replay.md")
        refusal = UNREADABLE % "<ids>"
        self.assertIn(refusal, [line.strip() for line in text.splitlines()])


if __name__ == "__main__":
    unittest.main()
