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

#: The vocabulary a party must never read: the internal system's names, the confidence
#: mechanics, the withholding and escalation mechanics. This is the same banned-word set
#: the acceptance tests use; code that composes or relays a party-facing string checks
#: against it and fails closed rather than shipping the word. Stem-shaped, not exact
#: words (S2, widened T2): "models", "judges", "withhold", "judgement", "confident",
#: "advocacy" leaked through an exact-word list; "agentic", "modelling"/"modelled",
#: "A.I." and the misspellings "withold"/"witheld" leaked through the first stems.
#: Deliberately `agent\w*`, NOT `agen\w*` — that would block "agency" — and the
#: A.I. alternative sits outside the \b group, because after a literal dot a word
#: boundary does not behave the way it does after a letter.
PARTY_UNSAFE_PATTERN = re.compile(
    r"\b(ai|agent\w*|advoca\w*|judg\w*|confiden\w*|withh?[eo]ld\w*|escalat\w*|model\w*)\b"
    r"|\ba\.\s?i\.",
    re.IGNORECASE,
)

#: The rule-ID prefixes docs/policy.md actually uses. This list is the ONE owner:
#: a new prefix added to the policy must be added here (the acceptance test derives
#: every real rule id from the policy and goes red until it is). Matching only real
#: prefixes (T1) keeps public tokens like the pack's own trip id TRIP-2026-09945,
#: "Sept-3" or "covid-19" out of the filter.
PARTY_RULE_ID_PREFIXES = ("GEN", "EV", "RD", "NS", "ESC")

#: Rule IDs (RD-1, ESC-4, ...) are internal citations; a party-facing string that
#: carries one is leaking the machinery, not explaining the decision. Case-insensitive
#: with up to 4 digits, over the real prefixes only (T1).
PARTY_UNSAFE_RULE_ID_PATTERN = re.compile(
    r"\b(?:%s)-\d{1,4}\b" % "|".join(PARTY_RULE_ID_PREFIXES),
    re.IGNORECASE,
)

#: Shown to the parties when the Judge does not rule. Deliberately says nothing about
#: AI, about which way the case is leaning, or about what the confidence was.
UNDER_REVIEW_MESSAGE = (
    "Your case is still under review. We will let you know as soon as a decision is made."
)


def is_party_safe(text: Any) -> bool:
    """True when a string carries nothing a party must not read.

    Checks the banned internal vocabulary and rule-ID-shaped tokens. Used by every
    code path that composes or relays a party-facing message or question.
    """
    if not isinstance(text, str):
        return False
    return not PARTY_UNSAFE_PATTERN.search(text) and not PARTY_UNSAFE_RULE_ID_PATTERN.search(text)

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

#: Prepended to a decided message when the ruling's LLM record does not prove the real
#: provider (the fail-closed proof check lives in party_view, app/server.py): a decision
#: made on an illustrative run must never read like a live review. Fixed text — it never
#: varies with the input — and it must keep passing is_party_safe and the acceptance
#: tests' forbidden-word regex. The trailing space lets the decision text follow directly.
DEMO_NOTICE_MESSAGE = (
    "Demo notice: this decision was produced by an illustrative run and is not a live review. "
)

OUTCOME_RULED = "ruled"
OUTCOME_WITHHELD = "withheld"
OUTCOME_HUMAN_REVIEW = "human_review"
OUTCOME_NEEDS_INFO = "needs_info"

#: The intake-form questions per category, with the exact labels the party page shows
#: (ui/party/party.js must agree; a test reads the page and asserts it). This table is
#: the ONE owner of the labels: the server's questionnaire validation derives from it,
#: and template questions quote it, so a party is asked about a field by the same words
#: everywhere.
INTAKE_QUESTIONS: Dict[str, tuple] = {
    "route_deviation": (
        ("expected_route", "What route did the app show you, and roughly how long was it?"),
        ("was_route_agreed", "Did you and the driver agree to take a different route?"),
        ("asked_driver_to_stop", "Did you ask the driver to stop anywhere along the way?"),
        ("safety_concern", "At any point were you worried for your safety?"),
    ),
    "no_show_charge": (
        ("where_were_you", "Where were you when the trip was meant to start?"),
        ("did_driver_contact_you", "Did the driver try to contact you?"),
        ("safety_concern", "At any point were you worried for your safety?"),
    ),
}

#: The intake questions that are answered with a choice, not free text. This table is
#: the ONE owner of that fact: the party page tags each question from it (a test reads
#: the page and asserts they agree), and the server's questionnaire validation derives
#: from INTAKE_QUESTIONS.
YES_NO_INTAKE_KEYS = frozenset({
    "was_route_agreed",
    "asked_driver_to_stop",
    "safety_concern",
    "did_driver_contact_you",
})

#: The code-built question sent when an intake field was left blank. The label comes
#: from INTAKE_QUESTIONS — never the raw field key, which is internal vocabulary.
BLANK_FIELD_QUESTION_TEMPLATE = 'We didn\'t get an answer to "%s". Could you tell us?'


def blank_field_question(label: str) -> str:
    """The party-facing question for one blank intake field, in plain words."""
    return BLANK_FIELD_QUESTION_TEMPLATE % label


#: W13: the follow-up questions an advocate may ask, per category. An advocate picks ids;
#: code renders the sentence, so no model-written text reaches a party. Sentences are
#: written for the rider: a driver-filed dispute is offered form slots only.
FOLLOW_UP_QUESTION_BANK: Dict[str, tuple] = {
    "route_deviation": (
        ("route_shown", "What route did the app show you before the trip started?"),
        ("route_discussed", "Did you and the driver talk about taking a different route? If so, what was said?"),
        ("stops_or_changes", "Did you ask the driver to stop, wait or change the destination during the trip? If so, where?"),
        ("road_conditions", "Did the driver mention a road closure or diversion during the trip?"),
        ("pickup_dropoff", "Were you picked up and dropped off where your booking said? If not, where?"),
    ),
    "no_show_charge": (
        ("waiting_place", "Where exactly were you waiting when the trip was meant to start?"),
        ("driver_contact", "Did the driver call or message you? If so, what was said?"),
        ("arrival_time", "Roughly what time did you reach the pickup point?"),
        ("cancel_reason", "Who cancelled the trip, and what was the reason?"),
    ),
}

MAX_FOLLOW_UP_SLOTS = 6

#: A form slot re-asks one intake question, quoting its label from INTAKE_QUESTIONS.
FORM_SLOT_PREFIX = "form:"
FORM_SLOT_QUESTION_TEMPLATE = 'About the form question "%s": could you tell us a little more?'


def follow_up_slot_ids(category: str) -> List[str]:
    """Every slot id an advocate may pick for this category: bank ids, then form ids."""
    bank = [slot for slot, _ in FOLLOW_UP_QUESTION_BANK.get(category, ())]
    form = [FORM_SLOT_PREFIX + key for key, _ in INTAKE_QUESTIONS.get(category, ())]
    return bank + form


def render_follow_up_slot(category: Any, slot_id: Any, filed_by: str = "rider") -> Optional[str]:
    """The party-facing sentence for one slot id, or None when the id is not offered."""
    if not isinstance(category, str) or not isinstance(slot_id, str):
        return None
    if slot_id.startswith(FORM_SLOT_PREFIX):
        label = dict(INTAKE_QUESTIONS.get(category, ())).get(slot_id[len(FORM_SLOT_PREFIX):])
        return FORM_SLOT_QUESTION_TEMPLATE % label if label else None
    if filed_by != "rider":
        return None
    return dict(FOLLOW_UP_QUESTION_BANK.get(category, ())).get(slot_id)


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
    try:
        number = float(value)
    except OverflowError:
        # An integer too large for a float is not a number this contract can carry. A
        # JSON reader returns ints of any size, so a model reply can carry one; it is
        # rejected exactly as NaN is, and never raises OverflowError out of the parse.
        raise ContractError(
            "%s: '%s' must be a finite number, got %r" % (agent, key, value)
        ) from None
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
    follow_up_slots: List[str] = field(default_factory=list)
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
        category: Optional[str] = None,
        filed_by: str = "rider",
    ) -> "AdvocateCase":
        outcome = RulingAction.parse(payload.get("requested_outcome"), field_name="requested_outcome")
        amount = _require_number(payload, "requested_amount_sgd", agent, minimum=0.0)
        all_slots = _optional_text_list(payload, "follow_up_slots", agent)
        ignored_slot_count = max(0, len(all_slots) - MAX_FOLLOW_UP_SLOTS)
        slots = all_slots[:MAX_FOLLOW_UP_SLOTS]

        notes: List[str] = []
        rendered_questions: List[str] = []
        for slot in slots:
            question = render_follow_up_slot(category, slot, filed_by)
            if question is None:
                display_slot = slot if len(slot) <= 40 else slot[:40] + "…"
                notes.append(
                    "follow-up slot %r dropped: not offered for this %s dispute"
                    % (display_slot, category)
                )
            elif question not in rendered_questions:
                rendered_questions.append(question)
        if ignored_slot_count:
            notes.append(
                "%d further follow-up slot ids ignored (limit %d)"
                % (ignored_slot_count, MAX_FOLLOW_UP_SLOTS)
            )
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
            follow_up_slots=slots,
            follow_up_questions=rendered_questions,
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
            "follow_up_slots": list(self.follow_up_slots),
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
    model_failure: Optional[Dict[str, Any]] = None

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
            "model_failure": self.model_failure,
        }


def _cited_rule_titles(ruling: "JudgeRuling", policy: Any) -> List[str]:
    """The plain titles of the rules a ruling rests on, safe for a party to read.

    At most 3; a title that cannot be resolved, is empty, or would leak the internal
    vocabulary is skipped. Escalation rules are excluded by ID prefix before any word
    check (S5): ESC-4's title "Amount above the autonomous cap" passes the word filter,
    so the prefix is the only reliable gate — a ruling citing only ESC rules gets no
    Basis line. Titles are the only policy content that crosses to the party — never
    IDs, never the rule text, never the Judge's explanation.
    """
    if policy is None:
        return []
    titles: List[str] = []
    for rule_id in ruling.cited_rule_ids:
        if len(titles) >= 3:
            break
        if rule_id.startswith("ESC-"):
            continue
        try:
            title = policy.rule_title(rule_id)
        except KeyError:
            continue
        title = (title or "").strip()
        if not title or not is_party_safe(title):
            continue
        titles.append(title)
    return titles


def party_message_for_ruling(ruling: "JudgeRuling", policy: Any = None) -> str:
    """The message both parties receive when a ruling is issued.

    Built in code from structured fields only (the operator ruling 2026-09-23, option A): the
    action, the amount for a money ruling, and the plain titles of the cited policy
    rules. The Judge's explanation is never relayed — it stays on
    resolution.ruling.explanation for the operator console. With no policy the message
    is action and amount alone.
    """
    if ruling.action == RulingAction.NO_ACTION.value:
        message = "Decision: no action."
    else:
        message = "Decision: %s of SGD %.2f." % (ruling.action, ruling.recommended_amount_sgd)
    titles = _cited_rule_titles(ruling, policy)
    if titles:
        message += " Basis: %s." % "; ".join(titles)
    return message
