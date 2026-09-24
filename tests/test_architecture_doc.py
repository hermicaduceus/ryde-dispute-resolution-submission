"""Acceptance target for docs/architecture.md, the architecture deliverable.

The challenge statement asks for "a clear visual representation of the multi-agent system
and key components". These tests pin the MECHANICAL fidelity of that document to the code:
every repo path it names exists, every event type and outcome the code emits is named, the
gate figures match app/config.json, and the README carries the same diagram as the doc.
They cannot tell whether a sentence is true. A line-by-line claim audit and a
cross-family review do that.
"""
import json
import re
import unittest
from pathlib import Path

from app.events import EventType
from app.schemas import (
    OUTCOME_HUMAN_REVIEW,
    OUTCOME_NEEDS_INFO,
    OUTCOME_RULED,
    OUTCOME_WITHHELD,
)
from app.server import PARTY_STATUS_BY_OUTCOME

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "docs" / "architecture.md"
README = ROOT / "README.md"
CODEBUDDY = ROOT / "CODEBUDDY.md"
CONFIG = ROOT / "app" / "config.json"

REQUIRED_SECTIONS = (
    "Overview",
    "Diagram",
    "Components",
    "Lifecycle of a dispute",
    "The four outcomes",
    "Gates enforced in code",
    "Observability",
    "What the parties see",
    "Policy and dataset packs",
    "LLM provider",
    "Limits",
)

CORE_MODULES = (
    "app/pipeline.py",
    "app/dispute.py",
    "app/evidence/compute.py",
    "app/agents/base.py",
    "app/agents/rider_advocate.py",
    "app/agents/driver_advocate.py",
    "app/agents/judge.py",
    "app/events.py",
    "app/schemas.py",
    "app/policy.py",
    "app/llm/mock.py",
    "app/llm/tencent.py",
    "app/server.py",
    "app/cli.py",
    "app/config.json",
    "ui/app.js",
    "ui/party/party.js",
    "docs/policy.md",
)

DIAGRAM_NODES = ("rider advocate", "driver advocate", "judge", "evidence pack", "human review")

PATH_TOKEN = re.compile(r"`((?:app|ui|data|docs|tools|tests)/[A-Za-z0-9_./-]*)")
MERMAID = re.compile(r"```mermaid\n(.*?)```", re.DOTALL)
# Our own tracker and review-round labels. They mean nothing to a judge. Case-sensitive,
# and checked outside the Mermaid block so that node ids like S1 stay legal.
TRACKER_LABELS = re.compile(r"\b(?:W\d{1,2}|R\d{1,2}|S[1-5]|T[1-4]|F[1-9])\b")
PROCESS_WORDS = re.compile(
    r"\bsession (?:one|two|three|four|five|six|seven)\b|\bHermi\b|\bHermes\b|planning repo",
    re.IGNORECASE,
)
TEST_COUNT = re.compile(r"\b\d{2,4}(?: tests\b|, stdlib)")


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


class ArchitectureDoc(unittest.TestCase):
    def doc(self) -> str:
        if not DOC.exists():
            self.fail("docs/architecture.md does not exist yet")
        return _text(DOC)

    def test_has_every_required_section(self):
        headings = set(re.findall(r"^## (.+?)\s*$", self.doc(), re.MULTILINE))
        self.assertEqual([], [s for s in REQUIRED_SECTIONS if s not in headings])

    def test_every_repo_path_it_names_exists(self):
        named = set(PATH_TOKEN.findall(self.doc()))
        self.assertEqual([], sorted(p for p in named if not (ROOT / p).exists()))

    def test_names_the_core_modules(self):
        text = self.doc()
        self.assertEqual([], [m for m in CORE_MODULES if "`%s`" % m not in text])

    def test_names_every_event_type(self):
        text = self.doc()
        types = [v for k, v in vars(EventType).items() if k.isupper()]
        self.assertTrue(types)
        self.assertEqual([], ["`%s`" % t for t in types if "`%s`" % t not in text])

    def test_names_every_outcome_and_party_status(self):
        text = self.doc()
        names = [OUTCOME_RULED, OUTCOME_WITHHELD, OUTCOME_HUMAN_REVIEW, OUTCOME_NEEDS_INFO]
        names += sorted(set(PARTY_STATUS_BY_OUTCOME.values()))
        self.assertEqual([], ["`%s`" % n for n in names if "`%s`" % n not in text])

    def test_gate_figures_match_config(self):
        text = self.doc()
        config = json.loads(CONFIG.read_text(encoding="utf-8"))
        cap = float(config["autonomous_cap_sgd"])
        cap_text = "SGD %d" % cap if cap.is_integer() else "SGD %.2f" % cap
        for needle in ("%.2f" % config["confidence_threshold"], cap_text, "ESC-2", "ESC-4"):
            self.assertIn(needle, text)

    def test_names_every_pack_and_the_default(self):
        text = self.doc()
        packs = sorted(p.name for p in (ROOT / "data" / "packs").iterdir() if p.is_dir())
        self.assertTrue(packs)
        self.assertEqual([], ["`%s`" % p for p in packs if "`%s`" % p not in text])
        default = re.escape(json.loads(CONFIG.read_text(encoding="utf-8"))["dataset_pack"])
        self.assertRegex(text, r"(?i)`%s`[^\n]*default|default[^\n]*`%s`" % (default, default))

    def test_states_the_mock_honestly(self):
        self.assertIn("MOCK", self.doc())

    def test_describes_the_party_boundary_with_real_symbols(self):
        text = self.doc()
        for needle in ("`party_view`", "allowlist", "`party_message_for_ruling`"):
            self.assertIn(needle, text)
        # The symbols the doc leans on must still exist, so this test cannot go stale.
        self.assertIn("def party_view(", _text(ROOT / "app" / "server.py"))
        self.assertIn("def party_message_for_ruling(", _text(ROOT / "app" / "schemas.py"))

    def test_no_internal_tracker_labels(self):
        prose = MERMAID.sub("", self.doc())
        self.assertEqual([], sorted({m.group(0) for m in TRACKER_LABELS.finditer(prose)}))
        self.assertEqual([], sorted({m.group(0) for m in PROCESS_WORDS.finditer(prose)}))

    def test_one_mermaid_diagram_shared_with_the_readme(self):
        doc_blocks = MERMAID.findall(self.doc())
        readme_blocks = MERMAID.findall(_text(README))
        self.assertEqual(1, len(doc_blocks), "docs/architecture.md needs exactly one mermaid block")
        self.assertEqual(1, len(readme_blocks), "README.md needs exactly one mermaid block")
        self.assertEqual(doc_blocks[0].strip(), readme_blocks[0].strip())
        lowered = doc_blocks[0].lower()
        self.assertEqual([], [n for n in DIAGRAM_NODES if n not in lowered])


class EntryPointsPointAtTheDoc(unittest.TestCase):
    def test_readme_links_the_doc(self):
        self.assertIn("](docs/architecture.md)", _text(README))

    def test_nothing_still_calls_the_doc_unwritten(self):
        for path in (README, CODEBUDDY):
            stale = [
                line for line in _text(path).splitlines()
                if "architecture" in line.lower() and "to come" in line.lower()
            ]
            self.assertEqual([], stale, path.name)

    def test_entry_points_carry_no_test_count(self):
        # A hard-coded count goes stale every session (the README said 225 when the suite
        # was 325). The command is the source of truth, not a number in prose.
        for path in (README, CODEBUDDY):
            self.assertEqual([], TEST_COUNT.findall(_text(path)), path.name)


# --------------------------------------------------------------- review-round pins
# Added after the cross-family review of the first draft. Each pins a finding that is
# mechanical enough to check; the semantic findings are verified by reading.

NODE_LABEL = re.compile(r"(\w+)\s*(?:\[\s*\"([^\"]+)\"\s*\]|\{\s*\"([^\"]+)\"\s*\}|\(\s*\"([^\"]+)\"\s*\))")
QUOTED = re.compile(r"\"[^\"]*\"")
BRACKETS = re.compile(r"\[[^\]]*\]|\{[^}]*\}|\([^)]*\)")
EDGE = re.compile(r"^\s*(\w+)\s*[-.=\s]+>\s*(\w+)")


def _diagram(text: str):
    """(labels by lowercased label -> node id, set of (from_id, to_id) edges)."""
    block = MERMAID.findall(text)[0]
    labels = {}
    for match in NODE_LABEL.finditer(block):
        label = next(g for g in match.groups()[1:] if g)
        labels.setdefault(label.strip().lower(), match.group(1))
    edges = set()
    for line in block.splitlines():
        bare = BRACKETS.sub("", QUOTED.sub("", line))
        found = EDGE.match(bare)
        if found:
            edges.add((found.group(1), found.group(2)))
    return labels, edges


def _node(labels, *needles):
    for label, node_id in labels.items():
        if all(n in label for n in needles):
            return node_id
    return None


class ReviewRoundPins(unittest.TestCase):
    def setUp(self):
        if not DOC.exists():
            self.fail("docs/architecture.md does not exist yet")
        self.text = _text(DOC)

    def test_withheld_ruling_reaches_human_review_in_the_diagram(self):
        labels, edges = _diagram(self.text)
        withheld, human = _node(labels, "withheld"), _node(labels, "human review")
        self.assertIsNotNone(withheld)
        self.assertIsNotNone(human)
        self.assertIn((withheld, human), edges)

    def test_dataset_pack_feeds_the_server_not_the_form(self):
        labels, edges = _diagram(self.text)
        pack, server = _node(labels, "dataset pack"), _node(labels, "server")
        self.assertIn((pack, server), edges)
        form = _node(labels, "intake form")
        self.assertNotIn((pack, form), edges)

    def test_diagram_shows_the_command_line_runner(self):
        labels, _edges = _diagram(self.text)
        self.assertTrue(_node(labels, "command") or _node(labels, "cli"), sorted(labels))

    def test_names_the_web_run_files_and_the_answers_route(self):
        for needle in ("`dispute.json`", "`answered.json`", "/api/disputes/<run_id>/answers"):
            self.assertIn(needle, self.text)

    def test_readme_names_all_three_judge_gates(self):
        readme = _text(README)
        self.assertNotIn("Two gates", readme)
        self.assertIn("ESC-2", readme)

    def test_readme_advocates_do_not_gather_evidence(self):
        self.assertNotIn("Gathers rider-side evidence", _text(README))
        self.assertNotIn("Gathers driver-side evidence", _text(README))


if __name__ == "__main__":
    unittest.main()
