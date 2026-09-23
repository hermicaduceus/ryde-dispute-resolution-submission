"""Local HTTP server: the party-facing intake form, the party view, and static files.

Standard library only (http.server + json + urllib). Run it with:

    python3 -m app.server          # http://127.0.0.1:8000  (/ the console, /party/ the party page)

Surfaces:

    GET  /api/trips?category=<c>          the trips a party can pick from (facts only)
    POST /api/disputes                    file a dispute from the intake form; runs the
                                          pipeline and returns the party view
    POST /api/disputes/<run_id>/answers   round two: answer a needs_info run's questions;
                                          re-runs with the answers attached
    GET  /<path>                          static files from ui/ only, never outside it

Two structural guarantees live here, both in Python rather than in any prompt:

  * party_view() is an allowlist with a fail-closed default. The page is only ever
    handed its five keys — run_id, dispute_id, status, message, questions — and any
    malformed case file degrades to the neutral under-review message with no questions.
    A withheld amount or a confidence value is structurally absent from the response,
    not merely unrendered.
  * The follow-up round limit and every validation gate are code. The party page is a
    client; nothing it can send changes what the server is willing to accept.
"""

from __future__ import annotations

import copy
import json
import os
import re
import shutil
import sys
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, unquote, urlsplit

from .config import load_config
from .dispute import AGENT_CATEGORIES, is_organiser_record, normalise_category, parse_dispute
from .events import EventLog
from .llm import LLMClient, build_llm_client
from .pipeline import run_dispute
from .policy import load_policy
from .schemas import (
    HUMAN_REVIEW_MESSAGE,
    INTAKE_QUESTIONS,
    NEEDS_INFO_MESSAGE,
    OUTCOME_HUMAN_REVIEW,
    OUTCOME_NEEDS_INFO,
    OUTCOME_RULED,
    OUTCOME_WITHHELD,
    UNDER_REVIEW_MESSAGE,
    is_party_safe,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
UI_DIR = REPO_ROOT / "ui"

CASE_FILE_NAME = "case_file.json"
DISPUTE_FILE_NAME = "dispute.json"
#: Written into a needs_info run directory once the party's answers have been applied,
#: so the same run can never be answered twice.
ANSWERED_FILE_NAME = "answered.json"

MAX_BODY_BYTES = 64 * 1024
DEFAULT_PORT = 8000

_RUN_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")

#: The categories the intake form offers. The two locked ones reach the agents; the
#: rest route to the human-review queue with a neutral message.
FORM_CATEGORIES = (
    "route_deviation",
    "no_show_charge",
    "property_damage_mess",
    "safety_incident",
    "other",
)

#: The intake questions per category, in form order. Derived from INTAKE_QUESTIONS in
#: app/schemas.py — the one owner of the labels the party page shows and the template
#: questions quote. Keys must match the pack's intake vocabulary.
QUESTIONNAIRES: Dict[str, Tuple[str, ...]] = {
    category: tuple(key for key, _label in items)
    for category, items in INTAKE_QUESTIONS.items()
}

#: outcome -> the status word the party page shows.
PARTY_STATUS_BY_OUTCOME = {
    OUTCOME_RULED: "decided",
    OUTCOME_WITHHELD: "under_review",
    OUTCOME_HUMAN_REVIEW: "passed_to_support",
    OUTCOME_NEEDS_INFO: "needs_info",
}

PARTY_VIEW_KEYS = ("run_id", "dispute_id", "status", "message", "questions")


# ------------------------------------------------------------------ the party view


class _MalformedCaseFile(Exception):
    """The case file does not carry a view we are willing to show the party."""


def _party_fallback(run_id: Any, dispute_id: Any) -> Dict[str, Any]:
    """The fail-closed view: neutral message, no questions, nothing else."""
    return {
        "run_id": run_id if isinstance(run_id, str) else "",
        "dispute_id": dispute_id if isinstance(dispute_id, str) else "",
        "status": "under_review",
        "message": UNDER_REVIEW_MESSAGE,
        "questions": [],
    }


def party_view(case_file: Any) -> Dict[str, Any]:
    """The only shape of a case file the party is ever handed.

    Built from an allowlist and failing closed: any malformed input — not a non-array
    object, an unknown outcome, questions_for_party that is not a list of strings, a
    decided file with a missing or empty party_message — returns the neutral
    under-review view with no questions. A non-decision status never shows the file's
    message (S1), so a blank one there costs nothing and must not cost the safe
    questions too (T4). A withheld ruling's amount and the Judge's confidence are
    structurally absent from everything this function returns.
    """
    run_id = case_file.get("run_id") if isinstance(case_file, dict) else None
    dispute_id = case_file.get("dispute_id") if isinstance(case_file, dict) else None
    try:
        if not isinstance(case_file, dict):
            raise _MalformedCaseFile
        resolution = case_file.get("resolution")
        if not isinstance(resolution, dict):
            raise _MalformedCaseFile
        message = resolution.get("party_message")
        status = PARTY_STATUS_BY_OUTCOME.get(resolution.get("outcome"))
        if status is None:
            raise _MalformedCaseFile
        # T4: only a decision shows the file's text, so only a decision needs a
        # non-blank one. Rejecting a blank message for every status would throw
        # away a needs-info file's safe questions over a string that is never
        # displayed.
        if status == "decided" and (not isinstance(message, str) or not message.strip()):
            raise _MalformedCaseFile
        questions = resolution.get("questions_for_party", [])
        if not isinstance(questions, list) or not all(isinstance(q, str) for q in questions):
            raise _MalformedCaseFile
        # Second line of defence (R1/S1): a decided message that carries the
        # internal vocabulary fails closed. The message builder in app/schemas.py
        # should never produce one, but a planted or stale case file does not get
        # the benefit of the doubt. The needs-info questions keep the same check.
        if status == "decided" and not is_party_safe(message):
            raise _MalformedCaseFile
        if status == "needs_info" and not all(is_party_safe(q) for q in questions):
            raise _MalformedCaseFile
        # Only a decision's message may vary (S1): every other status shows its
        # canonical constant, never the text a stale or planted file carries.
        canonical_message = {
            "under_review": UNDER_REVIEW_MESSAGE,
            "passed_to_support": HUMAN_REVIEW_MESSAGE,
            "needs_info": NEEDS_INFO_MESSAGE,
        }.get(status, message)
        return {
            "run_id": run_id if isinstance(run_id, str) else "",
            "dispute_id": dispute_id if isinstance(dispute_id, str) else "",
            "status": status,
            "message": canonical_message,
            "questions": list(questions) if status == "needs_info" else [],
        }
    except _MalformedCaseFile:
        return _party_fallback(run_id, dispute_id)


# ------------------------------------------------------------------- pack helpers


def _record_category(record: Dict[str, Any]) -> str:
    if is_organiser_record(record):
        return normalise_category(record.get("dispute_ticket", {}).get("dispute_type"))
    return normalise_category(record.get("category"))


#: Plain words for the trip's category (R9): the page never shows raw kind values.
KIND_LABELS = {
    "route_deviation": "Route complaint",
    "no_show_charge": "No-show charge",
    "other": "Other",
}


def _charge(fare: Any, cancellation_fee: Any, waiting_fee: Any) -> Tuple[Optional[float], Optional[str]]:
    """The amount a trip will cost the party and what that amount IS (R8).

    A fare and a fee are different charges; collapsing them under one unlabelled
    number told the party their no-show 'fare' was 6.61. Returns (None, None) when no
    charge is known — never a zero pretending to be a price.
    """
    if isinstance(fare, dict):
        charged = fare.get("charged_sgd")
        if isinstance(charged, (int, float)) and not isinstance(charged, bool):
            return round(float(charged), 2), "fare"
    for value, label in ((cancellation_fee, "cancellation fee"), (waiting_fee, "waiting fee")):
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return round(float(value), 2), label
    return None, None


def _trip_summary(record: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The party-facing facts of one pack record's trip. No names, profiles or traces."""
    if is_organiser_record(record):
        trip = record.get("trip_data") if isinstance(record.get("trip_data"), dict) else {}
        pickup = trip.get("pickup_location") if isinstance(trip.get("pickup_location"), dict) else {}
        dropoff = trip.get("dropoff_location") if isinstance(trip.get("dropoff_location"), dict) else {}
        pickup_name = pickup.get("name") if isinstance(pickup.get("name"), str) else None
        dropoff_name = dropoff.get("name") if isinstance(dropoff.get("name"), str) else None
        date = trip.get("requested_time") or trip.get("pickup_time")
        fare_sgd, charge_label = _charge(
            trip.get("fare") if isinstance(trip.get("fare"), dict) else None,
            trip.get("cancellation_fee"),
            trip.get("waiting_fee"),
        )
        trip_id = trip.get("trip_id")
        kind = normalise_category(record.get("dispute_ticket", {}).get("dispute_type"))
    else:
        trip = record.get("trip") if isinstance(record.get("trip"), dict) else {}
        pickup_name = dropoff_name = None
        date = trip.get("requested_at") or trip.get("pickup_at")
        fare_sgd, charge_label = _charge(
            trip.get("fare") if isinstance(trip.get("fare"), dict) else None, None, None
        )
        trip_id = trip.get("trip_id")
        kind = normalise_category(record.get("category"))

    if not isinstance(trip_id, str) or not trip_id:
        return None
    if pickup_name and dropoff_name:
        label = "%s to %s" % (pickup_name, dropoff_name)
    else:
        label = trip_id
    return {
        "trip_id": trip_id,
        "label": label,
        "kind": kind,
        "kind_label": KIND_LABELS.get(kind) or "Other",
        "pickup": pickup_name or "",
        "dropoff": dropoff_name or "",
        "date": date[:10] if isinstance(date, str) and date else "",
        "fare_sgd": fare_sgd,
        "charge_label": charge_label,
    }


def _load_pack_records(pack_dir: Path) -> List[Dict[str, Any]]:
    """Every record in the pack, in file-name order."""
    records: List[Dict[str, Any]] = []
    for path in sorted((pack_dir / "disputes").glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict):
            records.append(data)
    return records


def _trip_list(pack_dir: Path, category: str) -> List[Dict[str, Any]]:
    """The trips the party can pick from for one form category.

    The two locked categories list their own cases; any other category lists every
    trip, because an out-of-scope filing is still about a real trip.
    """
    records = _load_pack_records(pack_dir)
    if category == "route_deviation":
        records = [r for r in records if _record_category(r) == "route_deviation"]
    elif category == "no_show_charge":
        records = [r for r in records if _record_category(r) == "no_show_charge"]
    trips = []
    for record in records:
        summary = _trip_summary(record)
        if summary is not None:
            trips.append(summary)
    return trips


def _find_pack_record(pack_dir: Path, trip_id: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(trip_id, str) or not trip_id:
        return None
    for record in _load_pack_records(pack_dir):
        summary = _trip_summary(record)
        if summary is not None and summary["trip_id"] == trip_id:
            return record
    return None


# ------------------------------------------------------------------ filing builder


def _new_dispute_id() -> str:
    return "PF-%s" % uuid.uuid4().hex[:8].upper()


def _new_run_id() -> str:
    return "%s-%s" % (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        uuid.uuid4().hex[:8],
    )


def _build_record(
    pack_record: Dict[str, Any],
    *,
    dispute_id: str,
    category: str,
    filed_by: str,
    description: str,
    claim_amount_sgd: Optional[float],
    answers: Dict[str, str],
) -> Dict[str, Any]:
    """A new dispute record for one filing: platform evidence kept, party-stated
    fields replaced by the form's values.

    Party-stated fields the form does not collect (rider_claims_driver_absent, any
    carried follow-up answers) are removed, never inherited from the pack record the
    trip came from: the new dispute must say only what this party said.
    """
    record = copy.deepcopy(pack_record)
    claim_block: Dict[str, Any] = {"text": description}
    if claim_amount_sgd is not None:
        claim_block["amount_sgd"] = claim_amount_sgd
    filed_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

    if is_organiser_record(record):
        ticket = record["dispute_ticket"]
        ticket["dispute_id"] = dispute_id
        ticket["filed_by"] = filed_by
        ticket["dispute_type"] = category
        ticket["description"] = description
        ticket["filed_at"] = filed_at
        extensions = record.setdefault("ryde_extensions", {})
        extensions["claim"] = claim_block
        extensions["intake"] = dict(answers)
        extensions.pop("rider_claims_driver_absent", None)
        extensions.pop("follow_up_answers", None)
    else:
        record["dispute_id"] = dispute_id
        record["category"] = category
        record["filed_by"] = filed_by
        record["filed_at"] = filed_at
        record["claim"] = claim_block
        record["intake"] = dict(answers)
        cancellation = record.get("cancellation")
        if isinstance(cancellation, dict):
            cancellation.pop("rider_claims_driver_absent", None)
        record.pop("follow_up_answers", None)
    return record


# --------------------------------------------------------------------- validation


class _HTTPError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def _require_dict(value: Any) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise _HTTPError(400, "the request body must be a JSON object")
    return value


def _validate_filing(body: Dict[str, Any]) -> Dict[str, Any]:
    """Validate one intake-form submission. Raises _HTTPError on any bad field."""
    category = body.get("category")
    if category not in FORM_CATEGORIES:
        raise _HTTPError(400, "unknown category")

    filed_by = body.get("filed_by")
    if not isinstance(filed_by, str) or filed_by.strip().lower() not in ("rider", "driver"):
        raise _HTTPError(400, "filed_by must be 'rider' or 'driver'")
    filed_by = filed_by.strip().lower()

    description = body.get("description")
    if not isinstance(description, str) or not description.strip():
        raise _HTTPError(400, "description is required")
    if len(description) > 2000:
        raise _HTTPError(400, "description must be at most 2000 characters")

    claim = body.get("claim_amount_sgd")
    if claim is not None:
        if isinstance(claim, bool) or not isinstance(claim, (int, float)):
            raise _HTTPError(400, "claim_amount_sgd must be a number or null")
        if not 0 <= float(claim) <= 500:
            raise _HTTPError(400, "claim_amount_sgd must be between 0 and 500")

    answers = body.get("answers", {})
    if not isinstance(answers, dict):
        raise _HTTPError(400, "answers must be an object")
    questionnaire = QUESTIONNAIRES.get(category, ())
    for key, value in answers.items():
        if key not in questionnaire:
            raise _HTTPError(400, "unknown intake answer: %s" % key)
        if not isinstance(value, str):
            raise _HTTPError(400, "intake answer '%s' must be a string" % key)

    return {
        "category": category,
        "filed_by": filed_by,
        "description": description,
        "claim_amount_sgd": None if claim is None else float(claim),
        "answers": answers,
    }


def _validate_reply(body: Dict[str, Any], asked: List[str]) -> List[Dict[str, str]]:
    """The party's round-two answers: every question asked, answered exactly once,
    nothing else, each answer a non-blank string."""
    answers = body.get("answers")
    if not isinstance(answers, list):
        raise _HTTPError(400, "answers must be a list")
    cleaned: List[Dict[str, str]] = []
    for item in answers:
        if not isinstance(item, dict):
            raise _HTTPError(400, "each answer must be an object with question and answer")
        question = item.get("question")
        answer = item.get("answer")
        if not isinstance(question, str) or not isinstance(answer, str) or not answer.strip():
            raise _HTTPError(400, "each answer needs a question and a non-blank answer")
        cleaned.append({"question": question, "answer": answer})
    posted = [item["question"] for item in cleaned]
    if len(posted) != len(asked) or sorted(posted) != sorted(asked) or len(set(posted)) != len(posted):
        raise _HTTPError(400, "the answers must match the questions that were asked")
    return cleaned


def _write_answered_record(claim_path: Path, new_run_id: str, cleaned: List[Dict[str, str]]) -> None:
    """Record which run answered a claimed follow-up round (S4).

    Module-level so a test can patch it: when this write fails the round-two
    run has already succeeded, so the caller answers 200 with the ruling and
    keeps the (empty) claim file — the run stays answered, no retry can rule
    twice.
    """
    claim_path.write_text(
        json.dumps({"answered_by_run": new_run_id, "answers": cleaned}, indent=2) + "\n",
        encoding="utf-8",
    )


# ------------------------------------------------------------------------ handler


def _content_type(path: Path) -> str:
    return {
        ".html": "text/html; charset=utf-8",
        ".css": "text/css; charset=utf-8",
        ".js": "text/javascript; charset=utf-8",
        ".json": "application/json; charset=utf-8",
        ".svg": "image/svg+xml",
        ".png": "image/png",
    }.get(path.suffix.lower(), "application/octet-stream")


def _static_file(decoded_path: str) -> Optional[Tuple[Path, str]]:
    """Resolve a request path to a file under ui/, or None.

    Every check runs on the DECODED path: percent-encoded dots and separators are
    exactly as capable of leaving ui/ as literal ones. Any ".." or "." segment, any
    dotfile, and anything that still resolves outside ui/ is refused.
    """
    if "\x00" in decoded_path or "\\" in decoded_path:
        return None
    parts = [part for part in decoded_path.split("/") if part]
    if not parts:
        parts = ["index.html"]
    elif decoded_path.endswith("/"):
        parts.append("index.html")
    if any(part in ("..", ".") or part.startswith(".") for part in parts):
        return None
    root = UI_DIR.resolve()
    target = (root / Path(*parts)).resolve()
    if not target.is_relative_to(root):
        return None
    if target.is_dir():
        target = target / "index.html"
    if not target.is_file():
        return None
    return target, _content_type(target)


class RydeRequestHandler(BaseHTTPRequestHandler):
    """One connection. State lives on the server instance (self.server.ryde_state)."""

    server_version = "RydePartyServer/1.0"

    # ------------------------------------------------------------- plumbing

    def _send_json(self, status: int, payload: Dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path, content_type: str) -> None:
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> Dict[str, Any]:
        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            raise _HTTPError(400, "a request body is required")
        try:
            length = int(raw_length)
        except ValueError:
            raise _HTTPError(400, "invalid Content-Length")
        if length < 0:
            raise _HTTPError(400, "invalid Content-Length")
        if length > MAX_BODY_BYTES:
            raise _HTTPError(413, "request body too large")
        raw = self.rfile.read(length)
        try:
            return _require_dict(json.loads(raw.decode("utf-8")))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise _HTTPError(400, "the request body is not valid JSON")

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - stdlib signature
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), format % args))

    # ------------------------------------------------------------- routing

    def do_GET(self) -> None:  # noqa: N802 - stdlib naming
        try:
            split = urlsplit(self.path)
            if split.path.startswith("/api/"):
                self._route_api_get(split)
            else:
                self._serve_static(split.path)
        except _HTTPError as exc:
            self._send_json(exc.status, {"error": exc.message})
        except Exception:  # noqa: BLE001 - the server must answer, not die
            self._send_json(500, {"error": "internal error"})

    def do_POST(self) -> None:  # noqa: N802 - stdlib naming
        try:
            split = urlsplit(self.path)
            if not split.path.startswith("/api/"):
                raise _HTTPError(404, "not found")
            self._route_api_post(split)
        except _HTTPError as exc:
            self._send_json(exc.status, {"error": exc.message})
        except Exception:  # noqa: BLE001 - the server must answer, not die
            self._send_json(500, {"error": "internal error"})

    # ------------------------------------------------------------- API GET

    def _route_api_get(self, split) -> None:
        state = self.server.ryde_state  # type: ignore[attr-defined]
        if split.path == "/api/trips":
            params = parse_qs(split.query)
            category = params.get("category", [""])[0]
            self._send_json(200, {"trips": _trip_list(state.pack_dir, category)})
            return
        raise _HTTPError(404, "not found")

    # ------------------------------------------------------------- API POST

    def _route_api_post(self, split) -> None:
        state = self.server.ryde_state  # type: ignore[attr-defined]
        filing_match = re.fullmatch(r"/api/disputes", split.path)
        answer_match = re.fullmatch(r"/api/disputes/([^/]+)/answers", split.path)
        if filing_match:
            self._file_dispute(state)
            return
        if answer_match:
            self._answer_run(state, unquote(answer_match.group(1)))
            return
        raise _HTTPError(404, "not found")

    def _file_dispute(self, state: "_ServerState") -> None:
        body = self._read_body()
        filing = _validate_filing(body)

        pack_record = _find_pack_record(state.pack_dir, body.get("trip_id"))
        if pack_record is None:
            raise _HTTPError(404, "unknown trip")

        # R3/R5: the two locked categories argue from trip-specific evidence, so the
        # trip's own category must match what the form picked. A mismatch would either
        # crash the evidence layer (a no-show filing on a route trip) or fabricate
        # evidence (a "route" built from a driver's waiting-around GPS). Out-of-scope
        # categories run no evidence layer and still accept any trip. Checked before
        # anything is created: a refused filing leaves no run directory.
        record_category = _record_category(pack_record)
        if filing["category"] in AGENT_CATEGORIES and record_category != filing["category"]:
            raise _HTTPError(400, "this trip does not match the category you picked")

        record = _build_record(
            pack_record,
            dispute_id=_new_dispute_id(),
            category=filing["category"],
            filed_by=filing["filed_by"],
            description=filing["description"],
            claim_amount_sgd=filing["claim_amount_sgd"],
            answers=filing["answers"],
        )
        case = self._run_record(state, record)
        self._send_json(200, party_view(case.to_dict()))

    def _answer_run(self, state: "_ServerState", run_id: str) -> None:
        # The run id is checked after decoding: a malformed token is as unknown as a
        # missing directory, and neither may name a path outside the output directory.
        if not _RUN_ID_RE.fullmatch(run_id) or run_id in (".", ".."):
            raise _HTTPError(404, "unknown run")
        run_dir = (state.out_dir / run_id).resolve()
        if not run_dir.is_relative_to(state.out_dir.resolve()) or not run_dir.is_dir():
            raise _HTTPError(404, "unknown run")

        case_path = run_dir / CASE_FILE_NAME
        dispute_path = run_dir / DISPUTE_FILE_NAME
        try:
            case_file = json.loads(case_path.read_text(encoding="utf-8"))
            record = json.loads(dispute_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raise _HTTPError(404, "unknown run")
        if not isinstance(case_file, dict) or not isinstance(record, dict):
            raise _HTTPError(404, "unknown run")

        resolution = case_file.get("resolution")
        asked: List[str] = []
        if isinstance(resolution, dict):
            candidate = resolution.get("questions_for_party")
            if isinstance(candidate, list) and all(isinstance(q, str) for q in candidate):
                asked = list(candidate)
        if resolution is None or not isinstance(resolution, dict):
            raise _HTTPError(404, "unknown run")
        if resolution.get("outcome") != "needs_info":
            raise _HTTPError(409, "this run did not ask for more information")
        if not asked:
            raise _HTTPError(404, "unknown run")

        body = self._read_body()
        cleaned = _validate_reply(body, asked)

        # R4: claim the run atomically BEFORE anything is run. O_CREAT|O_EXCL is the
        # whole gate — on a ThreadingHTTPServer a check-then-write between two
        # concurrent answers lets both through; an exclusive create lets exactly one.
        claim_path = run_dir / ANSWERED_FILE_NAME
        try:
            claim_fd = os.open(claim_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            raise _HTTPError(409, "this run has already been answered")
        os.close(claim_fd)

        try:
            # Attach the answers in whichever slot this record's shape carries them,
            # then re-run: same dispute, fresh run, and the one-round gate guarantees
            # the case now goes all the way through.
            if is_organiser_record(record):
                record.setdefault("ryde_extensions", {})["follow_up_answers"] = cleaned
            else:
                record["follow_up_answers"] = cleaned

            new_case = self._run_record(state, record)
        except Exception:
            # R7: release the claim so the party can retry after the failure.
            try:
                claim_path.unlink()
            except OSError:
                pass
            raise

        try:
            _write_answered_record(claim_path, new_case.run_id, cleaned)
        except Exception as exc:
            # S4/T3: the round-two run already succeeded, so the answer happened —
            # the party gets their ruling even if the bookkeeping write failed for
            # any reason, not only an OSError. The claim file already exists
            # (empty), so the run stays answered and a retry cannot rule twice.
            print("answered.json write failed for run %s: %s" % (run_id, exc), file=sys.stderr)
        self._send_json(200, party_view(new_case.to_dict()))

    def _run_record(self, state: "_ServerState", record: Dict[str, Any]):
        run_id = _new_run_id()
        run_dir = state.out_dir / run_id
        try:
            events = EventLog(run_dir, run_id)
            case = run_dispute(
                dispute=parse_dispute(record),
                llm=state.llm,
                policy=state.policy,
                events=events,
                confidence_threshold=state.confidence_threshold,
                autonomous_cap_sgd=state.autonomous_cap_sgd,
            )
            case.write(run_dir)
            (run_dir / DISPUTE_FILE_NAME).write_text(
                json.dumps(record, indent=2, default=str) + "\n", encoding="utf-8"
            )
            return case
        except Exception:
            # R7: a crashed run must not leave a half-written directory behind — and
            # must remove only the directory this call created, never anything else.
            resolved = run_dir.resolve()
            if resolved != state.out_dir.resolve() and resolved.is_relative_to(state.out_dir.resolve()):
                shutil.rmtree(resolved, ignore_errors=True)
            raise

    # ------------------------------------------------------------- static

    def _serve_static(self, raw_path: str) -> None:
        resolved = _static_file(unquote(raw_path))
        if resolved is None:
            raise _HTTPError(404, "not found")
        path, content_type = resolved
        self._send_file(path, content_type)


class _ServerState:
    """Everything one server instance needs to run a dispute."""

    def __init__(self, pack_dir: Path, out_dir: Path, llm: LLMClient, confidence_threshold: float,
                 autonomous_cap_sgd: float, policy):
        self.pack_dir = pack_dir
        self.out_dir = out_dir
        self.llm = llm
        self.confidence_threshold = confidence_threshold
        self.autonomous_cap_sgd = autonomous_cap_sgd
        self.policy = policy


def make_server(
    port: int,
    pack_dir: Optional[Path] = None,
    out_dir: Optional[Path] = None,
    llm: Optional[LLMClient] = None,
) -> ThreadingHTTPServer:
    """An HTTP server bound to 127.0.0.1 only.

    `None` means the app/config.json default for that setting; `llm=None` builds the
    configured provider. Tests pass port=0 and read the bound port back.
    """
    config = load_config()
    resolved_pack = Path(pack_dir) if pack_dir is not None else config.dataset_pack_dir
    resolved_out = Path(out_dir) if out_dir is not None else config.out_dir
    if llm is None:
        provider = config.llm.provider
        if provider == "tencent":
            llm = build_llm_client(provider, settings=config.llm)
        else:
            llm = build_llm_client(provider)
    policy = load_policy(config.policy_path)

    httpd = ThreadingHTTPServer(("127.0.0.1", port), RydeRequestHandler)
    httpd.ryde_state = _ServerState(  # type: ignore[attr-defined]
        pack_dir=resolved_pack,
        out_dir=resolved_out,
        llm=llm,
        confidence_threshold=config.confidence_threshold,
        autonomous_cap_sgd=config.autonomous_cap_sgd,
        policy=policy,
    )
    return httpd


def main() -> int:
    httpd = make_server(DEFAULT_PORT)
    port = httpd.server_address[1]
    print("Ryde party surface on http://127.0.0.1:%d" % port)
    print("  party page:   http://127.0.0.1:%d/party/" % port)
    print("  console:      http://127.0.0.1:%d/" % port)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
