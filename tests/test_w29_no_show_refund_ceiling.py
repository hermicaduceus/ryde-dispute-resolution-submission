"""W29 acceptance target: NS-8, the no-show refund ceiling.

A no-show dispute is, at its widest, a dispute about one recorded fee. The policy's no-show
rules (NS-1..NS-5) never order more than that fee back to the rider, yet no gate enforced
it: a Judge ruling "refund 45.00" on a 6.61 fee reached the parties, with only ESC-4's
SGD 50 cap above it (reproduced 2026-10-04 with a stub Judge, NS-0202). Same class as
RD-4: the records prove a ceiling, the model must not move more than the records prove.

The gate (mirrors RD-4, and withholds, never rewrites):

- On a no-show-charge case, a refund larger than the recorded cancellation fee is
  withheld for a human.
- On a no-show-charge case, a compensation ruling is always withheld: a no-show record
  proves nothing owed to the driver.
- "No action" is never held by this gate, and neither is a refund within the fee
  (equal or below), including a full-fee refund.
- A missing or non-finite fee leaves the comparison unable to run — such a record cannot
  prove a fee either way, so the refund is withheld (a figure the record cannot prove is
  a missing figure).
- The gate sits in `app/agents/judge.py` beside the other money gates, label `NS-8`,
  and the withheld candidate carries the gate reason verbatim.

These tests are RED until the gate exists.
"""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.agents import judge as judge_module  # noqa: E402
from app.dispute import load_dispute  # noqa: E402
from app.evidence import compute  # noqa: E402
from app.events import EventLog  # noqa: E402
from app.llm.base import LLMClient, LLMResponse  # noqa: E402
from app.pipeline import run_dispute  # noqa: E402
from app.policy import load_policy  # noqa: E402

POLICY = load_policy(ROOT / "docs" / "policy.md")
PACK = ROOT / "data" / "packs" / "organiser-style-v1" / "disputes"

ADVOCATE_REPLY = {
    "claim_summary": "x",
    "evidence_cited": ["cancellation.cancellation_fee_sgd"],
    "policy_rule_ids": ["NS-3"],
    "argument": "x",
    "requested_outcome": "no action",
    "requested_amount_sgd": 0,
    "follow_up_slots": [],
}


class ScriptedLLM(LLMClient):
    """Deterministic stand-in: the Judge says exactly what a test needs it to say."""

    provider_name = "scripted"

    def __init__(self, judge_reply):
        self.judge_reply = judge_reply
        self.calls = []

    def complete(self, request):
        self.calls.append(request)
        body = self.judge_reply if request.agent == "judge" else ADVOCATE_REPLY
        return LLMResponse(text=body if isinstance(body, str) else _json(body),
                           provider="scripted", model="scripted")


def _json(payload):
    import json
    return json.dumps(payload)


def run_case(dispute_id, judge_reply, tmp):
    """Run one dispute with a scripted Judge; returns the case file."""
    dispute = load_dispute(PACK / ("%s.json" % dispute_id))
    events = EventLog(Path(tmp), "r")
    return run_dispute(
        dispute=dispute,
        llm=ScriptedLLM(judge_reply),
        policy=POLICY,
        events=events,
        confidence_threshold=0.65,
        autonomous_cap_sgd=50.0,
    )


def judge_refund(amount, refs=("cancellation.cancellation_fee_sgd",), rules=("NS-3",)):
    return {
        "action": "refund",
        "recommended_amount_sgd": amount,
        "confidence": 0.9,
        "explanation": "scripted",
        "cited_rule_ids": list(rules),
        "cited_evidence_refs": list(refs),
    }


def judge_compensation(amount):
    return {
        "action": "compensation",
        "recommended_amount_sgd": amount,
        "confidence": 0.9,
        "explanation": "scripted",
        "cited_rule_ids": ["NS-3"],
        "cited_evidence_refs": ["cancellation.cancellation_fee_sgd"],
    }


def judge_no_action():
    return {
        "action": "no action",
        "recommended_amount_sgd": 0.0,
        "confidence": 0.9,
        "explanation": "scripted",
        "cited_rule_ids": ["NS-3"],
        "cited_evidence_refs": ["cancellation.cancellation_fee_sgd"],
    }


def notes(case_file):
    return case_file.resolution.get("notes") or []


class NS8Gate(unittest.TestCase):
    """The gate itself, on the clean-record corpus case (NS-0202, fee 6.61, GPS fine)."""

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def test_refund_above_the_fee_is_withheld(self):
        cf = run_case("NS-0202", judge_refund(45.0), self._tmp.name)
        self.assertEqual("withheld", cf.resolution["outcome"])
        self.assertIn("NS-8", " ".join(notes(cf)), "the gate label names itself")
        # the candidate is intact for the human reviewer
        self.assertEqual(45.0, cf.resolution["withheld_candidate"]["recommended_amount_sgd"])

    def test_refund_equal_to_the_fee_is_delivered(self):
        cf = run_case("NS-0202", judge_refund(6.61), self._tmp.name)
        self.assertEqual("ruled", cf.resolution["outcome"])
        self.assertEqual(6.61, cf.resolution["ruling"]["recommended_amount_sgd"])

    def test_refund_below_the_fee_is_delivered(self):
        cf = run_case("NS-0202", judge_refund(3.0), self._tmp.name)
        self.assertEqual("ruled", cf.resolution["outcome"])

    def test_no_action_is_never_held_by_ns8(self):
        cf = run_case("NS-0202", judge_no_action(), self._tmp.name)
        self.assertEqual("ruled", cf.resolution["outcome"])

    def test_compensation_on_a_no_show_is_always_withheld(self):
        cf = run_case("NS-0202", judge_compensation(5.0), self._tmp.name)
        self.assertEqual("withheld", cf.resolution["outcome"])
        self.assertIn("NS-8", " ".join(notes(cf)))

    def test_small_compensation_is_withheld_too(self):
        # even below the fee: a no-show record proves nothing owed to the driver
        cf = run_case("NS-0202", judge_compensation(0.5), self._tmp.name)
        self.assertEqual("withheld", cf.resolution["outcome"])

    def test_the_withheld_event_carries_the_gate_label(self):
        import json as _json
        cf = run_case("NS-0202", judge_refund(45.0), self._tmp.name)
        event_lines = [_json.loads(l) for l in
                       (Path(self._tmp.name) / "events.jsonl").read_text().splitlines() if l.strip()]
        withheld = [e for e in event_lines if e.get("type") == "judge.ruling_withheld"]
        self.assertTrue(withheld, "a ruling_withheld event exists")
        payload = _json.loads(
            (Path(self._tmp.name) / withheld[0]["payload_ref"]).read_text()
        )
        self.assertIn("NS-8", payload.get("gates_failed", []))

    def test_route_cases_are_untouched_by_ns8(self):
        # RD-0103 is a route case: a refund above the fee makes no sense there,
        # and NS-8 must not fire on it (RD-4 owns route money).
        cf = run_case("RD-0103", judge_refund(45.0), self._tmp.name)
        joined = " ".join(notes(cf))
        self.assertNotIn("NS-8", joined, "NS-8 must not fire on a route case")


class NS8MissingFee(unittest.TestCase):
    """A fee the record cannot prove is a missing fee; the refund is withheld."""

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        import json as _json
        original = _json.loads((PACK / "NS-0202.json").read_text())
        original["cancellation_policy"]["cancellation_fee_after_wait"] = None
        path = Path(self._tmp.name) / "record.json"
        path.write_text(_json.dumps(original))
        self.record = path

    def run_case_from_record(self, judge_reply, tmp):
        dispute = load_dispute(self.record)
        events = EventLog(Path(tmp), "r")
        return run_dispute(
            dispute=dispute,
            llm=ScriptedLLM(judge_reply),
            policy=POLICY,
            events=events,
            confidence_threshold=0.65,
            autonomous_cap_sgd=50.0,
        )

    def test_refund_with_a_null_fee_is_withheld(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            cf = self.run_case_from_record(judge_refund(45.0), tmp)
        self.assertEqual("withheld", cf.resolution["outcome"])
        self.assertIn("NS-8", " ".join(notes(cf)))

    def test_no_action_with_a_null_fee_is_delivered(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            cf = self.run_case_from_record(judge_no_action(), tmp)
        self.assertEqual("ruled", cf.resolution["outcome"])


class NS8Unit(unittest.TestCase):
    """The gate helper, if the implementation exposes one, else the run path above covers it.

    These tests name the module surface the implementation is expected to expose:
    `ns8_provable_refund_ceiling_sgd(pack) -> Optional[float]` in app/agents/judge.py,
    the no-show counterpart of provable_refund_sgd. None means "the records prove no fee".
    """

    def test_helper_exists_and_reads_the_fee(self):
        self.assertTrue(hasattr(judge_module, "ns8_provable_refund_ceiling_sgd"),
                        "app/agents/judge.py must expose ns8_provable_refund_ceiling_sgd")

    def test_helper_returns_the_recorded_fee(self):
        dispute = load_dispute(PACK / "NS-0202.json")
        pack = compute.build_evidence_pack(dispute)
        fee = judge_module.ns8_provable_refund_ceiling_sgd(pack)
        self.assertEqual(6.61, fee)

    def test_helper_returns_none_when_no_cancellation_block(self):
        dispute = load_dispute(PACK / "RD-0103.json")
        pack = compute.build_evidence_pack(dispute)
        self.assertIsNone(judge_module.ns8_provable_refund_ceiling_sgd(pack))


class NS8Docs(unittest.TestCase):
    """The three docs that name the gates must carry NS-8 and the new count."""

    ARCH = ROOT / "docs" / "architecture.md"
    README = ROOT / "README.md"
    PROMPTS = ROOT / "docs" / "prompts.md"
    POLICY = ROOT / "docs" / "policy.md"

    def test_architecture_says_ten_gates_and_has_an_ns8_row(self):
        text = self.ARCH.read_text(encoding="utf-8")
        section = text.split("## Gates enforced in code", 1)[1].split("\n## ", 1)[0]
        self.assertTrue(section.lstrip().startswith("Ten gates"),
                        "the count sentence must lead and count NS-8")
        rows = [l for l in section.splitlines() if l.startswith("| ") and "---" not in l][1:]
        self.assertEqual(10, len(rows))
        row = next((r for r in rows if "NS-8" in r.split("|")[1]), None)
        self.assertIsNotNone(row, "a table row whose first cell names NS-8")
        self.assertIn("`app/agents/judge.py`", row)
        for needle in ("cancellation_fee_sgd", "compensation"):
            self.assertIn(needle, row, needle)

    def test_readme_gate_paragraph_names_seven_gates_and_ns8(self):
        text = self.README.read_text(encoding="utf-8")
        body = text.split("## Run", 1)[1].split("\n## ", 1)[0]
        para = next(p for p in body.split("\n\n") if "enforced in Python" in p)
        for gate in ("confidence", "ESC-4", "ESC-2", "NS-6", "RD-5", "NS-8"):
            self.assertIn(gate, para, gate)
        self.assertRegex(para, r"(?i)\bseven gates\b")

    def test_prompts_doc_names_seven_gates_and_ns8(self):
        text = self.PROMPTS.read_text(encoding="utf-8")
        flat = " ".join(text.split())
        self.assertIn("seven gates", flat)
        self.assertIn("NS-8", flat)
        # the six-gate phrasings are gone
        self.assertNotIn("six gates", flat)

    def test_prompts_doc_ns8_bullet_is_scoped_to_no_show(self):
        text = self.PROMPTS.read_text(encoding="utf-8")
        self.assertRegex(text, r"- \*\*NS-8\.\*\* On a no-show case,")

    def test_policy_ns8_section_states_the_enforcement(self):
        text = self.POLICY.read_text(encoding="utf-8")
        body = re.search(r"^### NS-8 .*?(?=^### |\Z)", text, re.M | re.S).group(0)
        self.assertIn("Enforcement (2026-10-04)", body)
        for needle in ("withheld", "compensation", "cancellation_fee_sgd"):
            self.assertIn(needle, body, needle)


if __name__ == "__main__":
    unittest.main()