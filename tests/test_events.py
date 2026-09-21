"""The event log: stable schema, append-only behaviour, resolvable payload refs."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from app.events import EVENT_SCHEMA_VERSION, Actor, EventLog, EventType

EXPECTED_KEYS = {
    "schema_version",
    "seq",
    "ts",
    "run_id",
    "type",
    "from",
    "to",
    "summary",
    "payload_ref",
}


class EventLogTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.run_dir = Path(self._tmp.name) / "run"
        self.log = EventLog(self.run_dir, "run-1")

    def tearDown(self):
        self._tmp.cleanup()

    def test_event_has_exactly_the_documented_schema(self):
        self.log.emit(EventType.RUN_STARTED, from_=Actor.SYSTEM, to=Actor.SYSTEM, summary="started")
        written = json.loads((self.run_dir / "events.jsonl").read_text(encoding="utf-8").strip())
        self.assertEqual(set(written.keys()), EXPECTED_KEYS)
        self.assertEqual(written["schema_version"], EVENT_SCHEMA_VERSION)

    def test_sequence_is_monotonic_from_one(self):
        for _ in range(3):
            self.log.emit(EventType.RUN_STARTED, from_=Actor.SYSTEM, to=Actor.SYSTEM, summary="x")
        self.assertEqual([event.seq for event in self.log.events()], [1, 2, 3])

    def test_timestamps_are_iso8601_with_an_offset(self):
        event = self.log.emit(EventType.RUN_STARTED, from_=Actor.SYSTEM, to=Actor.SYSTEM, summary="x")
        parsed = datetime.fromisoformat(event.ts)
        self.assertIsNotNone(parsed.tzinfo)

    def test_payload_is_written_and_resolvable_through_its_ref(self):
        event = self.log.emit(
            EventType.ADVOCATE_CASE_SUBMITTED,
            from_=Actor.RIDER_ADVOCATE,
            to=Actor.JUDGE,
            summary="case submitted",
            payload={"argument": "the driver took a longer route"},
        )
        self.assertIsNotNone(event.payload_ref)
        self.assertTrue((self.run_dir / event.payload_ref).exists())
        self.assertEqual(self.log.read_payload(event)["argument"], "the driver took a longer route")

    def test_event_without_a_payload_has_no_ref(self):
        event = self.log.emit(EventType.RUN_STARTED, from_=Actor.SYSTEM, to=Actor.SYSTEM, summary="x")
        self.assertIsNone(event.payload_ref)

    def test_log_is_append_only(self):
        self.log.emit(EventType.RUN_STARTED, from_=Actor.SYSTEM, to=Actor.SYSTEM, summary="first")
        first_line = (self.run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()[0]
        self.log.emit(EventType.RUN_COMPLETED, from_=Actor.SYSTEM, to=Actor.SYSTEM, summary="last")
        lines = (self.run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0], first_line)

    def test_read_back_from_disk_matches_the_in_memory_snapshot(self):
        self.log.emit(EventType.RUN_STARTED, from_=Actor.SYSTEM, to=Actor.SYSTEM, summary="x")
        self.log.emit(
            EventType.PARTY_NOTIFIED,
            from_=Actor.SYSTEM,
            to=Actor.PARTIES,
            summary="notified",
            payload={"message": "hello"},
        )
        self.assertEqual(EventLog.read_events(self.run_dir), self.log.snapshot())

    def test_corrupt_log_fails_loudly(self):
        (self.run_dir / "events.jsonl").write_text("{not json}\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            EventLog.read_events(self.run_dir)


if __name__ == "__main__":
    unittest.main()
