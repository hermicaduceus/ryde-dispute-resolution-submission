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
from typing import Any, Dict, Iterable, List, Optional

from ..dispute import CATEGORY_NO_SHOW_CHARGE, CATEGORY_ROUTE_DEVIATION, Dispute
from .schema import (
    EVIDENCE_SCHEMA_VERSION,
    CancellationEvidence,
    ChatSignalEvidence,
    DurationEvidence,
    EvidencePack,
    FareEvidence,
    FilingEvidence,
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


def _round_up(value: Optional[float], places: int) -> Optional[float]:
    """Round away from zero, for values a policy threshold is applied to.

    Both thresholds that read these fields are upper bounds: GEN-6 asks whether a filing
    is within 30 days, NS-1 whether a cancellation is at or below 3 minutes. Ordinary
    rounding carries a value across such a bound without it having been crossed, so
    30.004 days reads as 30.0 and a cancellation at 3 min 2 s reads as 3.0 — both land
    inside a window the real number sits outside. The Judge compares the figure it is
    shown and may not recompute it, so the figure must never flatter the claim.
    Rounding up keeps a value that exceeds the bound looking like it exceeds the bound.
    """
    if value is None:
        return None
    factor = 10.0 ** places
    return (math.ceil(value * factor) / factor) + 0.0


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


def _point_is_usable(point: Any) -> bool:
    """Whether a GPS trace point can take part in a computed distance.

    Mirrors the guards in haversine_km: not an object, coordinates missing or
    non-numeric, values non-finite or out of range — any of these makes the point
    unusable, and one unusable point makes the length of the whole trace unknown.
    """
    if not isinstance(point, dict):
        return False
    lat = _as_float(_first(point, "lat", "latitude"))
    lng = _as_float(_first(point, "lng", "lon", "longitude"))
    if lat is None or lng is None:
        return False
    if not (math.isfinite(lat) and math.isfinite(lng)):
        return False
    return -90.0 <= lat <= 90.0 and -180.0 <= lng <= 180.0


def haversine_km(a: Dict[str, Any], b: Dict[str, Any]) -> Optional[float]:
    """Great-circle distance between two {lat, lng} points, in km.

    Returns None for coordinates outside the valid ranges rather than computing a
    distance from them. A lat of 999 is not a long trip, it is a broken record, and a
    pack field the agents will argue from must never carry a number derived from one.
    """
    lat1, lng1 = _as_float(_first(a, "lat", "latitude")), _as_float(_first(a, "lng", "lon", "longitude"))
    lat2, lng2 = _as_float(_first(b, "lat", "latitude")), _as_float(_first(b, "lng", "lon", "longitude"))
    if lat1 is None or lng1 is None or lat2 is None or lng2 is None:
        return None
    for lat, lng in ((lat1, lng1), (lat2, lng2)):
        if not (math.isfinite(lat) and math.isfinite(lng)):
            return None
        if not (-90.0 <= lat <= 90.0 and -180.0 <= lng <= 180.0):
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


NEGATIVE_INTERVAL_NOTE = (
    "a timestamp pair ran backwards (the end precedes the start); the interval was "
    "discarded rather than recorded as a negative duration"
)


def _minutes_between(start: Any, end: Any, notes: List[str]) -> Optional[float]:
    """Minutes from start to end, or None if the pair is unusable.

    A negative interval means the record's timestamps are out of order. Returning the
    negative number would let it flow into the fare formula and produce a confident,
    precise, wrong figure: a dropoff before its pickup once yielded a recomputed fare of
    SGD 3.13 against a real 18.65, presented to the agents as a SGD 15.50 overcharge.
    Refusing to compute it is the only safe answer.
    """
    start_dt = _parse_ts(start, notes)
    end_dt = _parse_ts(end, notes)
    if start_dt is None or end_dt is None:
        return None
    minutes = (end_dt - start_dt).total_seconds() / 60.0
    if minutes < 0:
        if NEGATIVE_INTERVAL_NOTE not in notes:
            notes.append(NEGATIVE_INTERVAL_NOTE)
        return None
    return minutes


# ------------------------------------------------------------------------ route


def _build_route(trip: Dict[str, Any], notes: List[str]) -> RouteEvidence:
    points = trip.get("actual_route")
    points = points if isinstance(points, list) else []

    actual_km: Optional[float] = None
    first_ts = last_ts = None
    if points:
        broken = [index for index, point in enumerate(points) if not _point_is_usable(point)]
        if broken:
            # One unusable point means the trace's length is unknown, not shorter: a sum
            # over the usable remainder is a plausible wrong number, the worst thing a
            # pack field can be. The distance is voided and no deviation is computed.
            names = ", ".join(str(index) for index in broken)
            notes.append(
                "route point%s %s in the GPS trace %s unusable (not an object, or "
                "coordinates missing, non-numeric, non-finite, or out of range); the "
                "distance over the trace is unknown rather than partial, so no deviation "
                "was computed"
                % (
                    "s" if len(broken) > 1 else "",
                    names,
                    "are" if len(broken) > 1 else "is",
                )
            )
        else:
            legs = [haversine_km(previous, current) for previous, current in zip(points, points[1:])]
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

NEGATIVE_FARE_INPUT_NOTE = (
    "the fare could not be recomputed: a distance or duration was negative, which is a "
    "record defect rather than a cheap trip"
)

NON_POSITIVE_SURGE_NOTE = (
    "the fare could not be recomputed: the surge multiplier was zero or negative"
)


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
    # tools/build_corpus.py stores promo_sgd as a negative discount and the fare formula
    # subtracts it; abs() makes the stored sign irrelevant.
    promo = abs(_as_float(_first(components, "promo_sgd", "promo", "discount_sgd")) or 0.0)

    def recompute(distance_km: Optional[float], minutes: Optional[float]) -> Optional[float]:
        """The fare for these inputs, or None when the inputs cannot produce a real one.

        Negative distances or minutes, and a zero or negative surge, are record defects
        rather than cheap trips: each one makes the formula return a smaller or negative
        fare that reads as a legitimate overcharge finding. Refuse instead of computing.
        """
        if not rates:
            return None
        if per_km and distance_km is None:
            return None
        if per_min and minutes is None:
            return None
        if (distance_km is not None and distance_km < 0) or (minutes is not None and minutes < 0):
            if NEGATIVE_FARE_INPUT_NOTE not in notes:
                notes.append(NEGATIVE_FARE_INPUT_NOTE)
            return None
        if surge <= 0:
            if NON_POSITIVE_SURGE_NOTE not in notes:
                notes.append(NON_POSITIVE_SURGE_NOTE)
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


#: Booking time stands in for matching time when the record has no matching timestamp.
#: The two are not the same event, and the gap between them is dead time the rider did not
#: choose, so a cancellation measured from booking looks later than it was. NS-1's free
#: window is only 3 minutes wide, which makes this substitution decision-changing rather
#: than cosmetic. The Judge is told, so it can weigh a borderline interval accordingly.
MATCHING_ANCHOR_PROXY_NOTE = (
    "the record carries no matching timestamp, so the interval to cancellation was measured "
    "from booking time as a proxy; matching happens after booking, so the true interval from "
    "matching is shorter than the figure shown"
)


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

    # NS-1's free-cancellation window runs from MATCHING, not from arrival, so a rider
    # who cancels before any driver arrives has no other measurable interval. Without
    # this field the rule is unenforceable: the Judge may cite pack fields but may not
    # subtract two timestamps itself.
    #
    # Booking time is NOT matching time: a rider books, then the platform matches a driver
    # some seconds or minutes later. Measuring from booking overstates the interval and can
    # push a cancellation outside NS-1's 3-minute free window that was actually inside it.
    # So the anchor used is named in the pack, and falling back to booking time is recorded
    # as a proxy rather than presented as the real thing.
    matching_anchor_at = None
    matching_anchor_source = None
    for value, source in (
        (_first(raw, "matched_at", "accepted_at"), "matched_at"),
        ((dispute.trip or {}).get("matched_at"), "trip.matched_at"),
        ((dispute.trip or {}).get("requested_at"), "trip.requested_at"),
    ):
        if isinstance(value, str) and value.strip():
            matching_anchor_at = value
            matching_anchor_source = source
            break

    matching_to_cancel = _minutes_between(matching_anchor_at, cancelled_at, local_notes)
    if matching_to_cancel is None:
        local_notes.append(
            "no matching time and/or cancellation time in the record, so the interval "
            "from matching to cancellation could not be computed"
        )
    elif matching_anchor_source == "trip.requested_at":
        local_notes.append(MATCHING_ANCHOR_PROXY_NOTE)

    # Absent is not unusable. A block the record does not carry gets today's absence
    # note; a block that IS there but whose coordinates fail haversine_km is a broken
    # record, and the note must say so — "absent" would misstate what was filed.
    pickup_block = raw.get("pickup_point")
    driver_block = raw.get("driver_gps_at_arrival")
    pickup = pickup_block if isinstance(pickup_block, dict) and pickup_block else None
    driver_position = driver_block if isinstance(driver_block, dict) and driver_block else None
    distance_km = None
    if pickup is None or driver_position is None:
        local_notes.append(
            "no driver position at arrival and/or pickup point in the record, "
            "so the distance between them could not be computed"
        )
    else:
        distance_km = haversine_km(driver_position, pickup)
        if distance_km is None:
            local_notes.append(
                "the coordinates recorded for the driver position at arrival and/or the "
                "pickup point were present but unusable, so the distance between them "
                "could not be computed"
            )

    cancellation_fee = _as_float(_first(raw, "cancellation_fee_sgd", "fee_sgd", "no_show_fee_sgd"))
    waiting_fee = _as_float(raw.get("waiting_fee_sgd"))
    # The twin property: when the record states no cancellation fee, the fee it does
    # state (a waiting fee, in the organiser shape) stands in for comparison purposes.
    # A stated waiting fee is ALSO carried under its own name, so a record carrying
    # both loses neither.
    fee = cancellation_fee
    if fee is None and dispute.trip:
        fare = dispute.trip.get("fare") if isinstance(dispute.trip.get("fare"), dict) else {}
        breakdown = fare.get("breakdown") if isinstance(fare.get("breakdown"), dict) else {}
        fee = _as_float(_first(breakdown, "cancellation_sgd", "no_show_fee_sgd"))
    if cancellation_fee is not None and waiting_fee is not None:
        local_notes.append(
            "the record carried both a cancellation fee and a waiting fee; both amounts are shown"
        )

    # Which terms govern this case. Passed through exactly as the record states them, so
    # the agents can see that a charge was applied under, say, a 5 / 8 minute policy
    # rather than the 3-minute one they may know from elsewhere. This layer does not
    # reconcile the two: reading a rule out of a document is the Judge's job.
    case_policy = raw.get("case_policy") if isinstance(raw.get("case_policy"), dict) else None

    notes.extend(local_notes)
    return CancellationEvidence(
        driver_arrived_at=arrived_at if isinstance(arrived_at, str) else None,
        wait_started_at=wait_started_at if isinstance(wait_started_at, str) else None,
        cancelled_at=cancelled_at if isinstance(cancelled_at, str) else None,
        driver_wait_minutes=_round(wait_minutes, 1),
        arrival_to_cancel_minutes=_round(arrival_to_cancel, 1),
        matching_to_cancel_minutes=_round_up(matching_to_cancel, 1),
        matching_anchor_at=matching_anchor_at,
        matching_anchor_source=matching_anchor_source,
        driver_marked_no_show=_as_bool(raw.get("driver_marked_no_show")),
        rider_claims_driver_absent=_as_bool(raw.get("rider_claims_driver_absent")),
        driver_distance_from_pickup_m=_round(distance_km * 1000.0, 1) if distance_km is not None else None,
        cancellation_fee_sgd=_round(fee, 2),
        waiting_fee_sgd=_round(waiting_fee, 2),
        case_policy=case_policy,
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
        fraud_flags=_as_int(raw.get("fraud_flags")),
    )


def _build_profiles(dispute: Dispute, notes: List[str]) -> Optional[ProfileEvidence]:
    rider = _build_profile("rider", dispute.profiles.get("rider"))
    driver = _build_profile("driver", dispute.profiles.get("driver"))
    if rider is None and driver is None:
        notes.append("no behaviour profiles in the record")
        return None
    return ProfileEvidence(rider=rider, driver=driver)


# ------------------------------------------------------------------------- entry


# --------------------------------------------------------------- filing and service


#: Recognised service types, keyed on the normalised form: lowercased with spaces,
#: hyphens and underscores stripped. One entry per service — a key containing a space
#: would be unreachable, because the lookup removes separators before matching.
#: RydeTAXI trips are metered and sit outside the fare rules in the policy's section 4,
#: so the Judge needs to see which service a trip was.
_SERVICE_TYPES = {
    "rydex": "RydeX",
    "rydexl": "RydeXL",
    "rydetaxi": "RydeTAXI",
    "taxi": "RydeTAXI",
    "rydeexec": "RydeEXEC",
    "rydepool": "RydePOOL",
}

SERVICE_TYPE_UNKNOWN_NOTE = (
    "no service type in the record, so service-specific rules (for example the RydeTAXI "
    "carve-out) could not be applied"
)


def _service_type(trip: Dict[str, Any], notes: List[str]) -> Optional[str]:
    """The trip's service type, normalised, or None with a note.

    An unrecognised value is passed through verbatim rather than nulled: the record did
    state a service, and discarding it would claim the pack could not establish something
    it can. Only a missing or non-string value is null.
    """
    raw = _first(trip or {}, "service_type", "service", "product", "vehicle_type")
    if not isinstance(raw, str) or not raw.strip():
        if SERVICE_TYPE_UNKNOWN_NOTE not in notes:
            notes.append(SERVICE_TYPE_UNKNOWN_NOTE)
        return None
    key = re.sub(r"[\s_-]+", "", raw.strip().lower())
    return _SERVICE_TYPES.get(key, raw.strip())


FILING_WINDOW_UNVERIFIABLE_NOTE = (
    "the filing window could not be established: the record lacks a filing date or a trip "
    "date to measure it from"
)


def _build_filing(dispute: Dispute, notes: List[str]) -> FilingEvidence:
    """Days between the trip and the filing, so the filing-window rule is applicable.

    The Judge may not do arithmetic, so a rule about elapsed days is unenforceable unless
    the days are computed here. When either date is missing, days_since_trip is None and
    window_established is False — the policy's own fallback is to proceed rather than
    decline, and it can only take that path if it can see the window is unverifiable.
    """
    local: List[str] = []
    # From the parsed dispute, not from dispute.raw: the two record shapes file the date
    # in different places (top level vs dispute_ticket), and reading the parsed field is
    # what lets a GEN-6 filing window be established for either one. Reading raw here
    # silently nulled the window for every organiser-format record.
    filed_at = dispute.filed_at
    filed_at = filed_at if isinstance(filed_at, str) and filed_at.strip() else None

    trip = dispute.trip or {}
    cancellation = dispute.cancellation or {}
    reference = None
    for candidate in (
        trip.get("dropoff_at"),
        trip.get("pickup_at"),
        cancellation.get("cancelled_at"),
        trip.get("requested_at"),
    ):
        if isinstance(candidate, str) and candidate.strip():
            reference = candidate
            break

    days = None
    if filed_at and reference:
        minutes = _minutes_between(reference, filed_at, local)
        if minutes is not None:
            days = minutes / (60.0 * 24.0)
        else:
            # The string did not parse. Do not display it as though it were a date:
            # the pack's rule is that a value derived from a broken record is withheld,
            # not shown with a caveat somewhere else.
            filed_at = None

    if days is None:
        if FILING_WINDOW_UNVERIFIABLE_NOTE not in notes:
            notes.append(FILING_WINDOW_UNVERIFIABLE_NOTE)
        # Also kept on the block itself: a view rendering the filing section reads
        # filing.notes, and an unexplained null there is exactly the silent gap the
        # note exists to prevent. Cancellation already carries its notes in both places.
        if FILING_WINDOW_UNVERIFIABLE_NOTE not in local:
            local.append(FILING_WINDOW_UNVERIFIABLE_NOTE)

    for note in local:
        if note not in notes:
            notes.append(note)

    return FilingEvidence(
        filed_at=filed_at,
        trip_reference_at=reference,
        days_since_trip=_round_up(days, 2),
        window_established=days is not None,
        notes=list(local),
    )


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
    filing = _build_filing(dispute, notes)

    return EvidencePack(
        schema_version=EVIDENCE_SCHEMA_VERSION,
        dispute_id=dispute.dispute_id,
        category=dispute.category,
        generated_at=generated_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        trip_id=(trip.get("trip_id") if isinstance(trip.get("trip_id"), str) else None),
        rider_id=(trip.get("rider_id") if isinstance(trip.get("rider_id"), str) else None),
        driver_id=(trip.get("driver_id") if isinstance(trip.get("driver_id"), str) else None),
        service_type=_service_type(trip, notes),
        route=route,
        duration=duration,
        fare=fare,
        cancellation=cancellation,
        chat=chat,
        profiles=profiles,
        filing=filing,
        notes=notes,
    )
