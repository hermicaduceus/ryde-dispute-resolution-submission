"""Session A acceptance target (W22): README truth fixes and the two new gates in the docs.

Written BEFORE the build, so it is RED until the CodeBuddy lane ships
docs/build-briefs/session-nineteen-brief.md. Grill rulings 2026-10-01:

- Q5: the README's false lines go ("Status: building", "skeleton", the walkthrough line
  that waits for things that already exist).
- Q13: a "How this was built" section names CodeBuddy and "a planning agent", never the
  planning agent's tool name.
- Q11/Q12b: the README and docs/architecture.md name the NS-6 and RD-5 gates.

Each check is scoped to the section that must carry it, so a sentence elsewhere cannot
satisfy it (the standing rule after session twelve's false-green suite).
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
ARCH = ROOT / "docs" / "architecture.md"
MERMAID = re.compile(r"```mermaid\n(.*?)```", re.DOTALL)


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _section(text: str, heading: str) -> str:
    """The body under a `## heading`, up to the next `## ` heading. Fails loudly if absent."""
    match = re.search(r"^## %s[ \t]*\n(.*?)(?=^## |\Z)" % re.escape(heading), text, re.M | re.S)
    if match is None:
        raise AssertionError("no '## %s' section" % heading)
    return match.group(1)


class ReadmeTruth(unittest.TestCase):
    def setUp(self):
        self.text = _text(README)

    def test_the_false_lines_are_gone(self):
        for stale in ("Status: building", "skeleton",
                      "land once the case-file UI and the real LLM call are in"):
            with self.subTest(stale=stale):
                self.assertNotIn(stale, self.text)

    def test_the_status_line_says_what_runs(self):
        line = next((l for l in self.text.splitlines() if l.startswith("**Status:")), None)
        self.assertIsNotNone(line, "the README keeps a **Status:** line")
        self.assertRegex(line, r"(?i)tencent")
        self.assertRegex(line, r"(?i)end to end")

    def test_how_this_was_built(self):
        body = _section(self.text, "How this was built")
        self.assertIn("CodeBuddy", body)
        self.assertRegex(body, r"(?i)\ba planning agent\b")
        self.assertIn("evidence/", body, "point a judge at the screenshots")
        self.assertRegex(body, r"(?i)failing test|red test|test first")

    def test_no_planning_tool_is_named_anywhere(self):
        # Spelled in pieces so a publication scrub of these names cannot rewrite the guard itself.
        for name in ("Her" + "mi", "Her" + "mes", "Clau" + "de", "Anthro" + "pic", "Op" + "us"):
            with self.subTest(name=name):
                self.assertNotRegex(self.text, r"(?i)\b%s\b" % name)

    def test_the_gate_paragraph_names_all_seven_judge_gates(self):
        # Five gates until 2026-10-02; W28 added RD-4; W29 added NS-8.
        body = _section(self.text, "Run")
        self.assertNotIn("Three gates", body)
        para = next(p for p in body.split("\n\n") if "enforced in Python" in p)
        for gate in ("confidence", "ESC-4", "ESC-2", "NS-6", "NS-8", "RD-5"):
            self.assertIn(gate, para, gate)
        self.assertRegex(para, r"(?i)\bseven gates\b")

    def test_the_run_section_shows_the_eval_command(self):
        body = _section(self.text, "Run")
        self.assertIn("python3 -m app.eval", body)
        self.assertIn("--repeat", body)


class ArchitectureGates(unittest.TestCase):
    def setUp(self):
        self.text = _text(ARCH)
        self.gates = _section(self.text, "Gates enforced in code")

    def _rows(self):
        return [l for l in self.gates.splitlines() if l.startswith("| ") and "---" not in l][1:]

    def test_ten_gates_and_the_count_matches_the_table(self):
        # Eight until 2026-10-02; W28 added RD-4; W29 added NS-8.
        self.assertTrue(self.gates.lstrip().startswith("Ten gates"),
                        "the count sentence leads the section")
        self.assertEqual(10, len(self._rows()))

    def test_ns6_row(self):
        row = next((r for r in self._rows() if "NS-6" in r.split("|")[1]), None)
        self.assertIsNotNone(row, "a table row whose first cell names NS-6")
        self.assertIn("`app/agents/judge.py`", row)
        for needle in ("driver_distance_from_pickup_m", "10", "fraud_flags", "half"):
            self.assertIn(needle, row, needle)

    def test_rd5_row(self):
        row = next((r for r in self._rows() if "RD-5" in r.split("|")[1]), None)
        self.assertIsNotNone(row, "a table row whose first cell names RD-5")
        self.assertIn("`app/agents/judge.py`", row)
        for needle in ("difference_sgd", "1.00"):
            self.assertIn(needle, row, needle)

    def test_the_diagram_gate_node_names_both(self):
        for path in (ARCH, README):
            with self.subTest(doc=path.name):
                block = MERMAID.findall(_text(path))[0]
                line = next(l for l in block.splitlines() if l.strip().startswith("J --> G{"))
                self.assertIn("NS-6", line)
                self.assertIn("RD-5", line)


if __name__ == "__main__":
    unittest.main()
