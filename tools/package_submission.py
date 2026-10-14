"""Build a source ZIP from one committed Git revision without reading local secrets."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
import posixpath
import re
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Tuple

REQUIRED_FILES = (
    "tools/launch_live.py",
    "start-live.bat",
    "start-live.command",
    "docs/live-copy.md",
)
PRESERVED_FILES = ("tools/launch.py", "start.bat", "start.command")
ROLE_KEY_NAMES = (
    "TENCENT_ADP_RIDER_APP_KEY",
    "TENCENT_ADP_DRIVER_APP_KEY",
    "TENCENT_ADP_JUDGE_APP_KEY",
)
RESERVED_WINDOWS_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
}


class PackageRefusal(RuntimeError):
    """The selected source or destination cannot be packaged safely."""


class TreeEntry(NamedTuple):
    mode: str
    kind: str
    sha: str
    size: int
    path: str


def _git(repo: Path, *args: str) -> bytes:
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo)] + list(args),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError:
        raise PackageRefusal("could not run Git for the selected repository") from None
    if proc.returncode != 0:
        raise PackageRefusal("Git could not inspect the selected repository")
    return proc.stdout


def _decode(value: bytes, what: str) -> str:
    try:
        return value.decode("utf-8")
    except UnicodeDecodeError:
        raise PackageRefusal("the Git tree contains a non-UTF-8 %s" % what) from None


def _resolve_revision(repo: Path, revision: str) -> str:
    if not revision or revision.startswith("-"):
        raise PackageRefusal("cannot resolve source revision")
    try:
        raw = _git(repo, "rev-parse", "--verify", "%s^{commit}" % revision)
    except PackageRefusal:
        raise PackageRefusal("cannot resolve source revision") from None
    resolved = _decode(raw.strip(), "revision")
    if not re.fullmatch(r"[0-9a-f]{40}", resolved):
        raise PackageRefusal("cannot resolve source revision")
    return resolved


def _tree(repo: Path, revision: str) -> List[TreeEntry]:
    raw = _git(repo, "ls-tree", "-r", "-z", "--full-tree", revision)
    entries: List[TreeEntry] = []
    for item in raw.split(b"\0"):
        if not item:
            continue
        try:
            header, path_raw = item.split(b"\t", 1)
            mode_raw, kind_raw, sha_raw = header.split()
        except ValueError:
            raise PackageRefusal("the selected Git tree is malformed") from None
        path = _decode(path_raw, "path")
        mode = _decode(mode_raw, "tree mode")
        kind = _decode(kind_raw, "tree type")
        sha = _decode(sha_raw, "tree object")
        entries.append(TreeEntry(mode, kind, sha, 0, path))
    return entries


def _blob(repo: Path, sha: str) -> bytes:
    try:
        return _git(repo, "cat-file", "blob", sha)
    except PackageRefusal:
        raise PackageRefusal("could not read a Git source blob") from None


def _portable_component_reason(component: str) -> Optional[str]:
    if not component:
        return "empty path component"
    if component[-1] in ". ":
        return "trailing dot or space"
    if any(char in component for char in '<>:"|?*'):
        return "a character not portable to Windows"
    stem = component.split(".", 1)[0].rstrip(" .").upper()
    if stem in RESERVED_WINDOWS_NAMES:
        return "a reserved Windows name"
    return None


def _portable_path_reason(path: str) -> Optional[str]:
    if not isinstance(path, str) or not path:
        return "empty path"
    if "\\" in path:
        return "backslash"
    if path.startswith("/"):
        return "absolute path"
    if re.match(r"^[A-Za-z]:", path):
        return "drive name"
    if "\x00" in path or any(ord(char) < 32 or ord(char) == 127 for char in path):
        return "control character"
    if "//" in path:
        return "repeated separator"
    parts = path.split("/")
    if any(part in ("", ".", "..") for part in parts):
        return "dot or empty path component"
    for part in parts:
        reason = _portable_component_reason(part)
        if reason is not None:
            return reason
    return None


def _credential_path_reason(path: str) -> Optional[str]:
    normal = path.replace("\\", "/")
    lower = normal.lower()
    parts = lower.split("/")
    base = parts[-1] if parts else ""
    if base == ".env.example":
        return None
    if base == ".env" or base.startswith(".env."):
        return "live credential sidecar"
    if "secrets" in parts:
        return "credential store"
    if lower == ".codebuddy/settings.local.json" or lower.endswith("/.codebuddy/settings.local.json"):
        return "local credential settings"
    if base in ("credentials.json", "auth.json") or base.startswith("credentials."):
        return "credential store"
    if base.endswith((".pem", ".key", ".p12", ".pfx")):
        return "key material"
    if base in ("id_rsa", "id_ed25519", "id_ecdsa", "id_dsa"):
        return "private key material"
    return None


def _env_example_has_value(data: bytes) -> bool:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return True
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip().upper() in ROLE_KEY_NAMES and value.strip():
            return True
    return False


_BEARER_HEADER = re.compile(rb'(?i)authorization[ \t]*:[ \t]*bearer[ \t]+')


def _is_bearer_placeholder(tail: bytes) -> bool:
    """Accept only the documented literal marker and its serialized delimiters."""
    marker = re.match(rb'(?i)<key>', tail)
    if marker is None:
        return False
    remainder = tail[marker.end():]
    return not remainder or remainder.startswith((b'`', b'\n', b'\r\n', b'\\n', b'\\"', b'"'))


def _has_non_placeholder_bearer(data: bytes) -> bool:
    for match in _BEARER_HEADER.finditer(data):
        tail = data[match.end():]
        if _is_bearer_placeholder(tail):
            continue
        if re.match(rb'\S+', tail):
            return True
    return False


def content_refusals(path: str, data: bytes) -> List[str]:
    """Return narrow, value-free findings for one Git blob."""
    findings: List[str] = []
    lower = path.replace("\\", "/").lower()
    base = lower.rsplit("/", 1)[-1]
    if base == ".env.example" and _env_example_has_value(data):
        findings.append("non-empty value in an environment example")
    if data.startswith(b"version ") and b"git-lfs.github.com/spec/v1" in data[:256]:
        findings.append("Git LFS pointer")
    if re.search(rb"AKID[A-Za-z0-9]{16,}", data):
        findings.append("Tencent SecretId-shaped content")
    if re.search(rb"AKIA[0-9A-Z]{16}", data):
        findings.append("AWS access-key-shaped content")
    if re.search(rb"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----", data):
        findings.append("private-key-shaped content")
    if _has_non_placeholder_bearer(data):
        findings.append("bearer-token-shaped content")
    return findings


def _casefold_collisions(paths: List[str]) -> List[Tuple[str, str]]:
    first: Dict[str, str] = {}
    collisions: List[Tuple[str, str]] = []
    for path in paths:
        key = path.casefold()
        if key in first and first[key] != path:
            collisions.append((first[key], path))
        else:
            first[key] = path
    return collisions


def _junk_reason(path: str) -> Optional[str]:
    lower = path.lower()
    base = lower.rsplit("/", 1)[-1]
    if base == ".ds_store":
        return "OS junk"
    if base.startswith("~$"):
        return "editor lock"
    if lower.startswith("runs/") or "/runs/" in lower:
        return "run output"
    if lower.startswith("__pycache__/") or "/__pycache__/" in lower or base.endswith(".pyc"):
        return "Python cache"
    if lower.startswith(".pytest_cache/") or "/.pytest_cache/" in lower:
        return "test cache"
    if lower == ".codebuddy/settings.json" or lower.startswith(".codebuddy/"):
        return "local CodeBuddy settings"
    return None


def classify(entry: TreeEntry) -> Tuple[str, str]:
    path_reason = _portable_path_reason(entry.path)
    if path_reason is not None:
        return "refuse", "unsafe path (%s)" % path_reason
    credential_reason = _credential_path_reason(entry.path)
    if credential_reason is not None:
        return "refuse", credential_reason
    junk_reason = _junk_reason(entry.path)
    if junk_reason is not None:
        return "exclude", junk_reason
    if entry.kind != "blob" or entry.mode not in ("100644", "100755", "120000"):
        return "refuse", "unsupported Git entry mode or type"
    return "include", "source"


def _symlink_target(path: str, data: bytes) -> str:
    try:
        target = data.decode("utf-8")
    except UnicodeDecodeError:
        raise PackageRefusal("%s: symlink target is not UTF-8" % path) from None
    if not target or "\x00" in target or "\\" in target:
        raise PackageRefusal("%s: symlink target is unsafe" % path)
    if target.startswith("/"):
        raise PackageRefusal("%s: symlink points outside the package root" % path)
    resolved = posixpath.normpath(posixpath.join(posixpath.dirname(path), target))
    if resolved == ".." or resolved.startswith("../"):
        raise PackageRefusal("%s: symlink points outside the package root" % path)
    return resolved


def _validate_symlinks(records: Dict[str, Tuple[TreeEntry, bytes]]) -> None:
    paths = set(records)
    links: Dict[str, str] = {}
    for path, (entry, data) in records.items():
        if entry.mode != "120000":
            continue
        target = _symlink_target(path, data)
        if target not in paths and not any(name.startswith(target + "/") for name in paths):
            raise PackageRefusal("%s: symlink target is not in the package root" % path)
        links[path] = target

    def visit(path: str, stack: Tuple[str, ...]) -> None:
        if path not in links:
            return
        if path in stack:
            raise PackageRefusal("%s: symlink loop" % path)
        visit(links[path], stack + (path,))

    for path in links:
        visit(path, ())


def _output_raw_reason(raw: str) -> Optional[str]:
    if "\\" in raw:
        return "backslash"
    if re.match(r"^[A-Za-z]:", raw):
        return "drive name"
    if "\x00" in raw or any(ord(char) < 32 or ord(char) == 127 for char in raw):
        return "control character"
    for component in raw.replace("\\", "/").split("/"):
        if not component or component in (".", ".."):
            continue
        reason = _portable_component_reason(component)
        if reason is not None:
            return reason
    return None


def _same_disk_directory(left: Path, right: Path) -> bool:
    try:
        return os.path.isdir(str(left)) and os.path.samefile(str(left), str(right))
    except (OSError, ValueError):
        return False


def _inside_repository(repo: Path, output_parent: Path) -> bool:
    current = output_parent
    while True:
        if _same_disk_directory(current, repo):
            return True
        if current == current.parent:
            return False
        current = current.parent


def _validate_output(repo: Path, raw_out: str, purpose: str, revision: str) -> Path:
    reason = _output_raw_reason(raw_out)
    if reason is not None:
        raise PackageRefusal("unsafe output path (%s)" % reason)
    output = Path(raw_out)
    if not output.is_absolute():
        output = Path.cwd() / output
    if output.suffix.lower() != ".zip":
        raise PackageRefusal("output filename must end in .zip")
    marker = "ryde-live-%s-%s" % (purpose, revision[:12])
    if marker not in output.name:
        raise PackageRefusal("output filename does not contain the purpose and revision")
    if not output.parent.exists():
        raise PackageRefusal("output directory does not exist")
    if not output.parent.is_dir():
        raise PackageRefusal("output directory is not a directory")
    if os.path.lexists(str(output)):
        if output.is_symlink():
            raise PackageRefusal("output path is a symlink")
        raise PackageRefusal("output archive already exists")
    if _inside_repository(repo, output.parent):
        raise PackageRefusal("output is inside the repository")
    return output


def _wrapper_refusals(records: Dict[str, Tuple[TreeEntry, bytes]]) -> List[str]:
    findings: List[str] = []
    batch = records.get("start-live.bat")
    if batch is not None:
        entry, data = batch
        if entry.mode != "100644":
            findings.append("start-live.bat: expected Git mode 100644")
        if not data or data.count(b"\n") != data.count(b"\r\n"):
            findings.append("start-live.bat: expected CRLF line endings")
    command = records.get("start-live.command")
    if command is not None:
        entry, data = command
        if entry.mode != "100755":
            findings.append("start-live.command: expected Git mode 100755")
        if not data.startswith(b"#!/bin/bash\n") or b"\r" in data:
            findings.append("start-live.command: expected executable Unix line endings")
    return findings


def _commit_datetime(repo: Path, revision: str) -> Tuple[Tuple[int, int, int, int, int, int], str]:
    raw = _git(repo, "show", "-s", "--format=%ct", revision).strip()
    try:
        stamp = int(_decode(raw, "commit timestamp"))
    except ValueError:
        raise PackageRefusal("selected revision has no usable commit time") from None
    moment = datetime.fromtimestamp(stamp, tz=timezone.utc)
    return (
        (moment.year, moment.month, moment.day, moment.hour, moment.minute, moment.second),
        moment.isoformat(),
    )


def _zip_source_entry(archive: zipfile.ZipFile, name: str, data: bytes, mode: str,
                      date_time: Tuple[int, int, int, int, int, int]) -> None:
    info = zipfile.ZipInfo(name, date_time=date_time)
    info.compress_type = zipfile.ZIP_DEFLATED
    if mode == "120000":
        info.external_attr = 0o120777 << 16
    else:
        info.external_attr = int(mode, 8) << 16
    info.create_system = 3
    archive.writestr(info, data)


def _build_archive(output: Path, top: str, records: Dict[str, Tuple[TreeEntry, bytes]],
                   excluded: List[Dict[str, str]], manifest: Dict[str, object],
                   date_time: Tuple[int, int, int, int, int, int]) -> None:
    temporary = output.with_name("." + output.name + ".partial")
    if os.path.lexists(str(temporary)):
        raise PackageRefusal("temporary output path already exists")
    try:
        with zipfile.ZipFile(str(temporary), "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(records):
                entry, data = records[path]
                _zip_source_entry(archive, top + "/" + path, data, entry.mode, date_time)
            manifest_data = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
            _zip_source_entry(archive, top + "/MANIFEST.json", manifest_data, "100644", date_time)
        try:
            os.link(str(temporary), str(output))
        except FileExistsError:
            raise PackageRefusal("output archive already exists") from None
        os.unlink(str(temporary))
    except PackageRefusal:
        if os.path.lexists(str(temporary)):
            os.unlink(str(temporary))
        raise
    except Exception:
        if os.path.lexists(str(temporary)):
            os.unlink(str(temporary))
        raise PackageRefusal("could not write the output archive") from None


def _working_tree_dirty(repo: Path) -> bool:
    return bool(_git(repo, "status", "--porcelain", "--untracked-files=no"))


def build(repo: Path, revision: str, purpose: str, raw_out: str) -> Path:
    repo = Path(repo)
    if not repo.is_dir():
        raise PackageRefusal("repository directory does not exist")
    resolved = _resolve_revision(repo, revision)
    head = _resolve_revision(repo, "HEAD")
    dirty = _working_tree_dirty(repo)
    if dirty and resolved == head:
        raise PackageRefusal("source revision is ambiguous because tracked files are modified")
    output = _validate_output(repo, raw_out, purpose, resolved)
    entries = _tree(repo, resolved)
    by_path = {entry.path: entry for entry in entries}
    missing = [path for path in REQUIRED_FILES if path not in by_path]
    missing += [path for path in PRESERVED_FILES if path not in by_path]
    if missing:
        raise PackageRefusal("missing required package file or preserved source entry point: %s" %
                             ", ".join(missing))

    collisions = _casefold_collisions([entry.path for entry in entries])
    if collisions:
        detail = ", ".join("%s / %s" % pair for pair in collisions)
        raise PackageRefusal("case-fold collision in source paths: %s" % detail)

    records: Dict[str, Tuple[TreeEntry, bytes]] = {}
    excluded: List[Dict[str, str]] = []
    refusals: List[str] = []
    for entry in sorted(entries, key=lambda item: item.path):
        decision, reason = classify(entry)
        if decision == "refuse":
            refusals.append("%s (%s)" % (entry.path, reason))
            continue
        data = _blob(repo, entry.sha)
        findings = content_refusals(entry.path, data)
        if findings:
            refusals.extend("%s (%s)" % (entry.path, finding) for finding in findings)
            continue
        if decision == "exclude":
            excluded.append({"path": entry.path, "reason": reason})
        else:
            records[entry.path] = (entry, data)
    if refusals:
        raise PackageRefusal("unsafe source content or path: %s" % "; ".join(refusals))

    wrapper_findings = _wrapper_refusals(records)
    if wrapper_findings:
        raise PackageRefusal("wrapper validation failed: %s" % "; ".join(wrapper_findings))
    _validate_symlinks(records)

    date_time, commit_iso = _commit_datetime(repo, resolved)
    top = "ryde-live-%s-%s" % (purpose, resolved[:12])
    included = []
    for path in sorted(records):
        entry, data = records[path]
        included.append({
            "path": path,
            "git_mode": entry.mode,
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        })
    manifest = {
        "schema": "ryde-live-source-package-v1",
        "source": {
            "revision": resolved,
            "revision_abbrev": resolved[:12],
            "inventory": "Git tree blobs at the selected committed revision",
            "commit_time": commit_iso,
            "working_tree_dirty": dirty,
        },
        "package": {
            "purpose": purpose,
            "top_level_folder": top,
            "built_at": datetime.now(timezone.utc).isoformat(),
        },
        "required_files": list(REQUIRED_FILES),
        "included": included,
        "excluded": excluded,
        "counts": {"included": len(included), "excluded": len(excluded)},
        "notes": {
            "credentials": "The private .env.live is delivered separately and is never a source entry.",
            "pattern_scan": "The narrow pattern scan is not proof that the archive contains no real credential.",
            "w6_privacy_gate": "W6 privacy and release checks remain a parent-owned gate, including comparison against ACTUAL live key bytes.",
        },
    }
    _build_archive(output, top, records, excluded, manifest, date_time)
    print("Created %s" % output)
    print("Extract the ZIP first, then run the launcher from the package folder.")
    print("Copy the privately delivered .env.live beside the extracted source; do not put keys on a command line.")
    print("Use start-live.command on macOS or start-live.bat on Windows; the standard start.command and start.bat remain mock entry points.")
    print("The narrow pattern scan is not proof of a key-free archive; the release gate compares against ACTUAL live key bytes.")
    return output


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Package one committed Git source tree with no network call; this tool never reads, creates or rotates a credential.",
    )
    parser.add_argument("--repo", required=True, help="source repository directory")
    parser.add_argument("--revision", required=True, help="explicit committed source revision")
    parser.add_argument("--purpose", required=True, choices=("rehearsal", "submission"),
                        help="package purpose")
    parser.add_argument("--out", required=True, help="output ZIP path")
    return parser


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    try:
        build(Path(args.repo), args.revision, args.purpose, args.out)
    except PackageRefusal as exc:
        print("REFUSED: %s" % exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
