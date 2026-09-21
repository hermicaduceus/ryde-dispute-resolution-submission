"""The dispute record: what the intake form submits, and how it is routed.

Input contract for the pipeline (and for the swappable corpus in data/):

{
  "dispute_id": "RD-0001",                    required, string
  "category": "route_deviation",              required; see routing below
  "filed_by": "rider",                        "rider" | "driver"
  "filed_at": "2026-09-20T09:15:00+08:00",
  "claim":  {"text": "...", "amount_sgd": 6.40},
  "intake": {"<form question>": "<answer>"},  raw intake-form answers, pass-through
  "trip": {
     "trip_id": "T-1", "rider_id": "r-1", "driver_id": "d-1",
     "requested_at"/"pickup_at"/"dropoff_at": ISO-8601,
     "estimated_duration_min": 18, "estimated_distance_km": 7.2,
     "actual_distance_km": 9.4,               optional; else derived from actual_route
     "actual_route": [{"lat": 1.3, "lng": 103.8, "t": "..."}, ...],
     "fare": {
        "charged_sgd": 14.80,
        "breakdown": {"base_sgd": 3.20, "distance_sgd": 7.10, "time_sgd": 2.30,
                      "surge_sgd": 1.20, "promo_sgd": 1.00, "platform_fee_sgd": 0.80},
        "rates": {"base_sgd": 3.20, "per_km_sgd": 0.80, "per_min_sgd": 0.25,
                  "surge_multiplier": 1.2}
     }
  },
  "cancellation": {
     "driver_arrived_at": "...", "wait_started_at": "...", "cancelled_at": "...",
     "driver_wait_minutes": 5.5, "cancellation_fee_sgd": 4.00,
     "driver_marked_no_show": true, "rider_claims_driver_absent": true,
     "driver_gps_at_arrival": {"lat": .., "lng": ..}, "pickup_point": {"lat": .., "lng": ..}
  },
  "chat_log": [{"t": "...", "sender": "rider", "text": "..."}, ...],
  "profiles": {"rider": {...}, "driver": {...}}
}

Everything except dispute_id and category is optional; missing blocks produce an
Evidence Pack with null fields and an explanatory note, rather than a guess.

Routing: only the two locked categories reach the agents. Anything else — including the
form's "other" option, the statement's out-of-scope categories, and any value the corpus
does not use — goes to the human-review queue with a neutral message.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

CATEGORY_ROUTE_DEVIATION = "route_deviation"
CATEGORY_NO_SHOW_CHARGE = "no_show_charge"
CATEGORY_OTHER = "other"

#: Categories the three agents handle end to end. Nothing else, by locked scope.
AGENT_CATEGORIES = (CATEGORY_ROUTE_DEVIATION, CATEGORY_NO_SHOW_CHARGE)

_ALIASES = {
    "route_deviation": CATEGORY_ROUTE_DEVIATION,
    "route_deviation_claim": CATEGORY_ROUTE_DEVIATION,
    "deviation": CATEGORY_ROUTE_DEVIATION,
    "longer_route": CATEGORY_ROUTE_DEVIATION,
    "no_show_charge": CATEGORY_NO_SHOW_CHARGE,
    "no_show": CATEGORY_NO_SHOW_CHARGE,
    "noshow": CATEGORY_NO_SHOW_CHARGE,
    "no_show_fee": CATEGORY_NO_SHOW_CHARGE,
    "cancellation_fee": CATEGORY_NO_SHOW_CHARGE,
    "other": CATEGORY_OTHER,
    "property_damage": CATEGORY_OTHER,
    "property_damage_mess": CATEGORY_OTHER,
    "safety_incident": CATEGORY_OTHER,
}


class DisputeError(ValueError):
    """The submitted dispute record is not usable."""


def normalise_category(value: Any) -> str:
    """Map a submitted category onto one of the three routing buckets.

    Unknown values route to `other` (human review) rather than raising: the system must
    never let an unrecognised category reach an agent that was not scoped to handle it.
    """
    if not isinstance(value, str) or not value.strip():
        raise DisputeError("dispute category is required and must be a non-empty string")
    key = value.strip().lower().replace("-", "_").replace(" ", "_")
    return _ALIASES.get(key, CATEGORY_OTHER)


@dataclass(frozen=True)
class Dispute:
    """One filed dispute, parsed and routed."""

    dispute_id: str
    category: str
    category_as_submitted: str
    filed_by: str
    filed_at: Optional[str]
    claim: Dict[str, Any] = field(default_factory=dict)
    intake: Dict[str, Any] = field(default_factory=dict)
    trip: Dict[str, Any] = field(default_factory=dict)
    cancellation: Dict[str, Any] = field(default_factory=dict)
    chat_log: List[Dict[str, Any]] = field(default_factory=list)
    profiles: Dict[str, Any] = field(default_factory=dict)
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_agent_handled(self) -> bool:
        """True only for the two locked categories. Everything else goes to a human."""
        return self.category in AGENT_CATEGORIES

    @property
    def claim_text(self) -> str:
        text = self.claim.get("text")
        return text.strip() if isinstance(text, str) else ""

    @property
    def claim_amount_sgd(self) -> float:
        """The amount the filing party asked for, 0.0 when not stated."""
        amount = self.claim.get("amount_sgd")
        if isinstance(amount, bool) or not isinstance(amount, (int, float)):
            return 0.0
        return float(amount)

    def to_dict(self) -> Dict[str, Any]:
        return self.raw


def _mapping(value: Any, key: str, default: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if value is None:
        return dict(default or {})
    if not isinstance(value, dict):
        raise DisputeError("dispute field '%s' must be an object" % key)
    return value


def parse_dispute(data: Any) -> Dispute:
    """Validate a raw dispute dict into a Dispute. Raises DisputeError with the reason."""
    if not isinstance(data, dict):
        raise DisputeError("a dispute record must be a JSON object")

    dispute_id = data.get("dispute_id")
    if not isinstance(dispute_id, str) or not dispute_id.strip():
        raise DisputeError("dispute_id is required and must be a non-empty string")

    submitted_category = data.get("category")
    category = normalise_category(submitted_category)

    filed_by = data.get("filed_by") or "rider"
    if filed_by not in ("rider", "driver"):
        filed_by = "rider"

    chat_log = data.get("chat_log") or []
    if not isinstance(chat_log, list):
        raise DisputeError("dispute field 'chat_log' must be a list")

    filed_at = data.get("filed_at")
    return Dispute(
        dispute_id=dispute_id.strip(),
        category=category,
        category_as_submitted=str(submitted_category),
        filed_by=filed_by,
        filed_at=filed_at if isinstance(filed_at, str) else None,
        claim=_mapping(data.get("claim"), "claim"),
        intake=_mapping(data.get("intake"), "intake"),
        trip=_mapping(data.get("trip"), "trip"),
        cancellation=_mapping(data.get("cancellation"), "cancellation"),
        chat_log=[item for item in chat_log if isinstance(item, dict)],
        profiles=_mapping(data.get("profiles"), "profiles"),
        raw=dict(data),
    )


def load_dispute(path: Path) -> Dispute:
    """Read and validate one dispute JSON file."""
    dispute_path = Path(path)
    if not dispute_path.exists():
        raise DisputeError("dispute file not found: %s" % dispute_path)
    try:
        data = json.loads(dispute_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DisputeError("dispute file is not valid JSON (%s): %s" % (dispute_path, exc)) from exc
    return parse_dispute(data)
