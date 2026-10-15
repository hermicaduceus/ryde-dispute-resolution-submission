"""Assemble the EdgeOne Makers bundle for the live AI site from this repository.

    python3 deploy/edgeone/package.py OUT_DIR [--zip OUT_ZIP]

The bundle is the shipped application, unchanged, plus this folder's deploy-only files:

    OUT_DIR/
      edgeone.json                     deploy/edgeone/site/edgeone.json (root redirect, 120 s cap)
      index.html, party/, start/, ...  ui/, with the six "Operator console" links repointed
      cloud-functions/
        api/[[default]].py             deploy/edgeone/site/... (the adapter: provider, limits)
        ryde_deploy_policy.py          deploy/edgeone/site/... (docs/policy.md as a .py carrier)
        app/                           app/, byte for byte
        data/                          data/, byte for byte

Why the links move: the site's root redirects to the dispute page, so a link to the root would
loop back there; the console stays reachable at index.html. Each replacement must match exactly
once or the build stops. Why the policy carrier: the bundler drops .md files and docs/, so the
policy rides as a Python string and the adapter writes it back out after checking its SHA256.
The build refuses a carrier that no longer matches docs/policy.md.

No key is read or written here. The live site reads its three Tencent ADP app keys from the
EdgeOne project's environment variables at run time.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import shutil
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
SITE = HERE / "site"

# (path under ui/, exact old text, new text): the hosted copy's only differences from ui/.
HREF_REPOINTS = [
    ("index.html", '<a href="./" aria-current="page">Operator console</a>',
     '<a href="./index.html" aria-current="page">Operator console</a>'),
    ("party/index.html", '<a href="../">Operator console</a>', '<a href="../index.html">Operator console</a>'),
    ("party/driver.html", '<a href="../">Operator console</a>', '<a href="../index.html">Operator console</a>'),
    ("party/driver-filing.html", '<a href="../">Operator console</a>', '<a href="../index.html">Operator console</a>'),
    ("party/status.html", '<a href="../">Operator console</a>', '<a href="../index.html">Operator console</a>'),
    ("start/index.html", '<a class="start-card" href="../">', '<a class="start-card" href="../index.html">'),
]

SKIP_NAMES = {".DS_Store", "__pycache__"}


def _skip(path: Path) -> bool:
    return any(part in SKIP_NAMES or part.startswith("._") or part.endswith((".pyc", ".pyo"))
               for part in path.parts)


def _copy_tree(src: Path, dst: Path) -> None:
    for item in sorted(src.rglob("*")):
        rel = item.relative_to(src)
        if _skip(rel) or not item.is_file():
            continue
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(item, target)


def check_policy_carrier(repo: Path = REPO) -> None:
    spec = importlib.util.spec_from_file_location("ryde_deploy_policy_check",
                                                  SITE / "cloud-functions" / "ryde_deploy_policy.py")
    carrier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(carrier)
    policy = (repo / "docs" / "policy.md").read_bytes()
    if carrier.TEXT.encode("utf-8") != policy or hashlib.sha256(policy).hexdigest() != carrier.SHA256:
        raise SystemExit("ryde_deploy_policy.py no longer matches docs/policy.md; regenerate the carrier")


def build(out: Path, repo: Path = REPO) -> Path:
    out = Path(out)
    if out.exists() and any(out.iterdir()):
        raise SystemExit("output folder is not empty: %s" % out)
    check_policy_carrier(repo)
    out.mkdir(parents=True, exist_ok=True)
    _copy_tree(repo / "ui", out)
    for rel, old, new in HREF_REPOINTS:
        page = out / rel
        text = page.read_text(encoding="utf-8")
        if text.count(old) != 1:
            raise SystemExit("expected exactly one %r in ui/%s, found %d" % (old, rel, text.count(old)))
        page.write_text(text.replace(old, new), encoding="utf-8")
    _copy_tree(SITE, out)
    _copy_tree(repo / "app", out / "cloud-functions" / "app")
    _copy_tree(repo / "data", out / "cloud-functions" / "data")
    return out


def write_zip(site: Path, zip_path: Path) -> Path:
    """Deterministic zip: sorted entries, fixed timestamp, so two builds of one commit match."""
    zip_path = Path(zip_path)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for item in sorted(p for p in Path(site).rglob("*") if p.is_file()):
            info = zipfile.ZipInfo(item.relative_to(site).as_posix(), date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, item.read_bytes())
    return zip_path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out_dir")
    parser.add_argument("--zip", dest="zip_path")
    args = parser.parse_args(argv)
    site = build(Path(args.out_dir))
    if args.zip_path:
        write_zip(site, Path(args.zip_path))
    print("built %s" % site)
    return 0


if __name__ == "__main__":
    sys.exit(main())
