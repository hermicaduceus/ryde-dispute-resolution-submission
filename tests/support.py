"""Shared test helpers. Non-app: nothing under app/ imports this."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from app.dispute import Dispute, load_dispute
from app.events import EventLog
from app.llm import LLMClient, LLMError, LLMRequest, LLMResponse
from app.pipeline import CaseFile, run_dispute
from app.policy import PolicySet, load_policy

FIXTURES = Path(__file__).resolve().parent / "fixtures"
POLICY_FIXTURE = FIXTURES / "policy_min.md"

ROUTE_DEVIATION = "dispute_route_deviation.json"
NO_SHOW = "dispute_no_show_charge.json"
OUT_OF_SCOPE = "dispute_out_of_scope_category.json"

DEFAULT_THRESHOLD = 0.65


class ScriptedLLM(LLMClient):
    """An LLM client that returns exactly what a test tells it to, per agent.

    Used to drive the pipeline into states the mock will not produce on its own: invented
    citations, out-of-range confidence, malformed JSON.
    """

    provider_name = "scripted"

    def __init__(self, by_agent: Dict[str, Any]):
        self.by_agent = by_agent
        self.calls = []

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.calls.append(request)
        if request.agent not in self.by_agent:
            raise LLMError("no scripted response for agent %r" % request.agent)
        payload = self.by_agent[request.agent]
        if callable(payload):
            payload = payload(request)
        text = payload if isinstance(payload, str) else json.dumps(payload)
        return LLMResponse(text=text, provider=self.provider_name, model="scripted-v0")


def load_fixture_dispute(name: str) -> Dispute:
    return load_dispute(FIXTURES / name)


def load_fixture_policy() -> PolicySet:
    return load_policy(POLICY_FIXTURE)


def run_fixture(
    name: str,
    run_dir: Path,
    *,
    llm: Optional[LLMClient] = None,
    threshold: float = DEFAULT_THRESHOLD,
    run_id: str = "test-run",
) -> CaseFile:
    """Run one fixture dispute through the pipeline, writing artifacts into run_dir."""
    events = EventLog(run_dir, run_id)
    return run_dispute(
        dispute=load_fixture_dispute(name),
        llm=llm if llm is not None else _default_mock(),
        policy=load_fixture_policy(),
        events=events,
        confidence_threshold=threshold,
    )


def _default_mock() -> LLMClient:
    from app.llm import MockLLMClient

    return MockLLMClient()


def event_types(case_file: CaseFile):
    return [event["type"] for event in case_file.events]


def events_by_type(case_file: CaseFile, event_type: str):
    return [event for event in case_file.events if event["type"] == event_type]
