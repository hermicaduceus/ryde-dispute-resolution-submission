"""The dispute record: what the intake form submits, and how it is routed.

Two record shapes are accepted, and the shape is detected from the record itself — an
organiser record carries a top-level "dispute_ticket" object, ours does not. Everything
downstream of this module sees one shape: the Dispute fields below.

Shape 1 — Ryde's own (the intake form's output, and data/packs/ryde-synth-v1/):

{
  "dispute_id": "RD-0001",                    required, string
  "category": "route_deviation",              required; see routing below
  "filed_by": "rider",                        required; "rider" | "driver" (case/space tolerant)
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

Everything except dispute_id, category and filed_by is optional; missing blocks produce an
Evidence Pack with null fields and an explanatory note, rather than a guess.

Shape 2 — the organisers' (data/packs/organiser-style-v1/, and their own DISP-002):

{
  "dispute_ticket": {
     "dispute_id": "DISP-002", "trip_id": "TRIP-...", "filed_by": "rider",
     "dispute_type": "no_show_charge",        -> category (via normalise_category)
     "description": "...",                    -> claim.text when ryde_extensions has none
     "filed_at": "...", "status": "open"
  },
  "rider_profile" / "driver_profile": {...},  -> profiles.rider / profiles.driver
  "trip_data": {...},                         -> trip
  "gps_telemetry": [{"timestamp", "lat", "lng", "speed_kmh", "status"}, ...],
  "chat_logs": [{"timestamp", "sender", "type", "content"}, ...],   -> chat_log
  "app_events": [{"timestamp", "event_type", "details"}, ...],
  "cancellation_policy": {...},               -> cancellation.case_policy, untouched
  "ryde_extensions": {...}                    our fields their shape has no slot for
}

`_organiser_to_record` is the whole of that mapping, in one function, so a wrong line
shows up as a mismatched Evidence Pack field rather than as a wrong ruling later. Two
substitutions are deliberately never made, because each one would silently change rulings:

  * matched_at comes from the app_events entry with event_type "driver_assigned", or is
    left out. Booking time is not matching time; the Evidence Pack already flags a
    booking-time anchor as a proxy, and inventing one here would hide that (the NS-1
    defect of 2026-09-21).
  * driver_gps_at_arrival comes from the gps_telemetry row whose status is "arrived", or
    is left out. A missing arrival position is what escalates NS-0205; a position
    borrowed from the pickup point or the last row would rule the case instead.
  * rider_claims_driver_absent comes from ryde_extensions, or is left out. Whether the
    rider says the driver never came is never inferred from who filed the dispute: the
    rider's own words stay in claim.text for the Advocates, and the structured field
    says "not stated" unless the record states it (the session-five review).

Routing: only the two locked categories reach the agents. Anything else — including the
form's "other" option, the statement's out-of-scope categories, and any value the corpus
does not use — goes to the human-review queue with a neutral message.
"""

from __future__ import annotations

import json
import math
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
    #: The filing party's round-two answers, when the run stopped to ask for them.
    #: Present answers are the one-round gate: a dispute that carries them never stops
    #: for questions again. Empty until the party has answered.
    follow_up_answers: List[Dict[str, str]] = field(default_factory=list)
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
        """The amount the filing party asked for, 0.0 when not stated.

        A number that is present but not finite (NaN or Infinity, both of which a JSON
        reader accepts) is not a stated amount: it reads as 0.0, exactly like a string,
        and never reaches an agent's prompt as a figure.
        """
        amount = self.claim.get("amount_sgd")
        if isinstance(amount, bool) or not isinstance(amount, (int, float)):
            return 0.0
        try:
            number = float(amount)
        except OverflowError:  # an int too large for a float is not a stated amount either
            return 0.0
        return number if math.isfinite(number) else 0.0

    def to_dict(self) -> Dict[str, Any]:
        return self.raw


def _mapping(value: Any, key: str, default: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if value is None:
        return dict(default or {})
    if not isinstance(value, dict):
        raise DisputeError("dispute field '%s' must be an object" % key)
    return value


def _is_unreadable_number(value: Any) -> bool:
    """True for a present number that cannot be read as a finite float.

    NaN, Infinity and -Infinity are accepted by a JSON reader as bare tokens, and a
    reader returns an integer of any size; an integer too large for a float is not a
    usable figure either. All of them are unreadable, and are blanked before the value
    can reach an agent's prompt or the case file.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        number = float(value)
    except OverflowError:  # an integer too large for a float
        return True
    return not math.isfinite(number)


def _blank_unreadable(value: Any) -> Any:
    """A copy of a value with every unreadable number replaced by None, at any depth.

    The intake answers are echoed verbatim into all three agents' prompts and the case
    file, so an unreadable number there reaches both. Containers are copied, never
    mutated, so `raw` keeps the record exactly as it was filed.
    """
    if _is_unreadable_number(value):
        return None
    if isinstance(value, dict):
        return {key: _blank_unreadable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_blank_unreadable(item) for item in value]
    return value


def _blank_unreadable_party_ids(profiles: Dict[str, Any]) -> Dict[str, Any]:
    """Each party block with an unreadable party_id/id set to None.

    Only the identifiers are touched: the evidence layer reads the other profile fields
    and already treats an unreadable one as missing.
    """
    cleaned: Dict[str, Any] = {}
    for party, block in profiles.items():
        if isinstance(block, dict):
            block = dict(block)
            for key in ("party_id", "id"):
                if _is_unreadable_number(block.get(key)):
                    block[key] = None
        cleaned[party] = block
    return cleaned


# ------------------------------------------------------- the organisers' shape


def is_organiser_record(data: Any) -> bool:
    """True for the organisers' shape: a top-level dispute_ticket object."""
    return isinstance(data, dict) and isinstance(data.get("dispute_ticket"), dict)


def _object(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _copy_present(target: Dict[str, Any], source: Dict[str, Any], key: str, as_key: Optional[str] = None) -> None:
    """Carry a field across under its own name or a renamed one, when it is there.

    A missing key stays missing rather than becoming an explicit null: the Evidence Pack
    distinguishes "the record does not state this" from "the record states null", and only
    the first is true here.
    """
    value = source.get(key)
    if value is not None:
        target[as_key or key] = value


def _event_timestamp(events: Any, event_type: str) -> Optional[str]:
    """The timestamp of the app_events entry of this type, or None if there is no such entry."""
    for event in events if isinstance(events, list) else []:
        if isinstance(event, dict) and event.get("event_type") == event_type:
            timestamp = event.get("timestamp")
            if isinstance(timestamp, str) and timestamp.strip():
                return timestamp
    return None


def _arrival_position(telemetry: Any) -> Optional[Dict[str, Any]]:
    """The {lat, lng} of the telemetry row whose status is "arrived", or None.

    None is a real answer — NS-0205's record has no arrival row, and that absence is the
    evidence that escalates the case. Substituting the pickup point or the last row would
    supply a position the record does not contain.
    """
    for row in telemetry if isinstance(telemetry, list) else []:
        if isinstance(row, dict) and row.get("status") == "arrived":
            lat, lng = row.get("lat"), row.get("lng")
            if isinstance(lat, (int, float)) and isinstance(lng, (int, float)):
                return {"lat": lat, "lng": lng}
    return None


def _organiser_profile(party: str, raw: Any) -> Optional[Dict[str, Any]]:
    """One side's profile, in our field names. None when the record has no such block."""
    profile = _object(raw)
    if not profile:
        return None
    history = _object(profile.get("dispute_history"))
    mapped: Dict[str, Any] = {}
    _copy_present(mapped, profile, "%s_id" % party, "party_id")
    _copy_present(mapped, profile, "account_age_days")
    _copy_present(mapped, profile, "total_trips", "trips_completed")
    _copy_present(mapped, profile, "avg_rating", "rating")
    _copy_present(mapped, profile, "fraud_flags")
    _copy_present(mapped, history, "total_disputes", "disputes_total")
    # A rider's history counts disputes they won ("upheld"); a driver's counts disputes
    # lost against them ("upheld_against"). Both land on disputes_upheld, which is the
    # field the pack turns into the upheld rate the agents argue from.
    _copy_present(mapped, history, "upheld_against" if party == "driver" else "upheld", "disputes_upheld")
    return mapped


def _organiser_to_record(data: Dict[str, Any]) -> Dict[str, Any]:
    """Translate one organisers'-shape record into our shape. See the module docstring."""
    ticket = _object(data.get("dispute_ticket"))
    trip_data = _object(data.get("trip_data"))
    extensions = _object(data.get("ryde_extensions"))
    category = normalise_category(ticket.get("dispute_type"))

    # The claim and the intake answers live in our extension block; their own shape has no
    # slot for either. Without the block (DISP-002) the description is all the party said,
    # and no amount was asked for.
    claim = extensions.get("claim")
    if claim is None:
        claim = {"text": ticket.get("description")}

    trip: Dict[str, Any] = {}
    for source, target in (
        ("trip_id", "trip_id"),
        ("rider_id", "rider_id"),
        ("driver_id", "driver_id"),
        ("estimated_duration_min", "estimated_duration_min"),
        ("estimated_distance_km", "estimated_distance_km"),
        ("requested_time", "requested_at"),
        ("pickup_time", "pickup_at"),
        ("dropoff_time", "dropoff_at"),
    ):
        _copy_present(trip, trip_data, source, target)
    _copy_present(trip, extensions, "service_type")

    if isinstance(trip_data.get("fare"), dict):
        trip["fare"] = trip_data["fare"]
    else:
        # Their shape states a cancellation or waiting fee once, on trip_data; ours states
        # it twice — on the cancellation block and as the charged amount in the fare
        # breakdown. The reader places it in both, or the fee would vanish from the pack.
        fee = trip_data.get("cancellation_fee")
        if fee is None:
            fee = trip_data.get("waiting_fee")
        if fee is not None:
            trip["fare"] = {"charged_sgd": fee, "breakdown": {"cancellation_sgd": fee}}

    # Their gps_telemetry is the trip trace for a route case, but for a no-show it is the
    # approach-and-wait trace: a route built from it would report a distance the trip never
    # covered, so it becomes actual_route only where the trip actually ran.
    if category == CATEGORY_ROUTE_DEVIATION:
        route = [
            {"lat": row.get("lat"), "lng": row.get("lng"), "t": row.get("timestamp")}
            for row in (data.get("gps_telemetry") if isinstance(data.get("gps_telemetry"), list) else [])
            if isinstance(row, dict)
        ]
        if route:
            trip["actual_route"] = route

    cancellation: Dict[str, Any] = {}
    arrived_at = trip_data.get("driver_arrival_time")
    wait_started_at = trip_data.get("driver_wait_start")
    # A waiting fee is charged when the trip went ahead, so the boarding time is the
    # moment the charge was incurred (NS-0207); otherwise it is the cancellation.
    cancelled_at = trip_data.get("cancellation_time")
    if cancelled_at is None:
        cancelled_at = trip_data.get("rider_boarded_time")
    fee = trip_data.get("cancellation_fee")
    if fee is None:
        fee = trip_data.get("waiting_fee")

    has_cancellation_facts = any(
        value is not None
        for value in (
            arrived_at,
            wait_started_at,
            cancelled_at,
            fee,
            trip_data.get("cancellation_reason"),
        )
    )
    if has_cancellation_facts:
        _copy_present(cancellation, trip_data, "driver_arrival_time", "driver_arrived_at")
        _copy_present(cancellation, trip_data, "driver_wait_start", "wait_started_at")
        if cancelled_at is not None:
            cancellation["cancelled_at"] = cancelled_at
        # Each fee is carried under its own name, so a record stating both loses
        # neither (schema 1.3). cancellation_fee_sgd alone keeps the twin property:
        # with no cancellation fee stated, the fee this reader places in the fare
        # breakdown below (the waiting fee) stands in for comparison downstream.
        if trip_data.get("cancellation_fee") is not None:
            cancellation["cancellation_fee_sgd"] = trip_data["cancellation_fee"]
        if trip_data.get("waiting_fee") is not None:
            cancellation["waiting_fee_sgd"] = trip_data["waiting_fee"]
        # Never the booking time: the pack's matching anchor names its source, and a proxy
        # anchor invented here would be indistinguishable from a real one.
        matched_at = _event_timestamp(data.get("app_events"), "driver_assigned")
        if matched_at is not None:
            cancellation["matched_at"] = matched_at
        cancellation["driver_marked_no_show"] = trip_data.get("cancellation_reason") == "rider_no_show"
        if "rider_claims_driver_absent" in extensions:
            cancellation["rider_claims_driver_absent"] = extensions["rider_claims_driver_absent"]
        # Never inferred: whether the rider says the driver never came is a structured
        # fact only when the record states one (in ryde_extensions). Without it the field
        # stays unset and the pack reports None — the rider's own words remain in
        # claim.text, where the Advocates read them.
        pickup = _object(trip_data.get("pickup_location"))
        if "lat" in pickup and "lng" in pickup:
            cancellation["pickup_point"] = {"lat": pickup.get("lat"), "lng": pickup.get("lng")}
        position = _arrival_position(data.get("gps_telemetry"))
        if position is not None:
            cancellation["driver_gps_at_arrival"] = position
        # The terms that govern this case, so the agents can see which policy the charge
        # was applied under. Their shape carries it per case; passed through untouched.
        if isinstance(data.get("cancellation_policy"), dict):
            cancellation["case_policy"] = data["cancellation_policy"]

    chat_log: List[Dict[str, Any]] = []
    for message in data.get("chat_logs") if isinstance(data.get("chat_logs"), list) else []:
        if not isinstance(message, dict):
            continue
        entry: Dict[str, Any] = {
            "t": message.get("timestamp"),
            "sender": message.get("sender"),
            "text": message.get("content"),
        }
        # A call is stronger evidence of a contact attempt than a message, and "type" is
        # the only thing that tells them apart.
        if "type" in message:
            entry["type"] = message["type"]
        chat_log.append(entry)

    profiles: Dict[str, Any] = {}
    for party in ("rider", "driver"):
        profile = _organiser_profile(party, data.get("%s_profile" % party))
        if profile is not None:
            profiles[party] = profile

    return {
        "dispute_id": ticket.get("dispute_id"),
        "category": ticket.get("dispute_type"),
        "filed_by": ticket.get("filed_by"),
        "filed_at": ticket.get("filed_at"),
        "claim": claim,
        "intake": extensions.get("intake") or {},
        "trip": trip,
        "cancellation": cancellation,
        "chat_log": chat_log,
        "profiles": profiles,
        # Their shape has no slot for the party's round-two answers either; our
        # extension block is the one place they can arrive.
        "follow_up_answers": extensions.get("follow_up_answers"),
    }


# ------------------------------------------------------------- the shared parse


def parse_dispute(data: Any) -> Dispute:
    """Validate a raw dispute dict into a Dispute. Raises DisputeError with the reason."""
    if not isinstance(data, dict):
        raise DisputeError("a dispute record must be a JSON object")
    # `raw` keeps the record exactly as it arrived, whichever shape that was: the case
    # file's grievance section and the filed-dispute event show what was actually filed.
    return _parse_record(_organiser_to_record(data) if is_organiser_record(data) else data, raw=data)


def _follow_up_answers(value: Any) -> List[Dict[str, str]]:
    """Validate the party's round-two answers, or [] when the record carries none.

    Each entry must be an object with a string question and a string answer. Anything
    else is a broken record: coercing it would put words in the party's mouth on the
    file the advocates and the Judge read.
    """
    if value is None:
        return []
    if not isinstance(value, list):
        raise DisputeError("follow_up_answers must be a list of {question, answer} objects")
    answers: List[Dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            raise DisputeError("follow_up_answers entries must be objects with question and answer")
        question = item.get("question")
        answer = item.get("answer")
        if not isinstance(question, str) or not isinstance(answer, str):
            raise DisputeError(
                "follow_up_answers entries need a string 'question' and a string 'answer'"
            )
        answers.append({"question": question, "answer": answer})
    return answers


def _parse_record(data: Dict[str, Any], raw: Dict[str, Any]) -> Dispute:
    dispute_id = data.get("dispute_id")
    if not isinstance(dispute_id, str) or not dispute_id.strip():
        raise DisputeError("dispute_id is required and must be a non-empty string")

    submitted_category = data.get("category")
    category = normalise_category(submitted_category)

    raw_filed_by = data.get("filed_by")
    if not isinstance(raw_filed_by, str) or not raw_filed_by.strip():
        raise DisputeError(
            "filed_by is required and must be 'rider' or 'driver', not %r" % (raw_filed_by,)
        )
    filed_by = raw_filed_by.strip().lower()
    if filed_by not in ("rider", "driver"):
        raise DisputeError("filed_by must be 'rider' or 'driver', not %r" % raw_filed_by)

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
        # Blanked at parse: these answers are echoed into every agent's prompt and the
        # case file, so an unreadable number must never survive into either.
        intake=_blank_unreadable(_mapping(data.get("intake"), "intake")),
        trip=_mapping(data.get("trip"), "trip"),
        cancellation=_mapping(data.get("cancellation"), "cancellation"),
        chat_log=[item for item in chat_log if isinstance(item, dict)],
        profiles=_blank_unreadable_party_ids(_mapping(data.get("profiles"), "profiles")),
        follow_up_answers=_follow_up_answers(data.get("follow_up_answers")),
        raw=dict(raw),
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
