#!/usr/bin/env python3
"""W27: export a static replay site from two saved-run snapshots.

The public link is a static replay of real saved runs. This script records the
replay: for each snapshot (before and after the human decision) it starts the
real app.server on a throwaway copy of the snapshot, GETs every URL the site
needs, saves each 200 body byte-for-byte, copies ui/ with one shim script line
added to every page, and writes the replay shim and the landing page from
tools/replay/ with their placeholders filled.

Usage:

    python3 tools/export_replay.py --before DIR --after DIR --recorded-on YYYY-MM-DD --out DIR \\
        [--allow-mock] [--secrets-file PATH]

Every refusal exits 2, prints one line on stderr that starts with
"export_replay: ", and leaves nothing in --out. The input folders are never
modified: the server only ever sees a temp copy.

Non-app: nothing in app/ or ui/ imports or loads this file except through the
exported site.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app import server  # noqa: E402  (import after sys.path is set)
from app.config import DEFAULT_ENV_PATH, load_env_file  # noqa: E402
from app.llm import LLMClient  # noqa: E402

REFUSAL_PREFIX = "export_replay: "
SHIM_TAG = '<script src="/replay/replay-shim.js"></script>'
LABELS = ("before", "after")
RD_TRIP_ID = "T-RD0109"
MOCK_PROVIDER = "mock"
MOCK_PREFIX = "TEST REPLAY (mock model). "
CASE_FILE_NAME = "case_file.json"
DISPUTE_FILE_NAME = "dispute.json"
EVENTS_FILE_NAME = "events.jsonl"
PAYLOADS_DIRNAME = "payloads"
RUN_STARTED = "run.started"

UI_DIR = REPO_ROOT / "ui"
REPLAY_DIR = REPO_ROOT / "tools" / "replay"

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
CATEGORY_RE = re.compile(r'\{\s*id:\s*"([a-z_]+)",\s*label:')
DECISION_PATH_RE = re.compile(r"^/api/review/([^/]+)/decision$")

#: The fixed URLs every snapshot records, before the per-run ones.
FIXED_PATHS = ("/api/review/queue", "/api/review/overrides", "/api/demo/rider", "/api/demo/driver")


class Refusal(Exception):
    """A designed refusal: exit 2, one stderr line, nothing left in --out."""


class _RefusingLLM(LLMClient):
    """The exporter never calls a model: recording only reads saved runs back out.

    The server needs a client at startup; this one refuses every request, so a
    missing GET route can never silently turn into a live model call.
    """

    provider_name = "refusing"

    def complete(self, request):  # noqa: ANN001 - the interface, refused
        raise RuntimeError("export_replay reads saved runs; it never calls a model")


def _parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="export_replay.py",
        description="Export a static replay site from two saved-run snapshots.",
    )
    parser.add_argument("--before", required=True,
                        help="the snapshot taken before the human decision")
    parser.add_argument("--after", required=True,
                        help="the snapshot taken after the human decision")
    parser.add_argument("--recorded-on", required=True,
                        help="the recording date, exactly YYYY-MM-DD")
    parser.add_argument("--out", required=True,
                        help="the output site directory (missing or empty)")
    parser.add_argument("--allow-mock", action="store_true",
                        help="export runs recorded with the mock model (test replays only)")
    parser.add_argument("--secrets-file", default=None,
                        help="the file to scan for secrets (default: .env at the repository root)")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    try:
        return _export(args)
    except Refusal as refusal:
        sys.stderr.write(REFUSAL_PREFIX + _one_line(str(refusal)) + "\n")
        return 2
    except Exception as error:  # noqa: BLE001 - a refusal, never a traceback
        sys.stderr.write(REFUSAL_PREFIX + _one_line("export failed: %s" % error) + "\n")
        return 2


def _one_line(message: str) -> str:
    return " ".join(str(message).split())


# ------------------------------------------------------------------ validation


def _validated_date(value: Any) -> str:
    if not isinstance(value, str) or not DATE_RE.fullmatch(value):
        raise Refusal("--recorded-on must be a real calendar date in YYYY-MM-DD form, got %r" % value)
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise Refusal("--recorded-on must be a real calendar date in YYYY-MM-DD form, got %r" % value)
    return value


def _refuse_non_empty_out(out: Path) -> None:
    if not out.exists():
        return
    if not out.is_dir():
        raise Refusal("--out %s exists and is not a directory" % out)
    if any(out.iterdir()):
        raise Refusal("--out %s exists and is not empty; refusing to overwrite it" % out)


def _require_dir(path: Path, flag: str) -> None:
    if not path.is_dir():
        raise Refusal("%s %s is not a directory" % (flag, path))


def _read_json_object(path: Path) -> Optional[Dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        return None
    return data if isinstance(data, dict) else None


def _runs(snapshot: Path) -> List[Tuple[str, Dict[str, Any]]]:
    """Every run that is a direct child of the snapshot and holds a case file."""
    runs: List[Tuple[str, Dict[str, Any]]] = []
    for child in sorted(snapshot.iterdir()):
        if not child.is_dir():
            continue
        case = _read_json_object(child / CASE_FILE_NAME)
        if case is None:
            continue
        runs.append((child.name, case))
    return runs


def _trip_id(record: Dict[str, Any]) -> Any:
    trip = record.get("trip_data")
    if not isinstance(trip, dict):
        trip = record.get("trip")
    return trip.get("trip_id") if isinstance(trip, dict) else None


def _rd0109_run(snapshot: Path) -> str:
    """The run whose dispute record's trip is T-RD0109; exactly one per snapshot."""
    found = [
        run_id
        for run_id, _case in _runs(snapshot)
        if _trip_id(_read_json_object(snapshot / run_id / DISPUTE_FILE_NAME) or {}) == RD_TRIP_ID
    ]
    if len(found) != 1:
        raise Refusal("%s must hold exactly one %s run, found %d" % (snapshot, RD_TRIP_ID, len(found)))
    return found[0]


def _run_started_provider(run_dir: Path) -> Any:
    """The llm_provider of the run.started event payload, or None when unreadable."""
    try:
        lines = (run_dir / EVENTS_FILE_NAME).read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in lines:
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict) or event.get("type") != RUN_STARTED:
            continue
        ref = event.get("payload_ref")
        if not isinstance(ref, str) or not ref:
            return None
        payload = _read_json_object(run_dir / ref)
        return payload.get("llm_provider") if payload is not None else None
    return None


def _mock_runs(snapshot: Path) -> List[str]:
    return [
        run_id
        for run_id, _case in _runs(snapshot)
        if _run_started_provider(snapshot / run_id) == MOCK_PROVIDER
    ]


def _secret_values(secrets_file: Optional[str]) -> List[str]:
    path = Path(secrets_file) if secrets_file else Path(DEFAULT_ENV_PATH)
    try:
        values = load_env_file(path)
    except OSError as error:
        raise Refusal("could not read --secrets-file %s: %s" % (path, error))
    return sorted({value for value in values.values() if len(value) >= 8})


def _categories() -> List[str]:
    """The category ids ui/party/*.js offers, first-seen order across the files."""
    offered: List[str] = []
    for path in sorted((UI_DIR / "party").glob("*.js")):
        for value in CATEGORY_RE.findall(path.read_text(encoding="utf-8")):
            if value not in offered:
                offered.append(value)
    if not offered:
        raise Refusal("no category options found in ui/party/*.js")
    return offered


# ------------------------------------------------------------------ recording


def _fetch(base: str, path: str) -> Tuple[int, bytes]:
    try:
        with urllib.request.urlopen(base + path, timeout=60) as response:
            return int(response.status), response.read()
    except urllib.error.HTTPError as error:
        try:
            body = error.read()
        except OSError:
            body = b""
        return int(error.code), body
    except OSError as error:
        raise Refusal("could not reach the recording server for %s: %s" % (path, error))


def _required_paths(snapshot: Path, runs: List[Tuple[str, Dict[str, Any]]]) -> List[str]:
    paths = list(FIXED_PATHS)
    for category in _categories():
        paths.append("/api/trips?category=%s" % category)
    for run_id, case in runs:
        dispute_id = case.get("dispute_id")
        if not isinstance(dispute_id, str) or not dispute_id:
            raise Refusal("run %s has no dispute_id in its case file" % run_id)
        paths.append("/api/disputes/%s" % dispute_id)
        paths.append("/api/review/%s/case" % run_id)
        try:
            names = sorted(p.name for p in (snapshot / run_id / PAYLOADS_DIRNAME).iterdir() if p.is_file())
        except OSError:
            names = []
        for name in names:
            paths.append("/api/review/%s/payloads/%s" % (run_id, name))
    return paths


def _record_snapshot(snapshot: Path, dest: Path) -> None:
    """Record one snapshot through the real server on a throwaway copy."""
    copy_root = Path(tempfile.mkdtemp(prefix="w27-replay-snapshot-"))
    try:
        served = copy_root / "out"
        shutil.copytree(snapshot, served)
        httpd = server.make_server(0, out_dir=served, llm=_RefusingLLM())
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        base = "http://127.0.0.1:%d" % httpd.server_address[1]
        try:
            dest.mkdir(parents=True, exist_ok=True)
            manifest: Dict[str, str] = {}
            index = 0
            runs = _runs(snapshot)
            for path in _required_paths(snapshot, runs):
                status, body = _fetch(base, path)
                if status != 200:
                    raise Refusal("the recording server answered %d for %s" % (status, path))
                index += 1
                name = "%04d.json" % index
                (dest / name).write_bytes(body)
                manifest["GET " + path] = name
            for run_id, _case in runs:
                path = "/api/review/%s/prompts" % run_id
                status, body = _fetch(base, path)
                if status == 404:
                    continue
                if status != 200:
                    raise Refusal("the recording server answered %d for %s" % (status, path))
                index += 1
                name = "%04d.json" % index
                (dest / name).write_bytes(body)
                manifest["GET " + path] = name
            (dest / "manifest.json").write_text(
                json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
            )
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=10)
    finally:
        shutil.rmtree(copy_root, ignore_errors=True)


# ------------------------------------------------------------------ static site


def _html_with_shim(source: Path) -> bytes:
    lines = source.read_text(encoding="utf-8").splitlines(keepends=True)
    for index, line in enumerate(lines):
        if line.strip() == "<head>":
            lines.insert(index + 1, SHIM_TAG + "\n")
            return "".join(lines).encode("utf-8")
    raise Refusal("%s has no <head> line to insert the shim after" % source.relative_to(REPO_ROOT))


def _fill_placeholders(template: str, values: Dict[str, str], where: str) -> str:
    text = template
    for placeholder, value in values.items():
        text = text.replace(placeholder, value)
    if "{{" in text or "}}" in text:
        raise Refusal("%s still holds an unfilled placeholder" % where)
    return text


def _write_site(work: Path, rd_run_id: str, recorded_on: str, mock: bool) -> None:
    for source in sorted(UI_DIR.rglob("*")):
        if not source.is_file():
            continue
        target = work / source.relative_to(UI_DIR)
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.suffix == ".html":
            target.write_bytes(_html_with_shim(source))
        else:
            shutil.copyfile(source, target)

    replay = work / "replay"
    replay.mkdir(parents=True, exist_ok=True)
    shim = _fill_placeholders(
        (REPLAY_DIR / "replay-shim.js").read_text(encoding="utf-8"),
        {"{{RECORDED_ON}}": recorded_on, "{{MOCK_PREFIX}}": MOCK_PREFIX if mock else ""},
        "tools/replay/replay-shim.js",
    )
    (replay / "replay-shim.js").write_text(shim, encoding="utf-8")
    landing = _fill_placeholders(
        (REPLAY_DIR / "index.html").read_text(encoding="utf-8"),
        {"{{RECORDED_ON}}": recorded_on, "{{RD_RUN_ID}}": rd_run_id},
        "tools/replay/index.html",
    )
    (replay / "index.html").write_text(landing, encoding="utf-8")


def _scan_for_secrets(work: Path, secrets: List[str]) -> None:
    """Refuse when any secret value (length >= 8) occurs in any output file.

    Runs before anything is moved into --out; the message names the file and
    never the value.
    """
    if not secrets:
        return
    needles = [(value, value.encode("utf-8")) for value in secrets]
    for path in sorted(work.rglob("*")):
        if not path.is_file():
            continue
        data = path.read_bytes()
        for _value, needle in needles:
            if needle in data:
                raise Refusal(
                    "refusing to publish: a value from --secrets-file occurs in %s"
                    % path.relative_to(work).as_posix()
                )


def _publish(work: Path, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for entry in sorted(work.iterdir()):
        shutil.move(str(entry), str(out / entry.name))


# ------------------------------------------------------------------ the export


def _export(args: argparse.Namespace) -> int:
    recorded_on = _validated_date(args.recorded_on)
    out = Path(args.out)
    _refuse_non_empty_out(out)
    before = Path(args.before)
    after = Path(args.after)
    _require_dir(before, "--before")
    _require_dir(after, "--after")

    rd_before = _rd0109_run(before)
    rd_after = _rd0109_run(after)
    if rd_before != rd_after:
        raise Refusal(
            "--before and --after name different %s runs (%s, %s)" % (RD_TRIP_ID, rd_before, rd_after)
        )

    if not args.allow_mock:
        mocked = sorted(set(_mock_runs(before)) | set(_mock_runs(after)))
        if mocked:
            raise Refusal(
                "run(s) %s were recorded with the mock model; pass --allow-mock to export a test replay"
                % ", ".join(mocked)
            )

    secrets = _secret_values(args.secrets_file)

    work = Path(tempfile.mkdtemp(prefix="w27-replay-export-"))
    try:
        for label, snapshot in zip(LABELS, (before, after)):
            _record_snapshot(snapshot, work / "replay" / "data" / label)
        _write_site(work, rd_before, recorded_on, mock=args.allow_mock)
        _scan_for_secrets(work, secrets)
        _publish(work, out)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
