"""W23 B1 acceptance target: dispute status lookup and the two demo accounts.

RED until the build lane ships GET /api/disputes/<dispute_id>, GET /api/demo/rider and
GET /api/demo/driver (contract W23 B1 section 3, the operator rulings 2026-10-03 items 1a, 5, 6).

Pinned: which folders are runs (direct children only, eval runs never seen, corrupt files
skipped), which runs are party-filed (dispute.json), which run is a dispute's current one
(answered.json supersedes; latest generated_at; tie to the larger run id), both record shapes,
and the driver's read-only view.
"""

from __future__ import annotations

import contextlib
import io
import json
import unittest

from tests.w23_support import (
    ACCOUNT_ENTRY_KEYS,
    HUMAN_SENTENCE,
    PARTY_VIEW_KEYS,
    SYNTH_DIR,
    UNDER_REVIEW,
    Server,
    body,
)

NEEDS_INFO = ("Thank you — we need a little more information before we can continue with your case. "
              "Please answer the questions below and submit them, and we will take a fresh look as "
              "soon as your answers arrive.")
SUPPORT = "Thank you for your report. It has been passed to our support team, who will follow up with you."
ORG_T109_LABEL = "Changi Airport Terminal 3 to Ang Mo Kio (Kebun Baru)"


class _ServerCase(unittest.TestCase):
    pack_dir = None

    def setUp(self):
        self.server = Server(pack_dir=self.pack_dir)

    def tearDown(self):
        self.server.close()

    def get(self, path):
        status, headers, raw = self.server.raw("GET", path)
        self.assertEqual("no-store", headers.get("Cache-Control"), path)
        return status, (json.loads(raw) if raw else None)

    def rider(self):
        status, payload = self.get("/api/demo/rider")
        self.assertEqual(200, status)
        return payload

    def driver(self):
        status, payload = self.get("/api/demo/driver")
        self.assertEqual(200, status)
        return payload


# ------------------------------------------------------------------- lookup


class DisputeLookup(_ServerCase):
    def test_lookup_returns_the_party_view(self):
        view = self.server.file("T-RD0109", 5.81)
        status, looked = self.get("/api/disputes/%s" % view["dispute_id"])
        self.assertEqual(200, status)
        self.assertEqual(PARTY_VIEW_KEYS, list(looked))
        self.assertEqual(view, looked)

    def test_unknown_and_malformed_references_are_404(self):
        self.server.file("T-RD0109", 5.81)
        for ref in ("PF-NOPE0000", "A" * 64, "A" * 65, "bad%20id", "PF-%2F", "..", "%2e%2e"):
            with self.subTest(ref=ref):
                status, payload = self.get("/api/disputes/%s" % ref)
                self.assertEqual(404, status)
        self.assertEqual((404, {"error": "unknown dispute"}), self.get("/api/disputes/PF-NOPE0000"))

    def test_the_reference_pattern_boundary(self):
        view = self.server.file("T-RD0109", 5.81)
        for ref, expected in (("A" * 64, 200), ("A" * 65, 404), ("a.b_c-D9", 200)):
            # HAND-MADE SHAPE: no filing mints these ids; the copy carries them on both files.
            def edit(doc, ref=ref):
                if "dispute_ticket" in doc:
                    doc["dispute_ticket"]["dispute_id"] = ref
                doc["dispute_id"] = ref
            self.server.copy_run(view["run_id"], "copy-%d-%s" % (len(ref), ref[:3]), edit_case=edit, edit_dispute=edit)
            with self.subTest(ref=ref[:10], length=len(ref)):
                status, payload = self.get("/api/disputes/%s" % ref)
                self.assertEqual(expected, status, payload)

    def test_command_line_runs_are_not_party_filed(self):
        run_id = self.server.cli_run()
        case = self.server.case(run_id)
        self.assertEqual("RD-0109", case["dispute_id"])
        self.assertEqual((404, {"error": "unknown dispute"}), self.get("/api/disputes/RD-0109"))
        self.assertEqual([], self.rider()["disputes"])
        self.assertEqual([], self.driver()["disputes"])

    def test_a_human_decision_shows_on_the_lookup(self):
        view = self.server.file("T-RD0109", 55.16)
        self.assertEqual("under_review", self.get("/api/disputes/%s" % view["dispute_id"])[1]["status"])
        self.assertEqual(200, self.server.decide(view["run_id"], body("change", action="refund", amount_sgd=50.0))[0])
        self.assertEqual({"run_id": view["run_id"], "dispute_id": view["dispute_id"], "status": "decided",
                          "message": "Decision: refund of SGD 50.00. " + HUMAN_SENTENCE, "questions": []},
                         self.get("/api/disputes/%s" % view["dispute_id"])[1])


class CurrentRun(_ServerCase):
    def _needs_info(self):
        view = self.server.file("T-RD0109", 5.81, expected_route="")
        self.assertEqual("needs_info", view["status"], view)
        return view

    def _answer(self, view):
        reply = {"answers": [{"question": q, "answer": "I have nothing more to add"} for q in view["questions"]]}
        status, second = self.server.json("POST", "/api/disputes/%s/answers" % view["run_id"], reply)
        self.assertEqual(200, status, second)
        return second

    def test_an_answered_run_is_superseded_by_its_round_two_run(self):
        first = self._needs_info()
        self.assertEqual(first, self.get("/api/disputes/%s" % first["dispute_id"])[1])
        second = self._answer(first)
        # HAND-MADE SHAPE: the answered run is stamped LATER than its round-two run, so only
        # answered.json (not generated_at) can tell them apart.
        case_path = self.server.run_dir(first["run_id"]) / "case_file.json"
        case = json.loads(case_path.read_text(encoding="utf-8"))
        case["generated_at"] = "2099-01-01T00:00:00+00:00"
        case_path.write_text(json.dumps(case), encoding="utf-8")
        looked = self.get("/api/disputes/%s" % first["dispute_id"])[1]
        self.assertEqual(second, looked)
        self.assertEqual([second["run_id"]], [e["run_id"] for e in self.rider()["disputes"]])

    def test_latest_generated_at_then_larger_run_id(self):
        first = self.server.file("T-RD0109", 5.81)
        # HAND-MADE SHAPE: duplicate runs of one dispute, stamped to order them.
        def stamp(value):
            return lambda case: case.__setitem__("generated_at", value)
        self.server.copy_run(first["run_id"], "00000000T000000Z-aaaaaaaa", edit_case=stamp("2098-01-01T00:00:00+00:00"))
        self.server.copy_run(first["run_id"], "99999999T999999Z-zzzzzzzz", edit_case=stamp("2098-01-01T00:00:00+00:00"))
        self.assertEqual("99999999T999999Z-zzzzzzzz", self.get("/api/disputes/%s" % first["dispute_id"])[1]["run_id"])
        self.server.copy_run(first["run_id"], "00000000T000000Z-bbbbbbbb", edit_case=stamp("2098-06-01T00:00:00+00:00"))
        self.assertEqual("00000000T000000Z-bbbbbbbb", self.get("/api/disputes/%s" % first["dispute_id"])[1]["run_id"])
        self.assertEqual(1, len(self.rider()["disputes"]), "one entry per dispute, not per run")

    def test_only_direct_children_are_runs(self):
        from app import eval as eval_module

        view = self.server.file("T-RD0109", 55.16)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            eval_module.main(["--llm", "mock", "--pack", "ryde-synth-v1", "--out", str(self.server.out / "eval-test")])
        nested = list((self.server.out / "eval-test").rglob("case_file.json"))
        self.assertTrue(nested, "precondition: the eval wrote runs under the output folder")
        # HAND-MADE SHAPE: a party-filed run moved one level down must vanish as well.
        self.server.copy_run(view["run_id"], "nested-run", parent=self.server.out / "archive",
                             edit_case=lambda c: c.__setitem__("dispute_id", "PF-NESTED01"),
                             edit_dispute=lambda r: r["dispute_ticket"].__setitem__("dispute_id", "PF-NESTED01"))
        self.assertEqual(404, self.get("/api/disputes/PF-NESTED01")[0])
        self.assertEqual([view["dispute_id"]], [e["dispute_id"] for e in self.rider()["disputes"]])
        self.assertEqual([view["run_id"]], [c["run_id"] for c in self.get("/api/review/queue")[1]["cases"]])

    def test_corrupt_runs_are_skipped_never_a_500(self):
        view = self.server.file("T-RD0109", 55.16)
        for name, text in (("bad-json", "{"), ("array", "[]"), ("empty", "")):
            folder = self.server.out / name
            folder.mkdir()
            (folder / "case_file.json").write_text(text, encoding="utf-8")  # HAND-MADE SHAPE
            (folder / "dispute.json").write_text("{}", encoding="utf-8")
        (self.server.out / "no-case-file").mkdir()
        (self.server.out / "stray.txt").write_text("x", encoding="utf-8")
        for path in ("/api/disputes/%s" % view["dispute_id"], "/api/demo/rider", "/api/demo/driver",
                     "/api/review/queue", "/api/review/overrides"):
            with self.subTest(path=path):
                self.assertEqual(200, self.get(path)[0])
        self.assertEqual(1, len(self.rider()["disputes"]))


# ------------------------------------------------------------------- accounts


class RiderAccount(_ServerCase):
    def test_account_shape_and_entry(self):
        view = self.server.file("T-RD0109", 5.81)
        payload = self.rider()
        self.assertEqual(["account", "disputes"], sorted(payload))
        self.assertEqual({"kind": "rider", "label": "Demo account"}, payload["account"])
        self.assertEqual(1, len(payload["disputes"]))
        entry = payload["disputes"][0]
        self.assertEqual(ACCOUNT_ENTRY_KEYS, list(entry))
        record = json.loads((self.server.run_dir(view["run_id"]) / "dispute.json").read_text(encoding="utf-8"))
        self.assertEqual(view, {k: entry[k] for k in PARTY_VIEW_KEYS})
        self.assertEqual(record["dispute_ticket"]["filed_at"], entry["filed_at"])
        self.assertEqual(("route_deviation", ORG_T109_LABEL), (entry["category"], entry["trip_label"]))

    def test_rider_filings_only_with_the_form_category(self):
        rider = self.server.file("T-RD0109", 5.81)
        driver = self.server.file("T-RD0109", 5.81, filed_by="driver")
        support = self.server.file("T-RD0109", None, category="safety_incident")
        entries = {e["dispute_id"]: e for e in self.rider()["disputes"]}
        self.assertEqual({rider["dispute_id"], support["dispute_id"]}, set(entries))
        self.assertNotIn(driver["dispute_id"], entries)
        self.assertEqual(("safety_incident", "passed_to_support", SUPPORT),
                         tuple(entries[support["dispute_id"]][k] for k in ("category", "status", "message")))

    def test_needs_info_keeps_its_questions_for_the_rider(self):
        view = self.server.file("T-RD0109", 5.81, expected_route="")
        entry = self.rider()["disputes"][0]
        self.assertEqual(("needs_info", NEEDS_INFO, view["questions"], view["run_id"]),
                         (entry["status"], entry["message"], entry["questions"], entry["run_id"]))
        self.assertTrue(entry["questions"])

    def test_newest_filed_first_ties_by_dispute_id(self):
        views = [self.server.file("T-RD0109", 5.81) for _ in range(3)]
        stamps = ["2026-09-01T10:00:00+08:00", "2026-09-03T10:00:00+08:00", "2026-09-03T10:00:00+08:00"]
        for view, stamp in zip(views, stamps):
            # HAND-MADE SHAPE: filings seconds apart cannot carry days-apart filing times.
            path = self.server.run_dir(view["run_id"]) / "dispute.json"
            record = json.loads(path.read_text(encoding="utf-8"))
            record["dispute_ticket"]["filed_at"] = stamp
            path.write_text(json.dumps(record), encoding="utf-8")
        tied = sorted(v["dispute_id"] for v in views[1:])
        self.assertEqual(tied + [views[0]["dispute_id"]], [e["dispute_id"] for e in self.rider()["disputes"]])


class DriverAccount(_ServerCase):
    def test_constant_and_account_shape(self):
        from app.server import DEMO_DRIVER_ID

        self.assertEqual("D-2009", DEMO_DRIVER_ID)
        payload = self.driver()
        self.assertEqual({"kind": "driver", "label": "Demo account", "driver_id": "D-2009"}, payload["account"])
        self.assertEqual([], payload["disputes"])

    def test_disputes_about_the_demo_drivers_trips_from_any_filer(self):
        rider = self.server.file("T-RD0109", 5.81)
        driver = self.server.file("T-RD0109", 5.81, filed_by="driver")
        other_trip = self.server.file("T-RD0101", 5.81)
        entries = {e["dispute_id"]: e for e in self.driver()["disputes"]}
        self.assertEqual({rider["dispute_id"], driver["dispute_id"]}, set(entries))
        self.assertNotIn(other_trip["dispute_id"], entries)
        entry = entries[rider["dispute_id"]]
        self.assertEqual(ACCOUNT_ENTRY_KEYS, list(entry))
        self.assertEqual({"run_id": "", "dispute_id": rider["dispute_id"], "status": "decided",
                          "message": rider["message"], "questions": []}, {k: entry[k] for k in PARTY_VIEW_KEYS})
        self.assertEqual(("route_deviation", ORG_T109_LABEL), (entry["category"], entry["trip_label"]))

    def test_filer_facing_statuses_read_as_under_review(self):
        asking = self.server.file("T-RD0109", 5.81, expected_route="")
        support = self.server.file("T-RD0109", None, category="safety_incident")
        held = self.server.file("T-RD0109", 55.16)
        self.assertEqual(("needs_info", "passed_to_support", "under_review"),
                         (asking["status"], support["status"], held["status"]))
        entries = {e["dispute_id"]: e for e in self.driver()["disputes"]}
        for view in (asking, support, held):
            with self.subTest(status=view["status"]):
                self.assertEqual({"run_id": "", "dispute_id": view["dispute_id"], "status": "under_review",
                                  "message": UNDER_REVIEW, "questions": []},
                                 {k: entries[view["dispute_id"]][k] for k in PARTY_VIEW_KEYS})

    def test_a_human_decision_reaches_the_driver(self):
        held = self.server.file("T-RD0109", 55.16)
        self.assertEqual(200, self.server.decide(held["run_id"], body("reject"))[0])
        entry = self.driver()["disputes"][0]
        self.assertEqual(("decided", "Decision: no action. " + HUMAN_SENTENCE, ""),
                         (entry["status"], entry["message"], entry["run_id"]))


class SynthShapeAccounts(_ServerCase):
    """The pack's own record shape: top-level filed_by / filed_at / category, trip.driver_id."""

    pack_dir = SYNTH_DIR

    def test_both_accounts_read_the_top_level_shape(self):
        rider = self.server.file("T-RD0109", 5.81)
        driver = self.server.file("T-RD0109", 5.81, filed_by="driver")
        record = json.loads((self.server.run_dir(rider["run_id"]) / "dispute.json").read_text(encoding="utf-8"))
        self.assertNotIn("dispute_ticket", record)
        riders = self.rider()["disputes"]
        self.assertEqual([rider["dispute_id"]], [e["dispute_id"] for e in riders])
        self.assertEqual((record["filed_at"], "route_deviation", "T-RD0109"),
                         (riders[0]["filed_at"], riders[0]["category"], riders[0]["trip_label"]))
        self.assertEqual(sorted([rider["dispute_id"], driver["dispute_id"]]),
                         sorted(e["dispute_id"] for e in self.driver()["disputes"]))


if __name__ == "__main__":
    unittest.main()
