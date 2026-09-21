"""The policy loader: extraction, and failing loudly when the document is unusable."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.policy import PolicyError, extract_rules, load_policy

from .support import POLICY_FIXTURE


class PolicyLoadingTest(unittest.TestCase):
    def setUp(self):
        self.policy = load_policy(POLICY_FIXTURE)

    def test_rules_are_extracted_in_document_order(self):
        self.assertEqual(self.policy.rule_ids(), ["RD-1", "RD-2", "NS-1", "NS-2", "GEN-1"])

    def test_rule_text_carries_the_rule_body(self):
        text = self.policy.rule_text("NS-1")
        self.assertIn("NS-1", text)
        self.assertIn("waited at least 5 minutes", text)

    def test_cross_references_do_not_start_a_new_rule(self):
        # RD-2's body says "Where RD-1 holds" mid-sentence; that must not redefine RD-1.
        self.assertEqual(len(self.policy.rules), 5)
        self.assertIn("RD-1", self.policy.rule_text("RD-2"))

    def test_unknown_rule_ids_are_reported(self):
        self.assertEqual(self.policy.unknown_rule_ids(["RD-1", "ZZ-9"]), ["ZZ-9"])

    def test_has_rule(self):
        self.assertTrue(self.policy.has_rule("GEN-1"))
        self.assertFalse(self.policy.has_rule("GEN-99"))


class PolicyFailureTest(unittest.TestCase):
    def test_missing_document_fails_loudly(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(PolicyError) as caught:
                load_policy(Path(tmp) / "no-policy-here.md")
            self.assertIn("policy document not found", str(caught.exception))

    def test_empty_document_fails_loudly(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "policy.md"
            path.write_text("   \n\n", encoding="utf-8")
            with self.assertRaises(PolicyError):
                load_policy(path)

    def test_document_without_rules_fails_loudly(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "policy.md"
            path.write_text("# Policy\n\nNo numbered rules in this file.\n", encoding="utf-8")
            with self.assertRaises(PolicyError) as caught:
                load_policy(path)
            self.assertIn("no rules found", str(caught.exception))


class RuleExtractionTest(unittest.TestCase):
    def test_heading_bold_and_table_styles_are_all_accepted(self):
        text = "\n".join(
            [
                "### RD-1 — heading style",
                "body one",
                "**NS-1** bold style",
                "body two",
                "| GEN-1 | table style | notes |",
                "body three",
            ]
        )
        rules = extract_rules(text)
        self.assertEqual([rule.rule_id for rule in rules], ["RD-1", "NS-1", "GEN-1"])
        self.assertIn("body three", rules[2].text)

    def test_a_duplicate_definition_keeps_the_first(self):
        text = "### RD-1 — first\nbody\n### RD-1 — second\nother body\n"
        rules = extract_rules(text)
        self.assertEqual(len(rules), 1)
        self.assertIn("first", rules[0].text)


if __name__ == "__main__":
    unittest.main()
