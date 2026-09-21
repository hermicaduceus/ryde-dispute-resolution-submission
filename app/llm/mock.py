"""Deterministic mock LLM — proves the pipeline plumbing with no API key.

This is NOT a model. It is a mechanical stand-in that returns responses shaped exactly
like the agent contracts, so the pipeline, the event stream and the tests can be
exercised before a real Tencent endpoint is pinned. Every string it returns is prefixed
"MOCK" so a mock run can never be mistaken for a real ruling.

It is deterministic on purpose: same dispute in, byte-identical case file out, which is
what makes the end-to-end test meaningful.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from .base import LLMClient, LLMError, LLMRequest, LLMResponse

MOCK_MARKER = "MOCK"


def _pick(items: Any, count: int) -> List[Any]:
    if not isinstance(items, list):
        return []
    return items[:count]


class MockLLMClient(LLMClient):
    """Returns contract-shaped canned responses.

    judge_confidence is configurable so tests can drive the pipeline through the
    low-confidence gate (below threshold -> no ruling, neutral message to the parties).
    """

    provider_name = "mock"

    def __init__(self, judge_confidence: float = 0.86, model: str = "mock-llm-v0", **_ignored: Any):
        if not 0.0 <= float(judge_confidence) <= 1.0:
            raise LLMError("mock judge_confidence must be between 0 and 1")
        self.judge_confidence = float(judge_confidence)
        self.model = model
        self.calls: List[LLMRequest] = []

    # ------------------------------------------------------------------ interface

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.calls.append(request)
        builder = {
            "rider_advocate": self._advocate_response,
            "driver_advocate": self._advocate_response,
            "judge": self._judge_response,
        }.get(request.agent)
        if builder is None:
            raise LLMError("mock has no canned response for agent %r" % request.agent)

        payload = builder(request)
        return LLMResponse(
            text=json.dumps(payload, indent=2),
            provider=self.provider_name,
            model=self.model,
            usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "mocked": True},
            finish_reason="mock",
        )

    # ------------------------------------------------------------------- builders

    def _advocate_response(self, request: LLMRequest) -> Dict[str, Any]:
        meta = request.metadata
        party = str(meta.get("party") or "rider")
        dispute_id = str(meta.get("dispute_id") or "unknown")
        category = str(meta.get("category") or "unknown")
        refs = _pick(meta.get("available_evidence_refs"), 3)
        rule_ids = _pick(meta.get("available_rule_ids"), 2)
        claim_amount = float(meta.get("claim_amount_sgd") or 0.0)

        if party == "rider":
            requested_outcome = "refund"
            requested_amount = claim_amount
        else:
            requested_outcome = "no action"
            requested_amount = 0.0

        cited = ", ".join(refs) if refs else "no evidence fields available"
        return {
            "claim_summary": (
                "%s Advocate %s case for dispute %s (%s)."
                % (MOCK_MARKER, party, dispute_id, category)
            ),
            "evidence_cited": refs,
            "policy_rule_ids": rule_ids,
            "argument": (
                "%s deterministic stand-in for the %s Advocate. It cites the evidence "
                "pack fields it was given (%s) and the policy rules it was given (%s). "
                "No arithmetic is performed here: every number is read from the pack."
                % (MOCK_MARKER, party, cited, ", ".join(rule_ids) or "none")
            ),
            "requested_outcome": requested_outcome,
            "requested_amount_sgd": requested_amount,
            "follow_up_questions": [],
        }

    def _judge_response(self, request: LLMRequest) -> Dict[str, Any]:
        meta = request.metadata
        rule_ids = _pick(meta.get("available_rule_ids"), 2)
        claim_amount = float(meta.get("claim_amount_sgd") or 0.0)

        if claim_amount > 0.0:
            action = "refund"
            amount = claim_amount
        else:
            action = "no action"
            amount = 0.0

        return {
            "action": action,
            "recommended_amount_sgd": amount,
            "confidence": self.judge_confidence,
            "explanation": (
                "%s deterministic stand-in for the Judge. It weighs the two advocate cases "
                "it was given and applies the policy rules it was given (%s). The amount is "
                "read from the evidence pack, not computed here."
                % (MOCK_MARKER, ", ".join(rule_ids) or "none")
            ),
            "cited_rule_ids": rule_ids,
        }
