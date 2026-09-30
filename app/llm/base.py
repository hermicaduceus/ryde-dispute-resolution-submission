"""The LLM interface every adapter implements, plus JSON-response parsing.

One method: `complete(request) -> LLMResponse`. That is the whole contract, so an
adapter can be swapped without touching agent logic.
"""

from __future__ import annotations

import abc
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


class LLMError(RuntimeError):
    """The provider could not be reached, is misconfigured, or returned an error."""


class LLMTransientError(LLMError):
    """The provider failure may clear when the same call is tried again."""


class LLMContractError(LLMError):
    """The provider responded, but not with the JSON object the agent contract requires."""


@dataclass(frozen=True)
class LLMRequest:
    """One prompt to one agent.

    agent            which agent is asking ("rider_advocate", "driver_advocate", "judge")
    system_prompt    role, output contract and hard rules
    user_prompt      the case material: dispute intake, Evidence Pack, policy document
    metadata         adapter-facing hints. Real adapters ignore it; the mock uses it to
                     build deterministic responses. Never carries anything that is not
                     already in the prompts.
    """

    agent: str
    system_prompt: str
    user_prompt: str
    expect_json: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)
    timeout_seconds: Optional[float] = None

    def fingerprint(self) -> str:
        """Stable hash of the prompts — recorded with the case so a run is reproducible."""
        digest = hashlib.sha256()
        digest.update(self.agent.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(self.system_prompt.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(self.user_prompt.encode("utf-8"))
        return digest.hexdigest()[:16]


@dataclass(frozen=True)
class LLMResponse:
    """What came back, plus enough provenance to log it honestly."""

    text: str
    provider: str
    model: str
    usage: Dict[str, Any] = field(default_factory=dict)
    finish_reason: Optional[str] = None

    def as_log_fields(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "usage": self.usage,
            "finish_reason": self.finish_reason,
        }


class LLMClient(abc.ABC):
    """Interface every LLM adapter implements."""

    provider_name = "unknown"

    @abc.abstractmethod
    def complete(self, request: LLMRequest) -> LLMResponse:
        """Run one prompt. Raises LLMError on transport/config failure."""
        raise NotImplementedError


def parse_json_object(text: str, *, agent: str) -> Dict[str, Any]:
    """Parse the JSON object an agent contract requires out of a model response.

    Tolerates the two things models actually do: wrapping the object in a ```json
    fence, and adding a sentence before or after it. Anything else is a hard failure —
    a malformed response must never be silently repaired into a ruling.
    """
    if not isinstance(text, str) or not text.strip():
        raise LLMContractError("%s: model returned an empty response" % agent)

    candidate = text.strip()

    # Strip a fenced code block if the whole response is wrapped in one.
    if candidate.startswith("```"):
        body = candidate.split("\n", 1)[1] if "\n" in candidate else ""
        if body.rstrip().endswith("```"):
            body = body.rstrip()[: -len("```")]
        candidate = body.strip()

    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise LLMContractError(
                "%s: no JSON object found in model response: %r" % (agent, text[:400])
            )
        try:
            parsed = json.loads(candidate[start : end + 1])
        except json.JSONDecodeError as exc:
            raise LLMContractError(
                "%s: model response is not valid JSON (%s): %r" % (agent, exc, text[:400])
            ) from exc

    if not isinstance(parsed, dict):
        raise LLMContractError(
            "%s: expected a JSON object, got %s" % (agent, type(parsed).__name__)
        )
    return parsed
