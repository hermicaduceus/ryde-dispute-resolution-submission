"""W43 SHOULD RED acceptance (S3): the Judge prompt must define deviation_fare_delta_sgd right.

Written BEFORE the build, so it is RED on the frozen baseline until the W43 SHOULD lane ships.
The shipped system prompt (app/agents/judge.py, in Judge.system_prompt) tells the model that
the field is "the difference between the quoted fare and the metered fare for the route taken".
That is false twice over: no quoted-fare field exists anywhere in the record (the fare record
carries charged_sgd, the breakdown components and the tariff rates), and the field the evidence
layer actually computes is the fare recomputed for the route ACTUALLY taken minus the fare
recomputed for the ESTIMATED route (app/evidence/compute.py, FareEvidence). The prompt sends the
model a definition it cannot ground, which is the pack-only-arithmetic hole the review flagged.

The sentence's closing claim stays: the definition does not decide delivery — the code gates do.

Run: env -u PYTHONPATH /usr/bin/python3 -m unittest tests.test_w43_should_judge_delta_sentence -v
"""
from __future__ import annotations

import json
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

REPO = Path(__file__).resolve().parent.parent
POLICY = REPO / "docs" / "policy.md"
RECORD = REPO / "data" / "packs" / "ryde-synth-v1" / "disputes" / "RD-0103.json"

#: The definition the field actually has: recomputed actual route minus recomputed estimated route.
SHIPPED_SENTENCE = (
    "deviation_fare_delta_sgd is the difference between the fare recomputed for the route "
    "actually taken and the fare recomputed for the estimated route, not money the rider paid."
)
#: The sentence the frozen baseline ships, which names two figures no record contains.
BASELINE_SENTENCE = (
    "deviation_fare_delta_sgd is the difference between the quoted fare and the metered fare "
    "for the route taken, not money the rider paid."
)
#: The prompt keeps delivery in the code gates, not in this definition.
GATE_CLAIM = "A separate gate withholds rulings below a configured threshold"


def _system_prompt(case_id: str = "RD-0105"):
    dispute = load_dispute(REPO / "data" / "packs" / "organiser-style-v1" / "disputes"
                           / (case_id + ".json"))
    pack = build_evidence_pack(dispute)
    llm = ScriptedLLM({"judge": {
        "action": "no action", "recommended_amount_sgd": 0.0, "confidence": 0.95,
        "explanation": "scripted prompt-capture reply, not a live judgment",
        "cited_rule_ids": ["RD-4"], "cited_evidence_refs": ["fare.charged_sgd"],
    }})
    with tempfile.TemporaryDirectory(prefix="w43-s3-") as tmp:
        events = EventLog(Path(tmp) / "run", "w43-s3-prompt-capture")
        judge = Judge(llm=llm, events=events, policy=load_policy(POLICY))
        judge.run(
            dispute, pack,
            *[AdvocateCase(party=p, agent=p + "_advocate", claim_summary="scripted",
                           argument="scripted", requested_outcome="no action",
                           requested_amount_sgd=0.0) for p in ("rider", "driver")],
            confidence_threshold=0.65,
        )
    return llm.calls[0].system_prompt


class JudgeDeltaSentenceTests(unittest.TestCase):
    def test_the_shipped_sentence_defines_the_recomputed_difference(self):
        prompt = _system_prompt()
        self.assertEqual(
            1, prompt.count(SHIPPED_SENTENCE),
            "the system prompt must carry the corrected fare-delta definition exactly once",
        )

    def test_the_quoted_fare_definition_is_gone(self):
        prompt = _system_prompt()
        self.assertNotIn(BASELINE_SENTENCE, prompt)
        self.assertEqual(
            1, prompt.count("deviation_fare_delta_sgd"),
            "the prompt states one definition of the field, once",
        )

    def test_the_definition_matches_how_the_evidence_layer_computes_the_field(self):
        """The words must describe the mechanism, so the mechanism is run here: the field is
        recomputed(actual route) - recomputed(estimated route), and no quoted-fare field exists
        in the record the pack is built from."""
        record = json.loads(RECORD.read_text(encoding="utf-8"))
        dispute = load_dispute(RECORD)
        pack = build_evidence_pack(dispute)
        fare = pack.fare
        self.assertEqual(11.69, fare.recomputed_sgd)
        self.assertEqual(10.95, fare.recomputed_estimated_route_sgd)
        self.assertEqual(0.74, fare.deviation_fare_delta_sgd)
        self.assertEqual(
            round(fare.recomputed_sgd - fare.recomputed_estimated_route_sgd, 2),
            fare.deviation_fare_delta_sgd,
            "the sentence's definition is this difference, not a quoted-versus-metered one",
        )
        keys = set(record["trip"]["fare"])
        self.assertEqual({"charged_sgd", "breakdown", "rates"}, keys)
        self.assertEqual([], [key for key in keys if "quot" in key or "meter" in key],
                         "no quoted or metered fare field exists for the prompt to mean")

    def test_the_sentence_still_leaves_delivery_to_the_code_gates(self):
        """Preserve pin: the definition is a definition, not a promise about delivery."""
        prompt = _system_prompt()
        self.assertIn(GATE_CLAIM, prompt)
        self.assertTrue(SHIPPED_SENTENCE.endswith("not money the rider paid."))


if __name__ == "__main__":
    unittest.main()
