"""Tests for deploy/edgeone/package.py: the bundle is the shipped app plus the deploy files only.

    cd deploy/edgeone/tests && python3 -m unittest test_package -v
"""
import hashlib
import re
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import package  # noqa: E402

REPO = package.REPO


def _files(root):
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for p in sorted(Path(root).rglob("*")) if p.is_file()}


class Bundle(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.site = package.build(Path(cls.tmp.name) / "site")
        cls.files = _files(cls.site)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_app_and_data_are_byte_identical_to_the_repo(self):
        for name in ("app", "data"):
            src = {k: v for k, v in _files(REPO / name).items() if not package._skip(Path(k))}
            got = {k[len("cloud-functions/%s/" % name):]: v for k, v in self.files.items()
                   if k.startswith("cloud-functions/%s/" % name)}
            self.assertTrue(src, name)
            self.assertEqual(src, got, name)

    def test_ui_differs_only_by_the_six_console_links(self):
        src = {k: v for k, v in _files(REPO / "ui").items() if not package._skip(Path(k))}
        got = {k: v for k, v in self.files.items()
               if not k.startswith("cloud-functions/") and k != "edgeone.json"}
        self.assertEqual(sorted(src), sorted(got))
        changed = sorted(k for k in src if src[k] != got[k])
        self.assertEqual(sorted(rel for rel, _, _ in package.HREF_REPOINTS), changed)
        for rel, old, new in package.HREF_REPOINTS:
            self.assertEqual(src[rel].decode().replace(old, new), got[rel].decode(), rel)

    def test_no_console_link_points_at_the_redirected_root(self):
        for rel, old, new in package.HREF_REPOINTS:
            html = self.files[rel].decode()
            self.assertNotIn(old, html, rel)
            self.assertEqual(1, html.count(new), rel)
        for rel in ("index.html", "party/index.html", "party/driver.html",
                    "party/driver-filing.html", "party/status.html"):
            links = re.findall(r'<a href="([^"]*)"[^>]*>Operator console</a>', self.files[rel].decode())
            self.assertEqual(1, len(links), rel)
            self.assertTrue(links[0].endswith("index.html"), (rel, links))

    def test_deploy_files_are_exactly_the_three(self):
        extra = sorted(k for k in self.files
                       if not k.startswith(("cloud-functions/app/", "cloud-functions/data/"))
                       and (k.startswith("cloud-functions/") or k == "edgeone.json"))
        self.assertEqual(["cloud-functions/api/[[default]].py", "cloud-functions/ryde_deploy_policy.py",
                          "edgeone.json"], extra)

    def test_root_redirects_to_the_dispute_page(self):
        import json
        config = json.loads(self.files["edgeone.json"])
        self.assertEqual([{"source": "/", "destination": "/party/", "statusCode": 302}], config["redirects"])
        self.assertEqual(120, config["cloudFunctions"]["python"]["maxDuration"])

    def test_no_caches_or_os_litter(self):
        for k in self.files:
            self.assertFalse(package._skip(Path(k)), k)

    def test_zip_is_deterministic(self):
        a = package.write_zip(self.site, Path(self.tmp.name) / "a.zip")
        b = package.write_zip(self.site, Path(self.tmp.name) / "b.zip")
        self.assertEqual(hashlib.sha256(a.read_bytes()).hexdigest(), hashlib.sha256(b.read_bytes()).hexdigest())
        with zipfile.ZipFile(a) as zf:
            self.assertEqual(sorted(self.files), sorted(zf.namelist()))


class Refusals(unittest.TestCase):
    def test_policy_carrier_must_match_docs_policy(self):
        package.check_policy_carrier()  # the committed carrier matches
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp)
            (fake / "docs").mkdir()
            (fake / "docs" / "policy.md").write_bytes((REPO / "docs" / "policy.md").read_bytes() + b"\n")
            with self.assertRaises(SystemExit):
                package.check_policy_carrier(fake)

    def test_a_missing_link_stops_the_build(self):
        saved = package.HREF_REPOINTS
        try:
            package.HREF_REPOINTS = saved + [("index.html", "no such text", "x")]
            with tempfile.TemporaryDirectory() as tmp, self.assertRaises(SystemExit):
                package.build(Path(tmp) / "site")
        finally:
            package.HREF_REPOINTS = saved

    def test_refuses_a_non_empty_output_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "keep.txt").write_text("x")
            with self.assertRaises(SystemExit):
                package.build(Path(tmp))


if __name__ == "__main__":
    unittest.main()
