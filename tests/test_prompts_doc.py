"""Acceptance target for docs/prompts.md, the "how prompts drive the AI generation" deliverable.

These tests pin the MECHANICAL fidelity of that document to the code: every schema field
the agents' output contracts name appears in the doc, every section it must have exists,
every repo path it names exists, the gate figures match app/config.json, the hard rules
quoted match the code, and every worked example field name matches the real schemas. They
cannot tell whether a sentence is true; a line-by-line claim audit does that.
"""
import json
import re
import unittest
from pathlib import Path

from app.agents.base import HARD_RULES
from app.agents.judge import Judge
from app.agents.base import AdvocateAgent

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "docs" / "prompts.md"
CONFIG = ROOT / "app" / "config.json"

REQUIRED_SECTIONS = (
    "How the three agents work",
    "Shared prompt anatomy",
    "The hard rules",
    "What the code checks after every call",
    "Rider Advocate",
    "Driver Advocate",
    "Judge",
    "Worked example",
    "What the parties see",
    "Transport and the live endpoint",
)

# Field names from the real output schemas. The doc must name each one somewhere in its
# schema tables; a rename in the code turns this red until the doc follows.
ADVOCATE_SCHEMA_FIELDS = tuple(sorted(AdvocateAgent.OUTPUT_SCHEMA.keys()))
JUDGE_SCHEMA_FIELDS = tuple(sorted(Judge.OUTPUT_SCHEMA.keys()))

PATH_TOKEN = re.compile(r"`((?:app|ui|data|docs|tools|tests)/[A-Za-z0-9_./-]*)`")
# Our own tracker and review-round labels mean nothing to a judge.
TRACKER_LABELS = re.compile(r"\b(?:W\d{1,2}|R\d{1,2}|S[1-5]|T[1-4])\b")
PROCESS_WORDS = re.compile(
    r"\bsession (?:one|two|three|four|five|six|seven)\b|\bHermi\b|\bHermes\b|planning repo",
    re.IGNORECASE,
)

# Sentences of the hard-rules block that the doc must quote (or contain the opening of)
# verbatim, so a rewording in the code is visible in the doc's diff.
PINNED_RULE_OPENINGS = (
    "Never do arithmetic",
    "Cite evidence only by the exact dotted references",
    "Cite policy only by rule IDs",
    "Return exactly one JSON object",
)


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


class PromptsDoc(unittest.TestCase):
    def doc(self) -> str:
        if not DOC.exists():
            self.fail("docs/prompts.md does not exist yet")
        return _text(DOC)

    def test_has_every_required_section(self):
        headings = set(re.findall(r"^## (.+?)\s*$", self.doc(), re.MULTILINE))
        self.assertEqual([], [s for s in REQUIRED_SECTIONS if s not in headings])

    def test_every_repo_path_it_names_exists(self):
        named = set(PATH_TOKEN.findall(self.doc()))
        self.assertEqual([], sorted(p for p in named if not (ROOT / p).exists()))

    def test_names_every_advocate_schema_field(self):
        text = self.doc()
        self.assertEqual(
            [],
            [f for f in ADVOCATE_SCHEMA_FIELDS if "`%s`" % f not in text],
            "every Advocate output-schema field must be named in docs/prompts.md",
        )

    def test_names_every_judge_schema_field(self):
        text = self.doc()
        self.assertEqual(
            [],
            [f for f in JUDGE_SCHEMA_FIELDS if "`%s`" % f not in text],
            "every Judge output-schema field must be named in docs/prompts.md",
        )

    def test_pins_the_hard_rule_openings(self):
        text = self.doc()
        self.assertEqual(
            [],
            [opening for opening in PINNED_RULE_OPENINGS if opening not in text],
            "the doc must carry the hard rules' openings so a reword in code shows here",
        )

    def test_hard_rules_in_doc_match_code_text(self):
        """The doc carries the hard-rules block verbatim, fenced, so it cannot drift."""
        text = self.doc()
        self.assertIn("```text\n%s\n```" % HARD_RULES.strip(), text)

    def test_gate_figures_match_config(self):
        config = json.loads(CONFIG.read_text(encoding="utf-8"))
        text = self.doc()
        self.assertIn("SGD %.2f" % config["autonomous_cap_sgd"], text)
        self.assertIn("%.2f" % config["confidence_threshold"], text)

    def test_names_the_two_advocates_and_the_judge(self):
        text = self.doc()
        for name in ("Rider Advocate", "Driver Advocate", "Judge"):
            self.assertIn(name, text)

    def test_worked_example_uses_real_field_names(self):
        """The worked example's JSON field names all exist in the real schemas."""
        text = self.doc()
        blocks = re.findall(r"```json\n(.*?)```", text, re.DOTALL)
        self.assertTrue(blocks, "the doc must carry at least one fenced JSON example")
        allowed = set(ADVOCATE_SCHEMA_FIELDS) | set(JUDGE_SCHEMA_FIELDS)
        for block in blocks:
            payload = json.loads(block)
            unknown = [k for k in payload.keys() if k not in allowed]
            self.assertEqual(
                [],
                unknown,
                "worked-example fields must be real schema fields; unknown: %s" % unknown,
            )

    def test_worked_example_rules_and_refs_are_real(self):
        """Every rule ID and evidence ref in the examples exists in the policy or pack."""
        text = self.doc()
        policy_text = (ROOT / "docs" / "policy.md").read_text(encoding="utf-8")
        rule_ids = set(re.findall(r"^### ([A-Z]{2,4}-\d+)", policy_text, re.MULTILINE))
        # Dispute ids are RD-0103 (4 digits); rule ids are RD-1 (1-2 digits).
        for rule in set(re.findall(r"\b([A-Z]{2,4}-\d{1,2})\b", text)):
            if rule.startswith("SGD"):
                continue
            self.assertIn(
                rule,
                rule_ids | {"GEN-3"},
                "rule ID %s named in the doc is not a policy rule" % rule,
            )

    def test_no_tracker_labels_or_process_words(self):
        """A judge reads this doc; our internal ticket labels stay out of it."""
        text = self.doc()
        hits = sorted(set(TRACKER_LABELS.findall(text)))
        self.assertEqual([], hits, "tracker labels found in docs/prompts.md: %s" % hits)
        hits = sorted(set(m.group(0) for m in PROCESS_WORDS.finditer(text)))
        self.assertEqual([], hits, "process words found in docs/prompts.md: %s" % hits)

    def test_states_the_party_never_sees_agent_text(self):
        text = self.doc()
        self.assertIn(
            "The party never sees text an agent writes",
            text,
            "the doc must state the party-message guarantee up front",
        )


if __name__ == "__main__":
    unittest.main()