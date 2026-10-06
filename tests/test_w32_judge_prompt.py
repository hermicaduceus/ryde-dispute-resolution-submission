"""W32 RED acceptance. Run env -u PYTHONPATH /usr/bin/python3 -m unittest tests.test_w32_judge_prompt -v.

Prompt definition and preservation only, not live-model correctness. Baseline d50a891.
The expectations below are independent of application constants. Source preservation
uses AST to ignore comments and formatting, with exactly one sentence exemption inside
Judge.system_prompt. Actual transmitted prompt bytes are pinned separately.
"""
import ast
import copy
import hashlib
import re
import tempfile
import unittest
from pathlib import Path

from app.agents.judge import Judge
from app.dispute import load_dispute
from app.evidence import build_evidence_pack
from app.events import EventLog
from app.policy import load_policy
from app.schemas import AdvocateCase
from tests.support import ScriptedLLM

ROOT = Path(__file__).resolve().parents[1]
SENTENCE = "deviation_fare_delta_sgd is the difference between the quoted fare and the metered fare for the route taken, not money the rider paid."
BASE_SYSTEM_SHA256 = "119a939789e7d800f52d884f658b4d3ddabdaf045eb695255686d6e118775780"
BASE_JUDGE_AST_SHA256 = "e86ccd59e73067ec4e7b519c33714b2efe8888e0e9aee668ac46fc08330c8e99"


def _sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def _remove_added_sentence(text):
    # A single separator belongs to the added sentence, not the baseline prompt.
    for added in (SENTENCE + " ", SENTENCE + "\n", " " + SENTENCE, "\n" + SENTENCE):
        if added in text:
            return text.replace(added, "", 1)
    return text.replace(SENTENCE, "", 1)


def _capture(case_id="RD-0105", amount=0.0):
    dispute = load_dispute(ROOT / "data/packs/organiser-style-v1/disputes" / (case_id + ".json"))
    pack = build_evidence_pack(dispute)
    llm = ScriptedLLM({"judge": {
        "action": "refund" if amount else "no action",
        "recommended_amount_sgd": amount, "confidence": 0.95,
        "explanation": "scripted prompt-capture reply, not a live judgment",
        "cited_rule_ids": ["RD-4"], "cited_evidence_refs": ["fare.charged_sgd"],
    }})
    with tempfile.TemporaryDirectory(prefix="w32-") as tmp:
        events = EventLog(Path(tmp) / "run", "w32-prompt-capture")
        judge = Judge(llm=llm, events=events, policy=load_policy(ROOT / "docs/policy.md"))
        advocates = [AdvocateCase(party=p, agent=p + "_advocate", claim_summary="scripted",
                                  argument="scripted", requested_outcome="no action",
                                  requested_amount_sgd=0.0) for p in ("rider", "driver")]
        result = judge.run(dispute, pack, *advocates, confidence_threshold=0.65)
        gates = [events.read_payload(e)["gates_failed"] for e in events.events()
                 if e.type == "judge.ruling_withheld"]
    return llm.calls, result, gates


class W32JudgePromptTests(unittest.TestCase):
    def test_sentence_is_in_actual_llm_system_request_exactly_once(self):
        calls, _, _ = _capture()
        self.assertEqual(1, len(calls), "capture must reach exactly one LLM call")
        self.assertEqual(1, calls[0].system_prompt.count(SENTENCE),
                         "shipped system request lacks the exact W32 fare definition")

    def test_sentence_is_not_only_in_user_request(self):
        calls, _, _ = _capture()
        self.assertEqual(1, len(calls))
        self.assertNotIn(SENTENCE, calls[0].user_prompt,
                         "W32 belongs in system instructions, not case material")

    def test_every_existing_system_prompt_byte_is_preserved(self):
        calls, _, _ = _capture()
        self.assertEqual(1, len(calls))
        self.assertEqual(BASE_SYSTEM_SHA256, _sha(_remove_added_sentence(calls[0].system_prompt)),
                         "existing system prompt bytes changed beyond the one sentence")

    def test_existing_judge_code_and_money_gates_are_preserved(self):
        tree = copy.deepcopy(ast.parse((ROOT / "app/agents/judge.py").read_text()))
        judge = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Judge")
        prompt = next(n for n in judge.body if isinstance(n, ast.FunctionDef) and n.name == "system_prompt")
        for node in ast.walk(prompt):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                node.value = _remove_added_sentence(node.value)
        self.assertEqual(BASE_JUDGE_AST_SHA256, _sha(ast.dump(tree, include_attributes=False)),
                         "Judge code changed beyond the system_prompt sentence exemption")

    def test_judge_documentation_quotes_exact_shipped_sentence_once(self):
        doc = (ROOT / "docs/prompts.md").read_text()
        matches = re.findall(r"^## Judge\s*\n(.*?)(?=^## |\Z)", doc, re.M | re.S)
        self.assertEqual(1, len(matches), "documentation needs one Judge section")
        quotes = re.findall(r'"([^"\n]*deviation_fare_delta_sgd[^"\n]*)"', matches[0])
        self.assertEqual([SENTENCE], quotes,
                         "Judge section must quote the exact shipped sentence once")
        calls, _, _ = _capture()
        self.assertEqual(1, calls[0].system_prompt.count(quotes[0]))

    def test_rd0105_unpaid_delta_remains_held_by_rd4(self):
        _, result, gates = _capture("RD-0105", 5.56)
        self.assertEqual("withheld", result.outcome)
        self.assertEqual([["RD-4"]], gates)
        self.assertIsNone(result.ruling)
        self.assertEqual(5.56, result.withheld_candidate.recommended_amount_sgd)

    def test_rd0106_short_pricing_refund_remains_held_by_rd5(self):
        _, result, gates = _capture("RD-0106", 0.66)
        self.assertEqual("withheld", result.outcome)
        self.assertEqual([["RD-5"]], gates)
        self.assertIsNone(result.ruling)
        self.assertEqual(0.66, result.withheld_candidate.recommended_amount_sgd)
