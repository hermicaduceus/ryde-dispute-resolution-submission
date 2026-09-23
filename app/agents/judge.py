"""Judge — the impartial arbitrator.

Weighs both advocates' cases, applies the policy document, and issues one ruling with a
confidence score and a natural-language explanation.

The confidence gate is the Judge's contract, not a policy rule: a ruling whose confidence
is below the configured threshold is not delivered to the parties. It stands beside two
other Python-enforced gates: ESC-4 (the recommended amount above the autonomous cap) and
ESC-2 (a route-deviation case whose deviation could not be measured). The Judge's candidate
is still produced and recorded — that is what a human reviewer receives on escalation —
but `Resolution.ruling` stays empty and the parties see only the neutral holding message.
The threshold is passed in from configuration on every call; nothing here hard-codes it.
"""

from __future__ import annotations

import json
from typing import Any, Dict

from ..dispute import CATEGORY_ROUTE_DEVIATION, Dispute
from ..evidence import EvidencePack
from ..schemas import (
    OUTCOME_RULED,
    OUTCOME_WITHHELD,
    UNDER_REVIEW_MESSAGE,
    AdvocateCase,
    ContractError,
    JudgeRuling,
    Resolution,
    RulingAction,
    party_message_for_ruling,
)
from .base import AgentError, BaseAgent, HARD_RULES, citable_refs_block, dispute_block, evidence_block, policy_blocks, validate_citations

EVENT_RULING_ISSUED = "judge.ruling_issued"
EVENT_RULING_WITHHELD = "judge.ruling_withheld"


class Judge(BaseAgent):
    name = "judge"
    role_title = "Judge"

    OUTPUT_SCHEMA: Dict[str, Any] = {
        "action": "refund | compensation | no action",
        "recommended_amount_sgd": "number in SGD; 0.00 for no action",
        "confidence": "number between 0 and 1",
        "explanation": "the reasoning, in plain language, for both parties to read",
        "cited_rule_ids": ["RULE-1", "..."],
        "cited_evidence_refs": ["evidence.field.path", "..."],
    }

    def system_prompt(self) -> str:
        return (
            "You are the Judge in Ryde's autonomous dispute resolution system.\n\n"
            "YOUR ROLE\nWeigh the two advocate cases, apply the company policy, and issue one "
            "ruling. You are impartial: neither side has to win, and 'no action' is a ruling "
            "like any other. Where the evidence does not settle a question, say so in the "
            "explanation rather than filling the gap.\n\n"
            "%s\n\n"
            "CONFIDENCE\nconfidence is your honest probability that this ruling is the one the "
            "policy and the evidence support. A separate gate withholds rulings below a "
            "configured threshold, so an honest low confidence produces a holding message to "
            "the parties instead of a wrong ruling — that is a correct outcome, not a failure. "
            "Do not inflate your confidence to clear a bar, and do not deflate it to avoid "
            "deciding.\n\n"
            "CITING YOUR EVIDENCE\ncited_evidence_refs must name the Evidence Pack fields your "
            "ruling actually rests on, taken verbatim from the citable refs list you are given. "
            "A ruling nobody can trace back to specific numbers cannot be reviewed by the human "
            "who receives an escalation, so cite the fields that decided it, not every field you "
            "were shown.\n\n"
            "OUTPUT SCHEMA\n%s"
            % (HARD_RULES, json.dumps(self.OUTPUT_SCHEMA, indent=2))
        )

    def user_prompt(
        self,
        dispute: Dispute,
        pack: EvidencePack,
        rider_case: AdvocateCase,
        driver_case: AdvocateCase,
    ) -> str:
        return (
            "DISPUTE\n%s\n\n"
            "EVIDENCE PACK (computed deterministically; the only source of numbers)\n%s\n\n"
            "CITABLE EVIDENCE REFS\n%s\n\n"
            "RIDER ADVOCATE CASE\n%s\n\n"
            "DRIVER ADVOCATE CASE\n%s\n\n"
            "%s\n\n"
            "YOUR TASK\nWeigh both cases against the Evidence Pack and the policy, and issue "
            "one ruling: an action, an amount in SGD, your confidence, the rule IDs the "
            "ruling rests on, and an explanation written so both parties can read it."
            % (
                dispute_block(dispute),
                evidence_block(pack),
                citable_refs_block(pack),
                json.dumps(rider_case.to_dict(), indent=2),
                json.dumps(driver_case.to_dict(), indent=2),
                policy_blocks(self.policy),
            )
        )

    def run(
        self,
        dispute: Dispute,
        pack: EvidencePack,
        rider_case: AdvocateCase,
        driver_case: AdvocateCase,
        *,
        confidence_threshold: float,
        autonomous_cap_sgd: float = 50.00,
    ) -> Resolution:
        """Deliberate, then either issue the ruling or withhold it behind the gate."""
        payload, llm_info = self._ask(
            system_prompt=self.system_prompt(),
            user_prompt=self.user_prompt(dispute, pack, rider_case, driver_case),
            metadata={
                "dispute_id": dispute.dispute_id,
                "category": dispute.category,
                "claim_amount_sgd": dispute.claim_amount_sgd,
                "available_rule_ids": self.policy.rule_ids(),
                "available_evidence_refs": pack.field_refs(),
                "confidence_threshold": confidence_threshold,
                "autonomous_cap_sgd": autonomous_cap_sgd,
            },
        )

        try:
            ruling = JudgeRuling.from_payload(
                payload,
                agent=self.name,
                llm=llm_info,
                validation=validate_citations(
                    cited_refs=_cited_evidence_refs(payload),
                    cited_rules=_cited_rules(payload),
                    pack=pack,
                    policy=self.policy,
                ),
            )
        except ContractError as exc:
            raise AgentError("judge returned a response that breaks its contract: %s" % exc) from exc

        # Two independent gates stand between a ruling and the parties, and BOTH are
        # enforced here in Python rather than asked of the model in a prompt. A prompt is
        # a request; this is a guarantee. ESC-4 in particular moves money, so it must not
        # depend on the LLM having read its instructions carefully.
        gate_failures = []
        gate_summaries = []
        if ruling.confidence < confidence_threshold:
            gate_failures.append(
                (
                    "confidence",
                    "confidence %.2f is below the threshold %.2f"
                    % (ruling.confidence, confidence_threshold),
                )
            )
            gate_summaries.append("confidence is below the configured threshold")
        if (
            ruling.action != RulingAction.NO_ACTION.value
            and ruling.recommended_amount_sgd > autonomous_cap_sgd
        ):
            gate_failures.append(
                (
                    "ESC-4",
                    "SGD %.2f exceeds the autonomous decision cap of SGD %.2f"
                    % (ruling.recommended_amount_sgd, autonomous_cap_sgd),
                )
            )
            gate_summaries.append("the recommended amount exceeds the autonomous decision cap (ESC-4)")
        if (
            dispute.category == CATEGORY_ROUTE_DEVIATION
            and pack.route is not None
            and pack.route.deviation_pct is None
        ):
            # ESC-2 for route cases: a ruling that cannot name the deviation it rests on
            # is exactly the "plausible figure for a missing one" the policy forbids.
            # Route cases only — for a no-show, a missing arrival is itself the evidence
            # (NS-4), and gating on it would withhold the cases the policy rules.
            gate_failures.append(
                (
                    "ESC-2",
                    "route.deviation_pct is null, so the deviation a route-deviation "
                    "ruling rests on could not be measured (EV-1, ESC-2)",
                )
            )
            gate_summaries.append("the route deviation could not be measured (ESC-2)")

        if not gate_failures:
            self.events.emit(
                EVENT_RULING_ISSUED,
                from_=self.name,
                to="parties",
                summary="Judge ruled %s of SGD %.2f at confidence %.2f (threshold %.2f)"
                % (ruling.action, ruling.recommended_amount_sgd, ruling.confidence, confidence_threshold),
                payload={
                    "dispute_id": dispute.dispute_id,
                    "ruling": ruling.to_dict(),
                    "confidence_threshold": confidence_threshold,
                    "autonomous_cap_sgd": autonomous_cap_sgd,
                },
            )
            return Resolution(
                dispute_id=dispute.dispute_id,
                outcome=OUTCOME_RULED,
                party_message=party_message_for_ruling(ruling),
                confidence_threshold=confidence_threshold,
                ruling=ruling,
            )

        reasons = [reason for _gate, reason in gate_failures]
        self.events.emit(
            EVENT_RULING_WITHHELD,
            from_=self.name,
            to="parties",
            summary="Judge withheld the ruling: %s" % "; ".join(gate_summaries),
            payload={
                "dispute_id": dispute.dispute_id,
                "confidence": ruling.confidence,
                "confidence_threshold": confidence_threshold,
                "autonomous_cap_sgd": autonomous_cap_sgd,
                "gates_failed": [gate for gate, _reason in gate_failures],
                "withheld_candidate": ruling.to_dict(),
                "escalation": "queued for human review with the full case file",
            },
        )
        return Resolution(
            dispute_id=dispute.dispute_id,
            outcome=OUTCOME_WITHHELD,
            party_message=UNDER_REVIEW_MESSAGE,
            confidence_threshold=confidence_threshold,
            withheld_candidate=ruling,
            escalated_for_human_review=True,
            notes=["the ruling was not delivered: %s" % reason for reason in reasons],
        )


def _cited_rules(payload: Dict[str, Any]) -> list:
    return _string_list(payload, "cited_rule_ids")


def _cited_evidence_refs(payload: Dict[str, Any]) -> list:
    return _string_list(payload, "cited_evidence_refs")


def _string_list(payload: Dict[str, Any], key: str) -> list:
    value = payload.get(key)
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]
