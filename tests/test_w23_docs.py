"""W23 B1 acceptance target: the docs name the human decision (light pins).

RED until docs/architecture.md gains a `## Human decision` section and the README's Run
section links the status page. Each check is scoped to the section that must carry it.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _section(text: str, heading: str) -> str:
    match = re.search(r"^## %s[ \t]*\n(.*?)(?=^## |\Z)" % re.escape(heading), text, re.M | re.S)
    if match is None:
        raise AssertionError("no '## %s' section" % heading)
    return match.group(1)


class ArchitectureHumanDecision(unittest.TestCase):
    def setUp(self):
        self.body = _section((ROOT / "docs" / "architecture.md").read_text(encoding="utf-8"), "Human decision")

    def test_names_the_module_file_event_and_ceiling(self):
        for needle in ("`app/human_review.py`", "`human_decision.json`", "`human.decision_recorded`", "SGD 500"):
            with self.subTest(needle=needle):
                self.assertIn(needle, self.body)

    def test_names_the_four_api_paths_and_two_demo_paths(self):
        for path in ("/api/review/<run_id>/decision", "/api/review/queue", "/api/review/overrides",
                     "/api/disputes/<dispute_id>", "/api/demo/rider", "/api/demo/driver"):
            with self.subTest(path=path):
                self.assertIn(path, self.body)


class ReadmeLinksTheStatusPage(unittest.TestCase):
    def test_run_section_names_the_status_page(self):
        body = _section((ROOT / "README.md").read_text(encoding="utf-8"), "Run")
        self.assertIn("/party/status.html", body)


if __name__ == "__main__":
    unittest.main()
