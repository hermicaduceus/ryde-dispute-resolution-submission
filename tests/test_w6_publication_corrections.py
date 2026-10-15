"""W6 publication corrections: pin the explanatory text at each cited site.

These are documentation contracts, not application behaviour tests. The main suite separately
exercises the gates and transport retry paths. Each contract is scoped to the paragraph/table
row that makes the claim, so a nearby example cannot satisfy it. The name check is case-insensitive.
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parent.parent


def text(path):
    return (ROOT / path).read_text(encoding="utf-8")


def flat(s):
    return " ".join(s.split())


def between(s, first, last):
    return flat(s.split(first, 1)[1].split(last, 1)[0])


class PublicationCorrections(unittest.TestCase):
    def test_authorship_label_has_no_case_variant_of_the_private_name(self):
        s = text("docs/build-briefs/session-twelve-brief.md").splitlines()[2]
        self.assertIn("PLANNER-AUTHORED BRIEF", s)
        self.assertNotRegex(s, re.compile(r"\b" + "Her" + "mi" + r"\b", re.I))

    def test_policy_intro_qualifies_text_replacement(self):
        s = between(text("docs/policy.md"), "**Version", "---")
        self.assertIn("Replacing the text does not change the Python safeguards", s)
        self.assertIn("must remain aligned", s)
        self.assertNotIn("with no code change", s)

    def test_policy_parameters_name_the_separate_enforcement_locations(self):
        s = between(text("docs/policy.md"), "## Parameters", "| Parameter")
        self.assertIn("app/config.json", s)
        self.assertIn("app/agents/judge.py", s)
        self.assertNotIn("changed in one place", s)

    def test_architecture_qualifies_model_preconditions_and_python_gates(self):
        s = between(text("docs/architecture.md"), "## Policy and dataset packs", "Two dataset packs")
        self.assertIn("Replacing the text does not change the Python safeguards", s)
        self.assertIn("must remain aligned", s)
        self.assertNotIn("Nothing in the code evaluates the preconditions", s)

    def test_builder_contract_qualifies_policy_replacement(self):
        s = between(text("CODEBUDDY.md"), "- **Policy as a swappable document:", "- **Dataset")
        self.assertIn("must remain aligned", s)
        self.assertIn("Python safeguards", s)
        self.assertNotIn("drops in with no code change", s)

    def test_retry_paragraph_classifies_connection_refusal_as_transient(self):
        s = between(text("docs/prompts.md"), "- **Retry and time budget.", "## Rider Advocate")
        self.assertIn("connection refusals", s)
        self.assertIn("429", s)
        self.assertIn("firewall blocks fail at once", s)
        self.assertNotIn("a refused connection, a firewall block", s)

    def test_architecture_rd5_row_includes_no_rates_breakdown_floor(self):
        rows = [l for l in text("docs/architecture.md").splitlines() if l.startswith("| RD-5,")]
        self.assertEqual(1, len(rows))
        for term in ("fare.difference_sgd", "no tariff rates", "inconsistent breakdown", "charged_sgd", "component_sum_sgd", "ESC-2"):
            self.assertIn(term, rows[0])

    def test_prompt_rd5_bullet_includes_no_rates_breakdown_floor(self):
        s = between(text("docs/prompts.md"), "  - **RD-5.", "  - **RD-4.")
        for term in ("no tariff rates", "inconsistent breakdown", "ESC-2"):
            self.assertIn(term, s)

    def test_policy_rd5_enforcement_includes_no_rates_breakdown_floor(self):
        s = between(text("docs/policy.md"), "Enforcement (2026-10-01):", "### RD-6")
        for term in ("no tariff rates", "inconsistent breakdown", "charged_sgd", "component_sum_sgd", "ESC-2"):
            self.assertIn(term, s)


if __name__ == "__main__":
    unittest.main()
