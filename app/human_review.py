"""The human decision on a withheld case: validation, storage, and the party message.

A case the Judge withheld — a gate stopped it, or the model could not answer — waits
for a person. This module owns every rule of that decision: what a valid body is, the
SGD 500 ceiling, the decide-once write, and the words the party eventually reads. The
server only routes HTTP; the pages only render.

The decision is stored as `human_decision.json` in the run directory, written
atomically (a temp file linked into place) so exactly one of N concurrent requests
wins. The run's other files are never rewritten: `case_file.json` and `dispute.json`
stay byte-identical, the existing lines of `events.jsonl` stay byte-identical, and one
`human.decision_recorded` event is appended. If that append fails the decision still
stands and the failure is logged.

No money gate is consulted again (operator ruling): the gate that held the case does
not hold the person. A change to SGD 55.16 on a case held by ESC-4 is accepted, and a
change to SGD 5.56 on a case held by RD-4 is accepted.
"""

from __future__ import annotations

import json
import math
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from . import events
from .events import Actor, EventType
from .schemas import (
    ContractError,
    OUTCOME_WITHHELD,
    RulingAction,
    _cited_rule_titles,
)

HUMAN_DECISION_FILE_NAME = "human_decision.json"
HUMAN_AMOUNT_CEILING_SGD = 500.0
HUMAN_REVIEWED_SENTENCE = "A member of our team reviewed your case."
DECISIONS = ("approve", "change", "reject")
REVIEWER_MAX_CHARS = 80
REASON_MAX_CHARS = 1000

NOT_WAITING_MESSAGE = "this case is not waiting for a human decision"
APPROVE_NO_EXTRAS_MESSAGE = "approve takes no action or amount; use change"
NO_PROPOSAL_MESSAGE = "there is no proposed ruling to approve"
ABOVE_CEILING_MESSAGE = "the proposed amount is above SGD 500.00; use change"
ALREADY_DECIDED_MESSAGE = "this case already has a human decision"


class HumanDecisionError(Exception):
    """A human decision the system refuses, with the HTTP status it maps to."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


# --------------------------------------------------------------------- shape checks


def _finite_number(value: Any) -> Optional[float]:
    """The value as a finite float, or None. Bools and huge JSON ints are not figures."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except OverflowError:  # a JSON int too large for a float is not a figure
        return None
    return number if math.isfinite(number) else None


def _valid_candidate(candidate: Any) -> Optional[Tuple[str, float]]:
    """(wire action, cent-rounded amount) for a usable withheld candidate, else None.

    The candidate is the Judge's proposal kept on the case file for the reviewer. A
    model failure leaves it None; a hand-edited or stale file may hold any shape, and
    anything that is not an action plus a finite figure is not something to approve.
    """
    if not isinstance(candidate, dict):
        return None
    try:
        action = RulingAction.parse(candidate.get("action"))
    except ContractError:
        return None
    amount = _finite_number(candidate.get("recommended_amount_sgd"))
    if amount is None:
        return None
    return action.value, round(amount, 2)


def proposed_from_candidate(candidate: Any) -> Optional[Dict[str, Any]]:
    """The wire form of a usable withheld candidate, or None.

    The reviewer queue shows the proposal in exactly this shape; it is the same
    validity check `validate_decision` approves from.
    """
    valid = _valid_candidate(candidate)
    if valid is None:
        return None
    return {"action": valid[0], "amount_sgd": valid[1]}


def decision_record_is_valid(value: Any) -> bool:
    """True for the record shape `load_decision` accepts: an action and a finite amount.

    A record that fails this is ignored, never partially trusted: the party view
    stays under review and the case stays in the queue.
    """
    if not isinstance(value, dict):
        return False
    if value.get("action") not in {member.value for member in RulingAction}:
        return False
    return _finite_number(value.get("amount_sgd")) is not None


# ---------------------------------------------------------------------- validation


def validate_decision(body: Any, case_file: Any) -> Dict[str, Any]:
    """Validate one human decision against its case file. Pure — nothing touches disk.

    Raises HumanDecisionError with the HTTP status and the message the server relays.
    The order is fixed: the case must be waiting, then the decision, then the reviewer
    and the reason, then the decision's own fields.
    """
    resolution = case_file.get("resolution") if isinstance(case_file, dict) else None
    if not isinstance(resolution, dict) or resolution.get("outcome") != OUTCOME_WITHHELD:
        raise HumanDecisionError(409, NOT_WAITING_MESSAGE)
    if not isinstance(body, dict):
        raise HumanDecisionError(400, "the request body must be a JSON object")

    decision = body.get("decision")
    if not isinstance(decision, str) or decision not in DECISIONS:
        raise HumanDecisionError(400, "decision must be one of approve, change or reject")

    reviewer = body.get("reviewer")
    if not isinstance(reviewer, str):
        raise HumanDecisionError(400, "reviewer is required and must be a string")
    reviewer = reviewer.strip()
    if not reviewer:
        raise HumanDecisionError(400, "reviewer is required")
    if len(reviewer) > REVIEWER_MAX_CHARS:
        raise HumanDecisionError(400, "reviewer must be at most %d characters" % REVIEWER_MAX_CHARS)

    reason = body.get("reason")
    if not isinstance(reason, str):
        raise HumanDecisionError(400, "reason is required and must be a string")
    reason = reason.strip()
    if not reason:
        raise HumanDecisionError(400, "reason is required")
    if len(reason) > REASON_MAX_CHARS:
        raise HumanDecisionError(400, "reason must be at most %d characters" % REASON_MAX_CHARS)

    candidate = _valid_candidate(resolution.get("withheld_candidate"))
    proposed = None if candidate is None else {"action": candidate[0], "amount_sgd": candidate[1]}

    if decision == "approve":
        if "action" in body or "amount_sgd" in body:
            raise HumanDecisionError(400, APPROVE_NO_EXTRAS_MESSAGE)
        if candidate is None:
            raise HumanDecisionError(409, NO_PROPOSAL_MESSAGE)
        action, amount = candidate
        if action == RulingAction.NO_ACTION.value:
            amount = 0.0
        # The ceiling covers the proposal too: the model's amount has no upper bound in
        # its contract, so one click on a held SGD 600 proposal must not pay it.
        if amount > HUMAN_AMOUNT_CEILING_SGD:
            raise HumanDecisionError(400, ABOVE_CEILING_MESSAGE)
    elif decision == "change":
        try:
            parsed = RulingAction.parse(body.get("action"))
        except ContractError:
            raise HumanDecisionError(400, "action must be refund, compensation or no action")
        amount = _finite_number(body.get("amount_sgd"))
        if amount is None:
            raise HumanDecisionError(400, "amount_sgd must be a finite number")
        amount = round(amount, 2)
        if parsed is RulingAction.NO_ACTION:
            if amount != 0.0:
                raise HumanDecisionError(400, "a no-action decision carries no amount")
        elif amount <= 0.0:
            raise HumanDecisionError(400, "the amount must be above SGD 0.00")
        elif amount > HUMAN_AMOUNT_CEILING_SGD:
            raise HumanDecisionError(400, "the amount must be at most SGD 500.00")
        action = parsed.value
    else:  # reject
        if "action" in body or "amount_sgd" in body:
            raise HumanDecisionError(400, "reject takes no action or amount")
        action, amount = RulingAction.NO_ACTION.value, 0.0

    return {
        "schema_version": "1.0",
        "run_id": case_file.get("run_id"),
        "dispute_id": case_file.get("dispute_id"),
        "decision": decision,
        "reviewer": reviewer,
        "reason": reason,
        "action": action,
        "amount_sgd": amount,
        "proposed": proposed,
        "decided_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


# ------------------------------------------------------------------------- storage


def record_decision(run_dir: Path, case_file: Any, body: Any) -> Dict[str, Any]:
    """Validate, then store the decision exactly once and append one event.

    Decide once, atomically: the record is written to a temp file in the run directory
    and hard-linked into place, so of N concurrent requests exactly one wins and the
    file is never empty or partial. A second sequential decision is refused. The
    append-only event is best-effort: if it fails the decision stands, the failure is
    logged to stderr, and the record is still returned.
    """
    record = validate_decision(body, case_file)
    run_dir = Path(run_dir)
    final_path = run_dir / HUMAN_DECISION_FILE_NAME

    handle, tmp_name = tempfile.mkstemp(prefix=".human-decision-", suffix=".tmp", dir=str(run_dir))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(record, indent=2, sort_keys=False, default=str) + "\n")
        try:
            os.link(str(tmp_path), str(final_path))
        except FileExistsError:
            raise HumanDecisionError(409, ALREADY_DECIDED_MESSAGE)
    finally:
        try:
            tmp_path.unlink()
        except OSError:
            pass

    try:
        # Looked up through the module, so a test can patch app.events.append_event.
        events.append_event(
            run_dir,
            record["run_id"],
            EventType.HUMAN_DECISION_RECORDED,
            from_=Actor.HUMAN_REVIEW,
            to=Actor.PARTIES,
            summary="human reviewer %s decided: %s" % (record["reviewer"], record["decision"]),
            payload=record,
        )
    except Exception as exc:  # noqa: BLE001 - the decision stands without the log line
        print(
            "human decision event append failed for run %s: %s" % (record["run_id"], exc),
            file=sys.stderr,
        )
    return record


def load_decision(run_dir: Path) -> Optional[Dict[str, Any]]:
    """The stored decision record, or None. Fails closed on any bad shape or file."""
    path = Path(run_dir) / HUMAN_DECISION_FILE_NAME
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if decision_record_is_valid(data) else None


# -------------------------------------------------------------------- party message


class _CandidateRules:
    """The one field `_cited_rule_titles` reads, so its exact rules are reused."""

    def __init__(self, cited_rule_ids):
        self.cited_rule_ids = cited_rule_ids


def _candidate_titles(withheld_candidate: Any, policy: Any) -> list:
    if policy is None or not isinstance(withheld_candidate, dict):
        return []
    cited = withheld_candidate.get("cited_rule_ids")
    if not isinstance(cited, list):
        return []
    return _cited_rule_titles(_CandidateRules([rid for rid in cited if isinstance(rid, str)]), policy)


def party_message_for_human_decision(record: Dict[str, Any], withheld_candidate: Any, policy: Any) -> str:
    """The party-facing text for a human decision (operator ruling 2026-10-03).

    An approval keeps the AI's Basis line, because the human accepted the proposal and
    its reasoning; a change or a rejection never carries one, because the citations may
    contradict what the person decided. The reviewer's name and reason never appear.
    """
    action = record.get("action") if isinstance(record, dict) else None
    amount = record.get("amount_sgd") if isinstance(record, dict) else None
    decision = record.get("decision") if isinstance(record, dict) else None

    if action == RulingAction.NO_ACTION.value:
        message = "Decision: no action."
    else:
        message = "Decision: %s of SGD %.2f." % (action, amount)
    if decision == "approve":
        titles = _candidate_titles(withheld_candidate, policy)
        if titles:
            message += " Basis: %s." % "; ".join(titles)
    return "%s %s" % (message, HUMAN_REVIEWED_SENTENCE)
