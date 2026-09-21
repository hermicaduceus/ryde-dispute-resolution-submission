"""LLM adapters behind one small interface.

Agent logic never talks to a vendor SDK. It builds an LLMRequest and calls
`LLMClient.complete`. Swapping providers is a one-line change in the factory here,
with no edit to any agent.

Providers:
    mock      deterministic canned responses; proves the plumbing with no API key
    tencent   Tencent Cloud LLM API; concrete service details still to be pinned
              (see the TODO block at the top of tencent.py)
"""

from __future__ import annotations

from .base import LLMClient, LLMContractError, LLMError, LLMRequest, LLMResponse, parse_json_object
from .mock import MockLLMClient
from .tencent import TencentLLMClient

KNOWN_PROVIDERS = ("mock", "tencent")


def build_llm_client(provider: str, **kwargs):
    """Build an LLM client by name.

    kwargs are passed through to the adapter (e.g. settings=..., api_key=... for
    tencent, judge_confidence=... for mock).
    """
    name = (provider or "").strip().lower()
    if name == "mock":
        return MockLLMClient(**kwargs)
    if name == "tencent":
        return TencentLLMClient(**kwargs)
    raise LLMError(
        "unknown LLM provider %r; known providers: %s" % (provider, ", ".join(KNOWN_PROVIDERS))
    )


__all__ = [
    "LLMClient",
    "LLMContractError",
    "LLMError",
    "LLMRequest",
    "LLMResponse",
    "MockLLMClient",
    "TencentLLMClient",
    "KNOWN_PROVIDERS",
    "build_llm_client",
    "parse_json_object",
]
