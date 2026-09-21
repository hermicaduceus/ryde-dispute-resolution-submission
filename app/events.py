"""Append-only event log — the observable inter-agent communication surface.

The challenge statement requires inter-agent communication to be observable: a judge
must be able to see how the agents exchange information and build their cases. This
module is that record. It is built now, before any UI, because it is a hard requirement
and because a run that was not recorded cannot be reconstructed afterwards.

Storage layout for one run (default `<out_dir>/<run_id>/`):

    events.jsonl                 one JSON object per line, append-only, never rewritten
    payloads/<seq>-<type>.json   the full payload an event points at

The event strip in the UI reads events.jsonl and shows one line per event; clicking an
event opens its payload file. That is what `payload_ref` is for.

Stable event schema (schema_version 1.0) — every event carries exactly these fields:

    schema_version  str   "1.0"
    seq             int   1-based, monotonic within the run
    ts              str   UTC ISO-8601 with milliseconds and offset
    run_id          str   identifies the run
    type            str   dotted event type, from EventType below
    from            str   actor the event came from
    to              str   actor the event is addressed to
    summary         str   one-line, human-readable — what the strip shows
    payload_ref     str?  path to the payload file, relative to the run dir; null if none

Adding a field is a schema_version change. Removing or renaming one is too.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

EVENT_SCHEMA_VERSION = "1.0"

EVENTS_FILENAME = "events.jsonl"
PAYLOADS_DIRNAME = "payloads"


class EventType:
    """Dotted event types. Constants, not free strings, so the strip stays filterable."""

    RUN_STARTED = "run.started"
    DISPUTE_FILED = "dispute.filed"
    DISPUTE_ROUTED_TO_HUMAN_REVIEW = "dispute.routed_to_human_review"
    EVIDENCE_PACK_BUILT = "evidence.pack_built"
    CASE_ASSIGNED = "case.assigned"
    ADVOCATE_CASE_SUBMITTED = "advocate.case_submitted"
    ADVOCATE_FOLLOW_UP_REQUESTED = "advocate.follow_up_requested"
    JUDGE_DELIBERATION_STARTED = "judge.deliberation_started"
    JUDGE_RULING_ISSUED = "judge.ruling_issued"
    JUDGE_RULING_WITHHELD = "judge.ruling_withheld"
    PARTY_NOTIFIED = "party.notified"
    RUN_COMPLETED = "run.completed"


class Actor:
    """Who events come from and go to. Parties are spectators and never act."""

    SYSTEM = "system"
    RIDER_ADVOCATE = "rider_advocate"
    DRIVER_ADVOCATE = "driver_advocate"
    JUDGE = "judge"
    RIDER = "rider"
    DRIVER = "driver"
    PARTIES = "parties"
    HUMAN_REVIEW = "human_review"


@dataclass(frozen=True)
class Event:
    """One line of the log."""

    schema_version: str
    seq: int
    ts: str
    run_id: str
    type: str
    from_: str
    to: str
    summary: str
    payload_ref: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Wire form. The 'from' key is spelled out here because it is a Python keyword."""
        return {
            "schema_version": self.schema_version,
            "seq": self.seq,
            "ts": self.ts,
            "run_id": self.run_id,
            "type": self.type,
            "from": self.from_,
            "to": self.to,
            "summary": self.summary,
            "payload_ref": self.payload_ref,
        }


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "event"


class EventLog:
    """Append-only writer for one run.

    emit() is the only way in. Nothing here rewrites or deletes a line: the log is the
    evidence, so a rerun writes a new run directory rather than editing an old one.
    """

    def __init__(self, run_dir: Path, run_id: str):
        self.run_dir = Path(run_dir)
        self.run_id = run_id
        self.events_path = self.run_dir / EVENTS_FILENAME
        self.payloads_dir = self.run_dir / PAYLOADS_DIRNAME
        self._events: List[Event] = []

        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.payloads_dir.mkdir(parents=True, exist_ok=True)

    # -------------------------------------------------------------------- writing

    def emit(
        self,
        event_type: str,
        *,
        from_: str,
        to: str,
        summary: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Event:
        """Append one event, writing its payload file first so the ref is never dangling."""
        seq = len(self._events) + 1
        payload_ref = None
        if payload is not None:
            filename = "%04d-%s.json" % (seq, _slug(event_type))
            payload_path = self.payloads_dir / filename
            payload_path.write_text(
                json.dumps(payload, indent=2, sort_keys=False, default=str) + "\n",
                encoding="utf-8",
            )
            payload_ref = "%s/%s" % (PAYLOADS_DIRNAME, filename)

        event = Event(
            schema_version=EVENT_SCHEMA_VERSION,
            seq=seq,
            ts=datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            run_id=self.run_id,
            type=event_type,
            from_=from_,
            to=to,
            summary=summary,
            payload_ref=payload_ref,
        )

        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event.to_dict(), default=str) + "\n")

        self._events.append(event)
        return event

    # -------------------------------------------------------------------- reading

    def events(self) -> List[Event]:
        """Events emitted in this process, in order."""
        return list(self._events)

    def snapshot(self) -> List[Dict[str, Any]]:
        """In-memory events as wire dicts — what the UI strip renders."""
        return [event.to_dict() for event in self._events]

    def read_payload(self, event: Event) -> Dict[str, Any]:
        """Follow an event's payload_ref. Raises if the ref is missing or unreadable."""
        if not event.payload_ref:
            raise FileNotFoundError("event %d (%s) has no payload" % (event.seq, event.type))
        return json.loads((self.run_dir / event.payload_ref).read_text(encoding="utf-8"))

    @staticmethod
    def read_events(run_dir: Path) -> List[Dict[str, Any]]:
        """Read events.jsonl back from disk — the UI's entry point, and the tests'."""
        path = Path(run_dir) / EVENTS_FILENAME
        if not path.exists():
            raise FileNotFoundError("no event log at %s" % path)
        events = []
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError("corrupt event log at line %d of %s" % (line_number, path)) from exc
        return events
