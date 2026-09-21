"""End-to-end orchestration for one dispute.

The flow, and the traffic it leaves in the event log:

    parties  -> system           dispute filed (the intake-form submission)
    system   -> human_review     only for a category outside the two locked ones
    system   -> agents           Evidence Pack built (deterministic, before any LLM call)
    system   -> each advocate    case assigned
    advocate -> judge            case submitted
    advocate -> party            follow-up questions, only when the form is insufficient
    system   -> judge            deliberation started, with both cases
    judge    -> parties          ruling issued, or ruling withheld behind the gate
    system   -> parties          the message the parties actually receive
    system   -> system           run completed

Nothing here decides anything: the evidence layer computes, the agents argue and rule,
and this module only moves the case between them and records what happened.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .agents import DriverAdvocate, Judge, RiderAdvocate
from .dispute import Dispute
from .events import Actor, EventLog, EventType
from .evidence import build_evidence_pack
from .llm import LLMClient
from .policy import PolicySet
from .schemas import (
    HUMAN_REVIEW_MESSAGE,
    OUTCOME_HUMAN_REVIEW,
    AdvocateCase,
    Resolution,
)

CASE_FILE_NAME = "case_file.json"


@dataclass
class CaseFile:
    """The assembled record of one run: what was claimed, what the evidence showed, what
    was decided, and the event strip. Self-contained so a judge can read one file."""

    run_id: str
    dispute_id: str
    category: str
    generated_at: str
    confidence_threshold: float
    policy_path: str
    policy_rule_ids: List[str]
    evidence_pack: Optional[Dict[str, Any]]
    rider_case: Optional[Dict[str, Any]]
    driver_case: Optional[Dict[str, Any]]
    resolution: Dict[str, Any]
    events: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "dispute_id": self.dispute_id,
            "category": self.category,
            "generated_at": self.generated_at,
            "confidence_threshold": self.confidence_threshold,
            "policy": {"source_path": self.policy_path, "rule_ids": self.policy_rule_ids},
            "evidence_pack": self.evidence_pack,
            "claims": {"rider": self.rider_case, "driver": self.driver_case},
            "resolution": self.resolution,
            "events": self.events,
        }

    def write(self, run_dir: Path) -> Path:
        path = Path(run_dir) / CASE_FILE_NAME
        path.write_text(json.dumps(self.to_dict(), indent=2, default=str) + "\n", encoding="utf-8")
        return path


def run_dispute(
    *,
    dispute: Dispute,
    llm: LLMClient,
    policy: PolicySet,
    events: EventLog,
    confidence_threshold: float,
) -> CaseFile:
    """Run one dispute end to end and return its case file."""
    events.emit(
        EventType.RUN_STARTED,
        from_=Actor.SYSTEM,
        to=Actor.SYSTEM,
        summary="run started for dispute %s (%s) with %s, threshold %.2f"
        % (dispute.dispute_id, dispute.category, llm.provider_name, confidence_threshold),
        payload={
            "dispute_id": dispute.dispute_id,
            "category": dispute.category,
            "llm_provider": llm.provider_name,
            "confidence_threshold": confidence_threshold,
            "policy_path": str(policy.source_path),
            "policy_rule_ids": policy.rule_ids(),
        },
    )

    events.emit(
        EventType.DISPUTE_FILED,
        from_=dispute.filed_by,
        to=Actor.SYSTEM,
        summary="%s filed dispute %s as '%s'" % (dispute.filed_by, dispute.dispute_id, dispute.category_as_submitted),
        payload=dispute.raw,
    )

    # ---------------------------------------------------------------- routing
    if not dispute.is_agent_handled:
        return _human_review(dispute=dispute, events=events, policy=policy, threshold=confidence_threshold)

    # ---------------------------------------------------------------- evidence
    pack = build_evidence_pack(dispute)
    pack_event = events.emit(
        EventType.EVIDENCE_PACK_BUILT,
        from_=Actor.SYSTEM,
        to="agents",
        summary="Evidence Pack built: %d computed field(s) available to cite" % len(pack.field_refs()),
        payload=pack.to_dict(),
    )

    rider = RiderAdvocate(llm=llm, events=events, policy=policy)
    driver = DriverAdvocate(llm=llm, events=events, policy=policy)
    judge = Judge(llm=llm, events=events, policy=policy)

    for advocate in (rider, driver):
        events.emit(
            EventType.CASE_ASSIGNED,
            from_=Actor.SYSTEM,
            to=advocate.name,
            summary="case assigned to the %s" % advocate.role_title,
            payload={
                "dispute_id": dispute.dispute_id,
                "category": dispute.category,
                "evidence_pack_ref": pack_event.payload_ref,
            },
        )

    # ---------------------------------------------------------------- advocates
    rider_case = rider.run(dispute, pack)
    driver_case = driver.run(dispute, pack)

    events.emit(
        EventType.JUDGE_DELIBERATION_STARTED,
        from_=Actor.SYSTEM,
        to=judge.name,
        summary="both cases with the Judge for deliberation",
        payload={
            "dispute_id": dispute.dispute_id,
            "rider_case_agent": rider_case.agent,
            "driver_case_agent": driver_case.agent,
            "rider_requested": _requested(rider_case),
            "driver_requested": _requested(driver_case),
        },
    )

    # ------------------------------------------------------------------- judge
    resolution = judge.run(
        dispute,
        pack,
        rider_case,
        driver_case,
        confidence_threshold=confidence_threshold,
    )

    events.emit(
        EventType.PARTY_NOTIFIED,
        from_=Actor.SYSTEM,
        to=Actor.PARTIES,
        summary="parties notified: %s" % _outcome_phrase(resolution),
        payload={
            "dispute_id": dispute.dispute_id,
            "outcome": resolution.outcome,
            "message": resolution.party_message,
        },
    )

    case_file = CaseFile(
        run_id=events.run_id,
        dispute_id=dispute.dispute_id,
        category=dispute.category,
        generated_at=_now(),
        confidence_threshold=confidence_threshold,
        policy_path=str(policy.source_path),
        policy_rule_ids=policy.rule_ids(),
        evidence_pack=pack.to_dict(),
        rider_case=rider_case.to_dict(),
        driver_case=driver_case.to_dict(),
        resolution=resolution.to_dict(),
    )
    _complete(events, case_file, resolution)
    return case_file


# ------------------------------------------------------------------------ helpers


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _requested(case: AdvocateCase) -> Dict[str, Any]:
    return {"outcome": case.requested_outcome, "amount_sgd": case.requested_amount_sgd}


def _outcome_phrase(resolution: Resolution) -> str:
    if resolution.ruling is not None:
        return "%s of SGD %.2f" % (resolution.ruling.action, resolution.ruling.recommended_amount_sgd)
    return "your case is still under review"


def _human_review(
    *, dispute: Dispute, events: EventLog, policy: PolicySet, threshold: float
) -> CaseFile:
    """A category outside the two locked ones: human queue, neutral message, no agents."""
    events.emit(
        EventType.DISPUTE_ROUTED_TO_HUMAN_REVIEW,
        from_=Actor.SYSTEM,
        to=Actor.HUMAN_REVIEW,
        summary="category '%s' is outside the two handled categories; queued for human review"
        % dispute.category_as_submitted,
        payload={
            "dispute_id": dispute.dispute_id,
            "category_as_submitted": dispute.category_as_submitted,
            "reason": "no agent is scoped to handle this category",
        },
    )
    resolution = Resolution(
        dispute_id=dispute.dispute_id,
        outcome=OUTCOME_HUMAN_REVIEW,
        party_message=HUMAN_REVIEW_MESSAGE,
        confidence_threshold=threshold,
        escalated_for_human_review=True,
        notes=["routed to human review: category outside the two the agents handle"],
    )
    events.emit(
        EventType.PARTY_NOTIFIED,
        from_=Actor.SYSTEM,
        to=Actor.PARTIES,
        summary="parties notified: passed to the support team",
        payload={
            "dispute_id": dispute.dispute_id,
            "outcome": resolution.outcome,
            "message": resolution.party_message,
        },
    )

    case_file = CaseFile(
        run_id=events.run_id,
        dispute_id=dispute.dispute_id,
        category=dispute.category,
        generated_at=_now(),
        confidence_threshold=threshold,
        policy_path=str(policy.source_path),
        policy_rule_ids=policy.rule_ids(),
        evidence_pack=None,
        rider_case=None,
        driver_case=None,
        resolution=resolution.to_dict(),
    )
    _complete(events, case_file, resolution)
    return case_file


def _complete(events: EventLog, case_file: CaseFile, resolution: Resolution) -> None:
    case_file.events = events.snapshot()
    events.emit(
        EventType.RUN_COMPLETED,
        from_=Actor.SYSTEM,
        to=Actor.SYSTEM,
        summary="run completed: %s" % resolution.outcome,
        payload={
            "dispute_id": case_file.dispute_id,
            "outcome": resolution.outcome,
            "delivered_to_parties": resolution.delivered_to_parties,
            "escalated_for_human_review": resolution.escalated_for_human_review,
        },
    )
    case_file.events = events.snapshot()
