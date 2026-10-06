"""W27 static replay export: shared fixture and runners (non-app; nothing in app/ imports it).

The fixture is produced by the real pipeline on the mock: NS-0202 and RD-0109 filed through
POST /api/disputes against the real server (so the dispute records exist), copied to after/,
and the held RD-0109 run approved with app.human_review.record_decision. It is built once per
process and treated as read-only; a test that needs a variant copies it and says why.
"""

from __future__ import annotations

import atexit
import contextlib
import hashlib
import inspect
import io
import json
import os
import re
import runpy
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
EXPORTER = REPO / "tools" / "export_replay.py"
UI_DIR = REPO / "ui"
RECORDED_ON = "2026-10-06"
SHIM_TAG = '<script src="/replay/replay-shim.js"></script>'
MOCK_PREFIX = "TEST REPLAY (mock model). "
LABELS = ("before", "after")
#: The category ids the party pages offer (ui/party/party.js rider and driver option lists).
CATEGORIES = ["route_deviation", "no_show_charge", "property_damage_mess", "safety_incident", "other"]
REVIEWER = "Ana Lim"
#: The reviewer's reason on the recorded approval. Long and unique, so the secret scan can
#: use it as a value that occurs only in recorded bodies.
REVIEW_REASON = "W27 replay reviewer reason: the detour was not agreed."
BANNER_SENTENCE = ("Replay of saved runs recorded on %s, %s the human decision. Forms work as a "
                   "guided walk-through; nothing you submit is processed.")
GENERIC_REFUSAL = ("This is a replay. The recorded rider filed this case already. Use the replay "
                   "page's steps to see what happened next.")
DECISION_REFUSAL = ("This is a replay. In the recorded run, the reviewer chose: %s. Use 'Show after "
                    "the decision' in the banner to see the result.")
NOT_IN_REPLAY = {"error": "Not in this replay."}
LANDING_TITLE = "Ryde dispute resolution: replay"
LANDING_STEPS = [
    ("A no-show refund decided by the AI alone", "/party/status.html?snapshot=after"),
    ("An above-cap detour held for a human", "/index.html?snapshot=before&run=%(rd)s"),
    ("The human approves the held ruling", "/index.html?snapshot=after&run=%(rd)s"),
    ("What the rider sees", "/party/status.html?snapshot=after"),
]
REFUSAL_PREFIX = "export_replay: "


def clean_env() -> Dict[str, str]:
    return {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}


def sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def tree(root: Path) -> Dict[str, str]:
    """relative posix path -> sha256 for every file under root; directories as 'dir'."""
    out: Dict[str, str] = {}
    for path in sorted(Path(root).rglob("*")):
        rel = path.relative_to(root).as_posix()
        out[rel] = "dir" if path.is_dir() else sha(path)
    return out


def files(root: Path) -> List[str]:
    return sorted(p.relative_to(root).as_posix() for p in Path(root).rglob("*") if p.is_file())


def is_empty_or_absent(path: Path) -> bool:
    return not Path(path).exists() or (Path(path).is_dir() and not any(Path(path).iterdir()))


def refusal_lines(stderr: str) -> List[str]:
    """The exporter's own messages. Server request logs start with '[' and never count."""
    return [line for line in stderr.splitlines() if line.startswith(REFUSAL_PREFIX)]


# ------------------------------------------------------------------ fixture

_FIXTURE: Optional[Dict[str, Any]] = None
_TMP: List[tempfile.TemporaryDirectory] = []


def scratch_dir() -> Path:
    tmp = tempfile.TemporaryDirectory(prefix="w27-")
    _TMP.append(tmp)
    return Path(tmp.name)


@atexit.register
def _cleanup() -> None:
    for tmp in _TMP:
        tmp.cleanup()


def fixture() -> Dict[str, Any]:
    """{root, before, after, ns_run, rd_run, ns_dispute, rd_dispute, runs}. Read-only."""
    global _FIXTURE
    if _FIXTURE is not None:
        return _FIXTURE
    from app.human_review import record_decision
    from tests.w23_support import Server

    root = scratch_dir()
    server = Server()
    try:
        ns = server.file(trip_id="T-NS0202", category="no_show_charge", claim=None)
        rd = server.file(trip_id="T-RD0109", category="route_deviation", claim=55.16)
        before = root / "before"
        shutil.copytree(server.out, before)
    finally:
        server.close()
    if ns["status"] != "decided" or rd["status"] != "under_review":
        raise AssertionError("fixture premise broke: NS-0202 %s, RD-0109 %s" % (ns["status"], rd["status"]))
    after = root / "after"
    shutil.copytree(before, after)
    case = json.loads((after / rd["run_id"] / "case_file.json").read_text(encoding="utf-8"))
    record_decision(after / rd["run_id"], case,
                    {"decision": "approve", "reviewer": REVIEWER, "reason": REVIEW_REASON})
    _FIXTURE = {
        "root": root,
        "before": before,
        "after": after,
        "ns_run": ns["run_id"],
        "rd_run": rd["run_id"],
        "ns_dispute": ns["dispute_id"],
        "rd_dispute": rd["dispute_id"],
        "runs": sorted([ns["run_id"], rd["run_id"]]),
    }
    return _FIXTURE


def copy_fixture(providers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """HAND-MADE SHAPE: a copy of the fixture whose run.started payloads name another provider.

    The pipeline cannot record a real provider without a paid call, so the copy rewrites only
    the llm_provider field the exporter's mock refusal reads. providers: run_id -> provider.
    """
    fx = dict(fixture())
    root = scratch_dir()
    for label in LABELS:
        shutil.copytree(fx[label], root / label)
        fx[label] = root / label
        for run_id, provider in (providers or {}).items():
            path = root / label / run_id / "payloads" / "0001-run-started.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            assert payload.get("llm_provider") == "mock", payload
            payload["llm_provider"] = provider
            path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    fx["root"] = root
    return fx


def export_args(fx: Dict[str, Any], out: Path, *, allow_mock: bool = True,
                secrets: Optional[Path] = None, recorded_on: str = RECORDED_ON) -> List[str]:
    args = ["--before", str(fx["before"]), "--after", str(fx["after"]),
            "--recorded-on", recorded_on, "--out", str(out)]
    if allow_mock:
        args.append("--allow-mock")
    # Always explicit: the default (.env) must never make a test depend on a real key file.
    args += ["--secrets-file", str(secrets if secrets is not None else Path(out).parent / "no-such.env")]
    return args


def run_cli(args: List[str]) -> Tuple[int, str, str]:
    result = subprocess.run([sys.executable, "-B", str(EXPORTER)] + args, cwd=str(REPO),
                            env=clean_env(), capture_output=True, text=True, timeout=300)
    return result.returncode, result.stdout, result.stderr


def run_inprocess(args: List[str], override: Optional[Callable[[str], Optional[Tuple[int, Any]]]] = None):
    """Run the exporter as __main__ in this process, with the real server's API GET routing
    wrapped. override(target) -> (status, payload) answers that request instead; None passes
    it to the real route. Returns (exit code, stdout, stderr, make_server calls)."""
    from app import server

    if not EXPORTER.is_file():
        raise AssertionError("tools/export_replay.py does not exist")
    calls: List[Dict[str, Any]] = []
    real_make = server.make_server
    real_route = server.RydeRequestHandler._route_api_get

    def make(*a, **kw):
        bound = inspect.signature(real_make).bind(*a, **kw)
        bound.apply_defaults()
        calls.append(dict(bound.arguments))
        return real_make(*a, **kw)

    def route(self, split):
        target = split.path + ("?" + split.query if split.query else "")
        answer = override(target) if override is not None else None
        if answer is not None:
            self._send_json(answer[0], answer[1])
            return None
        return real_route(self, split)

    out, err = io.StringIO(), io.StringIO()
    code: Any = 0
    with mock.patch.object(server, "make_server", make), \
            mock.patch.object(server.RydeRequestHandler, "_route_api_get", route), \
            mock.patch.object(sys, "argv", [str(EXPORTER)] + args), \
            contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            runpy.run_path(str(EXPORTER), run_name="__main__")
        except SystemExit as exc:
            code = exc.code
    if code is None:
        code = 0
    return code, out.getvalue(), err.getvalue(), calls


# ------------------------------------------------------------------ expectations


def payload_names(run_dir: Path) -> List[str]:
    return sorted(p.name for p in (Path(run_dir) / "payloads").iterdir() if p.is_file())


def required_keys(fx: Dict[str, Any], label: str) -> List[str]:
    snapshot = Path(fx[label])
    keys = ["GET /api/review/queue", "GET /api/review/overrides", "GET /api/demo/rider",
            "GET /api/demo/driver"]
    keys += ["GET /api/trips?category=%s" % c for c in CATEGORIES]
    for run_id in fx["runs"]:
        dispute = fx["ns_dispute"] if run_id == fx["ns_run"] else fx["rd_dispute"]
        keys.append("GET /api/disputes/%s" % dispute)
        keys.append("GET /api/review/%s/case" % run_id)
        keys += ["GET /api/review/%s/payloads/%s" % (run_id, n) for n in payload_names(snapshot / run_id)]
    return keys


class LiveServer:
    """The real server on a throwaway copy of one snapshot, for comparing recorded bodies."""

    def __init__(self, snapshot: Path):
        from app.server import make_server
        from tests.w23_support import JudgeFails  # any client; GETs never call it

        self.tmp = tempfile.TemporaryDirectory(prefix="w27-live-")
        copy = Path(self.tmp.name) / "snap"
        shutil.copytree(snapshot, copy)
        self.httpd = make_server(0, out_dir=copy, llm=JudgeFails())
        self.base = "http://127.0.0.1:%d" % self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def get(self, path: str) -> Tuple[int, Any]:
        try:
            with urllib.request.urlopen(self.base + path, timeout=60) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as err:
            return err.code, None

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.tmp.cleanup()


def optional_keys_live(fx: Dict[str, Any], label: str) -> List[str]:
    """The prompts URLs the real server answers 200 for today (none before lane B merges)."""
    live = LiveServer(Path(fx[label]))
    try:
        return ["GET /api/review/%s/prompts" % run_id for run_id in fx["runs"]
                if live.get("/api/review/%s/prompts" % run_id)[0] == 200]
    finally:
        live.close()


def without_waiting(value: Any) -> Any:
    """The queue's waiting_seconds moves with the clock; everything else must match exactly."""
    if isinstance(value, dict):
        return {k: without_waiting(v) for k, v in value.items() if k != "waiting_seconds"}
    if isinstance(value, list):
        return [without_waiting(v) for v in value]
    return value


def manifest(out: Path, label: str) -> Dict[str, str]:
    path = Path(out) / "replay" / "data" / label / "manifest.json"
    if not path.is_file():
        raise AssertionError("no manifest at %s" % path)
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise AssertionError("the %s manifest is not an object" % label)
    return data


def recorded(out: Path, label: str, key: str) -> Any:
    entries = manifest(out, label)
    if key not in entries:
        raise AssertionError("%r is not in the %s manifest" % (key, label))
    return json.loads((Path(out) / "replay" / "data" / label / entries[key]).read_text(encoding="utf-8"))


_EXPORT: Dict[str, Any] = {}


def mock_export() -> Dict[str, Any]:
    """One successful --allow-mock export of the fixture, shared read-only by the shim tests."""
    if "out" not in _EXPORT:
        fx = fixture()
        out = scratch_dir() / "site"
        code, stdout, stderr = run_cli(export_args(fx, out, allow_mock=True))
        _EXPORT.update(out=out, code=code, stdout=stdout, stderr=stderr, fx=fx)
    return _EXPORT


def strip_js_comments(source: str) -> str:
    source = re.sub(r"/\*[\s\S]*?\*/", "", source)
    return re.sub(r"(?<![:\"'\\])//[^\n]*", "", source)
