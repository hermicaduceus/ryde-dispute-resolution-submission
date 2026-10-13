"""W44 (S-F01): a refused run-id collision must never delete the prior run.

Sol code review (2026-10-13), defect S-F01, through the real `POST /api/disputes` route:

  * W43 made `app/events.py` refuse a run directory that already holds a run, so
    `EventLog(run_dir, run_id)` can now raise inside `app/server.py` `_run_record`.
  * `_run_record`'s `except Exception:` handler then `shutil.rmtree`s the run directory
    and re-raises — on a collision that directory is the FIRST run's, so the second
    filer's request destroys the first filer's events, payloads and case file and
    answers HTTP 500.

The contract these tests pin, exercised through the real server and the real filing
route (`_new_run_id` is the injected seam — the collision is constructed, never hoped
for):

  * a filing whose generated id collides with an existing complete run retries with
    fresh ids (the retry rides over repeated collisions — at least 3 attempts) and
    succeeds as a new, complete run;
  * the prior run's directory is byte-identical afterwards: cleanup may remove only
    what the failing call itself created, never anything else;
  * if every attempt collides, the request fails cleanly and still deletes nothing;
  * once a retry has succeeded, a filing with a genuinely free id still works.

RED on clean HEAD (before the W44 fix): the first collision deletes the prior run and
answers 500, so these tests fail on the byte-identical and status assertions.
"""

from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path
from unittest import mock

from app import server
from tests.w23_support import ORG_DIR, Server

#: A rider route-deviation filing that validates: the same shape Server.file() posts.
FILING = {
    "category": "route_deviation",
    "filed_by": "rider",
    "trip_id": "T-RD0109",
    "description": "He went a very long way round.",
    "claim_amount_sgd": 55.16,
    "answers": {
        "expected_route": "Expressway, about 31 km.",
        "was_route_agreed": "No",
        "asked_driver_to_stop": "No",
        "safety_concern": "No",
    },
}


def _snapshot(run_dir: Path) -> dict:
    """Every entry under the run directory: relative path -> sha256, None for a dir.

    Byte-identical means byte-identical: every file's content is hashed, so a
    rewritten or appended file changes the snapshot even if its size does not.
    """
    snap = {}
    for path in sorted(run_dir.rglob("*")):
        rel = path.relative_to(run_dir).as_posix()
        snap[rel] = None if path.is_dir() else hashlib.sha256(path.read_bytes()).hexdigest()
    return snap


def _run_names(out: Path):
    return sorted(path.name for path in out.iterdir() if path.is_dir())


class ACollidedRunIdNeverDeletesThePriorRun(unittest.TestCase):
    """The defect: `_run_record`'s cleanup deletes the directory the collision names."""

    def setUp(self):
        self.server = Server(pack_dir=ORG_DIR)
        self.addCleanup(self.server.close)

    def _file(self):
        return self.server.json("POST", "/api/disputes", dict(FILING))

    def _file_complete_run(self) -> str:
        status, view = self._file()
        self.assertEqual(200, status, view)
        return view["run_id"]

    def _assert_run_complete(self, run_id: str) -> None:
        run_dir = self.server.run_dir(run_id)
        self.assertTrue((run_dir / "dispute.json").is_file(), "the filing must be stored")
        case = json.loads((run_dir / "case_file.json").read_text(encoding="utf-8"))
        self.assertEqual(run_id, case["run_id"])
        self.assertIn("resolution", case)
        events = [
            json.loads(line)
            for line in (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertTrue(events, "a complete run records its event strip")
        self.assertEqual({run_id}, {event["run_id"] for event in events})

    def test_a_colliding_filing_retries_and_the_prior_run_survives(self):
        prior_run = self._file_complete_run()
        before = _snapshot(self.server.run_dir(prior_run))

        # The first id the generator hands out is the existing run's: the exact
        # collision the defect destroys data on. The retry then gets a fresh id.
        fresh = "w44-retry-fresh-0001"
        ids = iter([prior_run, fresh, "w44-retry-fresh-0002"])
        with mock.patch.object(server, "_new_run_id", lambda: next(ids)):
            status, second = self._file()

        self.assertEqual(200, status, "a refused id must be retried, not answered 500: %s" % second)
        self.assertEqual(fresh, second["run_id"], "the retry must use a fresh id")
        self.assertEqual(
            before, _snapshot(self.server.run_dir(prior_run)),
            "the prior run's directory must be byte-identical: events, payloads and case file",
        )
        self._assert_run_complete(second["run_id"])

        # And the generator still works for a genuinely free id afterwards.
        third = self._file_complete_run()
        self.assertNotIn(third, (prior_run, second["run_id"]))
        self._assert_run_complete(third)
        self.assertEqual(before, _snapshot(self.server.run_dir(prior_run)))

    def test_the_retry_rides_over_repeated_collisions(self):
        prior_run = self._file_complete_run()
        before = _snapshot(self.server.run_dir(prior_run))

        # Two refused ids in a row: a retry that only tries twice cannot succeed, so
        # this pins the brief's "at least 3 attempts" against a real second filing.
        fresh = "w44-retry-fresh-0003"
        ids = iter([prior_run, prior_run, fresh, "w44-retry-fresh-0004"])
        with mock.patch.object(server, "_new_run_id", lambda: next(ids)):
            status, second = self._file()

        self.assertEqual(200, status, second)
        self.assertEqual(fresh, second["run_id"])
        self.assertEqual(before, _snapshot(self.server.run_dir(prior_run)))
        self._assert_run_complete(second["run_id"])

    def test_an_exhausted_retry_errors_cleanly_and_deletes_nothing(self):
        prior_run = self._file_complete_run()
        before = _snapshot(self.server.run_dir(prior_run))
        dirs_before = _run_names(self.server.out)

        # Every attempt collides. The handler may answer with an error — but the
        # cleanup promise holds: nothing this call did not create may be removed.
        with mock.patch.object(server, "_new_run_id", lambda: prior_run):
            status, payload = self._file()

        self.assertNotEqual(200, status, "an id that never becomes free cannot succeed")
        self.assertGreaterEqual(status, 400)
        self.assertIn("error", payload, payload)
        self.assertEqual(
            before, _snapshot(self.server.run_dir(prior_run)),
            "an exhausted retry must delete nothing",
        )
        self.assertEqual(dirs_before, _run_names(self.server.out),
                         "no half-created directory may be left behind")


if __name__ == "__main__":
    unittest.main()
