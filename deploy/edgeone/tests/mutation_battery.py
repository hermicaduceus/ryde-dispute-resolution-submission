"""Mutation battery for the live adapter: every mutation must turn test_live_adapter red.

    python3 deploy/edgeone/tests/mutation_battery.py [SITE_DIR]

With no SITE_DIR the bundle is assembled from this repository into a temporary folder.
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TESTS = Path(__file__).resolve().parent
if len(sys.argv) > 1:
    SITE = Path(sys.argv[1])
else:
    sys.path.insert(0, str(TESTS.parent))
    import package

    SITE = package.build(Path(tempfile.mkdtemp(prefix="ryde-edgeone-site-")) / "site")
ENTRY_REL = Path("cloud-functions/api/[[default]].py")

MUTATIONS = [
    ("provider mock", 'LIVE_PROVIDER = "tencent"', 'LIVE_PROVIDER = "mock"'),
    ("budget 120", "CASE_BUDGET_SECONDS = 100", "CASE_BUDGET_SECONDS = 120"),
    ("budget not passed", "case_budget_seconds=CASE_BUDGET_SECONDS,", "case_budget_seconds=config.llm.case_budget_seconds,"),
    ("visitor limit 11", "PER_VISITOR_LIMIT = 10", "PER_VISITOR_LIMIT = 11"),
    ("daily limit off-by-one", 'if counts["daily"] >= DAILY_LIMIT:', 'if counts["daily"] > DAILY_LIMIT:'),
    ("visitor check dropped", "if len(recent) >= PER_VISITOR_LIMIT:", "if False:"),
    ("daily check dropped", 'if counts["daily"] >= DAILY_LIMIT:', "if False:"),
    ("window never expires", "now - t < VISITOR_WINDOW_SECONDS]", "True]"),
    ("window 3600 -> 7200", "VISITOR_WINDOW_SECONDS = 3600", "VISITOR_WINDOW_SECONDS = 7200"),
    ("UTC day", "SGT = timezone(timedelta(hours=8))", "SGT = timezone.utc"),
    ("no day reset", 'if counts.get("day") != day or not isinstance(counts.get("daily"), int):', 'if not isinstance(counts.get("daily"), int):'),
    ("no refund", "                release_slot(visitor, stamp)", "                pass"),
    ("refund on success too", "if not (isinstance(status, int) and 200 <= status < 300):", "if True:"),
    ("count every category", "and body[\"category\"] in AGENT_CATEGORIES", "and True"),
    ("count answers", 'if urlsplit(self.path).path != "/api/disputes":', 'if not self.path.startswith("/api/disputes"):'),
    ("F1 route key drops query only", 'if urlsplit(self.path).path != "/api/disputes":', 'if self.path.split("?", 1)[0] != "/api/disputes":'),
    ("F2 midnight wipes visitors", 'counts = {"day": day, "daily": 0, "visitors": counts.get("visitors")}', 'counts = {"day": day, "daily": 0, "visitors": {}}'),
    ("F4 prefix restore dropped", 'self.path = "/api" + (self.path if self.path.startswith("/") else "/" + self.path)', 'pass'),
    ("F7 log dropped", 'sys.stderr.write("ryde live: state not ready: %s: %s\\n" % (type(exc).__name__, exc))', 'pass'),
    ("429 -> 400", "self._refuse(429, refusal)", "self._refuse(400, refusal)"),
    ("generic refusal text", "self._refuse(429, refusal)", 'self._refuse(429, "limit")'),
    ("503 swallowed", "self._refuse(503, NOT_CONFIGURED_MESSAGE)", "self._refuse(500, NOT_CONFIGURED_MESSAGE)"),
    ("visitor from forwarded", 'value = (self.headers.get("Eo-Connecting-Ip") or "").strip()', 'value = (self.headers.get("X-Forwarded-For") or "").split(",")[0].strip()'),
    ("visitor from EO-Client-IP", 'value = (self.headers.get("Eo-Connecting-Ip") or "").strip()', 'value = (self.headers.get("EO-Client-IP") or self.headers.get("Eo-Connecting-Ip") or "").strip()'),
    ("fallback mints per-request id", 'return value or "unknown"', 'return value or str(_now())'),
    ("no file lock", "        fcntl.flock(handle, fcntl.LOCK_EX)\n", ""),
    ("policy anchor dropped", "    pipeline._REPO_ROOT = root\n", ""),
    ("policy anchor unresolved", "    root = root.resolve()  # pipeline resolves the policy path, so the anchor must be resolved too\n", ""),
    ("corrupt file not reset", "            if not isinstance(counts, dict):\n                counts = {}\n", ""),
]


def run(site):
    env = dict(os.environ, RYDE_LIVE_SITE=str(site))
    env.pop("PYTHONPATH", None)
    p = subprocess.run([sys.executable, "-m", "unittest", "test_live_adapter"], cwd=TESTS, env=env,
                       capture_output=True, text=True, timeout=600)
    tail = p.stderr.strip().splitlines()[-1] if p.stderr.strip() else ""
    return p.returncode, tail


def main():
    base_rc, base_tail = run(SITE)
    print("BASE rc=%d %s" % (base_rc, base_tail))
    assert base_rc == 0, "base must be green"
    survivors = []
    for name, old, new in MUTATIONS:
        tmp = Path(tempfile.mkdtemp(prefix="mut-"))
        try:
            shutil.copytree(SITE / "cloud-functions", tmp / "cloud-functions")
            entry = tmp / ENTRY_REL
            src = entry.read_text()
            n = src.count(old)
            if n != 1:
                print("MISAPPLIED (%d hits): %s" % (n, name))
                survivors.append(name + " [misapplied]")
                continue
            entry.write_text(src.replace(old, new))
            rc, tail = run(tmp)
            verdict = "KILLED" if rc != 0 else "SURVIVED"
            print("%-8s %-28s %s" % (verdict, name, tail))
            if rc == 0:
                survivors.append(name)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    print("\nsurvivors: %d %s" % (len(survivors), survivors))
    sys.exit(1 if survivors else 0)


if __name__ == "__main__":
    main()
