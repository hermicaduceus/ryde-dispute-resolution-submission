"""W43 SHOULD RED acceptance (S1): two CLI runs in one second must not merge histories.

Written BEFORE the build, so it is RED on the frozen baseline until the W43 SHOULD lane ships.
Today the CLI builds its run id as `<UTC second>-<dispute slug>` (app/cli.py) and the event log
accepts a directory that already exists (app/events.py), so the two command forms README:122
and README:130-131 documents, run within one second, land on ONE directory: the log carries two
`run.started` events and the sequence numbers restart at 1 mid-file, the payload files are
rewritten in place, and `case_file.json` embeds only the later run's events (parent reproduction:
9 invocations -> 99 events). A judge running the documented commands quickly then gets one
directory presenting two different histories.

The collision is constructed deterministically with a FROZEN clock, never by hoping two runs
land in the same second.

Run: env -u PYTHONPATH /usr/bin/python3 -m unittest tests.test_w43_should_run_id -v
"""
from __future__ import annotations

import contextlib
import io
import json
import re
import tempfile
import unittest
from datetime import datetime as real_datetime
from datetime import timezone
from pathlib import Path
from unittest import mock

from app import cli
from app.events import EventLog

ROOT = Path(__file__).resolve().parents[1]
RECORD = ROOT / "data" / "packs" / "ryde-synth-v1" / "disputes" / "RD-0101.json"
#: The instant both invocations believe it is. Frozen, so the collision is not luck.
FROZEN_NOW = real_datetime(2026, 10, 13, 4, 56, 19, tzinfo=timezone.utc)
#: The run id the documented second-precision stamp produces for RD-0101 at that instant.
DOCUMENTED_RUN_ID = "20261013T045619Z-RD-0101"


class _FrozenDateTime(real_datetime):
    """A datetime whose ``now()`` is always one fixed instant."""

    @classmethod
    def now(cls, tz=None):  # noqa: D401 - the seam the run-id clock is read through
        return FROZEN_NOW


def _events(run_dir: Path):
    return [
        json.loads(line)
        for line in (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _run_dirs(out: Path):
    return sorted(path for path in out.iterdir() if path.is_dir())


class SameSecondRunIdTests(unittest.TestCase):
    """Two documented invocations, one frozen second, one --out directory."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="w43-s1-")
        self.addCleanup(self._tmp.cleanup)
        self.out = Path(self._tmp.name) / "runs"
        patcher = mock.patch.object(cli, "datetime", _FrozenDateTime)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _cli(self, *args: str) -> int:
        """One CLI run, with the report it prints kept out of the test output."""
        with contextlib.redirect_stdout(io.StringIO()):
            return cli.main(["--llm", "mock", "--out", str(self.out), *args])

    def _documented_pack_form(self) -> int:
        """README:122 — the dispute id inside a named pack."""
        return self._cli("--pack", "ryde-synth-v1", "--dispute", "RD-0101")

    def _documented_record_form(self) -> int:
        """README:130-131 — the same record by path. Absolute, so the CWD cannot matter,
        but the same file and so the same dispute id the documented relative form names."""
        return self._cli("--dispute", str(RECORD))

    def _both_documented_forms(self):
        return [self._documented_pack_form(), self._documented_record_form()]

    # ------------------------------------------------------------------ the collision

    def test_two_invocations_in_one_second_are_two_run_directories(self):
        self.assertEqual([cli.EXIT_OK, cli.EXIT_OK], self._both_documented_forms())
        self.assertEqual(
            2, len(_run_dirs(self.out)),
            "two documented invocations in one second must own two run directories, "
            "not merge into one log",
        )

    def test_each_run_directory_holds_one_complete_self_consistent_history(self):
        self._both_documented_forms()
        run_dirs = _run_dirs(self.out)
        self.assertEqual(2, len(run_dirs), "expected one directory per invocation")
        lengths = []
        for run_dir in run_dirs:
            events = _events(run_dir)
            lengths.append(len(events))
            self.assertEqual(
                list(range(1, len(events) + 1)), [event["seq"] for event in events],
                "%s: sequence numbers must run 1..n and never restart" % run_dir.name,
            )
            self.assertEqual(
                1, sum(1 for event in events if event["type"] == "run.started"),
                "%s: one run directory carries exactly one run.started" % run_dir.name,
            )
            self.assertEqual(
                {run_dir.name}, {event["run_id"] for event in events},
                "%s: every event in the log must name this run" % run_dir.name,
            )
            payloads = sorted(path.name for path in (run_dir / "payloads").iterdir())
            self.assertEqual(
                len(payloads), len(set(payloads)),
                "%s: payload file names must not be reused" % run_dir.name,
            )
            case = json.loads((run_dir / "case_file.json").read_text(encoding="utf-8"))
            self.assertEqual(run_dir.name, case["run_id"])
            self.assertEqual(
                len(events), len(case["events"]),
                "%s: the case file must embed its own run's events, not another run's"
                % run_dir.name,
            )
        self.assertEqual(
            1, len(set(lengths)),
            "both invocations ran the same case to completion, so each log must be the "
            "full run: %s" % lengths,
        )

    def test_a_lone_run_keeps_the_documented_run_id_shape(self):
        """Preserve pin: the visible name stays `<UTC second>-<dispute slug>`. The fix
        disambiguates a collision; it does not re-spell the name a judge already reads."""
        self.assertEqual(cli.EXIT_OK, self._documented_pack_form())
        run_dirs = _run_dirs(self.out)
        self.assertEqual(1, len(run_dirs))
        self.assertTrue(
            re.fullmatch(r"\d{8}T\d{6}Z-RD-0101", run_dirs[0].name),
            "unexpected run directory name %r" % run_dirs[0].name,
        )
        self.assertEqual(DOCUMENTED_RUN_ID, run_dirs[0].name)

    # ------------------------------------------------------------------ belt and braces

    def test_event_log_refuses_a_run_directory_an_earlier_run_filled(self):
        run_dir = Path(self._tmp.name) / "owned"
        first = EventLog(run_dir, "owned")
        first.emit("run.started", from_="system", to="system", summary="started")
        with self.assertRaises(ValueError):
            EventLog(run_dir, "owned")
        self.assertEqual([1], [event["seq"] for event in _events(run_dir)],
                         "the refusal must not have appended to the first run's log")

    def test_a_directory_that_is_not_yet_a_run_is_usable(self):
        """Preserve pin: a directory that merely EXISTS is not a run — a fresh --out path, or
        a temporary directory the caller made first. The refusal names a run, not a path."""
        run_dir = Path(self._tmp.name) / "fresh"
        run_dir.mkdir()
        (run_dir / "unrelated.txt").write_text("x", encoding="utf-8")
        log = EventLog(run_dir, "fresh")
        log.emit("run.started", from_="system", to="system", summary="started")
        self.assertEqual([1], [event["seq"] for event in _events(run_dir)])

    def test_event_log_refuses_a_run_directory_holding_payloads_without_a_log(self):
        run_dir = Path(self._tmp.name) / "half-run"
        (run_dir / "payloads").mkdir(parents=True)
        with self.assertRaises(ValueError):
            EventLog(run_dir, "half-run")

    def test_event_log_refuses_a_directory_left_with_a_log_but_no_payloads(self):
        """A run's log is a run's record, whatever else is missing from the directory."""
        run_dir = Path(self._tmp.name) / "log-only"
        run_dir.mkdir()
        (run_dir / "events.jsonl").write_text(
            "{\"schema_version\": \"1.0\", \"seq\": 1, \"type\": \"run.started\"}\n",
            encoding="utf-8")
        with self.assertRaises(ValueError):
            EventLog(run_dir, "log-only")

    def test_an_explicit_run_id_that_already_exists_fails_cleanly(self):
        """`--run-id` is an override, so the collision is the operator's to fix: the CLI
        must say so on stderr and exit non-zero, never die with a traceback and never
        append a second history into the first run's directory."""
        args = ["--pack", "ryde-synth-v1", "--dispute", "RD-0101", "--run-id", "fixed-run-id",
                "--llm", "mock", "--out", str(self.out)]
        self.assertEqual(cli.EXIT_OK, cli.main(args))
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            second = cli.main(args)
        self.assertEqual(cli.EXIT_FAILED, second)
        self.assertIn("refusing to reuse the run directory", stderr.getvalue())
        run_dirs = _run_dirs(self.out)
        self.assertEqual(["fixed-run-id"], [path.name for path in run_dirs])
        events = _events(run_dirs[0])
        self.assertEqual(
            list(range(1, len(events) + 1)), [event["seq"] for event in events],
            "the refused run must not have appended to the first run's log",
        )
        self.assertEqual(
            1, sum(1 for event in events if event["type"] == "run.started"),
            "one run directory carries exactly one run.started",
        )


if __name__ == "__main__":
    unittest.main()
