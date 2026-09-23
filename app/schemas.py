"""Output contracts, frozen this session.

These are the shapes the agents must produce and the shapes the rest of the system
consumes. They are validated at the boundary: a model response that does not satisfy its
contract raises, rather than being coerced into something plausible.

Judge output contract (fixed):
    action                  one of RulingAction: refund | compensation | no action
    recommended_amount_sgd  amount in SGD, 0.00 for a no-action ruling
    confidence              float in [0, 1]
    explanation             natural-language reasoning
    cited_rule_ids          policy rule IDs the reasoning rests on

Advocates produce an AdvocateCase, which carries the same two citation kinds: evidence
field references and policy rule IDs.

A ruling whose confidence is below the configured threshold is not delivered to the
parties: see Resolution and UNDER_REVIEW_MESSAGE. The threshold itself lives in
app/config.json and is passed in — never hard-coded here or in any agent.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

#: Shown to the parties when the Judge does not rule. Deliberately says nothing about
#: AI, about which way the case is leaning, or about what the confidence was.
UNDER_REVIEW_MESSAGE = (
    "Your case is still under review. We will let you know as soon as a decision is made."
)

#: Shown to the parties when the intake category is outside the two the agents handle.
HUMAN_REVIEW_MESSAGE = (
    "Thank you for your report. It has been passed to our support team, who will follow up with you."
)

#: Shown to the parties when the run stops to ask the filing party for more information.
#: Deliberately says nothing about AI, about which way the case is leaning, or about any
#: internal step: the party is asked for a little more, and nothing else.
NEEDS_INFO_MESSAGE = (
    "Thank you — we need a little more information before we can continue with your case. "
    "Please answer the questions below and submit them, and we will take a fresh look as "
    "soon as your answers arrive."
)

OUTCOME_RULED = "ruled"
OUTCOME_WITHHELD = "withheld"
OUTCOME_HUMAN_REVIEW = "human_review"
OUTCOME_NEEDS_INFO = "needs_info"


class ContractError(ValueError):
    """A model response does not satisfy the contract it was asked for."""


class RulingAction(str, Enum):
    """The ruling enum from the challenge statement. Values are the wire values."""

    REFUND = "refund"
    COMPENSATION = "compensation"
    NO_ACTION = "no action"

    @classmethod
    def parse(cls, value: Any, *, field_name: str = "action") -> "RulingAction":
        """Parse a model's value into the enum, tolerating underscore/hyphen/case drift."""
        if isinstance(value, RulingAction):
            return value
        if not isinstance(value, str):
            raise ContractError(
                "%s must be one of %s, got %r" % (field_name, _enum_values(), value)
            )
        normalised = re.sub(r"[\s_-]+", " ", value.strip().lower())
        for member in cls:
            if member.value == normalised:
                return member
        raise ContractError(
            "%s must be one of %s, got %r" % (field_name, _enum_values(), value)
        )


def _enum_values() -> str:
    return " | ".join(member.value for member in RulingAction)


# ------------------------------------------------------------------ field readers


def _require_text(payload: Dict[str, Any], key: str, agent: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ContractError("%s: '%s' is required and must be a non-empty string" % (agent, key))
    return value.strip()


def _require_number(
    payload: Dict[str, Any],
    key: str,
    agent: str,
    *,
    minimum: Optional[float] = None,
    maximum: Optional[float] = None,
) -> float:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractError("%s: '%s' is required and must be a number, got %r" % (agent, key, value))
    number = float(value)
    # NaN and Infinity survive json.loads and slip past every comparison below: NaN is
    # neither < minimum nor > maximum, so an unbounded-nonsense amount would reach the
    # parties as "refund of SGD nan". Reject them before the range checks.
    if not math.isfinite(number):
        raise ContractError(
            "%s: '%s' must be a finite number, got %r" % (agent, key, value)
        )
    if minimum is not None and number < minimum:
        raise ContractError("%s: '%s' must be >= %s, got %s" % (agent, key, minimum, number))
    if maximum is not None and number > maximum:
        raise ContractError("%s: '%s' must be <= %s, got %s" % (agent, key, maximum, number))
    return number


def _optional_text_list(payload: Dict[str, Any], key: str, agent: str) -> List[str]:
    value = payload.get(key)
    if value is None:
        return []
    if not isinstance(value, list):
        raise ContractError("%s: '%s' must be a list of strings, got %r" % (agent, key, value))
    items = []
    for item in value:
        if isinstance(item, str) and item.strip():
            items.append(item.strip())
        else:
            # Numbers were once coerced with str(). That invented a citation the model
            # never made: '5' resolves to no rule and no pack field, so it rode into the
            # ruling looking grounded while the validator, which drops non-strings, never
            # saw it. A citation that cannot resolve is worse than a missing one.
            raise ContractError(
                "%s: '%s' must contain only strings, found %r" % (agent, key, item)
            )
    return items


# --------------------------------------------------------------------- contracts


@dataclass(frozen=True)
class JudgeRuling:
    """The Judge's ruling, exactly as the contract specifies."""

    action: str
    recommended_amount_sgd: float
    confidence: float
    explanation: str
    cited_rule_ids: List[str]
    cited_evidence_refs: List[str] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)
    validation: Dict[str, Any] = field(default_factory=dict)
    llm: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(
        cls,
        payload: Dict[str, Any],
        *,
        agent: str = "judge",
        llm: Optional[Dict[str, Any]] = None,
        validation: Optional[Dict[str, Any]] = None,
    ) -> "JudgeRuling":
        action = RulingAction.parse(payload.get("action"))
        amount = _require_number(payload, "recommended_amount_sgd", agent, minimum=0.0)
        confidence = _require_number(payload, "confidence", agent, minimum=0.0, maximum=1.0)
        explanation = _require_text(payload, "explanation", agent)
        cited = _optional_text_list(payload, "cited_rule_ids", agent)
        cited_refs = _optional_text_list(payload, "cited_evidence_refs", agent)

        notes: List[str] = []
        if action is RulingAction.NO_ACTION and amount != 0.0:
            notes.append(
                "recommended_amount_sgd forced to 0.00: a no-action ruling carries no amount"
            )
            amount = 0.0
        if action is not RulingAction.NO_ACTION and amount == 0.0:
            notes.append("a %s ruling was issued with a zero amount" % action.value)
        if not cited:
            notes.append("no policy rule IDs cited")
        if not cited_refs:
            # GEN-2 requires a ruling to name the evidence behind it. A ruling with no
            # cited fields is not invalid, but it is unreviewable, and the case file
            # should say so rather than present it as fully grounded.
            notes.append("no evidence pack fields cited")

        merged = dict(validation or {})
        merged.setdefault("notes", [])
        merged["notes"] = list(merged["notes"]) + notes

        return cls(
            action=action.value,
            recommended_amount_sgd=round(amount, 2),
            confidence=round(confidence, 4),
            explanation=explanation,
            cited_rule_ids=cited,
            cited_evidence_refs=cited_refs,
            raw=dict(payload),
            validation=merged,
            llm=dict(llm or {}),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "recommended_amount_sgd": self.recommended_amount_sgd,
            "confidence": self.confidence,
            "explanation": self.explanation,
            "cited_rule_ids": list(self.cited_rule_ids),
            "cited_evidence_refs": list(self.cited_evidence_refs),
            "validation": self.validation,
            "llm": self.llm,
        }


@dataclass(frozen=True)
class AdvocateCase:
    """One advocate's case for one side."""

    party: str
    agent: str
    claim_summary: str
    argument: str
    requested_outcome: str
    requested_amount_sgd: float
    evidence_cited: List[str] = field(default_factory=list)
    policy_rule_ids: List[str] = field(default_factory=list)
    follow_up_questions: List[str] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)
    validation: Dict[str, Any] = field(default_factory=dict)
    llm: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(
        cls,
        payload: Dict[str, Any],
        *,
        party: str,
        agent: str,
        llm: Optional[Dict[str, Any]] = None,
        validation: Optional[Dict[str, Any]] = None,
    ) -> "AdvocateCase":
        outcome = RulingAction.parse(payload.get("requested_outcome"), field_name="requested_outcome")
        amount = _require_number(payload, "requested_amount_sgd", agent, minimum=0.0)

        notes: List[str] = []
        if outcome is RulingAction.NO_ACTION and amount != 0.0:
            notes.append("requested_amount_sgd forced to 0.00: a no-action request carries no amount")
            amount = 0.0

        merged = dict(validation or {})
        merged.setdefault("notes", [])
        merged["notes"] = list(merged["notes"]) + notes

        return cls(
            party=party,
            agent=agent,
            claim_summary=_require_text(payload, "claim_summary", agent),
            argument=_require_text(payload, "argument", agent),
            requested_outcome=outcome.value,
            requested_amount_sgd=round(amount, 2),
            evidence_cited=_optional_text_list(payload, "evidence_cited", agent),
            policy_rule_ids=_optional_text_list(payload, "policy_rule_ids", agent),
            follow_up_questions=_optional_text_list(payload, "follow_up_questions", agent),
            raw=dict(payload),
            validation=merged,
            llm=dict(llm or {}),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "party": self.party,
            "agent": self.agent,
            "claim_summary": self.claim_summary,
            "argument": self.argument,
            "requested_outcome": self.requested_outcome,
            "requested_amount_sgd": self.requested_amount_sgd,
            "evidence_cited": list(self.evidence_cited),
            "policy_rule_ids": list(self.policy_rule_ids),
            "follow_up_questions": list(self.follow_up_questions),
            "validation": self.validation,
            "llm": self.llm,
        }


@dataclass(frozen=True)
class Resolution:
    """What the system decided, and what the parties are told.

    `ruling` is set only when a ruling was actually issued to the parties. When the
    confidence gate trips, the Judge's candidate is kept in `withheld_candidate` for the
    human reviewer and `ruling` stays None, so nothing that renders this object
    naively can leak a withheld decision to a party.
    """

    dispute_id: str
    outcome: str
    party_message: str
    confidence_threshold: float
    ruling: Optional[JudgeRuling] = None
    withheld_candidate: Optional[JudgeRuling] = None
    escalated_for_human_review: bool = False
    #: Targeted questions for the filing party. Populated only for OUTCOME_NEEDS_INFO;
    #: always serialised ([] when none) so every consumer can read the field unguarded.
    questions_for_party: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    @property
    def delivered_to_parties(self) -> bool:
        """True when the parties receive a real decision rather than a holding message."""
        return self.outcome == OUTCOME_RULED

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dispute_id": self.dispute_id,
            "outcome": self.outcome,
            "party_message": self.party_message,
            "confidence_threshold": self.confidence_threshold,
            "delivered_to_parties": self.delivered_to_parties,
            "escalated_for_human_review": self.escalated_for_human_review,
            "questions_for_party": list(self.questions_for_party),
            "ruling": self.ruling.to_dict() if self.ruling else None,
            "withheld_candidate": self.withheld_candidate.to_dict() if self.withheld_candidate else None,
            "notes": list(self.notes),
        }


def party_message_for_ruling(ruling: JudgeRuling) -> str:
    """The message both parties receive when a ruling is issued."""
    if ruling.action == RulingAction.NO_ACTION.value:
        return "Decision: no action. %s" % ruling.explanation
    return "Decision: %s of SGD %.2f. %s" % (
        ruling.action,
        ruling.recommended_amount_sgd,
        ruling.explanation,
    )
