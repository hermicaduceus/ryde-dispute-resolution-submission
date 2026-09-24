"""Shared agent scaffolding: prompts, the LLM call, and citation validation.

Every agent gets the same material (the dispute intake, the Evidence Pack, the policy
document) and the same hard rules, and every agent returns one JSON object matching its
contract. The differences between agents are their role text and their output schema.

The hard rules are the ones the locked scope demands: no arithmetic by an agent (every
number comes from the pack), evidence cited by dotted field reference, policy cited by
rule ID, and nothing invented. Citations are validated against the pack and the policy
document after every call; anything that does not resolve is recorded on the case rather
than quietly dropped, so the case file shows what the model actually claimed.
"""

from __future__ import annotations

import abc
import json
from typing import Any, Dict, List, Optional, Tuple

from ..dispute import Dispute
from ..events import EventLog
from ..evidence import EvidencePack
from ..llm import LLMClient, LLMContractError, LLMError, LLMRequest, parse_json_object
from ..policy import PolicySet
from ..schemas import (
    AdvocateCase,
    ContractError,
    render_follow_up_slot,
    follow_up_slot_ids,
)

#: Kept deliberately blunt: these are the rules a model is most likely to drift from.
HARD_RULES = """HARD RULES
1. Never do arithmetic. Every number you state must be copied verbatim from the Evidence
   Pack. If a number you want is not in the pack, say it is unavailable — do not compute it.
2. Cite evidence only by the exact dotted references listed under CITABLE EVIDENCE REFS.
3. Cite policy only by rule IDs listed under POLICY RULE IDS. Never invent a rule ID.
4. Return exactly one JSON object matching the schema below. No prose around it, no code
   fence, no commentary."""


class AgentError(RuntimeError):
    """An agent could not complete its task."""


def _json_block(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=False, default=str)


def dispute_block(dispute: Dispute) -> str:
    """The intake-form submission, as the parties filed it."""
    lines = [
        "dispute_id: %s" % dispute.dispute_id,
        "category: %s" % dispute.category,
        "filed_by: %s" % dispute.filed_by,
        "filed_at: %s" % (dispute.filed_at or "not recorded"),
        'claim: "%s"' % dispute.claim_text,
        "amount_claimed_sgd: %s" % dispute.claim_amount_sgd,
    ]
    if dispute.intake:
        lines.append("intake_form_answers:")
        lines.append(_json_block(dispute.intake))
    if dispute.follow_up_answers:
        lines.append("follow_up_answers_from_the_party:")
        lines.append(_json_block(dispute.follow_up_answers))
    return "\n".join(lines)


def blank_intake_questions(dispute: Dispute) -> List[str]:
    """Intake keys whose answer is present but empty after trimming, in form order."""
    return [
        key
        for key, value in dispute.intake.items()
        if isinstance(value, str) and not value.strip()
    ]


def evidence_block(pack: EvidencePack) -> str:
    return _json_block(pack.to_dict())


def citable_refs_block(pack: EvidencePack) -> str:
    refs = pack.field_refs()
    if not refs:
        return "(none — the pack has no computed fields for this dispute)"
    return "\n".join("- %s" % ref for ref in refs)


def policy_blocks(policy: PolicySet) -> str:
    return "POLICY DOCUMENT\n%s\n\nPOLICY RULE IDS\n%s" % (
        policy.text.strip(),
        ", ".join(policy.rule_ids()) or "(none)",
    )


def validate_citations(
    *,
    cited_refs: List[str],
    cited_rules: List[str],
    pack: EvidencePack,
    policy: PolicySet,
) -> Dict[str, Any]:
    """Check every citation against the pack and the policy document.

    Nothing is removed: the case keeps the model's own claims, and the failures are
    recorded alongside them so the case file shows what was claimed and what resolved.
    """
    legal_refs = set(pack.field_refs())
    unknown_refs = [ref for ref in cited_refs if ref not in legal_refs]
    unknown_rules = policy.unknown_rule_ids(cited_rules)

    notes: List[str] = []
    if unknown_refs:
        notes.append(
            "%d cited evidence reference(s) do not resolve to a field in the pack" % len(unknown_refs)
        )
    if unknown_rules:
        notes.append(
            "%d cited policy rule ID(s) are not in the policy document" % len(unknown_rules)
        )

    return {
        "unknown_evidence_refs": unknown_refs,
        "unknown_rule_ids": unknown_rules,
        "notes": notes,
    }


class BaseAgent(abc.ABC):
    """Common behaviour: build the prompt, make the call, parse, validate."""

    name = "agent"
    role_title = "Agent"

    def __init__(self, llm: LLMClient, events: EventLog, policy: PolicySet):
        self.llm = llm
        self.events = events
        self.policy = policy

    # ------------------------------------------------------------------ to override

    @abc.abstractmethod
    def system_prompt(self) -> str:
        """Role, hard rules and output schema for this agent."""

    # -------------------------------------------------------------------- LLM call

    def _ask(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """One LLM call, parsed into a JSON object. Returns (payload, provenance)."""
        request = LLMRequest(
            agent=self.name,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            metadata=dict(metadata or {}),
        )
        try:
            response = self.llm.complete(request)
        except LLMError as exc:
            raise AgentError("%s: the LLM call failed: %s" % (self.name, exc)) from exc

        try:
            payload = parse_json_object(response.text, agent=self.name)
        except LLMContractError as exc:
            raise AgentError("%s: the model response did not match the contract: %s" % (self.name, exc)) from exc

        provenance = response.as_log_fields()
        provenance["request_fingerprint"] = request.fingerprint()
        return payload, provenance


class AdvocateAgent(BaseAgent):
    """Shared implementation for both advocates; the subclasses supply the side.

    The two advocates are separate agents with separate calls — one argues for the rider,
    one for the driver — and neither sees the other's case.
    """

    party = "rider"
    role_blurb = ""

    OUTPUT_SCHEMA: Dict[str, Any] = {
        "claim_summary": "one or two sentences stating what this side's case is",
        "evidence_cited": ["dotted.evidence.ref", "..."],
        "policy_rule_ids": ["RULE-1", "..."],
        "argument": "the case for this side, referring to the cited evidence and policy",
        "requested_outcome": "refund | compensation | no action",
        "requested_amount_sgd": "number, 0.00 for no action",
        "follow_up_slots": ["at most 3 slot ids from FOLLOW-UP QUESTION SLOTS, or []"],
    }

    def system_prompt(self) -> str:
        return (
            "You are the %s in Ryde's autonomous dispute resolution system.\n\n"
            "YOUR ROLE\n%s\n\n"
            "%s\n\n"
            "OUTPUT SCHEMA\n%s\n\n"
            "FOLLOW-UP QUESTIONS\nThe party cannot chat with you. You may put at most 3 "
            "slot IDs in follow_up_slots, and only when the intake answers conflict with "
            "the Evidence Pack or a fact you need is missing. Otherwise leave it empty. "
            "Choose only from FOLLOW-UP QUESTION SLOTS. The party never sees text you write; "
            "code renders the offered slot sentences, and questions go to the filing party only."
            % (self.role_title, self.role_blurb, HARD_RULES, _json_block(self.OUTPUT_SCHEMA))
        )

    def user_prompt(self, dispute: Dispute, pack: EvidencePack) -> str:
        offered_slots = []
        for slot in follow_up_slot_ids(dispute.category):
            sentence = render_follow_up_slot(dispute.category, slot, dispute.filed_by)
            if sentence is not None:
                offered_slots.append("%s: %s" % (slot, sentence))
        slot_block = "\n".join(offered_slots) or "(none offered)"
        return (
            "DISPUTE\n%s\n\n"
            "EVIDENCE PACK (computed deterministically; the only source of numbers)\n%s\n\n"
            "CITABLE EVIDENCE REFS\n%s\n\n"
            "%s\n\n"
            "FOLLOW-UP QUESTION SLOTS\n%s\n\n"
            "YOUR TASK\nArgue the %s's case. Say what the evidence shows, apply the policy "
            "rules that bear on it, and state the outcome the %s should receive and how much."
            % (
                dispute_block(dispute),
                evidence_block(pack),
                citable_refs_block(pack),
                policy_blocks(self.policy),
                slot_block,
                self.party,
                self.party,
            )
        )

    def run(self, dispute: Dispute, pack: EvidencePack) -> AdvocateCase:
        """Build this side's case, record the traffic, return the typed case."""
        payload, llm_info = self._ask(
            system_prompt=self.system_prompt(),
            user_prompt=self.user_prompt(dispute, pack),
            metadata={
                "party": self.party,
                "dispute_id": dispute.dispute_id,
                "category": dispute.category,
                "claim_amount_sgd": dispute.claim_amount_sgd,
                "available_evidence_refs": pack.field_refs(),
                "available_rule_ids": self.policy.rule_ids(),
                "filed_by": dispute.filed_by,
                "blank_intake_questions": blank_intake_questions(dispute),
                "has_follow_up_answers": bool(dispute.follow_up_answers),
            },
        )

        try:
            case = AdvocateCase.from_payload(
                payload,
                party=self.party,
                agent=self.name,
                llm=llm_info,
                validation=validate_citations(
                    cited_refs=_string_list(payload.get("evidence_cited")),
                    cited_rules=_string_list(payload.get("policy_rule_ids")),
                    pack=pack,
                    policy=self.policy,
                ),
                category=dispute.category,
                filed_by=dispute.filed_by,
            )
        except ContractError as exc:
            raise AgentError("%s returned a response that breaks its contract: %s" % (self.name, exc)) from exc

        self.events.emit(
            "advocate.case_submitted",
            from_=self.name,
            to="judge",
            summary="%s submitted a case citing %d evidence field(s) and %d rule(s)"
            % (self.role_title, len(case.evidence_cited), len(case.policy_rule_ids)),
            payload=case.to_dict(),
        )

        # The one-round gate, half one: a dispute that already carries the party's
        # answers never asks again, so the questions this advocate wanted are recorded
        # on its case but no request goes to the party. The pipeline enforces half two
        # (the Judge always runs when answers are present).
        if case.follow_up_questions and not dispute.follow_up_answers:
            self.events.emit(
                "advocate.follow_up_requested",
                from_=self.name,
                to=dispute.filed_by,
                summary="%s asked the %s %d follow-up question(s)"
                % (self.role_title, dispute.filed_by, len(case.follow_up_questions)),
                payload={
                    "dispute_id": dispute.dispute_id,
                    "party": dispute.filed_by,
                    "questions": case.follow_up_questions,
                    "slots": case.follow_up_slots,
                    "reason": "data conflicting or insufficient on the submitted form",
                },
            )

        return case


def _string_list(value: Any) -> List[str]:
    """Best-effort list of strings for pre-validation, without raising on odd shapes."""
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]
