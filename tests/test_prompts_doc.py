"""Acceptance target for docs/prompts.md, the "how prompts drive the AI generation" deliverable.

These tests pin the MECHANICAL fidelity of that document to the code: every schema field
the agents' output contracts name appears in the doc, every section it must have exists,
every repo path it names exists, the hard rules quoted match the code byte-for-byte, the
gate figures match app/config.json in the sentence that names the gate, the transport
constants match the code constants, the worked example matches the real run artifact in
tests/fixtures/w25-rd0103-live-example.json, and the party-message sentences match
app/schemas.py exactly. They cannot tell whether a sentence is true; a line-by-line claim
audit does that.

Pin philosophy (from the project's standing rule on source-level pins): a pin is scoped to
the code that must contain it, and drift must be caught in BOTH directions — change the
code and the doc must go stale; change the doc and the test must go red. A check that
only looks for a number "somewhere" pins nothing.
"""
import json
import re
import unittest
from pathlib import Path

from app.agents.base import (
    CONTRACT_REASKS,
    HARD_RULES,
    RETRY_DELAYS_SECONDS,
    AdvocateAgent,
)
from app.agents.judge import DE_MINIMIS_SGD, Judge
from app.llm.tencent import (
    FIREWALL_SAFE_CHARACTERS,
    MAX_RESPONSE_BYTES,
    MIN_CALL_INTERVAL_SECONDS,
)
from app.schemas import (
    DEMO_NOTICE_MESSAGE,
    HUMAN_REVIEW_MESSAGE,
    NEEDS_INFO_MESSAGE,
    UNDER_REVIEW_MESSAGE,
)

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "docs" / "prompts.md"
CONFIG = ROOT / "app" / "config.json"
FIXTURE = ROOT / "tests" / "fixtures" / "w25-rd0103-live-example.json"

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
# schema tables, AND the doc's schema tables must not name a field the schemas lack.
ADVOCATE_SCHEMA_FIELDS = tuple(sorted(AdvocateAgent.OUTPUT_SCHEMA.keys()))
JUDGE_SCHEMA_FIELDS = tuple(sorted(Judge.OUTPUT_SCHEMA.keys()))

PATH_TOKEN = re.compile(r"`((?:app|ui|data|docs|tools|tests)/[A-Za-z0-9_./-]*)`")
# Our own tracker and review-round labels mean nothing to a judge.
TRACKER_LABELS = re.compile(r"\b(?:W\d{1,2}|R\d{1,2}|S[1-5]|T[1-4])\b")
PROCESS_WORDS = re.compile(
    r"\bsession (?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    r"thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty)\b"
    r"|\bHermi\b|\bHermes\b|planning repo",
    re.IGNORECASE,
)


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


class PromptsDoc(unittest.TestCase):
    def doc(self) -> str:
        if not DOC.exists():
            self.fail("docs/prompts.md does not exist yet")
        return _text(DOC)

    # ------------------------------------------------------------- structure

    def test_has_every_required_section(self):
        headings = set(re.findall(r"^## (.+?)\s*$", self.doc(), re.MULTILINE))
        self.assertEqual([], [s for s in REQUIRED_SECTIONS if s not in headings])

    def test_every_repo_path_it_names_exists(self):
        named = set(PATH_TOKEN.findall(self.doc()))
        self.assertEqual([], sorted(p for p in named if not (ROOT / p).exists()))

    def test_no_tracker_labels_or_process_words(self):
        text = self.doc()
        hits = sorted(set(TRACKER_LABELS.findall(text)))
        self.assertEqual([], hits, "tracker labels found in docs/prompts.md: %s" % hits)
        hits = sorted(set(m.group(0) for m in PROCESS_WORDS.finditer(text)))
        self.assertEqual([], hits, "process words found in docs/prompts.md: %s" % hits)

    def test_names_the_two_advocates_and_the_judge(self):
        text = self.doc()
        for name in ("Rider Advocate", "Driver Advocate", "Judge"):
            self.assertIn(name, text)

    # ------------------------------------------------------ schemas, both ways

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

    def test_schema_table_rows_are_exactly_the_real_fields(self):
        """Doc-to-code: the schema tables may not invent fields.

        Every row of a schema table must start with a backticked field that exists in
        one of the real OUTPUT_SCHEMA dicts — so a fabricated row fails, while free
        prose elsewhere may still mention any field it likes.
        """
        text = self.doc()
        rows = re.findall(r"^\| `([a-z_]+)` \|", text, re.MULTILINE)
        self.assertTrue(rows, "no schema table rows found in docs/prompts.md")
        allowed = set(ADVOCATE_SCHEMA_FIELDS) | set(JUDGE_SCHEMA_FIELDS)
        invented = sorted(set(rows) - allowed)
        self.assertEqual(
            [],
            invented,
            "schema table rows name fields no agent schema has: %s" % invented,
        )

    # --------------------------------------------------------------- hard rules

    def test_hard_rules_in_doc_match_code_text(self):
        """The doc carries the hard-rules block verbatim, fenced, so it cannot drift."""
        text = self.doc()
        self.assertIn("```text\n%s\n```" % HARD_RULES.strip(), text)

    # -------------------------------------------------------------- gate figures

    def test_gate_figures_match_config_in_their_own_sentences(self):
        """Each figure is pinned inside the sentence naming its gate.

        Changing a figure in app/config.json must turn this red even when the same
        number appears elsewhere in the doc: the assert targets the gate's own clause,
        not the bare number.
        """
        config = json.loads(CONFIG.read_text(encoding="utf-8"))
        threshold = config["confidence_threshold"]
        cap = config["autonomous_cap_sgd"]
        budget = config["llm"]["case_budget_seconds"]
        text = self.doc()
        self.assertRegex(
            text,
            re.escape("threshold from `app/config.json`, currently %.2f, the" % threshold),
            "the confidence gate's sentence must carry the configured threshold",
        )
        self.assertRegex(
            text,
            re.escape("autonomous cap of SGD %.2f is withheld" % cap),
            "the ESC-4 sentence must carry the configured cap",
        )
        self.assertRegex(
            text,
            re.escape("`llm.case_budget_seconds`, currently %d)" % int(budget)),
            "the retry paragraph must carry the configured time budget",
        )

    def test_de_minimis_matches_code(self):
        text = self.doc()
        self.assertIn("SGD %.2f de minimis" % DE_MINIMIS_SGD, text)

    def test_transport_constants_match_code(self):
        """Pacing, response cap, re-ask count, backoff and cleaning pinned to code."""
        text = self.doc()
        self.assertRegex(
            text,
            re.escape("one per %.1f seconds" % MIN_CALL_INTERVAL_SECONDS),
            "pacing interval must match MIN_CALL_INTERVAL_SECONDS",
        )
        self.assertRegex(
            text,
            re.escape("larger than %d MiB" % (MAX_RESPONSE_BYTES // (1024 * 1024))),
            "response cap must match MAX_RESPONSE_BYTES",
        )
        self.assertEqual(1, CONTRACT_REASKS)
        self.assertRegex(text, r"[Oo]ne re-ask")
        delays = ", ".join("%d s" % d for d in RETRY_DELAYS_SECONDS)
        self.assertIn("(%s)" % delays, text)
        # The firewall character set: exactly the characters the code swaps.
        cleaned = {chr(c) for c, repl in FIREWALL_SAFE_CHARACTERS.items() if repl is not None}
        m = re.search(r"backticks are dropped and `([^`]+)` are swapped", text)
        if m is None:
            self.fail("the cleaning sentence must name the swapped characters")
        self.assertEqual(cleaned, set(m.group(1)) - {' '})

    # ------------------------------------------------------------ worked example

    def test_worked_example_judgement_matches_the_real_run(self):
        """The doc's Judge JSON is the artifact from the RD-0103 live run, exactly."""
        text = self.doc()
        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        ruling = fixture["ruling"]
        blocks = re.findall(r"```json\n(.*?)```", text, re.DOTALL)
        self.assertTrue(blocks, "the doc must carry at least one fenced JSON example")
        doc_ruling = json.loads(blocks[0])
        for key in (
            "action",
            "recommended_amount_sgd",
            "confidence",
            "explanation",
            "cited_rule_ids",
            "cited_evidence_refs",
        ):
            self.assertEqual(
                ruling[key],
                doc_ruling.get(key),
                "worked-example %s must match the real run" % key,
            )

    def test_worked_example_prose_matches_the_real_run(self):
        """The rider's rule list, field count and amount, and the run id, match the artifact."""
        flat = re.sub(r"\s+", " ", self.doc())
        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.assertIn(
            "run `%s`" % fixture["run_id"],
            flat,
            "the worked example must name the real run id",
        )
        rule_list = fixture["rider"]["policy_rule_ids"]
        rules = ", ".join(rule_list[:-1]) + " and " + rule_list[-1]
        self.assertIn(
            rules,
            flat,
            "the rider's rule list must match the run: %s" % rules,
        )
        self.assertIn(
            "citing %d pack fields" % fixture["rider"]["evidence_cited_count"],
            flat,
        )
        self.assertIn(
            "refund of SGD %.2f" % fixture["rider"]["requested_amount_sgd"],
            flat,
        )

    def test_worked_example_rules_are_real_policy_rules(self):
        """Every rule ID the doc names exists in the policy document."""
        text = self.doc()
        policy_text = (ROOT / "docs" / "policy.md").read_text(encoding="utf-8")
        rule_ids = set(re.findall(r"^### ([A-Z]{2,4}-\d+)", policy_text, re.MULTILINE))
        # Dispute ids are RD-0103 (4 digits); rule ids are RD-1 (1-2 digits).
        for rule in set(re.findall(r"\b([A-Z]{2,4}-\d{1,2})\b", text)):
            self.assertIn(
                rule,
                rule_ids,
                "rule ID %s named in the doc is not a policy rule" % rule,
            )

    # ---------------------------------------------------------- party messages

    def test_party_message_sentences_match_schemas_module(self):
        """The fixed sentences the doc quotes are the exact constants in the code."""
        flat = re.sub(r"\s+", " ", self.doc())
        self.assertIn('"%s"' % UNDER_REVIEW_MESSAGE, flat)
        # The doc may shorten the others with an ellipsis; pin their opening words.
        for sentence in (NEEDS_INFO_MESSAGE, HUMAN_REVIEW_MESSAGE, DEMO_NOTICE_MESSAGE):
            self.assertIn(
                re.sub(r"\s+", " ", sentence)[:30],
                flat,
                "the doc must quote the fixed message opening: %s" % sentence[:30],
            )

    def test_states_the_party_never_sees_agent_text(self):
        text = self.doc()
        self.assertIn(
            "The party never sees text an agent writes in a question, an",
            text,
            "the doc must state the party-message guarantee up front",
        )

    def test_pipeline_order_is_pinned(self):
        """The doc must say the stop-and-ask round happens before the Judge runs."""
        text = self.doc()
        self.assertIn(
            "the run stops *before the Judge*",
            text,
            "the pipeline section must pin that needs_info stops before the Judge",
        )
        self.assertIn("`needs_info` outcome", text)

    def test_citation_validation_is_described_as_recorded_not_blocking(self):
        text = self.doc()
        self.assertIn(
            "**A citation failure is recorded, not blocked:**",
            text,
            "the doc must not overstate what citation validation does",
        )


if __name__ == "__main__":
    unittest.main()