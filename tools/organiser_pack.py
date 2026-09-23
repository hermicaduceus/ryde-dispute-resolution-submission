"""Render the synthesised corpus in the organisers' sample-dataset shape.

NON-APP TOOL, imported only by tools/build_corpus.py. Nothing under app/ or ui/ imports it.

The organisers shared one sample case (DISP-002, a no-show charge dispute) whose JSON shape
differs from our corpus. This module re-expresses each of our 17 cases in that shape so the
pipeline can be exercised on the format the organisers actually use. It TRANSFORMS the
records build_corpus.py already generated; it never re-derives a number, so every fare,
timestamp, distance and wait in the organiser-style pack is the same fact as in
ryde-synth-v1. tests/test_organiser_pack.py asserts that field by field.

What the organiser shape has no slot for, and where we put it (all stated in pack.json):

  * route-deviation trips: their sample is a no-show, so it carries no fare, no route
    estimate and no trip-completion timestamps. Those facts sit in `trip_data` under our
    own snake_case names (`estimated_distance_km`, `fare`, `pickup_time`, ...), in the
    organiser's style but not from their sample.
  * the claim amount, the intake-form answers and `rider_claims_driver_absent`: their
    ticket has one free-text `description`. These ride in `ryde_extensions`, which a
    reader that only knows the organiser schema can ignore.
  * the per-case `cancellation_policy`: ours carry Ryde's PUBLISHED terms (the same
    parameters as docs/policy.md), so no label changes between packs. DISP-002 carries the
    organisers' own terms, which differ.

Prose (the free-text `description`, party names, vehicles) is not generated here. It is
read from tools/organiser_prose.json, drafted by a model and reviewed; this module refuses
to build if a description introduces a number the underlying claim and intake never state.
"""

from __future__ import annotations

import json
import math
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

TOOLS = Path(__file__).resolve().parent
PROSE_PATH = TOOLS / "organiser_prose.json"
SAMPLES_DIR = TOOLS / "organiser_samples"

PACK_NAME = "organiser-style-v1"
PACK_FORMAT = "organiser-v1"

EARTH_RADIUS_KM = 6371.0088

# Ryde's published cancellation terms, the same values as the docs/policy.md parameter table.
# Ryde publishes a single 3-minute figure for both the free window after matching and the
# wait after "I'm Here"; the organiser shape splits that into three keys, so the one figure
# fills all three.
RYDE_CANCELLATION_POLICY = {
    "free_cancellation_window_min": 3,
    "free_wait_time_min": 3,
    "no_show_threshold_min": 3,
    "cancellation_fee_after_wait": 6.61,
    "waiting_fee_after_wait": 5.00,
    "source": "Ryde published cancellation and waiting fee policy (docs/policy.md parameters)",
}

# Named places for the pickup and drop-off slots. Names were checked against the
# coordinates by reverse geocoding (OpenStreetMap Nominatim, 2026-09-23).
DHOBY_GHAUT = {"name": "Dhoby Ghaut", "lat": 1.2989, "lng": 103.8456}
ORCHARD_BOULEVARD = {"name": "Orchard Boulevard", "lat": 1.3048, "lng": 103.8318}

ROUTE_DROPOFF_NAMES = {
    "RD-0101": "Hougang Avenue 5",
    "RD-0102": "Buangkok East Drive",
    "RD-0103": "Upper Aljunied Road",
    "RD-0104": "Changi Airport Terminal 1",
    "RD-0105": "Upper Serangoon Road",
    "RD-0106": "Hougang Street 21",
    "RD-0107": "Lorong Ah Soo",
    "RD-0108": "Rivervale, Sengkang",
    "RD-0109": "Ang Mo Kio (Kebun Baru)",
}

# The booked destinations of the no-show trips that never ran. Real places, real coordinates.
NO_SHOW_DESTINATIONS = {
    "NS-0201": {"name": "VivoCity", "lat": 1.2644, "lng": 103.8222},
    "NS-0202": {"name": "Novena Square", "lat": 1.3203, "lng": 103.8438},
    "NS-0203": {"name": "Junction 8, Bishan", "lat": 1.3502, "lng": 103.8488},
    "NS-0204": {"name": "Tampines Mall", "lat": 1.3525, "lng": 103.9447},
    "NS-0205": {"name": "Jurong Point", "lat": 1.3397, "lng": 103.7066},
    "NS-0206": {"name": "Holland Village", "lat": 1.3111, "lng": 103.7958},
    "NS-0207": {"name": "Marina Bay Sands", "lat": 1.2834, "lng": 103.8607},
    "OS-0301": {"name": "Toa Payoh Central", "lat": 1.3326, "lng": 103.8474},
}

# Two long route traces walked straight out of Singapore in ryde-synth-v1 (a 39 km and a
# 64 km polyline on a constant bearing from Dhoby Ghaut end in Johor). Named places would
# expose that, so these two are re-walked inside Singapore. Same length to the metre, same
# point count, same timestamps; only the geography moves. Bearings per leg; the generator
# applies the same +/-6 degree wobble as build_corpus._polyline.
REWALKED_ROUTES = {
    "RD-0104": {
        "start": (1.3230, 103.6400),
        "pickup_name": "Tuas Avenue 13",
        "bearings": [83.0] * 15,
    },
    "RD-0109": {
        "start": (1.3575, 103.9880),
        "pickup_name": "Changi Airport Terminal 3",
        "bearings": [267.0] * 12 + [80.0] * 7,
    },
}

PAYMENT_METHODS = ("e-wallet", "card")


# --------------------------------------------------------------------------- geometry


def _haversine_km(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    (lat1, lng1), (lat2, lng2) = a, b
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(h))


def _walk(total_km: float, bearings: List[float], start: Tuple[float, float]) -> List[Tuple[float, float]]:
    leg_km = total_km / len(bearings)
    lat, lng = start
    out = [(round(lat, 6), round(lng, 6))]
    for index, bearing in enumerate(bearings):
        heading = math.radians(bearing + (6.0 if index % 2 == 0 else -6.0))
        d = leg_km / EARTH_RADIUS_KM
        p1, l1 = math.radians(lat), math.radians(lng)
        p2 = math.asin(math.sin(p1) * math.cos(d) + math.cos(p1) * math.sin(d) * math.cos(heading))
        l2 = l1 + math.atan2(
            math.sin(heading) * math.sin(d) * math.cos(p1),
            math.cos(d) - math.sin(p1) * math.sin(p2),
        )
        lat, lng = math.degrees(p2), math.degrees(l2)
        out.append((round(lat, 6), round(lng, 6)))
    return out


def _route_length_km(points: List[Dict[str, Any]]) -> float:
    return sum(
        _haversine_km((points[i]["lat"], points[i]["lng"]), (points[i + 1]["lat"], points[i + 1]["lng"]))
        for i in range(len(points) - 1)
    )


def _ts(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _iso(value: datetime) -> str:
    return value.isoformat()


# ------------------------------------------------------------------------------ prose


def load_prose() -> Dict[str, Dict[str, str]]:
    if not PROSE_PATH.is_file():
        raise SystemExit("missing %s: the organiser pack needs its reviewed prose file" % PROSE_PATH)
    return json.loads(PROSE_PATH.read_text(encoding="utf-8"))


_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_NUMBER_WORDS = (
    "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
    "eleven", "twelve", "fifteen", "twenty", "thirty", "half",
)


def check_description(dispute_id: str, description: str, record: Dict[str, Any]) -> None:
    """Refuse a description that introduces a number its claim and intake never state.

    A model wrote these. A number it invented would read as evidence to the agents (a
    waited-10-minutes the platform timestamps contradict, an amount nobody claimed), so
    every digit and number word must already appear in the filer's own words.
    """
    source = " ".join(
        [record["claim"]["text"]] + [str(v) for v in record.get("intake", {}).values()]
    ).lower()
    for number in _NUMBER.findall(description):
        if number not in source:
            raise SystemExit("%s: description introduces the number %r" % (dispute_id, number))
    lowered = description.lower()
    for word in _NUMBER_WORDS:
        if re.search(r"\b%s\b" % word, lowered) and not re.search(r"\b%s\b" % word, source):
            raise SystemExit("%s: description introduces the number word %r" % (dispute_id, word))
    if "$" in description or "sgd" in lowered:
        raise SystemExit("%s: description states an amount" % dispute_id)


# -------------------------------------------------------------------------- blocks


def _profiles(record: Dict[str, Any], prose: Dict[str, str], index: int) -> Tuple[Dict, Dict]:
    rider = record["profiles"]["rider"]
    driver = record["profiles"]["driver"]
    rider_profile = {
        "rider_id": rider["party_id"],
        "name": prose["rider_name"],
        "account_age_days": rider["account_age_days"],
        "total_trips": rider["trips_completed"],
        "avg_rating": rider["rating"],
        "dispute_history": {
            "total_disputes": rider["disputes_total"],
            "upheld": rider["disputes_upheld"],
            "rejected": rider["disputes_total"] - rider["disputes_upheld"],
        },
        # Our corpus records no fraud flags, and inventing one would be new evidence the
        # ryde-synth-v1 twin does not carry. Zero, stated rather than omitted.
        "fraud_flags": 0,
        "payment_method": PAYMENT_METHODS[index % 2],
    }
    driver_profile = {
        "driver_id": driver["party_id"],
        "name": prose["driver_name"],
        "account_age_days": driver["account_age_days"],
        "total_trips": driver["trips_completed"],
        "avg_rating": driver["rating"],
        "dispute_history": {
            "total_disputes": driver["disputes_total"],
            "upheld_against": driver["disputes_upheld"],
            "rejected": driver["disputes_total"] - driver["disputes_upheld"],
        },
        "fraud_flags": 0,
        "vehicle": prose["vehicle"],
    }
    return rider_profile, driver_profile


def _chat(record: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [
        {"timestamp": m["t"], "sender": m["sender"], "type": "message", "content": m["text"]}
        for m in record.get("chat_log", [])
    ]


def _ticket(record: Dict[str, Any], prose: Dict[str, str]) -> Dict[str, Any]:
    return {
        "dispute_id": record["dispute_id"],
        "trip_id": record["trip"]["trip_id"],
        "filed_by": record["filed_by"],
        "dispute_type": record["category"],
        "description": prose["description"],
        "filed_at": record["filed_at"],
        "status": "open",
    }


def _extensions(record: Dict[str, Any]) -> Dict[str, Any]:
    ext: Dict[str, Any] = {
        "_note": (
            "Fields our corpus carries that the organiser sample has no slot for. A reader "
            "that only knows the organiser schema can ignore this block."
        ),
        "claim": dict(record["claim"]),
        "intake": dict(record.get("intake", {})),
        "service_type": record["trip"].get("service_type"),
    }
    cancellation = record.get("cancellation")
    if cancellation is not None:
        ext["rider_claims_driver_absent"] = cancellation["rider_claims_driver_absent"]
    return ext


def _route_case(record: Dict[str, Any], prose: Dict[str, str], index: int) -> Dict[str, Any]:
    trip = record["trip"]
    dispute_id = record["dispute_id"]
    route = trip["actual_route"]

    if dispute_id in REWALKED_ROUTES:
        spec = REWALKED_ROUTES[dispute_id]
        original_km = _route_length_km(route)
        coords = _walk(original_km, spec["bearings"], spec["start"])
        if len(coords) != len(route):
            raise SystemExit("%s: re-walked trace has %d points, original %d" % (dispute_id, len(coords), len(route)))
        route = [{"lat": lat, "lng": lng, "t": route[i]["t"]} for i, (lat, lng) in enumerate(coords)]
        drift_m = abs(_route_length_km(route) - original_km) * 1000
        if drift_m > 1.0:
            raise SystemExit("%s: re-walked trace drifts %.2f m from the original length" % (dispute_id, drift_m))
        pickup_name = spec["pickup_name"]
    else:
        pickup_name = DHOBY_GHAUT["name"]

    telemetry = []
    for i, point in enumerate(route):
        if i == 0:
            speed, status = 0, "picked_up"
        else:
            prev = route[i - 1]
            km = _haversine_km((prev["lat"], prev["lng"]), (point["lat"], point["lng"]))
            hours = (_ts(point["t"]) - _ts(prev["t"])).total_seconds() / 3600.0
            speed = int(round(km / hours)) if hours > 0 else 0
            status = "dropped_off" if i == len(route) - 1 else "on_trip"
        telemetry.append(
            {"timestamp": point["t"], "lat": point["lat"], "lng": point["lng"], "speed_kmh": speed, "status": status}
        )

    trip_data: Dict[str, Any] = {
        "trip_id": trip["trip_id"],
        "rider_id": trip["rider_id"],
        "driver_id": trip["driver_id"],
        "pickup_location": {"name": pickup_name, "lat": route[0]["lat"], "lng": route[0]["lng"]},
        "dropoff_location": {
            "name": ROUTE_DROPOFF_NAMES[dispute_id],
            "lat": route[-1]["lat"],
            "lng": route[-1]["lng"],
        },
        "requested_time": trip["requested_at"],
        "pickup_time": trip["pickup_at"],
        "dropoff_time": trip["dropoff_at"],
        "estimated_duration_min": trip["estimated_duration_min"],
    }
    if "estimated_distance_km" in trip:
        trip_data["estimated_distance_km"] = trip["estimated_distance_km"]
    trip_data["fare"] = trip["fare"]

    charged = trip["fare"]["charged_sgd"]
    events = [
        {
            "timestamp": trip["requested_at"],
            "event_type": "booking_confirmed",
            "details": "Rider %s booked trip %s from %s to %s."
            % (trip["rider_id"], trip["trip_id"], pickup_name, ROUTE_DROPOFF_NAMES[dispute_id]),
        },
        {
            "timestamp": trip["pickup_at"],
            "event_type": "trip_started",
            "details": "Rider picked up. Live tracking enabled.",
        },
        {
            "timestamp": trip["dropoff_at"],
            "event_type": "trip_completed",
            "details": "Rider dropped off. Trip status: completed.",
        },
        {
            "timestamp": trip["dropoff_at"],
            "event_type": "fare_charged",
            "details": "$%.2f charged to rider payment method." % charged,
        },
    ]

    rider_profile, driver_profile = _profiles(record, prose, index)
    return {
        "dispute_ticket": _ticket(record, prose),
        "rider_profile": rider_profile,
        "driver_profile": driver_profile,
        "trip_data": trip_data,
        "gps_telemetry": telemetry,
        "chat_logs": _chat(record),
        "app_events": events,
        "ryde_extensions": _extensions(record),
    }


def _no_show_case(record: Dict[str, Any], prose: Dict[str, str], index: int) -> Dict[str, Any]:
    trip = record["trip"]
    dispute_id = record["dispute_id"]
    cancellation = record.get("cancellation")
    destination = NO_SHOW_DESTINATIONS[dispute_id]
    pickup = dict(ORCHARD_BOULEVARD)

    trip_data: Dict[str, Any] = {
        "trip_id": trip["trip_id"],
        "rider_id": trip["rider_id"],
        "driver_id": trip["driver_id"],
        "pickup_location": pickup,
        "dropoff_location": dict(destination),
        "requested_time": trip["requested_at"],
    }
    events: List[Dict[str, Any]] = [
        {
            "timestamp": trip["requested_at"],
            "event_type": "booking_confirmed",
            "details": "Rider %s booked trip %s from %s to %s."
            % (trip["rider_id"], trip["trip_id"], pickup["name"], destination["name"]),
        }
    ]
    telemetry: List[Dict[str, Any]] = []

    if cancellation is None:
        # OS-0301: the out-of-scope case has no cancellation facts at all.
        pass
    else:
        matched = cancellation["matched_at"]
        events.append(
            {
                "timestamp": matched,
                "event_type": "driver_assigned",
                "details": "Driver %s (%s) assigned." % (trip["driver_id"], prose["vehicle"]),
            }
        )
        arrived = cancellation.get("driver_arrived_at")
        wait_start = cancellation.get("wait_started_at")
        end = cancellation["cancelled_at"]
        fee = cancellation["cancellation_fee_sgd"]
        # NS-0207 is a waiting fee on a trip that went ahead: the wait ends with the rider
        # boarding, not with a cancellation, and the fee is a waiting fee.
        trip_went_ahead = dispute_id == "NS-0207"

        if arrived:
            trip_data["driver_arrival_time"] = arrived
        if wait_start:
            trip_data["driver_wait_start"] = wait_start
        if trip_went_ahead:
            trip_data["rider_boarded_time"] = end
            trip_data["waiting_fee"] = fee
        else:
            trip_data["cancellation_time"] = end
            trip_data["cancellation_fee"] = fee
            if cancellation["driver_marked_no_show"]:
                trip_data["cancellation_reason"] = "rider_no_show"
            else:
                trip_data["cancellation_reason"] = "rider_cancelled"

        if arrived:
            events.append(
                {
                    "timestamp": arrived,
                    "event_type": "driver_arrived",
                    "details": "Driver marked arrival (\"I'm Here\").",
                }
            )
        if wait_start:
            events.append(
                {"timestamp": wait_start, "event_type": "wait_timer_started", "details": "Wait timer started."}
            )
        if trip_went_ahead:
            events.append({"timestamp": end, "event_type": "rider_boarded", "details": "Rider boarded. Trip started."})
            events.append(
                {
                    "timestamp": end,
                    "event_type": "waiting_fee_applied",
                    "details": "$%.2f waiting fee added to the trip fare." % fee,
                }
            )
        else:
            who = "driver" if cancellation["driver_marked_no_show"] else "rider"
            events.append(
                {
                    "timestamp": end,
                    "event_type": "trip_cancelled",
                    "details": "Trip cancelled by %s. Reason: %s." % (who, trip_data["cancellation_reason"]),
                }
            )
            if fee:
                events.append(
                    {
                        "timestamp": end,
                        "event_type": "cancellation_fee_applied",
                        "details": "$%.2f cancellation fee charged to rider payment method." % fee,
                    }
                )

        # Telemetry exists only where ryde-synth-v1 recorded the driver's position at
        # arrival. Where it did not (NS-0204, NS-0205, NS-0206) the organiser pack has none
        # either: an invented trace would be evidence the twin case does not contain.
        gps = cancellation.get("driver_gps_at_arrival")
        if gps and arrived:
            arrived_t = _ts(arrived)
            end_t = _ts(end)
            # Approach from due north along the same meridian, so the arrival point stays
            # exactly where ryde-synth-v1 put it.
            for minutes_before, km_north, speed in ((5, 1.6, 34), (2, 0.5, 14)):
                telemetry.append(
                    {
                        "timestamp": _iso(arrived_t - timedelta(minutes=minutes_before)),
                        "lat": round(gps["lat"] + km_north / 110.574, 6),
                        "lng": gps["lng"],
                        "speed_kmh": speed,
                        "status": "en_route",
                    }
                )
            telemetry.append(
                {"timestamp": arrived, "lat": gps["lat"], "lng": gps["lng"], "speed_kmh": 0, "status": "arrived"}
            )
            tick = arrived_t + timedelta(minutes=2)
            while tick < end_t:
                telemetry.append(
                    {"timestamp": _iso(tick), "lat": gps["lat"], "lng": gps["lng"], "speed_kmh": 0, "status": "waiting"}
                )
                tick += timedelta(minutes=2)
            telemetry.append(
                {
                    "timestamp": end,
                    "lat": gps["lat"],
                    "lng": gps["lng"],
                    "speed_kmh": 0,
                    "status": "rider_boarded" if trip_went_ahead else "cancelled",
                }
            )

    events.sort(key=lambda e: e["timestamp"])
    rider_profile, driver_profile = _profiles(record, prose, index)
    out: Dict[str, Any] = {
        "dispute_ticket": _ticket(record, prose),
        "rider_profile": rider_profile,
        "driver_profile": driver_profile,
        "trip_data": trip_data,
        "gps_telemetry": telemetry,
        "chat_logs": _chat(record),
        "app_events": events,
    }
    if cancellation is not None:
        out["cancellation_policy"] = dict(RYDE_CANCELLATION_POLICY)
    out["ryde_extensions"] = _extensions(record)
    return out


def to_organiser_record(record: Dict[str, Any], prose: Dict[str, str], index: int) -> Dict[str, Any]:
    check_description(record["dispute_id"], prose["description"], record)
    if record["category"] == "route_deviation":
        return _route_case(record, prose, index)
    return _no_show_case(record, prose, index)


# ------------------------------------------------------------------ organiser samples


def organiser_samples() -> List[Tuple[str, str]]:
    """(dispute_id, exact JSON text) for each organiser-supplied sample under tools/.

    The JSON is lifted byte-for-byte from the fenced block in the organisers' markdown, so
    the pack carries their record unmodified. The surrounding markdown states the expected
    ruling, which is why the markdown stays in tools/ and never enters the pack.
    """
    out = []
    for path in sorted(SAMPLES_DIR.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        match = re.search(r"```json\n(.*?)```", text, re.S)
        if not match:
            raise SystemExit("%s: no ```json block found" % path)
        raw = match.group(1)
        dispute_id = json.loads(raw)["dispute_ticket"]["dispute_id"]
        out.append((dispute_id, raw))
    return out


# The organisers' sample states its expected ruling in prose. Recorded here in our label
# shape so an evaluation can score it; the reasoning is ours and says where it is fragile.
ORGANISER_LABELS = {
    "DISP-002": {
        "dispute_id": "DISP-002",
        "category": "no_show_charge",
        "expected_outcome": "ruled",
        "expected_action": "no action",
        "expected_amount_sgd": 0.0,
        "decisive_rule_ids": ["NS-2", "NS-3", "NS-6"],
        "label_source": "organiser (sample states: Cancellation charge UPHELD)",
        "rationale": (
            "Contested no-show settled by telemetry, as NS-6 requires: the driver's arrival "
            "point is the booked pickup point (0 m, NS-3) and the driver waited 8.0 minutes "
            "from arrival (08:43) to cancellation (08:51). The case carries its own "
            "cancellation_policy (5 min free wait, 8 min no-show threshold, $5.00 fee), which "
            "supersedes the Ryde parameters for this trip. Two fragilities a correct ruling "
            "must handle explicitly: the wait EQUALS the 8-minute threshold rather than "
            "exceeding it (the sample's own event log treats reaching it as sufficient), and "
            "the booking was scheduled for 08:45, so measured from the scheduled time the "
            "wait is only 6 minutes. The charge stands only when the wait runs from arrival."
        ),
    }
}
