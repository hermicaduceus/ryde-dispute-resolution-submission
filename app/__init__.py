"""Ryde — multi-agent autonomous dispute resolution (backend).

Three agents (Rider Advocate, Driver Advocate, Judge), a deterministic evidence
layer, and an append-only event log that makes the inter-agent traffic observable.

Layout:
    config.py        runtime settings (confidence threshold, LLM provider)
    events.py        append-only structured event log
    evidence/        deterministic Evidence Pack (all arithmetic lives here)
    llm/             thin LLM adapters behind one interface (mock + Tencent)
    agents/          the three agents and their LLM-call contracts
    schemas.py       frozen output contracts (Judge ruling, advocate case)
    policy.py        loads the swappable policy document (docs/policy.md)
    pipeline.py      end-to-end orchestration for one dispute
    cli.py           command-line entry point

Standard library only. No third-party runtime dependency.
"""

__version__ = "0.1.0"
