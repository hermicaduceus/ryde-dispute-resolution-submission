"""Deterministic computation of the Evidence Pack.

Every number in this module is produced by plain arithmetic over the dispute record.
No model is called here, nothing is inferred, and nothing is guessed: when an input is
missing the corresponding field is null and a note says why. That is what makes the
pack auditable and what lets the agents be forbidden from doing their own maths.

Conventions, applied consistently:
  * distances in km (haversine over GPS points), money in SGD rounded to 2 dp
  * durations in minutes rounded to 1 dp, percentages rounded to 2 dp
  * timestamps are ISO-8601 strings; a timestamp without an offset is read as +08:00
    (Singapore) and a note records that this assumption was made
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from ..dispute import CATEGORY_NO_SHOW_CHARGE, CATEGORY_ROUTE_DEVIATION, Dispute
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

EARTH_RADIUS_KM = 6371.0088
DEFAULT_OFFSET = timezone(timedelta(hours=8))  # Asia/Singapore
SGT_ASSUMPTION_NOTE = "a timestamp without an offset was read as +08:00 (Asia/Singapore)"
BREAKDOWN_TOLERANCE_SGD = 0.01

# --- chat lexicon v1 -------------------------------------------------------------------
# Deterministic keyword sets. A heuristic, labelled as one wherever it surfaces.
# Multi-word or hyphenated entries are matched against the message text; single words
# are matched against its tokens.
NEGATIVE_MARKERS = (
    "late", "wrong", "longer", "detour", "overcharged", "overcharge", "angry",
    "unacceptable", "terrible", "refused", "not here", "no show", "no-show",
    "absent", "never arrived", "did not arrive", "didn't arrive", "charged me", "extra",
)
POSITIVE_MARKERS = (
    "thanks", "thank you", "appreciate", "no problem", "sorry", "ok", "okay", "fine", "good",
)
AGREEMENT_MARKERS = ("ok", "okay", "sure", "agreed", "deal", "no problem", "yes", "fine")
DISAGREEMENT_MARKERS = (
    "did not", "didn't", "never arrived", "refuse", "refused", "disagree", "wrong",
    "not true", "no i", "not what",
)
THREAT_MARKERS = (
    "report you", "report this", "police", "lawsuit", "sue", "social media", "one star",
    "1 star", "complaint", "escalate",
)

_WORD_RE = re.compile(r"[a-z']+")


class EvidenceInputError(ValueError):
    """The dispute is missing the input block its category cannot be assessed without."""


# ------------------------------------------------------------------ small helpers


def _round(value: Optional[float], places: int) -> Optional[float]:
    # `+ 0.0` normalises negative zero, so a computed 0.00 never prints as -0.0.
    return None if value is None else round(value, places) + 0.0


def _as_float(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _as_bool(value: Any) -> Optional[bool]:
    return value if isinstance(value, bool) else None


def _as_int(value: Any) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


def _first(mapping: Dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return None


def haversine_km(a: Dict[str, Any], b: Dict[str, Any]) -> Optional[float]:
    """Great-circle distance between two {lat, lng} points, in km."""
    lat1, lng1 = _as_float(_first(a, "lat", "latitude")), _as_float(_first(a, "lng", "lon", "longitude"))
    lat2, lng2 = _as_float(_first(b, "lat", "latitude")), _as_float(_first(b, "lng", "lon", "longitude"))
    if None in (lat1, lng1, lat2, lng2):
        return None
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lng2 - lng1)
    h = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(h))


def _parse_ts(value: Any, notes: List[str]) -> Optional[datetime]:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        if SGT_ASSUMPTION_NOTE not in notes:
            notes.append(SGT_ASSUMPTION_NOTE)
        parsed = parsed.replace(tzinfo=DEFAULT_OFFSET)
    return parsed


def _minutes_between(start: Any, end: Any, notes: List[str]) -> Optional[float]:
    start_dt = _parse_ts(start, notes)
    end_dt = _parse_ts(end, notes)
    if start_dt is None or end_dt is None:
        return None
    return (end_dt - start_dt).total_seconds() / 60.0


# ------------------------------------------------------------------------ route


def _build_route(trip: Dict[str, Any], notes: List[str]) -> RouteEvidence:
    points = trip.get("actual_route")
    points = points if isinstance(points, list) else []

    actual_km: Optional[float] = None
    first_ts = last_ts = None
    if points:
        legs = []
        for previous, current in zip(points, points[1:]):
            if not isinstance(previous, dict) or not isinstance(current, dict):
                continue
            leg = haversine_km(previous, current)
            if leg is not None:
                legs.append(leg)
        if legs:
            actual_km = sum(legs)
        else:
            notes.append("route points were present but no consecutive pair was usable")
        timestamps = [p.get("t") for p in points if isinstance(p, dict) and isinstance(p.get("t"), str)]
        if timestamps:
            first_ts, last_ts = timestamps[0], timestamps[-1]
    else:
        stated = _as_float(trip.get("actual_distance_km"))
        if stated is not None:
            actual_km = stated
            notes.append("actual distance taken from the record, not recomputed from GPS points")

    estimated_km = _as_float(_first(trip, "estimated_distance_km", "estimated_distance"))
    if actual_km is not None and estimated_km is None:
        notes.append("no estimated distance in the record, so route deviation could not be computed")

    deviation_km = None
    deviation_pct = None
    if actual_km is not None and estimated_km is not None:
        deviation_km = actual_km - estimated_km
        if estimated_km > 0:
            deviation_pct = deviation_km / estimated_km * 100.0

    return RouteEvidence(
        actual_distance_km=_round(actual_km, 3),
        estimated_distance_km=_round(estimated_km, 3),
        deviation_km=_round(deviation_km, 3),
        deviation_pct=_round(deviation_pct, 2),
        point_count=len(points),
        first_point_ts=first_ts,
        last_point_ts=last_ts,
    )


def _build_duration(trip: Dict[str, Any], notes: List[str]) -> DurationEvidence:
    actual = _minutes_between(_first(trip, "pickup_at", "started_at"), _first(trip, "dropoff_at", "ended_at"), notes)
    estimated = _as_float(_first(trip, "estimated_duration_min", "estimated_duration_minutes"))
    if actual is not None and estimated is None:
        notes.append("no estimated duration in the record, so duration overrun could not be computed")

    delta = pct = None
    if actual is not None and estimated is not None:
        delta = actual - estimated
        if estimated > 0:
            pct = delta / estimated * 100.0

    return DurationEvidence(
        actual_minutes=_round(actual, 1),
        estimated_minutes=_round(estimated, 1),
        delta_minutes=_round(delta, 1),
        delta_pct=_round(pct, 2),
    )


# ------------------------------------------------------------------------- fare


def _build_fare(
    trip: Dict[str, Any],
    actual_km: Optional[float],
    actual_minutes: Optional[float],
    estimated_km: Optional[float],
    estimated_minutes: Optional[float],
    notes: List[str],
) -> FareEvidence:
    """Recompute the fare from the recorded tariff rates and the trip's own numbers.

    The formula is fixed and stated here so it can be audited:
        total = (base + per_km * distance + per_min * minutes) * surge - promo
    """
    fare = trip.get("fare") if isinstance(trip.get("fare"), dict) else {}
    charged = _as_float(fare.get("charged_sgd"))

    components_raw = fare.get("breakdown") if isinstance(fare.get("breakdown"), dict) else {}
    components = {
        str(key): float(value)
        for key, value in components_raw.items()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    }
    rates_raw = fare.get("rates") if isinstance(fare.get("rates"), dict) else {}
    rates = {
        str(key): float(value)
        for key, value in rates_raw.items()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    }

    base = _as_float(_first(rates, "base_sgd", "base_fare_sgd")) or 0.0
    per_km = _as_float(_first(rates, "per_km_sgd", "distance_rate_sgd")) or 0.0
    per_min = _as_float(_first(rates, "per_min_sgd", "time_rate_sgd")) or 0.0
    surge = _as_float(_first(rates, "surge_multiplier", "surge")) or 1.0
    promo = abs(_as_float(_first(components, "promo_sgd", "promo", "discount_sgd")) or 0.0)

    def recompute(distance_km: Optional[float], minutes: Optional[float]) -> Optional[float]:
        if not rates:
            return None
        if per_km and distance_km is None:
            return None
        if per_min and minutes is None:
            return None
        subtotal = base + per_km * (distance_km or 0.0) + per_min * (minutes or 0.0)
        return subtotal * surge - promo

    recomputed = recompute(actual_km, actual_minutes)
    recomputed_expected_route = recompute(estimated_km, estimated_minutes)

    if not rates:
        notes.append("no tariff rates in the record, so the fare could not be recomputed")
    elif recomputed is None:
        notes.append("tariff rates present but the trip numbers needed to recompute were missing")

    deviation_fare_delta = None
    if recomputed is not None and recomputed_expected_route is not None:
        deviation_fare_delta = recomputed - recomputed_expected_route

    difference = pct = None
    if charged is not None and recomputed is not None:
        difference = charged - recomputed
        if recomputed > 0:
            pct = difference / recomputed * 100.0

    component_sum = sum(components.values()) if components else None
    breakdown_consistent = None
    if component_sum is not None and charged is not None:
        breakdown_consistent = abs(component_sum - charged) <= BREAKDOWN_TOLERANCE_SGD

    return FareEvidence(
        charged_sgd=_round(charged, 2),
        recomputed_sgd=_round(recomputed, 2),
        recomputed_estimated_route_sgd=_round(recomputed_expected_route, 2),
        deviation_fare_delta_sgd=_round(deviation_fare_delta, 2),
        difference_sgd=_round(difference, 2),
        difference_pct=_round(pct, 2),
        component_sum_sgd=_round(component_sum, 2),
        breakdown_consistent=breakdown_consistent,
        components_sgd={key: _round(value, 2) for key, value in components.items()},
        rates=rates,
        notes=[],
    )


# ------------------------------------------------------------------ cancellation


def _build_cancellation(dispute: Dispute, notes: List[str]) -> Optional[CancellationEvidence]:
    raw = dispute.cancellation
    if not raw:
        return None

    local_notes: List[str] = []
    arrived_at = _first(raw, "driver_arrived_at", "arrived_at")
    wait_started_at = _first(raw, "wait_started_at")
    cancelled_at = _first(raw, "cancelled_at", "cancellation_at")

    explicit_wait = _as_float(_first(raw, "driver_wait_minutes", "wait_minutes"))
    wait_minutes = explicit_wait
    if wait_minutes is None:
        wait_minutes = _minutes_between(arrived_at or wait_started_at, cancelled_at, local_notes)
    arrival_to_cancel = _minutes_between(arrived_at, cancelled_at, local_notes)

    pickup = raw.get("pickup_point") if isinstance(raw.get("pickup_point"), dict) else {}
    driver_position = raw.get("driver_gps_at_arrival") if isinstance(raw.get("driver_gps_at_arrival"), dict) else {}
    distance_km = haversine_km(driver_position, pickup) if pickup and driver_position else None
    if not pickup or not driver_position:
        local_notes.append(
            "no driver position at arrival and/or pickup point in the record, "
            "so the distance between them could not be computed"
        )

    fee = _as_float(_first(raw, "cancellation_fee_sgd", "fee_sgd", "no_show_fee_sgd"))
    if fee is None and dispute.trip:
        fare = dispute.trip.get("fare") if isinstance(dispute.trip.get("fare"), dict) else {}
        breakdown = fare.get("breakdown") if isinstance(fare.get("breakdown"), dict) else {}
        fee = _as_float(_first(breakdown, "cancellation_sgd", "no_show_fee_sgd"))

    notes.extend(local_notes)
    return CancellationEvidence(
        driver_arrived_at=arrived_at if isinstance(arrived_at, str) else None,
        wait_started_at=wait_started_at if isinstance(wait_started_at, str) else None,
        cancelled_at=cancelled_at if isinstance(cancelled_at, str) else None,
        driver_wait_minutes=_round(wait_minutes, 1),
        arrival_to_cancel_minutes=_round(arrival_to_cancel, 1),
        driver_marked_no_show=_as_bool(raw.get("driver_marked_no_show")),
        rider_claims_driver_absent=_as_bool(raw.get("rider_claims_driver_absent")),
        driver_distance_from_pickup_m=_round(distance_km * 1000.0, 1) if distance_km is not None else None,
        cancellation_fee_sgd=_round(fee, 2),
        notes=local_notes,
    )


# -------------------------------------------------------------------------- chat


def _marker_hits(text_lower: str, tokens: Iterable[str], markers: Iterable[str]) -> int:
    token_set = set(tokens)
    hits = 0
    for marker in markers:
        if " " in marker or "-" in marker:
            if marker in text_lower:
                hits += 1
        elif marker in token_set:
            hits += 1
    return hits


def _build_chat(chat_log: List[Dict[str, Any]], notes: List[str]) -> ChatSignalEvidence:
    rider_count = driver_count = 0
    negative = positive = 0
    negative_by_party: Dict[str, int] = {"rider": 0, "driver": 0}
    agreements = disagreements = threats = 0
    timestamps: List[str] = []

    for message in chat_log:
        sender = str(message.get("sender") or message.get("from") or "unknown").lower()
        text = message.get("text")
        text = text if isinstance(text, str) else ""
        lower = text.lower()
        tokens = _WORD_RE.findall(lower)

        if sender == "rider":
            rider_count += 1
        elif sender == "driver":
            driver_count += 1

        timestamp = message.get("t") or message.get("ts") or message.get("at")
        if isinstance(timestamp, str) and timestamp.strip():
            timestamps.append(timestamp)

        negative_hits = _marker_hits(lower, tokens, NEGATIVE_MARKERS)
        positive_hits = _marker_hits(lower, tokens, POSITIVE_MARKERS)
        if negative_hits and not positive_hits:
            negative += 1
            if sender in negative_by_party:
                negative_by_party[sender] += 1
        elif positive_hits and not negative_hits:
            positive += 1

        agreements += _marker_hits(lower, tokens, AGREEMENT_MARKERS)
        disagreements += _marker_hits(lower, tokens, DISAGREEMENT_MARKERS)
        threats += _marker_hits(lower, tokens, THREAT_MARKERS)

    if not chat_log:
        notes.append("no chat log in the record, so no communication signals were derived")

    return ChatSignalEvidence(
        message_count=len(chat_log),
        rider_messages=rider_count,
        driver_messages=driver_count,
        negative_messages=negative,
        positive_messages=positive,
        negative_messages_by_party=negative_by_party,
        agreement_markers=agreements,
        disagreement_markers=disagreements,
        threat_markers=threats,
        first_message_at=timestamps[0] if timestamps else None,
        last_message_at=timestamps[-1] if timestamps else None,
    )


# ---------------------------------------------------------------------- profiles


def _build_profile(party: str, raw: Any) -> Optional[PartyProfile]:
    if not isinstance(raw, dict) or not raw:
        return None
    total = _as_int(_first(raw, "disputes_total", "disputes_filed", "disputes"))
    upheld = _as_int(_first(raw, "disputes_upheld", "upheld"))
    trips = _as_int(_first(raw, "trips_completed", "trips"))

    upheld_rate = None
    if total and upheld is not None and total > 0:
        upheld_rate = upheld / total
    dispute_rate = None
    if trips and total is not None and trips > 0:
        dispute_rate = total / trips

    return PartyProfile(
        party_id=_first(raw, "party_id", "id"),
        party=party,
        account_age_days=_as_int(_first(raw, "account_age_days", "account_age")),
        trips_completed=trips,
        disputes_total=total,
        disputes_upheld=upheld,
        upheld_rate=_round(upheld_rate, 4),
        dispute_rate=_round(dispute_rate, 4),
        rating=_round(_as_float(raw.get("rating")), 2),
    )


def _build_profiles(dispute: Dispute, notes: List[str]) -> Optional[ProfileEvidence]:
    rider = _build_profile("rider", dispute.profiles.get("rider"))
    driver = _build_profile("driver", dispute.profiles.get("driver"))
    if rider is None and driver is None:
        notes.append("no behaviour profiles in the record")
        return None
    return ProfileEvidence(rider=rider, driver=driver)


# ------------------------------------------------------------------------- entry


def build_evidence_pack(dispute: Dispute, generated_at: Optional[str] = None) -> EvidencePack:
    """Compute the pack for one dispute.

    Raises EvidenceInputError when the block the category is assessed on is absent —
    a route-deviation dispute with no trip, or a no-show dispute with no cancellation
    record, cannot be assessed and must not produce a half-empty pack that agents then
    argue over.
    """
    if dispute.category == CATEGORY_ROUTE_DEVIATION and not dispute.trip:
        raise EvidenceInputError(
            "dispute %s is a route-deviation case but carries no trip record; "
            "the Evidence Pack cannot be built" % dispute.dispute_id
        )
    if dispute.category == CATEGORY_NO_SHOW_CHARGE and not dispute.cancellation:
        raise EvidenceInputError(
            "dispute %s is a no-show case but carries no cancellation record; "
            "the Evidence Pack cannot be built" % dispute.dispute_id
        )

    notes: List[str] = []
    trip = dispute.trip
    route = _build_route(trip, notes) if trip else None
    duration = _build_duration(trip, notes) if trip else None
    fare = (
        _build_fare(
            trip,
            route.actual_distance_km if route else None,
            duration.actual_minutes if duration else None,
            route.estimated_distance_km if route else None,
            duration.estimated_minutes if duration else None,
            notes,
        )
        if trip
        else None
    )
    cancellation = _build_cancellation(dispute, notes)
    chat = _build_chat(dispute.chat_log, notes)
    profiles = _build_profiles(dispute, notes)

    return EvidencePack(
        schema_version=EVIDENCE_SCHEMA_VERSION,
        dispute_id=dispute.dispute_id,
        category=dispute.category,
        generated_at=generated_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        trip_id=(trip.get("trip_id") if isinstance(trip.get("trip_id"), str) else None),
        rider_id=(trip.get("rider_id") if isinstance(trip.get("rider_id"), str) else None),
        driver_id=(trip.get("driver_id") if isinstance(trip.get("driver_id"), str) else None),
        route=route,
        duration=duration,
        fare=fare,
        cancellation=cancellation,
        chat=chat,
        profiles=profiles,
        notes=notes,
    )
