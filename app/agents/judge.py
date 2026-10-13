"""Judge — the impartial arbitrator.

Weighs both advocates' cases, applies the policy document, and issues one ruling with a
confidence score and a natural-language explanation.

The confidence gate is the Judge's contract, not a policy rule: a ruling whose confidence
is below the configured threshold is not delivered to the parties. It stands beside six
other Python-enforced gates: ESC-4 (the recommended amount above the autonomous cap),
ESC-2 (a route-deviation case whose deviation could not be measured, whose fare charged is
not a recorded figure, or whose record states a fare input it cannot read), NS-6 (a contested
no-show whose fee has no recorded arrival position may only be refunded in full, and only
for a low fee and a clean rider record), NS-8 (a no-show refund larger than the recorded
fee, any compensation on a no-show case, or any refund whose fee the record cannot read,
is withheld for a human), RD-5 (a proven overcharge of at least the de
minimis amount must actually be refunded) and RD-4 (a route refund larger than the records
prove the rider overpaid, or any compensation on a route case, is withheld for a human).
The Judge's candidate is still produced and
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
#: RD-1: a deviation is material at this percentage AND this distance...
MATERIAL_DEVIATION_PCT = 20.0
MATERIAL_DEVIATION_KM = 1.0
#: ...or at this distance whatever the percentage.
MATERIAL_DEVIATION_GROSS_KM = 5.0


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


def deviation_is_material(pack: EvidencePack) -> bool:
    """RD-1 in code: is the recorded route deviation material?

    Material at >= 5.0 km whatever the percentage, or at >= 20% and >= 1.0 km together.
    A missing, non-finite or bool figure is not material, and neither is a pack with no
    route block. When the gross distance limb is cleared the percentage is not needed at
    all — it may be missing.
    """
    route = pack.route
    if route is None:
        return False
    km = route.deviation_km
    if _is_figure(km) and km >= MATERIAL_DEVIATION_GROSS_KM:
        return True
    pct = route.deviation_pct
    return (
        _is_figure(km)
        and _is_figure(pct)
        and pct >= MATERIAL_DEVIATION_PCT
        and km >= MATERIAL_DEVIATION_KM
    )


def provable_refund_sgd(pack: EvidencePack) -> float:
    """RD-4: the largest refund the records actually prove the rider is owed.

    The max of three proofs, never below zero, rounded to the cent:

    1. ``fare.difference_sgd`` (RD-5, a pricing error);
    2. ``fare.charged_sgd - fare.component_sum_sgd`` when the breakdown is inconsistent
       (EV-3: the line items add up to less than the charge) — this works without rates;
    3. ``fare.charged_sgd - fare.recomputed_estimated_route_sgd`` when RD-1 says the
       deviation is material (RD-3 / RD-4: the charge above the fare the expected route
       would have cost).

    ``fare.deviation_fare_delta_sgd`` is deliberately never read: on a fixed fare paid as
    quoted it is what the detour *would* have cost, not money the rider paid. A missing or
    unreadable figure contributes nothing; no fare block proves zero.
    """
    fare = pack.fare
    if fare is None:
        return 0.0
    proven = 0.0
    if _is_figure(fare.difference_sgd):
        proven = max(proven, fare.difference_sgd)
    if (
        fare.breakdown_consistent is False
        and _is_figure(fare.charged_sgd)
        and _is_figure(fare.component_sum_sgd)
    ):
        proven = max(proven, fare.charged_sgd - fare.component_sum_sgd)
    if (
        deviation_is_material(pack)
        and _is_figure(fare.charged_sgd)
        and _is_figure(fare.recomputed_estimated_route_sgd)
    ):
        proven = max(proven, fare.charged_sgd - fare.recomputed_estimated_route_sgd)
    return round(proven, 2)


def ns8_provable_refund_ceiling_sgd(pack: EvidencePack) -> Optional[float]:
    """NS-8: the recorded no-show fee — the largest refund a no-show record proves.

    A no-show dispute is, at its widest, a dispute about the one fee the record states:
    the policy's no-show rules (NS-1..NS-5) never order more than that fee back to the
    rider. The fee rounded to the cent is therefore the ceiling any refund must fit
    under, and a compensation ruling fits under no ceiling at all.

    ``None`` means the records prove no ceiling either way: the pack carries no
    cancellation block, or the fee is missing or not a finite figure (bool is not a
    figure). A gate reading ``None`` holds the refund rather than guessing.
    """
    cancellation = pack.cancellation
    if cancellation is None:
        return None
    fee = cancellation.cancellation_fee_sgd
    if not _is_figure(fee):
        return None
    return round(fee, 2)


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
            "were shown.\n"
            "deviation_fare_delta_sgd is the difference between the fare recomputed for "
            "the route actually taken and the fare recomputed for the estimated route, "
            "not money the rider paid.\n\n"
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

        # The gates stand between a ruling and the parties, and all of them are enforced
        # here in Python rather than asked of the model in a prompt. A prompt is a
        # request; this is a guarantee. ESC-4 and RD-4 in particular move money, so they
        # must not depend on the LLM having read its instructions carefully.
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
            # charge the record cannot prove is a missing figure too, and a record that
            # states a fare input it cannot read (a tariff rate or the promo) leaves the
            # overcharge unprovable either way. One gate, wider — never two entries,
            # whatever combination fires. Route cases only — for a no-show, a missing
            # arrival is itself the evidence (NS-4), and gating on it would withhold the
            # cases the policy rules.
            deviation_missing = (
                pack.route is not None and not _is_figure(pack.route.deviation_pct)
            )
            charge_missing = pack.fare is None or not _is_figure(pack.fare.charged_sgd)
            unreadable_inputs = (
                list(pack.fare.unreadable_inputs) if pack.fare is not None else []
            )
            if deviation_missing or charge_missing or unreadable_inputs:
                reason_parts = []
                summary_parts = []
                if deviation_missing:
                    reason_parts.append("route.deviation_pct is not a recorded figure")
                    summary_parts.append("the route deviation could not be measured")
                if charge_missing:
                    reason_parts.append("fare.charged_sgd is not a recorded figure")
                    summary_parts.append("the fare charged could not be established")
                if unreadable_inputs:
                    reason_parts.append(
                        "the record states %s it cannot read (%s)"
                        % (
                            "a fare input" if len(unreadable_inputs) == 1 else "fare inputs",
                            ", ".join("fare.%s" % name for name in unreadable_inputs),
                        )
                    )
                    summary_parts.append("the fare inputs in the record could not be read")
                gate_failures.append(
                    (
                        "ESC-2",
                        "%s, so the fare finding a route-deviation ruling rests on "
                        "cannot be made (EV-1, ESC-2)" % "; ".join(reason_parts),
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

        if (
            dispute.category == CATEGORY_NO_SHOW_CHARGE
            and ruling.action != RulingAction.NO_ACTION.value
        ):
            # NS-8: on a no-show case, money may only move as far as the recorded fee
            # proves. A refund larger than the fee is held (equal goes out — the fee is
            # the ceiling every no-show rule orders within), and compensation is always
            # held, because a no-show record proves nothing owed to the driver. A fee
            # that is missing or not a finite figure proves no ceiling either way, so
            # any refund on such a record is held rather than guessed. The candidate is
            # never rewritten; the human receives exactly what the Judge proposed.
            ceiling = ns8_provable_refund_ceiling_sgd(pack)
            if ruling.action == RulingAction.COMPENSATION.value:
                held = True
                reason = (
                    "NS-8: a no-show record proves nothing owed to the driver; the "
                    "proposed compensation of SGD %.2f is not supported"
                    % ruling.recommended_amount_sgd
                )
                summary = "the ruling pays compensation a no-show record does not support (NS-8)"
            elif ceiling is None:
                held = True
                reason = (
                    "NS-8: the cancellation fee in the record is missing or not a "
                    "readable figure, so the records prove no ceiling either way; the "
                    "refund of SGD %.2f is held"
                    % ruling.recommended_amount_sgd
                )
                summary = "the no-show fee in the records could not be read (NS-8)"
            else:
                held = round(ruling.recommended_amount_sgd, 2) > ceiling
                reason = (
                    "NS-8: the records prove a no-show fee of SGD %.2f; the proposed "
                    "refund of SGD %.2f is more than that"
                    % (ceiling, ruling.recommended_amount_sgd)
                )
                summary = "the ruling refunds more than the no-show fee the records prove (NS-8)"
            if held:
                gate_failures.append(("NS-8", reason))
                gate_summaries.append(summary)

        fare = pack.fare
        # RD-5's floor reads the overcharge the RECORDS prove, not only the one the tariff
        # rates recompute. A route record that states no tariff rates at all has no
        # difference_sgd to read, yet its own inconsistent breakdown can prove an overcharge
        # on its own (EV-3: the line items add up to less than the charge), so a floor reading
        # only that field lets a no-action or short refund through on a record whose own
        # numbers show the overcharge. The widening stays narrow on purpose: it reads the
        # breakdown only where the record states NO rates (a rate the record cannot read is
        # ESC-2's reason and ESC-2 already holds that case — one record defect reads as one
        # reason, as RD-4 does), and a difference present but not finite remains the unreadable
        # branch below. Refunding more than the proven figure is not this gate's concern:
        # RD-4 is the ceiling.
        rd5_proven_sgd = None
        if fare is not None and _is_figure(fare.difference_sgd):
            rd5_proven_sgd = round(fare.difference_sgd, 2)
        elif (
            fare is not None
            and fare.difference_sgd is None
            and not fare.rates
            and fare.breakdown_consistent is False
            and _is_figure(fare.charged_sgd)
            and _is_figure(fare.component_sum_sgd)
            and not any(gate == "ESC-2" for gate, _reason in gate_failures)
        ):
            rd5_proven_sgd = round(fare.charged_sgd - fare.component_sum_sgd, 2)
        if (
            dispute.category == CATEGORY_ROUTE_DEVIATION
            and rd5_proven_sgd is not None
            and rd5_proven_sgd >= DE_MINIMIS_SGD
        ):
            covered = (
                ruling.action == RulingAction.REFUND.value
                and round(ruling.recommended_amount_sgd, 2) >= rd5_proven_sgd
            )
            if not covered:
                gate_failures.append(
                    (
                        "RD-5",
                        "RD-5: the records prove an overcharge of SGD %.2f; the proposed "
                        "%s of SGD %.2f does not refund it"
                        % (
                            rd5_proven_sgd,
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

        if (
            dispute.category == CATEGORY_ROUTE_DEVIATION
            and ruling.action != RulingAction.NO_ACTION.value
            and not any(gate == "ESC-2" for gate, _reason in gate_failures)
            and not (
                fare is not None
                and fare.difference_sgd is not None
                and not _is_figure(fare.difference_sgd)
            )
        ):
            # RD-4: on a route case, money may only move as far as the records prove it is
            # owed. A refund larger than the provable overpayment is held (equal goes out;
            # the short side is RD-5's concern), and compensation is always held — a route
            # record proves nothing owed to the driver. Skipped when ESC-2 already holds
            # the case, or when fare.difference_sgd is present but unreadable (RD-5's
            # unreadable branch): one record defect reads as one reason. The candidate is
            # never rewritten; the human receives exactly what the Judge proposed.
            proven = provable_refund_sgd(pack)
            if ruling.action == RulingAction.COMPENSATION.value:
                held = True
                reason = (
                    "RD-4: a route-deviation record proves nothing owed to the driver; "
                    "the proposed compensation of SGD %.2f is not supported"
                    % ruling.recommended_amount_sgd
                )
            else:
                held = round(ruling.recommended_amount_sgd, 2) > proven
                reason = (
                    "RD-4: the records prove an overpayment of SGD %.2f; the proposed "
                    "refund of SGD %.2f is more than that"
                    % (proven, ruling.recommended_amount_sgd)
                )
            if held:
                gate_failures.append(("RD-4", reason))
                gate_summaries.append(
                    "the ruling pays more than the records prove is owed (RD-4)"
                )

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
