"""Typed schema of the Evidence Pack.

The Evidence Pack is the only place quantitative facts about a dispute exist. Every
number an agent may rely on is computed here, by deterministic Python, from the raw
dispute record. Agents cite pack fields by dotted reference and never do arithmetic
themselves — `field_refs()` is the list of legal citations and `value_at()` resolves one.

Field names are part of the agent-facing contract: renaming one changes what advocates
and the Judge can cite, so treat this file as a schema, not an implementation detail.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

#: Bumped whenever the pack's shape changes, including purely additive changes — the
#: same doctrine the event log states. A consumer holding two packs must be able to tell
#: them apart by this string alone, and "the new field is simply absent" is not a signal
#: it can distinguish from "the field was null in that case".
#: 1.1 added service_type, the filing block, and the cancellation matching anchor.
#: 1.2 added cancellation.case_policy and profiles.*.fraud_flags.
EVIDENCE_SCHEMA_VERSION = "1.2"

# Keys that are provenance rather than evidence: an agent citing them would be citing
# metadata, not a fact about the trip. Excluded from field_refs().
_NON_CITABLE_KEYS = frozenset(
    {
        "schema_version",
        "dispute_id",
        "category",
        "generated_at",
        "trip_id",
        "rider_id",
        "driver_id",
        "party_id",
        "party",
        "role",
        "notes",
        "method",
    }
)


@dataclass(frozen=True)
class RouteEvidence:
    """Route deviation: how far the trip actually went versus the expected route."""

    actual_distance_km: Optional[float]
    estimated_distance_km: Optional[float]
    deviation_km: Optional[float]
    deviation_pct: Optional[float]
    point_count: int
    first_point_ts: Optional[str] = None
    last_point_ts: Optional[str] = None
    method: str = "haversine over consecutive GPS points"


@dataclass(frozen=True)
class DurationEvidence:
    """Trip duration against the estimate."""

    actual_minutes: Optional[float]
    estimated_minutes: Optional[float]
    delta_minutes: Optional[float]
    delta_pct: Optional[float]


@dataclass(frozen=True)
class FareEvidence:
    """Fare recomputation from the recorded breakdown and tariff rates.

    recomputed_sgd                    what the trip as actually driven should have cost
    recomputed_estimated_route_sgd    what the expected route would have cost
    deviation_fare_delta_sgd          the difference between those two
    difference_sgd                    charged minus recomputed (positive = overcharged)
    breakdown_consistent              do the recorded components add up to the charge
    """

    charged_sgd: Optional[float]
    recomputed_sgd: Optional[float]
    recomputed_estimated_route_sgd: Optional[float]
    deviation_fare_delta_sgd: Optional[float]
    difference_sgd: Optional[float]
    difference_pct: Optional[float]
    component_sum_sgd: Optional[float]
    breakdown_consistent: Optional[bool]
    components_sgd: Dict[str, float] = field(default_factory=dict)
    rates: Dict[str, float] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class CancellationEvidence:
    """No-show charge: the timestamps and positions that decide whether the driver showed.

    The pack reports the numbers only. Whether a wait was long enough, or a driver was
    close enough, is a policy question and is decided by the policy document — never here.
    """

    driver_arrived_at: Optional[str]
    wait_started_at: Optional[str]
    cancelled_at: Optional[str]
    driver_wait_minutes: Optional[float]
    arrival_to_cancel_minutes: Optional[float]
    matching_to_cancel_minutes: Optional[float]
    driver_marked_no_show: Optional[bool]
    rider_claims_driver_absent: Optional[bool]
    driver_distance_from_pickup_m: Optional[float]
    cancellation_fee_sgd: Optional[float]
    #: Which timestamp matching_to_cancel_minutes was measured from, and its source key.
    #: Named so the Judge can see when the interval rests on booking time as a proxy
    #: rather than on a real matching event.
    matching_anchor_at: Optional[str] = None
    matching_anchor_source: Optional[str] = None
    #: The cancellation terms that govern this case, as the record states them (the
    #: organisers' pack carries 5 / 8 minute terms on their sample, Ryde's own 3-minute
    #: terms elsewhere). Passed through untouched, never merged with or checked against
    #: docs/policy.md: which document governs is the Judge's call, not this layer's.
    case_policy: Optional[Dict[str, Any]] = None
    notes: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class FilingEvidence:
    """When the dispute was filed relative to the trip.

    Exists because the policy's filing window (GEN-6) is decisive but was previously
    inexpressible: the Judge may only cite pack fields and may not do arithmetic, so a
    rule about elapsed days needs the days computed here or it can never be applied.
    """

    filed_at: Optional[str]
    trip_reference_at: Optional[str]
    days_since_trip: Optional[float]
    window_established: bool
    notes: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class ChatSignalEvidence:
    """Deterministic keyword signals from the trip chat log.

    This is a lexicon count, not a trained sentiment model. It is labelled as such so
    nobody reads more into it than it is.
    """

    message_count: int
    rider_messages: int
    driver_messages: int
    negative_messages: int
    positive_messages: int
    negative_messages_by_party: Dict[str, int] = field(default_factory=dict)
    agreement_markers: int = 0
    disagreement_markers: int = 0
    threat_markers: int = 0
    first_message_at: Optional[str] = None
    last_message_at: Optional[str] = None
    method: str = "lexicon-v1 keyword counts (deterministic heuristic, not a model)"


@dataclass(frozen=True)
class PartyProfile:
    """Historical behaviour profile for one party. Pass-through plus derived rates."""

    party_id: Optional[str]
    party: str
    account_age_days: Optional[int]
    trips_completed: Optional[int]
    disputes_total: Optional[int]
    disputes_upheld: Optional[int]
    upheld_rate: Optional[float]
    dispute_rate: Optional[float]
    rating: Optional[float]
    #: Platform fraud flags against the party, when the record carries them. None means
    #: the record does not say, which is not the same as zero — an agent may not read
    #: silence as a clean record.
    fraud_flags: Optional[int] = None


@dataclass(frozen=True)
class ProfileEvidence:
    rider: Optional[PartyProfile]
    driver: Optional[PartyProfile]
    notes: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class EvidencePack:
    """Everything an agent is allowed to treat as fact about one dispute."""

    schema_version: str
    dispute_id: str
    category: str
    generated_at: str
    trip_id: Optional[str]
    rider_id: Optional[str]
    driver_id: Optional[str]
    service_type: Optional[str]
    route: Optional[RouteEvidence]
    duration: Optional[DurationEvidence]
    fare: Optional[FareEvidence]
    cancellation: Optional[CancellationEvidence]
    chat: ChatSignalEvidence
    profiles: Optional[ProfileEvidence]
    filing: Optional[FilingEvidence] = None
    notes: List[str] = field(default_factory=list)

    # ------------------------------------------------------------------ serialisation

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    # --------------------------------------------------------------- citation surface

    def field_refs(self) -> List[str]:
        """Every legal citation, as dotted paths to the pack's computed scalars."""
        refs: List[str] = []
        _collect_refs(self.to_dict(), "", refs)
        return sorted(refs)

    def value_at(self, ref: str) -> Any:
        """Resolve a dotted reference. Raises KeyError with the legal refs listed."""
        node: Any = self.to_dict()
        for part in ref.split("."):
            if isinstance(node, dict) and part in node:
                node = node[part]
            elif isinstance(node, list) and part.isdigit() and int(part) < len(node):
                node = node[int(part)]
            else:
                raise KeyError(
                    "no evidence field %r in the pack for dispute %s" % (ref, self.dispute_id)
                )
        return node


def _collect_refs(node: Any, prefix: str, out: List[str]) -> None:
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
