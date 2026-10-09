"""Parent-added pins: a linked run directory cannot bypass the leaf bounds."""
import json
import shutil
import unittest
from tests.test_w35_r2_K import RunFixture, get


class RunDirectoryBounds(RunFixture):
    def escape_run(self):
        target = self.outside / "external-run"
        shutil.move(str(self.run_dir()), str(target))
        self.run_dir().symlink_to(target, target_is_directory=True)
        self.assertTrue(self.run_dir().is_dir(), "fixture must be a valid external directory link")

    def test_lists_do_not_read_a_run_directory_outside_the_output_root(self):
        self.escape_run()
        for endpoint, field in (("/api/review/queue", "cases"),
                                ("/api/review/runs", "runs"),
                                ("/api/demo/rider", "disputes")):
            with self.subTest(endpoint=endpoint):
                status, data = get(self.base, endpoint)
                self.assertEqual(200, status)
                self.assertEqual([], data[field], "external run directory must not appear")
        self.assertEqual(404, get(self.base, "/api/review/%s/case" % self.run_id)[0])
        self.assertEqual(404, get(self.base, "/api/disputes/%s" % self.dispute_id)[0])

    def test_overrides_do_not_read_an_external_run_directory(self):
        self.decide()
        status, data = get(self.base, "/api/review/overrides")
        self.assertEqual(200, status)
        self.assertTrue(data["groups"], "fixture contains a stored rejection")
        self.escape_run()
        status, data = get(self.base, "/api/review/overrides")
        self.assertEqual(200, status)
        self.assertEqual([], data["groups"])

    def test_internal_directory_link_remains_readable(self):
        target = self.server.out / "stored" / "internal-run"
        target.parent.mkdir()
        shutil.move(str(self.run_dir()), str(target))
        self.run_dir().symlink_to(target, target_is_directory=True)
        self.assertIn(self.run_id, self.listed())
        self.assertIn(self.run_id, self.queued())
        self.assertIn(self.dispute_id, self.rider_entries())
        self.assertEqual(200, get(self.base, "/api/review/%s/case" % self.run_id)[0])

    def test_root_alias_and_broken_directory_links_are_skipped(self):
        from app.server import _direct_runs
        (self.server.out / "root-alias").symlink_to(self.server.out, target_is_directory=True)
        (self.server.out / "loop").symlink_to("loop", target_is_directory=True)
        (self.server.out / "dangling").symlink_to(self.outside / "absent", target_is_directory=True)
        # If a file appears at the root it still must not be exposed through root-alias.
        root_case = json.loads((self.run_dir() / "case_file.json").read_text())
        root_case["run_id"] = "root-alias"
        (self.server.out / "case_file.json").write_text(json.dumps(root_case))
        self.assertEqual([self.run_id], [path.name for path, _case in _direct_runs(self.server.out)])
