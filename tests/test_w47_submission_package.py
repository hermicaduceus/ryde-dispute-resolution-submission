"""W47 acceptance: package one selected source revision for the teammate's live copy.

Contract: the W47 live-submission-fallback brief. Written RED-first by the planner; the
builder makes this file green without editing it.

What is pinned, and why each pin exists
---------------------------------------

* **The inventory is a Git tree.** The archive is built from ONE explicitly selected
  committed revision read through ``git ls-tree``/``git cat-file``. A recursive ZIP of the
  development folder would ship build output, run output, a stale ``__pycache__`` and any
  half-finished file the operator had open. ``test_all_entries_share_one_top_level_folder``
  and the manifest tests pin the shape; the junk test pins the omissions.
* **A tracked credential stops the run.** ``.env.live`` must never be inside the archive,
  and neither must an accidentally tracked key file or a filled-in env template. Refusing
  (not silently omitting) is deliberate: an omission would hide a real defect in the
  selected revision, and a "clean" archive built from a tree that contains a key is a
  false claim. The refusal message names the PATH and the rule, never the value — a
  refusal gets quoted into reports and chat.
* **The tool never reads a credential — proven behaviourally.** The packager reads Git
  objects and nothing else. The proof is behavioural: one test poisons the child
  environment with obviously fake key values and proves nothing from it reaches the
  archive, the manifest, or the output, and the release gate compares the package against
  the ACTUAL live key bytes privately. The AST import allowlist further down is a
  structural guard, NOT a proof that no credential is read, and is never reported as one.
* **Wrapper bytes and modes survive.** ``start-live.bat`` needs CRLF (cmd.exe), so the ZIP
  must carry the committed CRLF bytes; ``start-live.command`` needs its executable bit, so
  the ZIP's own ``external_attr`` must carry 0755. Both are checked from inside the ZIP.
* **Rebuilds agree.** Two builds of one revision must have the same inventory and the same
  content hashes; entry timestamps come from the commit, so only the manifest's declared
  build time differs. "The timestamps differ" is never accepted as evidence of a real
  content difference, and vice versa.
* **Output stays outside the repository** and is refused when the path itself is unsafe.

Fixture rules
-------------

Everything runs in ONE isolated fixture repository created under this lane's TMPDIR with a
fixed author (never the operator's identity) and a tiny placeholder live launcher, because a required
file must exist in the selected tree for the inclusion path to be exercised. These
placeholders are fixtures: they are not the reference implementation and are never
packaged for real. The only credential-looking strings here are conspicuously fake
(``AKIDFAKE...`` / ``FAKE-POISON``) and live inside test fixtures, never in a package.

No browser, no server, no network, no live model call: this file is CPU-only.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[1]
PACKAGER = REPO / "tools" / "package_submission.py"
LIVE_DOC = REPO / "docs" / "live-copy.md"

#: Conspicuously fake credential shapes. A fixture, never a real key: the parent compares
#: against the actual live key bytes privately, outside this file.
FAKE_SECRET_ID = "AKID" + "FAKE0W47EXAMPLEtoken0"
FAKE_POISON_KEY = "FAKE-POISON-0W47-NEVER-A-REAL-KEY"

#: This lane's TMPDIR. It is created before any tempfile/subprocess use, and it is where
#: every fixture repository and every produced archive lives.
LANE_TMP = Path(os.environ.get("W47_TEST_TMPDIR")
                or (Path(tempfile.gettempdir()) / "w47-prep-b-tests"))

#: The fixed fixture author: never the operator's identity.
FIXTURE_AUTHOR = "W47 Packaging Fixture"
FIXTURE_EMAIL = "w47-fixture@example.invalid"
FIXTURE_DATE = "2026-10-14T00:00:00+08:00"

REQUIRED_FILES = ("tools/launch_live.py", "start-live.bat", "start-live.command",
                  "docs/live-copy.md")

#: The modules the packager may import. Nothing here can reach a network, and nothing here
#: can read a credential store. A new import must fail this test on purpose.
ALLOWED_IMPORTS = {
    "__future__", "argparse", "datetime", "hashlib", "json", "os", "posixpath", "re",
    "subprocess", "sys", "typing", "zipfile", "pathlib",
}
NETWORK_MODULES = {"socket", "urllib", "http", "requests", "ftplib", "smtplib", "ssl",
                   "telnetlib", "xmlrpc"}

BAT_CRLF = (
    b"@echo off\r\n"
    b"cd /d \"%~dp0\"\r\n"
    b"py -3 -c \"import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)\"\r\n"
    b"py -3 tools\\launch_live.py %*\r\n"
    b"pause\r\n"
)

MAC_SCRIPT = (
    b"#!/bin/bash\n"
    b"cd \"$(dirname \"$0\")\"\n"
    b"exec python3 tools/launch_live.py \"$@\"\n"
)

ENV_EXAMPLE = (
    b"# Ryde - environment template. Commit this file; never commit .env itself.\n"
    b"# One published ADP app per agent; the AppKey is shown on that app's publish page.\n"
    b"TENCENT_ADP_RIDER_APP_KEY=\n"
    b"TENCENT_ADP_DRIVER_APP_KEY=\n"
    b"TENCENT_ADP_JUDGE_APP_KEY=\n"
    b"# TENCENT_ADP_ENDPOINT=\n"
)

FIXTURE_FILES: Dict[str, bytes] = {
    ".gitattributes": b"# Keep the Windows launcher's CRLF line endings exactly as committed.\n*.bat -text\n",
    ".gitignore": b"*.log\nruns/\n__pycache__/\n.DS_Store\n.env\n.env.*\n",
    ".env.example": ENV_EXAMPLE,
    "README.md": b"# Ryde dispute resolution demo\n\nFixture tree for the W47 packaging tests.\n",
    "app/config.json": b'{"confidence_threshold": 0.65, "llm": {"provider": "mock"}}\n',
    "app/config.py": b'"""Runtime configuration (fixture copy)."""\nMOCK_PROVIDER = "mock"\n',
    "data/packs/organiser-style-v1/pack.json": b'{"name": "organiser-style-v1", "case_count": 1}\n',
    "docs/live-copy.md": b"# Live copy instructions (fixture placeholder)\n\nSee the W47 brief.\n",
    "evidence/2026-10-01_note.md": b"# Evidence note\n\nSaved run and provider proof live here.\n",
    "start.bat": BAT_CRLF,
    "start-live.bat": BAT_CRLF,
    "start.command": MAC_SCRIPT,
    "start-live.command": MAC_SCRIPT,
    "tests/support.py": b'"""Fixture test helper."""\n',
    "tests/test_demo.py": b"def test_placeholder():\n    assert True\n",
    "tools/launch.py": b'"""Mock launcher (fixture placeholder)."""\n',
    "tools/launch_live.py": b'"""Live launcher helper (fixture placeholder)."""\n',
    "ui/index.html": b"<!doctype html><title>Ryde console</title>\n",
    "ui/start/index.html": b"<!doctype html><title>Ryde dispute resolution demo</title>\n",
    # Spaces and ordinary Unicode are supported by the portable-path rule: these two files
    # are packed, not refused, and pin that the guard does not over-reach.
    "docs/release notes/README v2.md": b"# Release notes\n\nA path with spaces in it.\n",
    "data/\u00fcn\u00efcode/case-\u4f8b\u5b50.json":
        "{\"name\": \"unicode\", \"kept\": true}\n".encode("utf-8"),
}

#: Tracked junk: omitted from the package, recorded in the manifest as excluded.
JUNK_FILES: Dict[str, bytes] = {
    ".DS_Store": b"\x00\x01macOS junk\x00",
    "tools/deployment/~$ryde-dispute-pitch.pptx": b"\x00stale editor lock\x00",
    "__pycache__/cached.cpython-39.pyc": b"\x00compiled cache\x00",
    "runs/2026-10-14_case.json": b'{"run": "generated, not source"}\n',
    ".pytest_cache/CACHEDIR.TAG": b"Signature: 8a477f597d28d172789f06886806bc55\n",
}

EXECUTABLE_FILES = ("start.command", "start-live.command")


# --------------------------------------------------------------------------- helpers


def _git_env() -> Dict[str, str]:
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env.update({
        "GIT_AUTHOR_NAME": FIXTURE_AUTHOR,
        "GIT_AUTHOR_EMAIL": FIXTURE_EMAIL,
        "GIT_COMMITTER_NAME": FIXTURE_AUTHOR,
        "GIT_COMMITTER_EMAIL": FIXTURE_EMAIL,
        "GIT_AUTHOR_DATE": FIXTURE_DATE,
        "GIT_COMMITTER_DATE": FIXTURE_DATE,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "LC_ALL": "C",
    })
    return env


def git(repo: Path, *args: str) -> str:
    proc = subprocess.run(["git", "-C", str(repo)] + list(args), capture_output=True,
                          env=_git_env(), text=True)
    if proc.returncode != 0:
        raise AssertionError("fixture git %s failed: %s" % (" ".join(args), proc.stderr))
    return proc.stdout


def write_fixture_files(root: Path, files: Dict[str, bytes]) -> None:
    for name, data in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    for name in EXECUTABLE_FILES:
        if name in files:
            (root / name).chmod(0o755)


def init_fixture_repo(root: Path, files: Dict[str, bytes], junk: Dict[str, bytes]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True,
                   capture_output=True, env=_git_env())
    write_fixture_files(root, files)
    write_fixture_files(root, junk)
    # Junk is added with -f on purpose: the point of the test is the file a developer
    # committed by accident, which .gitignore would otherwise have hidden.
    subprocess.run(["git", "-C", str(root), "add", "-f", "-A"], check=True,
                   capture_output=True, env=_git_env())
    subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", "fixture: initial tree"],
                   check=True, capture_output=True, env=_git_env())


def read_zip(path: Path) -> Dict[str, Tuple[zipfile.ZipInfo, bytes]]:
    with zipfile.ZipFile(str(path)) as archive:
        return {info.filename: (info, archive.read(info)) for info in archive.infolist()}


def entry_mode(info: zipfile.ZipInfo) -> int:
    """The full Unix mode word a ZIP extractor restores, from ``external_attr``.

    The file-type bits are kept on purpose: 0o100644 / 0o100755 for a regular file,
    0o120777 for a symlink. Python's own extractor recreates a symlink from 0o120777 and
    would otherwise write a text file holding the target path.
    """
    return info.external_attr >> 16


def load_packager_module():
    spec = importlib.util.spec_from_file_location("w47_package_submission", str(PACKAGER))
    if spec is None or spec.loader is None:
        raise AssertionError("cannot load %s" % PACKAGER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ----------------------------------------------------------------------- base class


class PackageFixture(unittest.TestCase):
    """One shared fixture repository, copied per test, plus the packager's invocation."""

    @classmethod
    def setUpClass(cls):
        # Deliberately does NOT require the packager. A missing implementation must surface
        # as an assertion FAILURE inside each test, never as a setUpClass ERROR; the fixture
        # repository does not need the packager to be built.
        LANE_TMP.mkdir(parents=True, exist_ok=True)
        cls.class_tmp = Path(tempfile.mkdtemp(prefix="w47-submission-", dir=str(LANE_TMP)))
        cls.base_repo = cls.class_tmp / "fixture-repo"
        init_fixture_repo(cls.base_repo, FIXTURE_FILES, JUNK_FILES)
        cls.first_sha = git(cls.base_repo, "rev-parse", "HEAD").strip()
        (cls.base_repo / "README.md").write_bytes(
            FIXTURE_FILES["README.md"] + b"\nA second commit, so an older revision exists.\n")
        subprocess.run(["git", "-C", str(cls.base_repo), "add", "-f", "-A"], check=True,
                       capture_output=True, env=_git_env())
        subprocess.run(["git", "-C", str(cls.base_repo), "commit", "-q", "-m", "fixture: second"],
                       check=True, capture_output=True, env=_git_env())
        cls.head_sha = git(cls.base_repo, "rev-parse", "HEAD").strip()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(str(cls.class_tmp), ignore_errors=True)

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="case-", dir=str(LANE_TMP)))
        self.addCleanup(shutil.rmtree, str(self.tmp), True)

    # -- fixture repository ---------------------------------------------------------

    def copy_repo(self, name: str = "repo") -> Path:
        dest = self.tmp / name
        shutil.copytree(str(self.base_repo), str(dest), symlinks=True)
        return dest

    def commit(self, repo: Path, message: str = "fixture change") -> str:
        subprocess.run(["git", "-C", str(repo), "add", "-f", "-A"], check=True,
                       capture_output=True, env=_git_env())
        subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", message], check=True,
                       capture_output=True, env=_git_env())
        return git(repo, "rev-parse", "HEAD").strip()

    def abbrev(self, repo: Path, rev: str = "HEAD", width: int = 12) -> str:
        return git(repo, "rev-parse", "--short=%d" % width, rev).strip()

    def commit_with_literal_entries(self, repo: Path, entries: Dict[str, bytes]) -> str:
        """A commit whose tree carries the given raw paths WITHOUT touching the worktree.

        Used to plant names that cannot coexist with their twin on a case-insensitive host
        (a case-fold collision) or that are not portable at all (a backslash, a drive
        letter, a case variant of a credential path). ``git update-index --cacheinfo``
        writes the index directly, so the working tree stays clean and HEAD stays the clean
        fixture revision: the packager is then pointed at this commit by SHA while the
        dirty-tree rule sees nothing to refuse, so the rule under test is never masked by a
        "dirty working tree" refusal. These paths live only inside an isolated POSIX Git
        fixture; nothing is ever checked out or extracted from them.
        """
        index = self.tmp / ("index-%d" % len(list(self.tmp.glob("index-*"))))
        env = _git_env()
        env["GIT_INDEX_FILE"] = str(index)
        head = git(repo, "rev-parse", "HEAD").strip()
        subprocess.run(["git", "-C", str(repo), "read-tree", head], check=True,
                       capture_output=True, env=env)
        for path, data in entries.items():
            blob = subprocess.run(["git", "-C", str(repo), "hash-object", "-w", "--stdin"],
                                  input=data, capture_output=True, env=env)
            blob_sha = blob.stdout.decode("ascii").strip()
            if blob.returncode != 0 or not blob_sha:
                raise AssertionError("fixture could not write blob for %r: %s"
                                     % (path, blob.stderr.decode("utf-8", "replace")))
            subprocess.run(["git", "-C", str(repo), "update-index", "--add", "--cacheinfo",
                            "100644,%s,%s" % (blob_sha, path)], check=True,
                           capture_output=True, env=env)
        tree = subprocess.run(["git", "-C", str(repo), "write-tree"], check=True,
                              capture_output=True, env=env).stdout.decode("ascii").strip()
        commit = subprocess.run(["git", "-C", str(repo), "commit-tree", tree, "-p", head,
                                 "-m", "fixture: literal tree entries"], check=True,
                                capture_output=True, env=_git_env()).stdout.decode("ascii").strip()
        self.assertNotEqual(head, commit)
        return commit

    # -- packager ------------------------------------------------------------------

    def out_name(self, repo: Path, purpose: str = "rehearsal", rev: str = "HEAD",
                 suffix: str = "") -> str:
        return "ryde-live-%s-%s%s.zip" % (purpose, self.abbrev(repo, rev), suffix)

    def require_packager(self) -> None:
        """A missing implementation is an assertion FAILURE, not a collection ERROR.

        Called from inside each test (through ``pack``) so the RED baseline reads as a set
        of intended assertion failures instead of setUp/setUpClass errors.
        """
        self.assertTrue(PACKAGER.is_file(),
                        "tools/package_submission.py is missing: this suite is RED until "
                        "the packager exists")

    def pack(self, repo: Path, rev: str = "HEAD", purpose: str = "rehearsal",
             out: Optional[Path] = None, extra: Tuple[str, ...] = (),
             env: Optional[Dict[str, str]] = None, name: Optional[str] = None):
        self.require_packager()
        out = Path(out) if out is not None else (self.tmp / (name or self.out_name(repo, purpose, rev)))
        child_env = dict(os.environ)
        child_env.pop("PYTHONPATH", None)
        child_env.update({
            "TMPDIR": str(LANE_TMP),
            "PYTHONDONTWRITEBYTECODE": "1",
        })
        if env:
            child_env.update(env)
        proc = subprocess.run(
            [sys.executable, "-B", str(PACKAGER), "--repo", str(repo), "--revision", rev,
             "--purpose", purpose, "--out", str(out)] + list(extra),
            cwd=str(repo), env=child_env, capture_output=True, text=True, timeout=180)
        return proc, out

    def pack_ok(self, repo: Path, **kwargs):
        proc, out = self.pack(repo, **kwargs)
        self.assertEqual(0, proc.returncode,
                         "packaging failed: %s%s" % (proc.stdout, proc.stderr))
        self.assertTrue(out.is_file(), "no archive was written to %s" % out)
        return out

    def assert_refused(self, proc, out: Path, *needles: str) -> str:
        """A refusal: non-zero, a message naming the reason, and NO output file."""
        self.assertNotEqual(0, proc.returncode, "expected a refusal, got: %s" % proc.stdout)
        self.assertFalse(out.exists(), "a refused run must not leave %s behind" % out)
        text = proc.stdout + proc.stderr
        self.assertIn("REFUSED", text)
        for needle in needles:
            self.assertIn(needle, text)
        return text

    def manifest_of(self, out: Path) -> Dict[str, object]:
        entries = read_zip(out)
        manifests = [name for name in entries if name.endswith("/MANIFEST.json")]
        self.assertEqual(1, len(manifests), "exactly one MANIFEST.json, got %s" % manifests)
        return json.loads(entries[manifests[0]][1].decode("utf-8"))

    def zipped(self, out: Path) -> Dict[str, bytes]:
        return {name: data for name, (_info, data) in read_zip(out).items()}


# ------------------------------------------------------------------ the built archive


class PackageContract(PackageFixture):

    def test_package_is_built_from_the_selected_revision_and_names_it(self):
        repo = self.copy_repo()
        out = self.pack_ok(repo)
        manifest = self.manifest_of(out)
        self.assertEqual(self.head_sha, manifest["source"]["revision"])
        self.assertEqual(self.head_sha[:12], manifest["source"]["revision_abbrev"])
        self.assertEqual("rehearsal", manifest["package"]["purpose"])
        self.assertEqual(self.head_sha[:12], self.abbrev(repo))
        self.assertIn(self.head_sha[:12], out.name)

    def test_manifest_lists_every_included_entry_with_mode_and_sha256(self):
        repo = self.copy_repo()
        out = self.pack_ok(repo)
        manifest = self.manifest_of(out)
        self.assertIn("included", manifest)
        rows = {row["path"]: row for row in manifest["included"]}
        zipped = self.zipped(out)
        top = manifest["package"]["top_level_folder"]
        for path, row in rows.items():
            name = top + "/" + path
            self.assertIn(name, zipped, "%s is listed but missing from the ZIP" % path)
            self.assertEqual(hashlib.sha256(zipped[name]).hexdigest(), row["sha256"],
                             "%s: the manifest hash is not the packaged content" % path)
            self.assertEqual(len(zipped[name]), row["bytes"])
            self.assertIn(row["git_mode"], ("100644", "100755", "120000"))
        # And nothing is in the ZIP that the manifest does not list.
        self.assertEqual(
            set(top + "/" + path for path in rows) | {top + "/MANIFEST.json"},
            set(zipped))
        self.assertEqual(len(rows) + 1, len(zipped))

    def test_manifest_records_purpose_inventory_and_the_release_notes(self):
        repo = self.copy_repo()
        out = self.pack_ok(repo, purpose="submission", name=self.out_name(repo, "submission"))
        manifest = self.manifest_of(out)
        self.assertEqual("submission", manifest["package"]["purpose"])
        self.assertIn("inventory", manifest["source"])
        self.assertIn("Git tree", manifest["source"]["inventory"])
        self.assertEqual(sorted(REQUIRED_FILES), sorted(manifest["required_files"]))
        for row in manifest["excluded"]:
            self.assertTrue(row["reason"], "an omission must carry a reason")
        notes = manifest["notes"]
        self.assertIn("pattern_scan", notes)
        self.assertIn("not proof", notes["pattern_scan"],
                      "the pattern scan must not be claimed as an exhaustive key scan")
        self.assertIn("W6", notes["w6_privacy_gate"])
        self.assertIn(".env.live", notes["credentials"])

    def test_every_entry_sits_under_one_top_level_folder_with_relative_paths(self):
        repo = self.copy_repo()
        out = self.pack_ok(repo)
        names = list(read_zip(out))
        top = self.manifest_of(out)["package"]["top_level_folder"]
        self.assertTrue(names)
        for name in names:
            self.assertFalse(name.startswith("/"), name)
            self.assertNotIn("..", name.split("/"), name)
            self.assertTrue(name.startswith(top + "/"), name)
        self.assertEqual({top}, {name.split("/", 1)[0] for name in names})

    def test_a_clean_run_prints_the_extraction_and_sidecar_steps(self):
        repo = self.copy_repo()
        proc, out = self.pack(repo)
        self.assertEqual(0, proc.returncode, proc.stderr)
        self.assertIn("Extract the ZIP first", proc.stdout)
        self.assertIn(".env.live", proc.stdout)
        self.assertIn("start-live.bat", proc.stdout)
        # The console must state the narrow, true guarantee and the remaining release step —
        # never the old unconditional "No key is inside this archive".
        self.assertIn("not proof", proc.stdout)
        self.assertIn("ACTUAL live key bytes", proc.stdout)
        self.assertNotIn("No key is inside this archive", proc.stdout,
                         "the packager must not claim the archive is key-free")

    def test_refuses_a_revision_that_does_not_resolve(self):
        repo = self.copy_repo()
        proc, out = self.pack(repo, rev="0" * 40)
        self.assert_refused(proc, out, "cannot resolve source revision")

    def test_refuses_a_selected_revision_missing_required_files(self):
        repo = self.copy_repo()
        (repo / "start-live.bat").unlink()
        (repo / "docs" / "live-copy.md").unlink()
        self.commit(repo, "fixture: drop a wrapper and the copy")
        proc, out = self.pack(repo)
        text = self.assert_refused(proc, out, "missing required package file")
        self.assertIn("start-live.bat", text)
        self.assertIn("docs/live-copy.md", text)

    def test_output_name_must_carry_the_purpose_and_the_revision(self):
        repo = self.copy_repo()
        proc, out = self.pack(repo, name="package.zip")
        self.assert_refused(proc, out, "does not contain")
        self.assertIn("revision", (proc.stdout + proc.stderr))


# ------------------------------------------------------------------- credential safety


class PackageCredentialSafety(PackageFixture):

    def test_tracked_env_live_file_is_refused(self):
        repo = self.copy_repo()
        (repo / ".env.live").write_bytes(
            b"TENCENT_ADP_RIDER_APP_KEY=%s\n" % FAKE_SECRET_ID.encode())
        self.commit(repo, "fixture: accidentally tracked sidecar")
        proc, out = self.pack(repo)
        self.assert_refused(proc, out, ".env.live", "live credential")

    def test_tracked_key_material_and_secret_store_are_refused(self):
        repo = self.copy_repo()
        (repo / "secrets").mkdir()
        (repo / "secrets" / "adp.pem").write_bytes(b"-----BEGIN " + b"PRIVATE KEY-----\n")
        (repo / "credentials.json").write_bytes(b'{"app_key": "fake"}\n')
        self.commit(repo, "fixture: accidentally tracked key material")
        proc, out = self.pack(repo)
        text = self.assert_refused(proc, out, "secrets/adp.pem", "credentials.json")
        self.assertNotIn("BEGIN PRIVATE KEY", text)

    def test_a_filled_in_env_example_is_refused(self):
        repo = self.copy_repo()
        (repo / ".env.example").write_bytes(
            b"TENCENT_ADP_RIDER_APP_KEY=abc123def456ghi789jkl\n"
            b"TENCENT_ADP_DRIVER_APP_KEY=\n")
        self.commit(repo, "fixture: template with a real-looking value")
        proc, out = self.pack(repo)
        self.assert_refused(proc, out, ".env.example", "non-empty value")

    def test_the_empty_env_example_is_packaged(self):
        repo = self.copy_repo()
        out = self.pack_ok(repo)
        zipped = self.zipped(out)
        top = self.manifest_of(out)["package"]["top_level_folder"]
        self.assertIn(top + "/.env.example", zipped)
        self.assertIn(b"TENCENT_ADP_RIDER_APP_KEY=\n", zipped[top + "/.env.example"])

    def test_a_fake_tencent_secret_id_inside_a_tracked_document_is_refused(self):
        repo = self.copy_repo()
        (repo / "evidence" / "2026-10-14_provider-note.md").write_bytes(
            b"# Provider note\n\nThe app key is %s\n" % FAKE_SECRET_ID.encode())
        self.commit(repo, "fixture: SecretId pasted into a note")
        proc, out = self.pack(repo)
        text = self.assert_refused(proc, out, "2026-10-14_provider-note.md", "SecretId")
        self.assertNotIn(FAKE_SECRET_ID, text, "the refusal echoed the credential value")

    def test_refusal_messages_never_echo_a_credential_value(self):
        repo = self.copy_repo()
        (repo / "data").mkdir(exist_ok=True)
        (repo / "data" / "provider-notes.md").write_bytes(
            b"rider key: %s\n" % FAKE_SECRET_ID.encode())
        self.commit(repo, "fixture: key in a data note")
        proc, out = self.pack(repo)
        text = self.assert_refused(proc, out)
        self.assertNotIn(FAKE_SECRET_ID, text)

    def test_environment_variables_are_never_read_into_the_package(self):
        repo = self.copy_repo()
        poisoned = {
            "TENCENT_ADP_RIDER_APP_KEY": FAKE_POISON_KEY,
            "TENCENT_ADP_DRIVER_APP_KEY": FAKE_POISON_KEY,
            "TENCENT_ADP_JUDGE_APP_KEY": FAKE_POISON_KEY,
            "TENCENT_ADP_ENDPOINT": "https://poison.invalid/adp/v2/chat",
        }
        proc, out = self.pack(repo, env=poisoned)
        self.assertEqual(0, proc.returncode, proc.stderr)
        self.assertNotIn(FAKE_POISON_KEY, proc.stdout + proc.stderr)
        with zipfile.ZipFile(str(out)) as archive:
            for info in archive.infolist():
                self.assertNotIn(FAKE_POISON_KEY.encode(), archive.read(info),
                                 "%s carries an environment value" % info.filename)
        self.assertNotIn(FAKE_POISON_KEY, out.read_bytes().decode("latin-1"))

    def test_an_empty_tracked_env_live_is_refused_by_the_path_rule_alone(self):
        """The path rule must refuse ``.env.live`` even with NO credential-shaped content.

        An empty sidecar trips no content pattern, so only the path classification can
        catch it. This pins that the refusal is the path rule, not a coincidental content
        match that would hide a removed path guard.
        """
        repo = self.copy_repo()
        (repo / ".env.live").write_bytes(b"")
        self.commit(repo, "fixture: empty accidentally tracked sidecar")
        proc, out = self.pack(repo)
        text = self.assert_refused(proc, out, ".env.live", "live credential")
        self.assertNotIn("non-empty value", text,
                         "nothing about this file's content should be the reason")
        self.assertNotIn("SecretId", text)

    def test_a_plain_tracked_env_live_value_is_refused_by_the_path_rule(self):
        """An ordinary value with no AKID/private-key shape is still refused by the path.

        The value here (an empty assignment plus a comment) matches no high-signal content
        pattern, so a content guard cannot be the thing doing the work.
        """
        repo = self.copy_repo()
        (repo / ".env.live").write_bytes(
            b"# sidecar received separately\nTENCENT_ADP_RIDER_APP_KEY=\n")
        self.commit(repo, "fixture: plain tracked sidecar")
        proc, out = self.pack(repo)
        self.assert_refused(proc, out, ".env.live", "live credential")

    def test_a_case_variant_credential_path_in_the_selected_tree_is_refused(self):
        """Case variants of credential paths are refused at the package boundary.

        ``.ENV.LIVE``, ``SECRETS/key.txt`` and ``SERVER.KEY`` are planted as real Git tree
        entries (through the index, so they never exist as files) and must stop the build
        with no output, even though their empty content trips no content pattern.
        """
        repo = self.copy_repo()
        rev = self.commit_with_literal_entries(repo, {
            ".ENV.LIVE": b"", "SECRETS/key.txt": b"", "SERVER.KEY": b""})
        proc, out = self.pack(repo, rev=rev, name=self.out_name(repo, rev=rev))
        text = self.assert_refused(proc, out, ".ENV.LIVE", "SECRETS/key.txt", "SERVER.KEY")
        self.assertIn("credential", text)


# ------------------------------------------------------------------- the inventory


class PackageInventory(PackageFixture):

    def test_editor_locks_and_os_junk_are_omitted_and_recorded(self):
        repo = self.copy_repo()
        out = self.pack_ok(repo)
        zipped = self.zipped(out)
        for junk in JUNK_FILES:
            self.assertNotIn(junk, {name.split("/", 1)[1] for name in zipped if "/" in name},
                             "%s must not be packaged" % junk)
        excluded = {row["path"]: row["reason"] for row in self.manifest_of(out)["excluded"]}
        for junk in JUNK_FILES:
            self.assertIn(junk, excluded, "%s must be recorded as excluded" % junk)
        self.assertIn("editor lock", excluded["tools/deployment/~$ryde-dispute-pitch.pptx"])
        self.assertIn("OS junk", excluded[".DS_Store"])

    def test_complete_source_tests_and_evidence_are_kept(self):
        repo = self.copy_repo()
        out = self.pack_ok(repo)
        names = {name.split("/", 1)[1] for name in self.zipped(out) if "/" in name}
        for kept in ("ui/start/index.html", "ui/index.html", "app/config.py", "app/config.json",
                     "data/packs/organiser-style-v1/pack.json", "evidence/2026-10-01_note.md",
                     "tests/support.py", "tools/launch.py", "tools/launch_live.py",
                     "start.bat", "start.command", "start-live.bat", "start-live.command",
                     "docs/live-copy.md", ".gitattributes", ".env.example"):
            self.assertIn(kept, names)

    def test_wrapper_crlf_and_executable_mode_survive_into_the_zip(self):
        repo = self.copy_repo()
        out = self.pack_ok(repo)
        entries = read_zip(out)
        top = self.manifest_of(out)["package"]["top_level_folder"]
        bat_info, bat = entries[top + "/start-live.bat"]
        self.assertGreater(bat.count(b"\r\n"), 3)
        self.assertEqual(bat.count(b"\n"), bat.count(b"\r\n"),
                         "every packaged batch line must end CRLF")
        self.assertEqual(BAT_CRLF, bat, "the committed bytes, unaltered")
        self.assertEqual(0o100644, entry_mode(bat_info))
        for name in ("start-live.command", "start.command"):
            info = entries[top + "/" + name][0]
            self.assertEqual(0o100755, entry_mode(info),
                             "%s must extract executable" % name)
        self.assertTrue(entries[top + "/start-live.command"][1].startswith(b"#!"))

    def test_refuses_a_windows_wrapper_committed_with_lf_endings(self):
        repo = self.copy_repo()
        (repo / "start-live.bat").write_bytes(BAT_CRLF.replace(b"\r\n", b"\n"))
        self.commit(repo, "fixture: LF batch file")
        proc, out = self.pack(repo)
        self.assert_refused(proc, out, "start-live.bat", "CRLF")

    def test_refuses_a_macos_wrapper_git_does_not_record_as_executable(self):
        repo = self.copy_repo()
        (repo / "start-live.command").write_bytes(MAC_SCRIPT)
        (repo / "start-live.command").chmod(0o644)
        self.commit(repo, "fixture: non-executable macOS wrapper")
        proc, out = self.pack(repo)
        self.assert_refused(proc, out, "start-live.command", "100755")

    def test_a_contained_symlink_is_preserved_as_a_link(self):
        repo = self.copy_repo()
        os.symlink("../README.md", str(repo / "docs" / "readme-link.md"))
        self.commit(repo, "fixture: contained symlink")
        out = self.pack_ok(repo)
        entries = read_zip(out)
        top = self.manifest_of(out)["package"]["top_level_folder"]
        info, data = entries[top + "/docs/readme-link.md"]
        self.assertEqual(0o120777, entry_mode(info), "the link must stay a link")
        self.assertEqual(b"../README.md", data)

    def test_an_escaping_symlink_is_refused(self):
        repo = self.copy_repo()
        os.symlink("../../outside-the-package.md", str(repo / "docs" / "escape.md"))
        self.commit(repo, "fixture: escaping symlink")
        proc, out = self.pack(repo)
        self.assert_refused(proc, out, "docs/escape.md", "outside the package root")

    def test_paths_with_spaces_and_unicode_are_packaged(self):
        repo = self.copy_repo()
        out = self.pack_ok(repo)
        names = {name.split("/", 1)[1] for name in self.zipped(out) if "/" in name}
        self.assertIn("docs/release notes/README v2.md", names)
        self.assertIn("data/\u00fcn\u00efcode/case-\u4f8b\u5b50.json", names)

    def test_refuses_a_backslash_blob_path_in_the_selected_tree(self):
        repo = self.copy_repo()
        rev = self.commit_with_literal_entries(repo, {"..\\escape.txt": b"payload\n"})
        proc, out = self.pack(repo, rev=rev, name=self.out_name(repo, rev=rev))
        self.assert_refused(proc, out, "unsafe path", "backslash")

    def test_refuses_a_windows_drive_blob_path_in_the_selected_tree(self):
        repo = self.copy_repo()
        rev = self.commit_with_literal_entries(repo, {"C:outside.txt": b"payload\n"})
        proc, out = self.pack(repo, rev=rev, name=self.out_name(repo, rev=rev))
        self.assert_refused(proc, out, "unsafe path", "drive")

    def test_refuses_a_casefold_name_collision_in_the_selected_tree(self):
        repo = self.copy_repo()
        rev = self.commit_with_literal_entries(repo, {"Foo.txt": b"one\n", "foo.txt": b"two\n"})
        proc, out = self.pack(repo, rev=rev, name=self.out_name(repo, rev=rev))
        text = self.assert_refused(proc, out, "collision")
        self.assertIn("case", text)


# ---------------------------------------------------------------------- the output


class PackageOutput(PackageFixture):

    def test_refuses_an_output_path_inside_the_repository(self):
        repo = self.copy_repo()
        proc, out = self.pack(repo, out=repo / self.out_name(repo))
        self.assert_refused(proc, out, "inside the repository")

    def test_refuses_an_output_directory_that_does_not_exist(self):
        repo = self.copy_repo()
        proc, out = self.pack(repo, out=self.tmp / "absent" / self.out_name(repo))
        self.assert_refused(proc, out, "does not exist")

    def test_refuses_an_output_path_that_is_a_symlink(self):
        repo = self.copy_repo()
        target = self.tmp / "real-archive.zip"
        target.write_bytes(b"")
        link = self.tmp / self.out_name(repo)
        os.symlink(str(target), str(link))
        proc, _out = self.pack(repo, out=link)
        self.assertNotEqual(0, proc.returncode)
        self.assertIn("symlink", proc.stdout + proc.stderr)

    def test_refuses_an_output_path_without_a_zip_suffix(self):
        repo = self.copy_repo()
        proc, out = self.pack(repo, out=self.tmp / (self.out_name(repo)[:-4] + ".tar"))
        self.assert_refused(proc, out, ".zip")

    def test_packaging_leaves_the_repository_untouched(self):
        repo = self.copy_repo()
        before = git(repo, "status", "--porcelain", "--untracked-files=all")
        listing_before = sorted(p.relative_to(repo).as_posix() for p in repo.rglob("*"))
        self.pack_ok(repo)
        self.assertEqual(before, git(repo, "status", "--porcelain", "--untracked-files=all"))
        self.assertEqual(listing_before, sorted(p.relative_to(repo).as_posix()
                                                for p in repo.rglob("*")))

    def test_a_dirty_working_tree_at_head_is_refused(self):
        repo = self.copy_repo()
        (repo / "README.md").write_bytes(FIXTURE_FILES["README.md"] + b"\nuncommitted edit\n")
        proc, out = self.pack(repo)
        self.assert_refused(proc, out, "ambiguous")

    def test_an_explicit_older_revision_packages_while_the_tree_is_dirty(self):
        repo = self.copy_repo()
        (repo / "README.md").write_bytes(FIXTURE_FILES["README.md"] + b"\nuncommitted edit\n")
        out = self.pack_ok(repo, rev=self.first_sha,
                           name=self.out_name(repo, rev=self.first_sha))
        manifest = self.manifest_of(out)
        self.assertEqual(self.first_sha, manifest["source"]["revision"])
        self.assertIs(True, manifest["source"]["working_tree_dirty"])

    def test_refuses_an_output_inside_the_repository_through_a_case_variant_directory(self):
        """A case-variant alias of the repository directory is still refused.

        ``os.path.samefile(REPO, repo)`` is true on a case-insensitive host, but
        ``Path.resolve`` keeps the given case, so a plain resolved-path comparison misses
        it. The destination directory's disk identity must catch it.
        """
        repo = self.copy_repo()
        alias = repo.parent / repo.name.upper()
        if not (alias.is_dir() and os.path.samefile(str(alias), str(repo))):
            self.skipTest("this filesystem is case-sensitive: no case-variant alias exists")
        proc, out = self.pack(repo, out=alias / self.out_name(repo))
        self.assert_refused(proc, out, "inside the repository")

    def test_refuses_an_output_inside_a_symlinked_repository_directory(self):
        repo = self.copy_repo()
        link = self.tmp / "repo-link"
        os.symlink(str(repo), str(link))
        proc, out = self.pack(repo, out=link / self.out_name(repo))
        self.assert_refused(proc, out, "inside the repository")


# ------------------------------------------------------------------ reproducibility


class PackageReproducibility(PackageFixture):

    def test_two_builds_of_one_revision_agree_on_inventory_and_content(self):
        repo = self.copy_repo()
        first = self.pack_ok(repo, name=self.out_name(repo) )
        second = self.pack_ok(repo, name=self.out_name(repo, suffix="-rebuild"))
        left, right = self.zipped(first), self.zipped(second)
        self.assertEqual(sorted(left), sorted(right))
        for name in sorted(left):
            if name.endswith("/MANIFEST.json"):
                continue
            self.assertEqual(hashlib.sha256(left[name]).hexdigest(),
                             hashlib.sha256(right[name]).hexdigest(),
                             "%s differs between two builds of one revision" % name)
        # The one intended difference: the manifest's declared build time.
        left_manifest = self.manifest_of(first)
        right_manifest = self.manifest_of(second)
        self.assertEqual(
            {k: v for k, v in left_manifest.items() if k != "package"},
            {k: v for k, v in right_manifest.items() if k != "package"})
        for key in ("purpose", "top_level_folder"):
            self.assertEqual(left_manifest["package"][key], right_manifest["package"][key])

    def test_entry_timestamps_are_the_commit_time_not_the_build_time(self):
        repo = self.copy_repo()
        out = self.pack_ok(repo)
        committed = datetime.fromtimestamp(
            int(git(repo, "show", "-s", "--format=%ct").strip()), tz=timezone.utc)
        expected = (committed.year, committed.month, committed.day,
                    committed.hour, committed.minute, committed.second)
        for info in read_zip(out).values():
            self.assertEqual(expected, info[0].date_time,
                             "%s carries a wall-clock timestamp" % info[0].filename)


# ---------------------------------------------------------------------- interface


class PackageInterface(unittest.TestCase):

    def setUp(self):
        if not PACKAGER.is_file():
            self.fail("tools/package_submission.py is missing: this suite is RED until the "
                      "packager exists")
        self.source = PACKAGER.read_text(encoding="utf-8")

    def test_the_module_imports_only_stdlib_that_cannot_reach_a_network(self):
        tree = ast.parse(self.source)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        self.assertTrue(imported, "no imports found: is this the packager?")
        self.assertEqual(set(), imported - ALLOWED_IMPORTS,
                         "unexpected import(s): a package build reads Git, nothing else")
        self.assertEqual(set(), imported & NETWORK_MODULES, "the packager must not be able "
                                                            "to make a network call")
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                self.assertFalse(node.value.startswith(("http://", "https://")),
                                 "a URL literal is in the packager: %r" % node.value)

    def test_own_test_source_is_safe_to_package(self):
        module = load_packager_module()
        refusals = module.content_refusals(
            "tests/test_w47_submission_package.py", Path(__file__).read_bytes()
        )
        self.assertEqual([], refusals,
                         "negative secret fixtures must be constructed at runtime, not "
                         "embedded as credential-shaped blobs in distributed source")

    def test_the_cli_help_states_the_credential_rules(self):
        proc = subprocess.run([sys.executable, "-B", str(PACKAGER), "--help"],
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(0, proc.returncode, proc.stderr)
        # argparse wraps the description, so compare against unwrapped text.
        help_text = " ".join(proc.stdout.split())
        for needle in ("--revision", "--purpose", "--out"):
            self.assertIn(needle, help_text)
        self.assertIn("never reads, creates or rotates a credential", help_text)
        self.assertIn("no network call", help_text)

    def test_the_instructions_document_reach_the_teammate(self):
        if not LIVE_DOC.is_file():
            self.fail("docs/live-copy.md is missing: this suite is RED until it exists")
        text = LIVE_DOC.read_text(encoding="utf-8")
        for needle in (".env.live", "start-live.bat", "start-live.command",
                       "Python 3.9", "internet", "terminal", "mock", "credentials",
                       "drafts/w26/demo-script.md"):
            self.assertIn(needle, text, "docs/live-copy.md must cover %r" % needle)

    def test_the_instructions_cover_both_purposes_and_the_script_handoff(self):
        if not LIVE_DOC.is_file():
            self.fail("docs/live-copy.md is missing: this suite is RED until it exists")
        text = LIVE_DOC.read_text(encoding="utf-8")
        self.assertIn("MANIFEST.json", text)
        for needle in ("rehearsal", "submission", "handoff", "Open Anyway"):
            self.assertIn(needle, text, "docs/live-copy.md must mention %r" % needle)

    def test_instructions_distinguish_included_source_from_separate_recording_script(self):
        self.assertTrue(LIVE_DOC.is_file(), "docs/live-copy.md is missing")
        text = " ".join(LIVE_DOC.read_text(encoding="utf-8").split())
        self.assertIn("`tools/deployment/demo-video-script.md` is an included source file", text)
        self.assertIn("accepted recording script is a separate teammate handoff", text)
        self.assertNotIn("Neither script is inside this ZIP", text)
        self.assertNotIn("never files in this ZIP", text)

    def test_bearer_examples_do_not_hide_credential_like_values(self):
        module = load_packager_module()
        header = b"Authorization" + b": Bearer "
        examples = [
            header + b"<KEY>",
            b"`" + header + b"<KEY>`",
            json.dumps({"content": (header + b"<KEY>\nNext example").decode()}).encode(),
            json.dumps({"content": (b"`" + header + b"<KEY>`\nNext example").decode()}).encode(),
        ]
        for body in examples:
            with self.subTest(kind="literal example", bytes=len(body)):
                self.assertEqual([], module.content_refusals("evidence/example.jsonl", body))
        fake = b"FAKE0" + b"W47BearerFixtureNotARealCredential"
        for value in (fake, b"<KEY>" + fake, b"<" + fake + b">"):
            for body in (header + value, json.dumps({"content": (header + value).decode()}).encode()):
                with self.subTest(kind="credential-like value", bytes=len(body)):
                    self.assertTrue(module.content_refusals("evidence/example.jsonl", body),
                                    "a literal-example exception must not hide another value")

    def test_live_copy_claims_match_the_release_and_available_entry_points(self):
        self.assertTrue(LIVE_DOC.is_file())
        text = " ".join(LIVE_DOC.read_text(encoding="utf-8").split())
        self.assertNotIn("only route in this copy that selects the real provider", text)
        self.assertNotIn("No package, instruction or manifest contains an actual key.", text)
        self.assertIn("package.purpose", text)


class PackagePathRules(unittest.TestCase):
    """Direct checks on the packager's path and credential classifiers.

    These call the module's functions with hostile path STRINGS, so they hold on a
    case-insensitive host where two case-variant files cannot both exist on disk. A missing
    helper function is reported as an assertion failure, never as an AttributeError.
    """

    def module(self):
        self.assertTrue(PACKAGER.is_file(),
                        "tools/package_submission.py is missing: this suite is RED until "
                        "the packager exists")
        return load_packager_module()

    def test_credential_paths_are_classified_case_insensitively(self):
        module = self.module()
        for path in (".env", ".env.live", ".ENV.LIVE", ".Env.Live", "SECRETS/key.txt",
                     "Secrets/adp.pem", "server.KEY", "credentials.json", "CREDENTIALS.JSON",
                     "auth.json", ".codebuddy/settings.local.json",
                     ".CodeBuddy/Settings.Local.json"):
            self.assertIsNotNone(module._credential_path_reason(path),
                                 "%s must be classified as a credential path" % path)

    def test_the_committed_env_template_stays_exempt_case_insensitively(self):
        module = self.module()
        for path in (".env.example", ".ENV.EXAMPLE", ".env.Example"):
            self.assertIsNone(module._credential_path_reason(path),
                              "%s is the empty template, not a credential path" % path)

    def test_a_case_variant_env_example_is_still_scanned_for_a_filled_value(self):
        module = self.module()
        filled = b"TENCENT_ADP_RIDER_APP_KEY=abc123def456ghi789jkl\n"
        self.assertTrue(module.content_refusals(".ENV.EXAMPLE", filled),
                        "a case variant of .env.example must be scanned for a filled value")
        self.assertEqual([], module.content_refusals(".ENV.EXAMPLE",
                                                     b"TENCENT_ADP_RIDER_APP_KEY=\n"))

    def test_portable_path_helper_rejects_hostile_names(self):
        module = self.module()
        helper = getattr(module, "_portable_path_reason", None)
        self.assertIsNotNone(helper, "the packager must validate path portability")
        for path in ("..\\escape.txt", "C:\\outside.txt", "C:outside.txt",
                     "//server/share/x", "/etc/passwd", "a/../b", "a/./b", "a//b",
                     "a\x00b", "a\x01b", "..", ""):
            self.assertIsNotNone(helper(path), "%r must not be a portable path" % path)
        for path in ("docs/release notes/README v2.md", ".env.example",
                     "data/\u00fcn\u00efcode/case-\u4f8b\u5b50.json"):
            self.assertIsNone(helper(path), "%r is a valid portable path" % path)

    def test_casefold_collisions_are_detected(self):
        module = self.module()
        helper = getattr(module, "_casefold_collisions", None)
        self.assertIsNotNone(helper, "the packager must detect portable case-fold collisions")
        self.assertEqual([("Foo.txt", "foo.txt")], helper(["Foo.txt", "foo.txt", "bar.txt"]))
        self.assertEqual([], helper(["a.txt", "b.txt"]))

    def test_classify_refuses_case_variant_credential_paths(self):
        module = self.module()
        for path in (".ENV.LIVE", "SECRETS/key.txt"):
            decision, _reason = module.classify(
                module.TreeEntry("100644", "blob", "0" * 40, 0, path))
            self.assertEqual("refuse", decision, "%s must be refused" % path)

    def test_classify_refuses_hostile_portable_paths(self):
        module = self.module()
        for path in ("..\\escape.txt", "C:\\outside.txt", "/etc/passwd"):
            decision, _reason = module.classify(
                module.TreeEntry("100644", "blob", "0" * 40, 0, path))
            self.assertEqual("refuse", decision, "%s must be refused" % path)


@unittest.skipUnless(os.environ.get("W47_BASELINE_TREE"),
                     "set W47_BASELINE_TREE to a read-only baseline copy")
class BaselineTree(unittest.TestCase):
    """The real archived tree is the one that matters.

    Two opt-in checks, both against ``W47_BASELINE_TREE`` (the read-only baseline copy):

    1. the pattern scan must not refuse the committed documents and evidence — a scanner
       that cries wolf on the real tree is worse than none;
    2. the packager must build the REAL 491-file tree cleanly, keeping CRLF and the
       executable bit and omitting the committed editor lock.

    They are opt-in because they read 38 MB; the mutation battery runs the rest. The four
    required files are added as tiny PLACEHOLDERS in an isolated fixture repository cloned
    from the archive (lane A's helper/wrappers are placeholders until the build lands;
    they are never reference source here).
    """

    def test_the_archived_baseline_tree_trips_no_credential_pattern(self):
        root = Path(os.environ["W47_BASELINE_TREE"])
        self.assertTrue(root.is_dir(), root)
        self.assertTrue(PACKAGER.is_file(), "tools/package_submission.py is missing")
        module = load_packager_module()
        scanned = 0
        hits: List[str] = []
        for path in sorted(root.rglob("*")):
            if not path.is_file() or ".git" in path.parts:
                continue
            scanned += 1
            hits.extend(module.content_refusals(path.relative_to(root).as_posix(),
                                                path.read_bytes()))
        self.assertGreater(scanned, 300, "the baseline tree looks empty: %d files" % scanned)
        self.assertEqual([], hits[:10], "%d false positive(s) on the real tree" % len(hits))

    def test_the_archived_baseline_tree_packages_cleanly(self):
        source = Path(os.environ["W47_BASELINE_TREE"])
        self.assertTrue(source.is_dir(), source)
        if not PACKAGER.is_file():
            self.fail("tools/package_submission.py is missing")
        LANE_TMP.mkdir(parents=True, exist_ok=True)
        tmp = Path(tempfile.mkdtemp(prefix="w47-fulltree-", dir=str(LANE_TMP)))
        self.addCleanup(shutil.rmtree, str(tmp), True)
        repo = tmp / "repo"
        shutil.copytree(str(source), str(repo), symlinks=True)
        # Placeholders for the required files only: lane A's live launcher, its two
        # wrappers and this lane's copy. Tiny, named, in an isolated fixture repo.
        placeholders = {
            "tools/launch_live.py": b'"""Live launcher helper (placeholder)."""\n',
            "docs/live-copy.md": b"# Live copy (placeholder)\n",
        }
        write_fixture_files(repo, placeholders)
        (repo / "start-live.bat").write_bytes(BAT_CRLF)
        (repo / "start-live.command").write_bytes(MAC_SCRIPT)
        (repo / "start-live.command").chmod(0o755)
        subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True,
                       capture_output=True, env=_git_env())
        subprocess.run(["git", "-C", str(repo), "add", "-f", "-A"], check=True,
                       capture_output=True, env=_git_env())
        subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "fixture: baseline tree"],
                       check=True, capture_output=True, env=_git_env())
        sha = git(repo, "rev-parse", "HEAD").strip()
        out = tmp / ("ryde-live-rehearsal-%s.zip" % sha[:12])
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        proc = subprocess.run(
            [sys.executable, "-B", str(PACKAGER), "--repo", str(repo), "--revision", "HEAD",
             "--purpose", "rehearsal", "--out", str(out)],
            cwd=str(repo), env=env, capture_output=True, text=True, timeout=600)
        self.assertEqual(0, proc.returncode, proc.stdout + proc.stderr)
        manifest = json.loads(read_zip(out)[
            "ryde-live-rehearsal-%s/MANIFEST.json" % sha[:12]][1].decode("utf-8"))
        self.assertGreater(manifest["counts"]["included"], 450)
        entries = read_zip(out)
        self.assertEqual(0o100755, entry_mode(
            entries["ryde-live-rehearsal-%s/start-live.command" % sha[:12]][0]))
        bat = entries["ryde-live-rehearsal-%s/start-live.bat" % sha[:12]][1]
        self.assertEqual(bat.count(b"\n"), bat.count(b"\r\n"))
        names = {name.split("/", 1)[1] for name in entries}
        self.assertNotIn("tools/deployment/~$ryde-dispute-pitch.pptx", names,
                         "the committed editor lock must be omitted")
        self.assertNotIn(".env", names)
        self.assertNotIn(".env.live", names)
        self.assertIn("docs/policy.md", names)
        self.assertIn("data/packs/organiser-style-v1/ground-truth.json", names)


if __name__ == "__main__":
    unittest.main()
