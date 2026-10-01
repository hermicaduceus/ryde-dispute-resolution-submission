"""Judge — the impartial arbitrator.

Weighs both advocates' cases, applies the policy document, and issues one ruling with a
confidence score and a natural-language explanation.

The confidence gate is the Judge's contract, not a policy rule: a ruling whose confidence
is below the configured threshold is not delivered to the parties. It stands beside four
other Python-enforced gates: ESC-4 (the recommended amount above the autonomous cap),
ESC-2 (a route-deviation case whose deviation could not be measured, or whose fare
charged is not a recorded figure), NS-6 (a contested
no-show whose fee has no recorded arrival position may only be refunded in full, and only
for a low fee and a clean rider record) and RD-5 (a proven overcharge of at least the de
minimis amount must actually be refunded). The Judge's candidate is still produced and
recorded — that is what a human reviewer receives on escalation — but `Resolution.ruling`
stays empty and the parties see only the neutral holding message. Every gate withholds;
none rewrites what the Judge proposed. The threshold is passed in from configuration on
every call; nothing here hard-codes it.
"""

from __future__ import annotations

import json
import math
from typing import Any, Dict, List, Optional

from ..dispute import CATEGORY_NO_SHOW_CHARGE, CATEGORY_ROUTE_DEVIATION, Dispute
from ..evidence import EvidencePack
from ..schemas import (
    OUTCOME_RULED,
    OUTCOME_WITHHELD,
    UNDER_REVIEW_MESSAGE,
    AdvocateCase,
    JudgeRuling,
    Resolution,
    RulingAction,
    party_message_for_ruling,
)
from .base import BaseAgent, HARD_RULES, citable_refs_block, dispute_block, evidence_block, policy_blocks, validate_citations

EVENT_RULING_ISSUED = "judge.ruling_issued"
EVENT_RULING_WITHHELD = "judge.ruling_withheld"

#: NS-6: the largest contested no-show fee the system may refund without a human.
CONTESTED_NO_SHOW_AUTO_LIMIT_SGD = 10.00
#: RD-5: an overcharge below this is de minimis and is not gated.
DE_MINIMIS_SGD = 1.00


def _is_figure(value: Any) -> bool:
    """True only for a real, finite number. bool is an int subclass, so it is excluded.

    A value that is present but not finite (NaN or Infinity, both of which a JSON reader
    accepts) is not a figure a gate may compare: NaN compares False against everything
    and Infinity compares the wrong way, so each would slip through as if recorded.
    """
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _is_count(value: Any) -> bool:
    """True only for a real integer. bool is an int subclass, so it is excluded."""
    return isinstance(value, int) and not isinstance(value, bool)


def ns6_auto_refund_eligible(pack: EvidencePack) -> bool:
    """NS-6: whether a contested no-show refund may be issued without a human.

    Every condition must hold, and a missing figure always fails its condition: an
    unrecorded fee, fraud flag or dispute history is not a clean record. This decides
    who decides the case, never which way it goes.
    """
    cancellation = pack.cancellation
    if cancellation is None:
        return False
    fee = cancellation.cancellation_fee_sgd
    if not _is_figure(fee) or fee <= 0 or fee > CONTESTED_NO_SHOW_AUTO_LIMIT_SGD:
        return False

    profiles = pack.profiles
    rider = profiles.rider if profiles is not None else None
    if rider is None:
        return False
    if not _is_count(rider.fraud_flags) or rider.fraud_flags != 0:
        return False

    total = rider.disputes_total
    upheld = rider.disputes_upheld
    if not _is_count(total) or not _is_count(upheld):
        return False
    if total < 0 or upheld < 0 or upheld > total:
        return False
    # Rejected = total minus upheld; eligible when rejected is no more than half.
    return (total - upheld) * 2 <= total


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
        extra_notes: Optional[List[str]] = None,
    ) -> Resolution:
        """Deliberate, then either issue the ruling or withhold it behind the gate.

        `extra_notes` carries pipeline-level observations (the one-round follow-up gate)
        onto the resolution, whichever way the ruling goes.
        """
        def build(payload: Dict[str, Any], llm_info: Dict[str, Any]) -> JudgeRuling:
            return JudgeRuling.from_payload(
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

        ruling = self._ask(
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
            build=build,
        )

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
        if dispute.category == CATEGORY_ROUTE_DEVIATION:
            # ESC-2 for route cases: a ruling that cannot name the deviation it rests on
            # is exactly the "plausible figure for a missing one" the policy forbids.
            # EV-1 names the fare charged as the third figure a fare finding needs, so a
            # charge the record cannot prove is a missing figure too. One gate, wider —
            # never two entries, even when both figures are missing. Route cases only —
            # for a no-show, a missing arrival is itself the evidence (NS-4), and gating
            # on it would withhold the cases the policy rules.
            deviation_missing = (
                pack.route is not None and not _is_figure(pack.route.deviation_pct)
            )
            charge_missing = pack.fare is None or not _is_figure(pack.fare.charged_sgd)
            if deviation_missing or charge_missing:
                missing_fields = []
                summary_parts = []
                if deviation_missing:
                    missing_fields.append("route.deviation_pct")
                    summary_parts.append("the route deviation could not be measured")
                if charge_missing:
                    missing_fields.append("fare.charged_sgd")
                    summary_parts.append("the fare charged could not be established")
                gate_failures.append(
                    (
                        "ESC-2",
                        "%s %s not a recorded figure, so the fare finding a "
                        "route-deviation ruling rests on cannot be made (EV-1, ESC-2)"
                        % (
                            " and ".join(missing_fields),
                            "are" if len(missing_fields) > 1 else "is",
                        ),
                    )
                )
                gate_summaries.append("%s (ESC-2)" % " and ".join(summary_parts))

        cancellation = pack.cancellation
        if (
            dispute.category == CATEGORY_NO_SHOW_CHARGE
            and cancellation is not None
            and cancellation.driver_marked_no_show is True
            and cancellation.rider_claims_driver_absent is True
            and cancellation.driver_distance_from_pickup_m is None
        ):
            # NS-6: a contested no-show with no recorded arrival position has no GPS
            # proof for the fee. The only ruling allowed through is a refund of exactly
            # the fee, and only for a low fee and a clean rider record; everything else
            # goes to a human. The candidate ruling is never rewritten.
            eligible = ns6_auto_refund_eligible(pack)
            fee = cancellation.cancellation_fee_sgd
            full_refund = (
                ruling.action == RulingAction.REFUND.value
                and _is_figure(fee)
                and round(ruling.recommended_amount_sgd, 2) == round(fee, 2)
            )
            if not (eligible and full_refund):
                if eligible:
                    reason = (
                        "NS-6: the contested no-show fee has no recorded arrival position "
                        "and is refunded in full under GEN-3; the proposed %s of SGD %.2f "
                        "is not that refund"
                        % (ruling.action, ruling.recommended_amount_sgd)
                    )
                else:
                    reason = (
                        "NS-6: the contested no-show refund is not automatic here — the "
                        "fee must be recorded and at most SGD %.2f, the rider's fraud "
                        "flags recorded and zero, and no more than half the rider's past "
                        "disputes rejected" % CONTESTED_NO_SHOW_AUTO_LIMIT_SGD
                    )
                gate_failures.append(("NS-6", reason))
                gate_summaries.append(
                    "the contested no-show refund is not a supported automatic refund (NS-6)"
                )

        fare = pack.fare
        if (
            dispute.category == CATEGORY_ROUTE_DEVIATION
            and fare is not None
            and _is_figure(fare.difference_sgd)
            and fare.difference_sgd >= DE_MINIMIS_SGD
        ):
            # RD-5: the records prove an overcharge of at least the de minimis amount,
            # so a ruling that refunds less than the proven difference (or nothing) is
            # held for a human. Refunding more than the difference is not this gate's
            # concern.
            covered = (
                ruling.action == RulingAction.REFUND.value
                and round(ruling.recommended_amount_sgd, 2) >= round(fare.difference_sgd, 2)
            )
            if not covered:
                gate_failures.append(
                    (
                        "RD-5",
                        "RD-5: the records prove an overcharge of SGD %.2f; the proposed "
                        "%s of SGD %.2f does not refund it"
                        % (
                            fare.difference_sgd,
                            ruling.action,
                            ruling.recommended_amount_sgd,
                        ),
                    )
                )
                gate_summaries.append(
                    "the ruling refunds less than the overcharge the records prove (RD-5)"
                )
        elif (
            dispute.category == CATEGORY_ROUTE_DEVIATION
            and fare is not None
            and fare.difference_sgd is not None
            and not _is_figure(fare.difference_sgd)
        ):
            # RD-5: a difference that is present but not finite cannot prove or disprove
            # an overcharge, so no ruling may be issued on it. None still means "no
            # overcharge figure", which is not this gate's concern.
            gate_failures.append(
                (
                    "RD-5",
                    "RD-5: the fare.difference_sgd in the record is not a finite number, "
                    "so the overcharge it would show cannot be established; the ruling "
                    "is held (RD-5)",
                )
            )
            gate_summaries.append("the overcharge figure in the records could not be read (RD-5)")

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
                party_message=party_message_for_ruling(ruling, self.policy),
                confidence_threshold=confidence_threshold,
                ruling=ruling,
                notes=list(extra_notes or []),
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
            notes=["the ruling was not delivered: %s" % reason for reason in reasons]
            + list(extra_notes or []),
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
