"""W58: the live EdgeOne deploy (deploy/edgeone/) stays green inside the main suite.

The adapter imports app/ from beside itself inside an assembled bundle, so its tests run in their
own interpreter from deploy/edgeone/tests (package.py assembles the bundle into a temporary
folder). This file only runs them and requires every one to pass with none skipped.

Run: env -u PYTHONPATH python3 -B -m unittest tests.test_w58_deploy_edgeone -v
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEPLOY_TESTS = REPO / "deploy" / "edgeone" / "tests"


class DeployEdgeOneSuite(unittest.TestCase):
    def test_adapter_and_package_tests_pass(self):
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        env.pop("RYDE_LIVE_SITE", None)
        result = subprocess.run([sys.executable, "-B", "-m", "unittest", "test_live_adapter", "test_package"],
                                cwd=DEPLOY_TESTS, env=env, capture_output=True, text=True, timeout=600)
        tail = result.stderr[-3000:]
        self.assertEqual(0, result.returncode, tail)
        ran = re.search(r"Ran (\d+) tests?", result.stderr)
        self.assertTrue(ran, tail)
        self.assertGreaterEqual(int(ran.group(1)), 33, tail)
        self.assertRegex(result.stderr, r"\nOK\s*$", tail)


if __name__ == "__main__":
    unittest.main()
