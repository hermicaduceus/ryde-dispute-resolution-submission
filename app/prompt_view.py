"""What each agent was asked: the prompts a run actually sent, rebuilt from its payloads.

The console shows the parties' claims, the computed evidence and the disposition, but not
the question the agents were answering. This module reconstructs that question without
touching a model and without writing anything: the run's own stored payloads
(dispute.filed, evidence.pack_built, the advocate.case_submitted payloads and the Judge's
ruling payload) are fed back through the UNCHANGED builders, and the rebuilt
``LLMRequest.fingerprint()`` is compared with the fingerprint the run recorded.

A payload is found by event type and sender, never by sequence number: a needs_info stop
writes the driver's case as payload 0008, not 0007, because the rider's follow-up request
sits between them.

Statuses:

    match        the rebuilt prompts hash to the fingerprint the run recorded
    changed      both fingerprints exist and differ (the prompts shown are today's)
    not_called   the agent never ran: no Evidence Pack was built (out-of-scope routing),
                 or the Judge was never reached (a needs_info stop before deliberation)
    unavailable  a payload the rebuild or the recorded fingerprint needs is missing,
                 corrupt or not an object

The module is read-only by construction: it never calls a model and never writes to disk.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .agents.base import HARD_RULES
from .agents.driver_advocate import DriverAdvocate
from .agents.judge import Judge
from .agents.rider_advocate import RiderAdvocate
from .dispute import Dispute, parse_dispute
from .events import EventType
from .evidence.schema import _NON_CITABLE_KEYS
from .llm.base import LLMRequest

#: Contract order: the two advocates, then the Judge.
AGENT_ORDER: Tuple[str, ...] = ("rider_advocate", "driver_advocate", "judge")

AGENT_LABELS = {
    "rider_advocate": "Rider Advocate",
    "driver_advocate": "Driver Advocate",
    "judge": "Judge",
}

AGENT_ROLES = {
    "rider_advocate": "Argues the rider's side from the Evidence Pack and the policy.",
    "driver_advocate": "Argues the driver's side from the Evidence Pack and the policy.",
    "judge": (
        "Weighs both cases and issues one ruling. Python gates decide whether it reaches "
        "the parties."
    ),
}

AGENT_CLASSES = {
    "rider_advocate": RiderAdvocate,
    "driver_advocate": DriverAdvocate,
    "judge": Judge,
}

POLICY_SOURCE = "docs/policy.md"

STATUS_MATCH = "match"
STATUS_CHANGED = "changed"
STATUS_NOT_CALLED = "not_called"
STATUS_UNAVAILABLE = "unavailable"

#: The top-level pack sections the summary names, in the pack's own order.
_EVIDENCE_SECTIONS = frozenset(
    {"route", "duration", "fare", "cancellation", "chat", "profiles", "filing"}
)

_EVENTS_FILENAME = "events.jsonl"

_RULE_LINE_RE = re.compile(r"^\d+\.\s")


def _hard_rule_lines(text: str) -> List[str]:
    """The numbered rules of HARD_RULES, each joined to one line with single spaces."""
    lines: List[str] = []
    current: Optional[str] = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line == "HARD RULES":
            continue
        if _RULE_LINE_RE.match(line):
            if current is not None:
                lines.append(current)
            current = line
        elif current is not None:
            current = "%s %s" % (current, line)
    if current is not None:
        lines.append(current)
    return lines


_HARD_RULE_LINES = _hard_rule_lines(HARD_RULES)


class _PackView:
    """A read-only stand-in for EvidencePack, backed by the stored pack payload."""

    def __init__(self, data: Dict[str, Any]):
        self._data = data

    def to_dict(self) -> Dict[str, Any]:
        return self._data

    def field_refs(self) -> List[str]:
        """Every legal citation, with the same walk EvidencePack.field_refs uses."""
        refs: List[str] = []
        _collect_refs(self._data, "", refs)
        return sorted(refs)


class _CaseView:
    """A read-only stand-in for AdvocateCase, backed by the stored case payload."""

    def __init__(self, data: Dict[str, Any]):
        self._data = data

    def to_dict(self) -> Dict[str, Any]:
        return self._data


def _collect_refs(node: Any, prefix: str, out: List[str]) -> None:
    """Mirror of app.evidence.schema._collect_refs over the stored pack dict."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key in _NON_CITABLE_KEYS:
                continue
            _collect_refs(value, "%s.%s" % (prefix, key) if prefix else key, out)
        return
    if isinstance(node, list):
        for index, value in enumerate(node):
            _collect_refs(value, "%s.%d" % (prefix, index), out)
        return
    if node is None:
        return
    out.append(prefix)


def _read_events(run_path: Path) -> Tuple[List[Dict[str, Any]], bool]:
    """(events, readable). A missing or corrupt log reads as no events, never raising."""
    try:
        text = (run_path / _EVENTS_FILENAME).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return [], False
    events: List[Dict[str, Any]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, RecursionError):
            return [], False
        if not isinstance(event, dict):
            return [], False
        events.append(event)
    return events, True


def _first_event(
    events: List[Dict[str, Any]], event_type: str, sender: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """The first event of this type (and sender), in log order."""
    for event in events:
        if event.get("type") == event_type and (sender is None or event.get("from") == sender):
            return event
    return None


def _read_payload(run_path: Path, event: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The JSON object an event points at, or None when it is missing, unreadable, not an
    object, or points outside the run directory."""
    if not isinstance(event, dict):
        return None
    ref = event.get("payload_ref")
    if not isinstance(ref, str) or not ref:
        return None
    try:
        path = (run_path / ref).resolve()
        if not path.is_relative_to(run_path.resolve()) or not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        return None
    return data if isinstance(data, dict) else None


def _parse_dispute_safely(data: Optional[Dict[str, Any]]) -> Optional[Dispute]:
    if not isinstance(data, dict):
        return None
    try:
        return parse_dispute(data)
    except Exception:  # a payload the parser cannot accept is 'unavailable', never a 500
        return None


def _fingerprint_from_llm(block: Dict[str, Any]) -> Optional[str]:
    llm = block.get("llm")
    if not isinstance(llm, dict):
        return None
    value = llm.get("request_fingerprint")
    return value if isinstance(value, str) and value else None


def _case_fingerprint(data: Optional[Dict[str, Any]]) -> Optional[str]:
    if not isinstance(data, dict):
        return None
    return _fingerprint_from_llm(data)


def _ruling_fingerprint(
    payload: Optional[Dict[str, Any]], event_type: str
) -> Optional[str]:
    """The Judge's recorded fingerprint, from the block its ruling event carries."""
    if not isinstance(payload, dict):
        return None
    key = "ruling" if event_type == EventType.JUDGE_RULING_ISSUED else "withheld_candidate"
    block = payload.get(key)
    if not isinstance(block, dict):
        return None
    return _fingerprint_from_llm(block)


def _rule_count(policy: Any) -> int:
    try:
        return len(policy.rule_ids())
    except Exception:
        return 0


def _case_facts(
    dispute: Optional[Dispute], pack_data: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    sections: List[str] = []
    citable = 0
    try:
        if isinstance(pack_data, dict):
            for key, value in pack_data.items():
                if key in _EVIDENCE_SECTIONS and value is not None:
                    sections.append(key)
            citable = len(_PackView(pack_data).field_refs())
    except Exception:
        sections, citable = [], 0
    return {
        "evidence_sections": sections,
        "citable_refs": citable,
        "form_answers": len(dispute.intake) if dispute is not None else 0,
        "claim_amount_sgd": dispute.claim_amount_sgd if dispute is not None else None,
    }


def _position(side: str, case_data: Dict[str, Any]) -> Dict[str, Any]:
    outcome = case_data.get("requested_outcome")
    amount = case_data.get("requested_amount_sgd")
    return {
        "side": side,
        "outcome": outcome if isinstance(outcome, str) else None,
        "amount_sgd": amount
        if isinstance(amount, (int, float)) and not isinstance(amount, bool)
        else None,
    }


def _advocate_positions(cases: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
    rider = cases.get("rider_advocate")
    driver = cases.get("driver_advocate")
    if not isinstance(rider, dict) or not isinstance(driver, dict):
        return None
    return [_position("rider", rider), _position("driver", driver)]


def _summary(
    agent: str,
    policy: Any,
    dispute: Optional[Dispute],
    pack_data: Optional[Dict[str, Any]],
    cases: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "role": AGENT_ROLES[agent],
        "hard_rules": _HARD_RULE_LINES,
        "case_facts": _case_facts(dispute, pack_data),
        "advocate_positions": _advocate_positions(cases) if agent == "judge" else None,
        "policy": {"rule_count": _rule_count(policy), "source": POLICY_SOURCE},
        "asked_to_return": list(AGENT_CLASSES[agent].OUTPUT_SCHEMA.keys()),
    }


def _entry(
    agent: str,
    status: str,
    recorded: Optional[str],
    rebuilt: Optional[str],
    system_prompt: Optional[str],
    user_prompt: Optional[str],
    summary: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "agent": agent,
        "label": AGENT_LABELS[agent],
        "status": status,
        "recorded_fingerprint": recorded,
        "rebuilt_fingerprint": rebuilt,
        "summary": summary,
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
    }


def _rebuild(
    agent: str,
    policy: Any,
    dispute: Dispute,
    pack_data: Dict[str, Any],
    cases: Dict[str, Any],
) -> Tuple[str, str]:
    """The prompts the unchanged builders produce for this run today."""
    if agent == "judge":
        judge = Judge(llm=None, events=None, policy=policy)
        system = judge.system_prompt()
        user = judge.user_prompt(
            dispute,
            _PackView(pack_data),
            _CaseView(cases["rider_advocate"]),
            _CaseView(cases["driver_advocate"]),
        )
        return system, user
    advocate = AGENT_CLASSES[agent](llm=None, events=None, policy=policy)
    system = advocate.system_prompt()
    user = advocate.user_prompt(dispute, _PackView(pack_data))
    return system, user


def build_prompt_view(run_dir: Path, policy: Any) -> Dict[str, Any]:
    """Rebuild the three agents' prompts for one run, and compare fingerprints.

    Never calls a model, never writes, and never raises: a payload that cannot be read
    degrades to 'unavailable' rather than an error.
    """
    run_path = Path(run_dir)
    run_id = run_path.name

    events, events_readable = _read_events(run_path)

    pack_event = _first_event(events, EventType.EVIDENCE_PACK_BUILT)
    pack_data = _read_payload(run_path, pack_event)

    dispute = _parse_dispute_safely(
        _read_payload(run_path, _first_event(events, EventType.DISPUTE_FILED))
    )

    ruling_event = _first_event(events, EventType.JUDGE_RULING_ISSUED)
    ruling_type = EventType.JUDGE_RULING_ISSUED
    if ruling_event is None:
        ruling_event = _first_event(events, EventType.JUDGE_RULING_WITHHELD)
        ruling_type = EventType.JUDGE_RULING_WITHHELD
    judge_recorded = _ruling_fingerprint(_read_payload(run_path, ruling_event), ruling_type)

    cases: Dict[str, Any] = {}
    for name in ("rider_advocate", "driver_advocate"):
        cases[name] = _read_payload(
            run_path, _first_event(events, EventType.ADVOCATE_CASE_SUBMITTED, name)
        )

    deliberation = _first_event(events, EventType.JUDGE_DELIBERATION_STARTED)

    if not events_readable:
        shared: Optional[str] = STATUS_UNAVAILABLE
    elif pack_event is None:
        shared = STATUS_NOT_CALLED
    elif pack_data is None or dispute is None:
        shared = STATUS_UNAVAILABLE
    else:
        shared = None

    entries: List[Dict[str, Any]] = []
    for name in AGENT_ORDER:
        summary = _summary(name, policy, dispute, pack_data, cases)
        if shared is not None:
            entries.append(_entry(name, shared, None, None, None, None, summary))
            continue

        recorded: Optional[str] = None
        try:
            if name == "judge":
                if deliberation is None:
                    entries.append(
                        _entry(name, STATUS_NOT_CALLED, None, None, None, None, summary)
                    )
                    continue
                recorded = judge_recorded
                if (
                    cases["rider_advocate"] is None
                    or cases["driver_advocate"] is None
                    or recorded is None
                ):
                    entries.append(
                        _entry(name, STATUS_UNAVAILABLE, recorded, None, None, None, summary)
                    )
                    continue
            else:
                recorded = _case_fingerprint(cases[name])
                if cases[name] is None or recorded is None:
                    entries.append(
                        _entry(name, STATUS_UNAVAILABLE, recorded, None, None, None, summary)
                    )
                    continue
            system, user = _rebuild(name, policy, dispute, pack_data, cases)
            rebuilt = LLMRequest(
                agent=name, system_prompt=system, user_prompt=user
            ).fingerprint()
        except Exception:  # a rebuild that cannot be done is 'unavailable', never a 500
            entries.append(_entry(name, STATUS_UNAVAILABLE, recorded, None, None, None, summary))
            continue
        status = STATUS_MATCH if rebuilt == recorded else STATUS_CHANGED
        entries.append(_entry(name, status, recorded, rebuilt, system, user, summary))

    return {"run_id": run_id, "agents": entries}
