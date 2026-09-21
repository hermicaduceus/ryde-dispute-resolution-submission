"""Deterministic evidence layer.

`build_evidence_pack(dispute)` turns a raw dispute record into the typed Evidence Pack
that every agent reads. All arithmetic in the system happens here.
"""

from __future__ import annotations

from .compute import EvidenceInputError, build_evidence_pack, haversine_km
from .schema import (
    EVIDENCE_SCHEMA_VERSION,
    CancellationEvidence,
    ChatSignalEvidence,
    DurationEvidence,
    EvidencePack,
    FareEvidence,
    PartyProfile,
    ProfileEvidence,
    RouteEvidence,
)

__all__ = [
    "EVIDENCE_SCHEMA_VERSION",
    "CancellationEvidence",
    "ChatSignalEvidence",
    "DurationEvidence",
    "EvidenceInputError",
    "EvidencePack",
    "FareEvidence",
    "PartyProfile",
    "ProfileEvidence",
    "RouteEvidence",
    "build_evidence_pack",
    "haversine_km",
]
