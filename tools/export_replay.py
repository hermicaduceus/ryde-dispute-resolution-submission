#!/usr/bin/env python3
"""W27: export a static replay site from two saved-run snapshots.

The public link is a static replay of real saved runs. This script records the
replay: for each snapshot (before and after the human decision) it starts the
real app.server on a throwaway copy of the snapshot, GETs every URL the site
needs, saves each 200 body byte-for-byte, copies ui/ with one shim script line
added to every page, and writes the replay shim and the landing page from
tools/replay/ with their placeholders filled. The landing page's first three
steps are built from the recorded case bodies, so they state what the replay
shows.

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
import html
import json
import math
import re
import shutil
import sys
import tempfile
import threading
import urllib.error
import urllib.parse
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
NS_TRIP_ID = "T-NS0202"
MOCK_PROVIDER = "mock"
MOCK_PREFIX = "TEST REPLAY (mock model). "
NO_ACTION = "no action"
CASE_FILE_NAME = "case_file.json"
DISPUTE_FILE_NAME = "dispute.json"
EVENTS_FILE_NAME = "events.jsonl"
PAYLOADS_DIRNAME = "payloads"
RUN_STARTED = "run.started"

UI_DIR = REPO_ROOT / "ui"
REPLAY_DIR = REPO_ROOT / "tools" / "replay"

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
CATEGORY_RE = re.compile(r'\{\s*id:\s*"([a-z_]+)",\s*label:')

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


def _refuse_unsafe_paths(out: Path, before: Path, after: Path) -> None:
    """Refuse an --out that would land on the exporter's own inputs or outputs."""
    for flag, folder in (("--before", before), ("--after", after)):
        if out == folder or out.is_relative_to(folder):
            raise Refusal(
                "--out %s is inside %s %s; choose an output folder outside the snapshots"
                % (out, flag, folder)
            )
    ui = UI_DIR.resolve()
    if out == ui or out.is_relative_to(ui):
        raise Refusal("--out %s is inside the repository's ui/ folder" % out)
    replay = REPLAY_DIR.resolve()
    if out == replay or out.is_relative_to(replay):
        raise Refusal("--out %s is inside tools/replay/" % out)
    if before == after:
        raise Refusal("--before and --after resolve to the same folder: %s" % before)


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


def _run_by_trip(snapshot: Path, trip_id: str) -> str:
    """The run whose dispute record's trip is `trip_id`; exactly one per snapshot."""
    found = [
        run_id
        for run_id, _case in _runs(snapshot)
        if _trip_id(_read_json_object(snapshot / run_id / DISPUTE_FILE_NAME) or {}) == trip_id
    ]
    if len(found) != 1:
        raise Refusal("%s must hold exactly one %s run, found %d" % (snapshot, trip_id, len(found)))
    return found[0]


# ------------------------------------------------------------------ provider gate


def _provider_from_event(run_dir: Path, event: Dict[str, Any]) -> Optional[str]:
    """The llm_provider of one run.started event, or None when it cannot be read.

    A payload_ref that escapes the run folder — a relative climb, an absolute
    path elsewhere, or a symlink pointing outside — is as unreadable as a
    missing or malformed payload.
    """
    ref = event.get("payload_ref")
    if not isinstance(ref, str) or not ref:
        return None
    try:
        payload_path = (run_dir / ref).resolve()
        if not payload_path.is_relative_to(run_dir.resolve()):
            return None
    except (OSError, ValueError, RuntimeError):
        return None
    payload = _read_json_object(payload_path)
    if payload is None:
        return None
    provider = payload.get("llm_provider")
    if not isinstance(provider, str) or not provider:
        return None
    return provider


def _run_provider_verdict(run_dir: Path) -> str:
    """'mock' when any run.started payload says mock, else 'unreadable' when any cannot be
    read, else 'readable'. Every run.started event of the run is read."""
    try:
        lines = (run_dir / EVENTS_FILE_NAME).read_text(encoding="utf-8").splitlines()
    except (OSError, ValueError):
        return "unreadable"
    saw_started = False
    saw_mock = False
    saw_unreadable = False
    for line in lines:
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict) or event.get("type") != RUN_STARTED:
            continue
        saw_started = True
        provider = _provider_from_event(run_dir, event)
        if provider is None:
            saw_unreadable = True
        elif provider == MOCK_PROVIDER:
            saw_mock = True
    if not saw_started:
        return "unreadable"
    if saw_mock:
        return "mock"
    if saw_unreadable:
        return "unreadable"
    return "readable"


def _provider_refusal(before: Path, after: Path) -> Optional[str]:
    """The mock or unreadable refusal line, or None. Runs before anything is recorded."""
    verdicts: Dict[str, List[str]] = {}
    for snapshot in (before, after):
        for run_id, _case in _runs(snapshot):
            verdicts.setdefault(run_id, []).append(_run_provider_verdict(snapshot / run_id))
    mocked = sorted(run_id for run_id, states in verdicts.items() if MOCK_PROVIDER in states)
    if mocked:
        return ("run(s) %s were recorded with the mock model; pass --allow-mock to export a test replay"
                % ", ".join(mocked))
    unreadable = sorted(run_id for run_id, states in verdicts.items() if "unreadable" in states)
    if unreadable:
        return ("the model provider of run(s) %s could not be read; pass --allow-mock to export a test replay"
                % ", ".join(unreadable))
    return None


# ------------------------------------------------------------------ secrets


def _secret_values(secrets_file: Optional[str]) -> List[str]:
    path = Path(secrets_file) if secrets_file else Path(DEFAULT_ENV_PATH)
    try:
        values = load_env_file(path)
    except OSError as error:
        raise Refusal("could not read --secrets-file %s: %s" % (path, error))
    return sorted({value for value in values.values() if len(value) >= 8})


def _secret_needles(values: List[str]) -> List[bytes]:
    """Every form a value can ship in: raw, JSON-escaped (ASCII and not), HTML-escaped
    and percent-encoded."""
    needles = set()
    for value in values:
        forms = (
            value,
            json.dumps(value)[1:-1],
            json.dumps(value, ensure_ascii=False)[1:-1],
            html.escape(value),
            urllib.parse.quote(value, safe=""),
        )
        for form in forms:
            if form:
                needles.add(form.encode("utf-8"))
    return sorted(needles)


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


def _recorded_json(work: Path, label: str, key: str) -> Dict[str, Any]:
    """One recorded body from the staging tree, by its manifest key."""
    data_dir = work / "replay" / "data" / label
    manifest = _read_json_object(data_dir / "manifest.json")
    if manifest is None:
        raise Refusal("the %s recording has no manifest" % label)
    name = manifest.get(key)
    if not isinstance(name, str) or not name:
        raise Refusal("the %s recording has no %s" % (label, key))
    body = _read_json_object(data_dir / name)
    if body is None:
        raise Refusal("the %s recording of %s is not a JSON object" % (label, key))
    return body


# ------------------------------------------------------------------ landing steps


def _is_finite_number(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(float(value))
    except OverflowError:
        return False


def _phrase(container: Any, amount_field: str) -> Optional[str]:
    """The phrase for an action/amount pair, or None when the container gives no phrase."""
    if not isinstance(container, dict):
        return None
    action = container.get("action")
    if not isinstance(action, str) or not action:
        return None
    if action == NO_ACTION:
        return NO_ACTION
    amount = container.get(amount_field)
    if _is_finite_number(amount):
        return "%s SGD %.2f" % (action, float(amount))
    return action


def _case_and_decision(body: Dict[str, Any]) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    case = body.get("case_file")
    decision = body.get("human_decision")
    return (case if isinstance(case, dict) else {},
            decision if isinstance(decision, dict) else None)


def _resolution(case: Dict[str, Any]) -> Dict[str, Any]:
    resolution = case.get("resolution")
    return resolution if isinstance(resolution, dict) else {}


def _outcome_text(outcome: Any) -> str:
    return outcome if isinstance(outcome, str) and outcome else "unknown"


def _step_one(body: Dict[str, Any]) -> str:
    case, decision = _case_and_decision(body)
    resolution = _resolution(case)
    phrase = _phrase(resolution.get("ruling"), "recommended_amount_sgd")
    if (resolution.get("outcome") == "ruled"
            and resolution.get("delivered_to_parties") is True
            and decision is None
            and phrase is not None):
        return "A no-show case the AI decided alone: %s" % phrase
    return "A no-show case: %s" % _outcome_text(resolution.get("outcome"))


def _step_two(body: Dict[str, Any]) -> str:
    case, decision = _case_and_decision(body)
    resolution = _resolution(case)
    phrase = _phrase(resolution.get("withheld_candidate"), "recommended_amount_sgd")
    if resolution.get("outcome") == "withheld" and decision is None and phrase is not None:
        return "A detour case the AI held for a human: it proposed %s" % phrase
    return "A detour case: %s" % _outcome_text(resolution.get("outcome"))


def _step_three(body: Dict[str, Any]) -> str:
    _case, decision = _case_and_decision(body)
    if decision is None:
        return "No human decision was recorded"
    choice = decision.get("decision")
    phrase = _phrase(decision, "amount_sgd")
    if choice == "reject":
        return "The human rejected it: no action"
    if choice == "approve" and phrase is not None:
        return "The human approved: %s" % phrase
    if choice == "change" and phrase is not None:
        return "The human changed it to: %s" % phrase
    return "The human decided: %s" % (phrase if phrase is not None else _outcome_text(choice))


def _landing_steps(work: Path, ns_run: str, rd_run: str) -> List[str]:
    """Steps 1-3 from the recorded case bodies, so the page states what the replay shows."""
    ns_after = _recorded_json(work, "after", "GET /api/review/%s/case" % ns_run)
    rd_before = _recorded_json(work, "before", "GET /api/review/%s/case" % rd_run)
    rd_after = _recorded_json(work, "after", "GET /api/review/%s/case" % rd_run)
    return [_step_one(ns_after), _step_two(rd_before), _step_three(rd_after), "What the rider sees"]


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


def _write_site(work: Path, rd_run_id: str, recorded_on: str, mock: bool, steps: List[str]) -> None:
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
        {
            "{{RECORDED_ON}}": recorded_on,
            "{{RD_RUN_ID}}": rd_run_id,
            "{{STEP_1}}": html.escape(steps[0]),
            "{{STEP_2}}": html.escape(steps[1]),
            "{{STEP_3}}": html.escape(steps[2]),
        },
        "tools/replay/index.html",
    )
    (replay / "index.html").write_text(landing, encoding="utf-8")


def _scan_for_secrets(work: Path, secrets: List[str]) -> None:
    """Refuse when any secret value (length >= 8) occurs in any output file, in any form.

    Runs before anything is moved into --out; the message names the file and
    never the value.
    """
    if not secrets:
        return
    needles = _secret_needles(secrets)
    for path in sorted(work.rglob("*")):
        if not path.is_file():
            continue
        data = path.read_bytes()
        for needle in needles:
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
    out = Path(args.out).resolve()
    before = Path(args.before).resolve()
    after = Path(args.after).resolve()
    _refuse_non_empty_out(out)
    _refuse_unsafe_paths(out, before, after)
    _require_dir(before, "--before")
    _require_dir(after, "--after")

    rd_before = _run_by_trip(before, RD_TRIP_ID)
    rd_after = _run_by_trip(after, RD_TRIP_ID)
    if rd_before != rd_after:
        raise Refusal(
            "--before and --after name different %s runs (%s, %s)" % (RD_TRIP_ID, rd_before, rd_after)
        )
    ns_before = _run_by_trip(before, NS_TRIP_ID)
    ns_after = _run_by_trip(after, NS_TRIP_ID)
    if ns_before != ns_after:
        raise Refusal(
            "--before and --after name different %s runs (%s, %s)" % (NS_TRIP_ID, ns_before, ns_after)
        )

    if not args.allow_mock:
        refusal = _provider_refusal(before, after)
        if refusal:
            raise Refusal(refusal)

    secrets = _secret_values(args.secrets_file)

    work = Path(tempfile.mkdtemp(prefix="w27-replay-export-"))
    try:
        for label, snapshot in zip(LABELS, (before, after)):
            _record_snapshot(snapshot, work / "replay" / "data" / label)
        steps = _landing_steps(work, ns_before, rd_before)
        _write_site(work, rd_before, recorded_on, mock=args.allow_mock, steps=steps)
        _scan_for_secrets(work, secrets)
        _publish(work, out)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
