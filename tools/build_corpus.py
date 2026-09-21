#!/usr/bin/env python3
"""Generate the labelled dispute corpus in data/.

NON-APP TOOL. Nothing under app/ or ui/ imports from here. Run it to regenerate the
corpus after editing the case table below:

    python3 tools/build_corpus.py          # write data/
    python3 tools/build_corpus.py --check  # regenerate into a temp dir and diff

Why a generator rather than hand-written JSON: every case carries fare arithmetic and a
GPS polyline that must agree with each other, or the Evidence Pack computes something
different from what the case intends and the ground-truth label becomes a lie. The
numbers are derived here from a few per-case parameters, so they cannot drift apart.

Ground-truth labels are written to data/ground-truth.json, deliberately NOT into the
dispute records: a label inside the input would be visible to the agents and would make
every accuracy measurement worthless.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "data"
SGT = timezone(timedelta(hours=8))
EARTH_RADIUS_KM = 6371.0088

# A central Singapore start point for generated routes (Dhoby Ghaut area).
ORIGIN = (1.2989, 103.8456)


# --------------------------------------------------------------------------- geometry


def _haversine_km(a, b) -> float:
    (lat1, lng1), (lat2, lng2) = a, b
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(h))


def _polyline(total_km: float, points: int, start=ORIGIN, bearing_deg: float = 35.0):
    """A polyline of `points` vertices whose haversine length is `total_km`.

    Built by walking a constant bearing in equal legs, with a small alternating
    cross-track offset so the trace looks like a road rather than a ruler. The offset is
    applied symmetrically, so it cancels out and the total length stays exact to within
    a metre; the caller asserts that.
    """
    legs = points - 1
    leg_km = total_km / legs
    bearing = math.radians(bearing_deg)
    lat, lng = start
    out = [(round(lat, 6), round(lng, 6))]
    for index in range(legs):
        # Nudge the bearing left then right on alternating legs: the path bends, the
        # per-leg distance does not change.
        wobble = math.radians(6.0 if index % 2 == 0 else -6.0)
        heading = bearing + wobble
        d = leg_km / EARTH_RADIUS_KM
        p1 = math.radians(lat)
        l1 = math.radians(lng)
        p2 = math.asin(math.sin(p1) * math.cos(d) + math.cos(p1) * math.sin(d) * math.cos(heading))
        l2 = l1 + math.atan2(
            math.sin(heading) * math.sin(d) * math.cos(p1),
            math.cos(d) - math.sin(p1) * math.sin(p2),
        )
        lat, lng = math.degrees(p2), math.degrees(l2)
        out.append((round(lat, 6), round(lng, 6)))
    return out


def _route_block(total_km: float, points: int, start_at: datetime, minutes: float):
    coords = _polyline(total_km, points)
    step = minutes / (len(coords) - 1)
    return [
        {
            "lat": lat,
            "lng": lng,
            "t": (start_at + timedelta(minutes=step * index)).isoformat(),
        }
        for index, (lat, lng) in enumerate(coords)
    ]


def _polyline_km(route: List[Dict[str, Any]]) -> float:
    return sum(
        _haversine_km((route[i]["lat"], route[i]["lng"]), (route[i + 1]["lat"], route[i + 1]["lng"]))
        for i in range(len(route) - 1)
    )


# ------------------------------------------------------------------------------- fare


def _fare(rates: Dict[str, float], km: float, minutes: float, promo: float = 0.0) -> Dict[str, Any]:
    """The fare for a trip of km/minutes at these rates, with a consistent breakdown.

    Mirrors the Evidence Pack's formula exactly:
        total = (base + per_km * km + per_min * minutes) * surge - promo
    The breakdown components are the same terms with surge already applied, so they sum
    to the charge and `fare.breakdown_consistent` is true.
    """
    surge = rates.get("surge_multiplier", 1.0)
    base_c = rates["base_sgd"] * surge
    dist_c = rates["per_km_sgd"] * km * surge
    time_c = rates["per_min_sgd"] * minutes * surge
    total = base_c + dist_c + time_c - promo
    breakdown = {
        "base_sgd": round(base_c, 2),
        "distance_sgd": round(dist_c, 2),
        "time_sgd": round(time_c, 2),
    }
    if promo:
        breakdown["promo_sgd"] = -round(promo, 2)
    # Absorb rounding drift into the distance component so the breakdown sums exactly.
    drift = round(total, 2) - round(sum(breakdown.values()), 2)
    if abs(drift) >= 0.01:
        breakdown["distance_sgd"] = round(breakdown["distance_sgd"] + drift, 2)
    return {"charged_sgd": round(total, 2), "breakdown": breakdown, "rates": dict(rates)}


def _raw_fare(rates: Dict[str, float], km: float, minutes: float, promo: float = 0.0) -> float:
    surge = rates.get("surge_multiplier", 1.0)
    return (rates["base_sgd"] + rates["per_km_sgd"] * km + rates["per_min_sgd"] * minutes) * surge - promo


STANDARD_RATES = {"base_sgd": 3.20, "per_km_sgd": 0.80, "per_min_sgd": 0.25, "surge_multiplier": 1.0}
SURGE_RATES = {"base_sgd": 3.20, "per_km_sgd": 0.80, "per_min_sgd": 0.25, "surge_multiplier": 1.4}

CANCELLATION_FEE = 6.61
WAITING_FEE = 5.00


# ------------------------------------------------------------------------ case builders


def route_case(
    *,
    dispute_id: str,
    actual_km: float,
    estimated_km: float,
    actual_min: float,
    estimated_min: float,
    rates: Optional[Dict[str, float]] = None,
    charge_mode: str = "actual",
    promo: float = 0.0,
    claim_text: str,
    intake: Dict[str, str],
    chat: List[Dict[str, str]],
    profiles: Dict[str, Any],
    day: int = 14,
    hour: int = 9,
    points: int = 10,
    break_breakdown: Optional[float] = None,
    drop_estimated_distance: bool = False,
    service_type: str = "RydeX",
) -> Dict[str, Any]:
    """One route-deviation dispute.

    charge_mode decides what the rider was actually billed:
      'actual'    — billed for the distance driven (deviation costs the rider)
      'quoted'    — billed the quoted fixed fare (deviation absorbed by the platform)
    """
    rates = dict(rates or STANDARD_RATES)
    pickup = datetime(2026, 9, day, hour, 30, tzinfo=SGT)
    dropoff = pickup + timedelta(minutes=actual_min)
    route = _route_block(actual_km, points, pickup, actual_min)

    if charge_mode == "quoted":
        fare = _fare(rates, estimated_km, estimated_min, promo)
    else:
        fare = _fare(rates, actual_km, actual_min, promo)

    if break_breakdown is not None:
        # An inconsistent breakdown: the components no longer sum to the charge.
        fare["charged_sgd"] = round(fare["charged_sgd"] + break_breakdown, 2)

    delta = _raw_fare(rates, actual_km, actual_min, promo) - _raw_fare(
        rates, estimated_km, estimated_min, promo
    )

    trip: Dict[str, Any] = {
        "trip_id": "T-%s" % dispute_id.replace("-", ""),
        "rider_id": profiles["rider"]["party_id"],
        "driver_id": profiles["driver"]["party_id"],
        "service_type": service_type,
        "requested_at": (pickup - timedelta(minutes=4)).isoformat(),
        "pickup_at": pickup.isoformat(),
        "dropoff_at": dropoff.isoformat(),
        "estimated_duration_min": estimated_min,
        "estimated_distance_km": estimated_km,
        "actual_route": route,
        "fare": fare,
    }
    if drop_estimated_distance:
        del trip["estimated_distance_km"]

    return {
        "dispute_id": dispute_id,
        "category": "route_deviation",
        "filed_by": "rider",
        "filed_at": (dropoff + timedelta(hours=2)).isoformat(),
        "claim": {"text": claim_text, "amount_sgd": round(max(delta, 0.0), 2)},
        "intake": intake,
        "trip": trip,
        "chat_log": chat,
        "profiles": profiles,
    }


def no_show_case(
    *,
    dispute_id: str,
    wait_minutes: float,
    driver_distance_m: Optional[float],
    fee: float,
    driver_marked_no_show: bool,
    rider_claims_driver_absent: bool,
    claim_text: str,
    intake: Dict[str, str],
    chat: List[Dict[str, str]],
    profiles: Dict[str, Any],
    filed_by: str = "rider",
    day: int = 14,
    hour: int = 19,
    matched_to_cancel_min: Optional[float] = None,
    driver_arrived: bool = True,
    service_type: str = "RydeX",
) -> Dict[str, Any]:
    """One no-show / cancellation-fee dispute.

    driver_distance_m is the driver's distance from the booked pickup point when they
    marked arrival; the two coordinates are placed that far apart so the Evidence Pack
    recomputes the same number rather than trusting a stated one.
    """
    matched = datetime(2026, 9, day, hour, 0, tzinfo=SGT)
    # Booking happens before matching. Keeping them distinct matters: NS-1's free window
    # runs from matching, and a corpus where the two coincide would never exercise the
    # difference, so a proxy measuring from booking would look correct here and be wrong
    # in production.
    requested = matched - timedelta(seconds=40)
    arrived = matched + timedelta(minutes=6)
    cancelled = arrived + timedelta(minutes=wait_minutes)
    if matched_to_cancel_min is not None:
        cancelled = matched + timedelta(minutes=matched_to_cancel_min)

    pickup_point = {"lat": 1.3048, "lng": 103.8318}
    cancellation: Dict[str, Any] = {
        "cancelled_at": cancelled.isoformat(),
        "matched_at": matched.isoformat(),
        "cancellation_fee_sgd": fee,
        "driver_marked_no_show": driver_marked_no_show,
        "rider_claims_driver_absent": rider_claims_driver_absent,
        "pickup_point": pickup_point,
    }
    if driver_arrived:
        cancellation["driver_arrived_at"] = arrived.isoformat()
        cancellation["wait_started_at"] = arrived.isoformat()
    if driver_distance_m is not None:
        # Offset purely in latitude: 1 degree of latitude is ~110.574 km everywhere.
        offset_deg = (driver_distance_m / 1000.0) / 110.574
        cancellation["driver_gps_at_arrival"] = {
            "lat": round(pickup_point["lat"] + offset_deg, 6),
            "lng": pickup_point["lng"],
        }

    return {
        "dispute_id": dispute_id,
        "category": "no_show_charge",
        "filed_by": filed_by,
        "filed_at": (cancelled + timedelta(hours=1)).isoformat(),
        "claim": {"text": claim_text, "amount_sgd": fee},
        "intake": intake,
        "trip": {
            "trip_id": "T-%s" % dispute_id.replace("-", ""),
            "rider_id": profiles["rider"]["party_id"],
            "driver_id": profiles["driver"]["party_id"],
            "service_type": service_type,
            "requested_at": requested.isoformat(),
            "fare": {"charged_sgd": fee, "breakdown": {"cancellation_sgd": fee}},
        },
        "cancellation": cancellation,
        "chat_log": chat,
        "profiles": profiles,
    }


def profile(rider_id: str, driver_id: str, **overrides) -> Dict[str, Any]:
    rider = {
        "party_id": rider_id,
        "account_age_days": 640,
        "trips_completed": 180,
        "disputes_total": 2,
        "disputes_upheld": 1,
        "rating": 4.8,
    }
    driver = {
        "party_id": driver_id,
        "account_age_days": 1100,
        "trips_completed": 4200,
        "disputes_total": 5,
        "disputes_upheld": 1,
        "rating": 4.72,
    }
    rider.update(overrides.get("rider", {}))
    driver.update(overrides.get("driver", {}))
    return {"rider": rider, "driver": driver}


# ------------------------------------------------------------------------- the corpus


def build_cases() -> List[Dict[str, Any]]:
    """Every case, paired with its ground-truth label and the reasoning behind it."""
    cases: List[Dict[str, Any]] = []

    def add(record, *, outcome, action, rules, amount=None, rationale):
        cases.append(
            {
                "record": record,
                "label": {
                    "dispute_id": record["dispute_id"],
                    "category": record["category"],
                    "expected_outcome": outcome,
                    "expected_action": action,
                    "expected_amount_sgd": amount,
                    "decisive_rule_ids": rules,
                    "rationale": rationale,
                },
            }
        )

    # -- route deviation ---------------------------------------------------------

    add(
        route_case(
            dispute_id="RD-0101",
            actual_km=9.6,
            estimated_km=6.4,
            actual_min=31,
            estimated_min=18,
            claim_text="The driver took a much longer way round and I paid more than the app quoted.",
            intake={
                "what_went_wrong": "Driver ignored the route in the app and drove a long way round.",
                "expected_route": "The app showed about 6.4 km via the expressway.",
                "was_route_agreed": "No",
                "asked_driver_to_stop": "No",
                "safety_concern": "No",
            },
            chat=[
                {"t": "2026-09-14T09:32:00+08:00", "sender": "rider", "text": "Why are we going this way? The app showed the expressway."},
                {"t": "2026-09-14T09:34:00+08:00", "sender": "driver", "text": "This way is better."},
                {"t": "2026-09-14T09:55:00+08:00", "sender": "rider", "text": "This is much longer than the estimate."},
            ],
            profiles=profile("R-5001", "D-2001"),
        ),
        outcome="ruled",
        action="refund",
        amount=5.81,
        rules=["RD-1", "RD-2", "RD-3"],
        rationale=(
            "50% / 3.2 km deviation clears both limbs of RD-1. The rider questioned the route "
            "while it was happening and the driver gave no reason RD-2 recognises, so the "
            "deviation is unjustified and the fare delta is refunded."
        ),
    )

    add(
        route_case(
            dispute_id="RD-0102",
            actual_km=11.2,
            estimated_km=7.0,
            actual_min=29,
            estimated_min=19,
            claim_text="Fare was higher than quoted.",
            intake={
                "what_went_wrong": "Final fare was more than the app quoted at booking.",
                "expected_route": "Direct route to the original drop-off.",
                "was_route_agreed": "Yes, I asked him to drop my colleague first.",
                "asked_driver_to_stop": "Yes, I added a stop",
                "safety_concern": "No",
            },
            chat=[
                {"t": "2026-09-14T09:33:00+08:00", "sender": "rider", "text": "Can we stop at Buona Vista first to drop my colleague?"},
                {"t": "2026-09-14T09:33:40+08:00", "sender": "driver", "text": "Ok no problem."},
                {"t": "2026-09-14T09:58:00+08:00", "sender": "rider", "text": "Thanks."},
            ],
            profiles=profile("R-5002", "D-2002"),
        ),
        outcome="ruled",
        action="no action",
        amount=0.0,
        rules=["RD-1", "RD-2"],
        rationale=(
            "The deviation is material, but the rider asked for the extra stop in the chat and "
            "confirmed it on the intake form. RD-2 makes an agreed route change a justified "
            "deviation, so the higher fare stands."
        ),
    )

    add(
        route_case(
            dispute_id="RD-0103",
            actual_km=5.3,
            estimated_km=5.0,
            actual_min=17,
            estimated_min=15,
            claim_text="Driver did not take the exact route in the app.",
            intake={
                "what_went_wrong": "The route was not identical to the one the app showed.",
                "expected_route": "The route the app displayed at booking.",
                "was_route_agreed": "No",
                "asked_driver_to_stop": "No",
                "safety_concern": "No",
            },
            chat=[
                {"t": "2026-09-14T09:47:00+08:00", "sender": "driver", "text": "We are here, thank you."},
            ],
            profiles=profile("R-5003", "D-2003", rider={"disputes_total": 9, "disputes_upheld": 1, "trips_completed": 60}),
        ),
        outcome="ruled",
        action="no action",
        amount=0.0,
        rules=["RD-1"],
        rationale=(
            "6% / 0.3 km is below both limbs of RD-1, so the deviation is immaterial and no "
            "remedy arises. The rider's high dispute rate is context only and is not the reason "
            "the claim fails (GEN-8)."
        ),
    )

    add(
        route_case(
            dispute_id="RD-0104",
            actual_km=39.0,
            estimated_km=32.5,
            actual_min=54,
            estimated_min=44,
            claim_text="Long airport trip went well out of the way and cost more.",
            intake={
                "what_went_wrong": "Driver left the expressway and went a long way round.",
                "expected_route": "Direct expressway route to the airport.",
                "was_route_agreed": "No",
                "asked_driver_to_stop": "No",
                "safety_concern": "No",
            },
            chat=[
                {"t": "2026-09-14T09:52:00+08:00", "sender": "rider", "text": "Why did we come off the expressway?"},
                {"t": "2026-09-14T09:54:00+08:00", "sender": "driver", "text": "Ok."},
            ],
            profiles=profile("R-5004", "D-2004"),
            points=16,
            service_type="RydeXL",
        ),
        outcome="ruled",
        action="refund",
        amount=7.70,
        rules=["RD-1", "RD-3"],
        rationale=(
            "20% is at the first limb's threshold but 6.5 km independently clears RD-1's gross "
            "limb, which exists precisely for long trips where a percentage understates the "
            "detour. Unjustified, so the delta is refunded."
        ),
    )

    add(
        route_case(
            dispute_id="RD-0105",
            actual_km=10.4,
            estimated_km=7.2,
            actual_min=33,
            estimated_min=21,
            charge_mode="quoted",
            claim_text="The driver took a longer route, I want the extra distance refunded.",
            intake={
                "what_went_wrong": "Driver drove much further than the app route.",
                "expected_route": "About 7 km direct.",
                "was_route_agreed": "No",
                "asked_driver_to_stop": "No",
                "safety_concern": "No",
            },
            chat=[
                {"t": "2026-09-14T09:40:00+08:00", "sender": "rider", "text": "This is not the way the app showed."},
                {"t": "2026-09-14T09:41:00+08:00", "sender": "driver", "text": "Traffic."},
            ],
            profiles=profile("R-5005", "D-2005"),
        ),
        outcome="ruled",
        action="no action",
        amount=0.0,
        rules=["RD-1", "RD-4"],
        rationale=(
            "The deviation is material and unjustified, but the rider was charged the quoted "
            "fixed fare: charged_sgd equals recomputed_estimated_route_sgd. RD-4 says a rider "
            "who paid the quoted price was not overcharged. The routing is recorded under GEN-7."
        ),
    )

    add(
        route_case(
            dispute_id="RD-0106",
            actual_km=8.2,
            estimated_km=8.0,
            actual_min=24,
            estimated_min=22,
            break_breakdown=3.40,
            claim_text="The receipt does not add up. I was charged more than the parts listed.",
            intake={
                "what_went_wrong": "The total on my receipt is more than the items listed on it.",
                "expected_route": "Route was fine, the problem is the bill.",
                "was_route_agreed": "Yes",
                "asked_driver_to_stop": "No",
                "safety_concern": "No",
            },
            chat=[
                {"t": "2026-09-14T09:54:00+08:00", "sender": "rider", "text": "Thanks."},
            ],
            profiles=profile("R-5006", "D-2006"),
        ),
        outcome="ruled",
        action="refund",
        amount=3.40,
        rules=["EV-3", "RD-5"],
        rationale=(
            "No material deviation, but the breakdown does not sum to the amount charged "
            "(breakdown_consistent is false) and the charge exceeds the recomputed fare by the "
            "same 3.40. RD-5 refunds a pricing error independent of routing; fare accuracy is "
            "the operator's responsibility, not the driver's."
        ),
    )

    add(
        route_case(
            dispute_id="RD-0107",
            actual_km=7.3,
            estimated_km=7.1,
            actual_min=41,
            estimated_min=22,
            claim_text="Trip took nearly twice as long as the estimate and cost more.",
            intake={
                "what_went_wrong": "The trip took far longer than the app said it would.",
                "expected_route": "Same route, but it should have been about 22 minutes.",
                "was_route_agreed": "Yes",
                "asked_driver_to_stop": "No",
                "safety_concern": "No",
            },
            chat=[
                {"t": "2026-09-14T09:50:00+08:00", "sender": "rider", "text": "Traffic is terrible today."},
                {"t": "2026-09-14T09:51:00+08:00", "sender": "driver", "text": "Yes, accident ahead. Sorry."},
            ],
            profiles=profile("R-5007", "D-2007"),
        ),
        outcome="ruled",
        action="no action",
        amount=0.0,
        rules=["RD-1", "RD-6"],
        rationale=(
            "86% duration overrun with a 3% distance variance. RD-6: a trip that took longer "
            "without travelling further is a traffic outcome, and the chat shows both parties "
            "attributing it to an accident. The time charge stands."
        ),
    )

    add(
        route_case(
            dispute_id="RD-0108",
            actual_km=12.5,
            estimated_km=8.0,
            actual_min=36,
            estimated_min=22,
            drop_estimated_distance=True,
            claim_text="I think the driver went a long way round but I am not sure what was quoted.",
            intake={
                "what_went_wrong": "The trip felt much longer than it should have been.",
                "expected_route": "I do not remember what the app showed.",
                "was_route_agreed": "No",
                "asked_driver_to_stop": "No",
                "safety_concern": "No",
            },
            chat=[
                {"t": "2026-09-14T09:58:00+08:00", "sender": "rider", "text": "That felt longer than it should be."},
            ],
            profiles=profile("R-5008", "D-2008"),
        ),
        outcome="escalated",
        action=None,
        amount=None,
        rules=["EV-1", "ESC-2"],
        rationale=(
            "The record has no estimated distance, so route.deviation_km and deviation_pct are "
            "both null and RD-1 cannot be tested. EV-1 requires all three inputs; ESC-2 sends it "
            "to a human rather than inventing a baseline."
        ),
    )

    add(
        route_case(
            dispute_id="RD-0109",
            actual_km=64.0,
            estimated_km=31.0,
            actual_min=104,
            estimated_min=52,
            rates=SURGE_RATES,
            claim_text="Driver drove nearly twice the distance on a long surge-priced trip.",
            intake={
                "what_went_wrong": "Driver went a very long way round on an already expensive trip.",
                "expected_route": "About 31 km direct.",
                "was_route_agreed": "No",
                "asked_driver_to_stop": "No",
                "safety_concern": "No",
            },
            chat=[
                {"t": "2026-09-14T10:10:00+08:00", "sender": "rider", "text": "Where are we going? This is not the route."},
                {"t": "2026-09-14T10:12:00+08:00", "sender": "driver", "text": "Ok."},
                {"t": "2026-09-14T11:00:00+08:00", "sender": "rider", "text": "I will report this, it is unacceptable."},
            ],
            profiles=profile("R-5009", "D-2009"),
            points=20,
        ),
        outcome="escalated",
        action=None,
        amount=None,
        rules=["RD-1", "RD-3", "ESC-4"],
        rationale=(
            "The deviation is material and unjustified and the delta exceeds the SGD 50 "
            "autonomous cap, so ESC-4 prepares the ruling as a recommendation but sends it to a "
            "human. The merits are clear; the amount is what withholds it."
        ),
    )

    # -- no-show / cancellation fee ---------------------------------------------

    add(
        no_show_case(
            dispute_id="NS-0201",
            wait_minutes=5.5,
            driver_distance_m=18.0,
            fee=CANCELLATION_FEE,
            driver_marked_no_show=True,
            rider_claims_driver_absent=True,
            claim_text="I was charged a no-show fee but I was on my way down.",
            intake={
                "what_went_wrong": "Charged a cancellation fee when I was coming down to the lobby.",
                "where_were_you": "In the lift, about 2 minutes away.",
                "did_driver_contact_you": "He messaged that he had arrived.",
                "safety_concern": "No",
            },
            chat=[
                {"t": "2026-09-14T19:06:00+08:00", "sender": "driver", "text": "I am here at the lobby."},
                {"t": "2026-09-14T19:09:00+08:00", "sender": "driver", "text": "Hello, are you coming?"},
                {"t": "2026-09-14T19:11:00+08:00", "sender": "driver", "text": "I have waited more than 5 minutes, I need to cancel."},
            ],
            profiles=profile("R-6001", "D-3001"),
        ),
        outcome="ruled",
        action="no action",
        amount=0.0,
        rules=["NS-1", "NS-2", "NS-3"],
        rationale=(
            "The driver was 18 m from the booked pickup point and waited 5.5 minutes, so both "
            "preconditions in NS-2 and NS-3 are met and the fee was earned. The rider being "
            "nearly ready does not unmake a valid charge."
        ),
    )

    add(
        no_show_case(
            dispute_id="NS-0202",
            wait_minutes=1.5,
            driver_distance_m=25.0,
            fee=CANCELLATION_FEE,
            driver_marked_no_show=True,
            rider_claims_driver_absent=False,
            claim_text="The driver cancelled almost immediately and I was still charged.",
            intake={
                "what_went_wrong": "Driver cancelled about a minute after saying he arrived.",
                "where_were_you": "Walking out of the building, I could see the car.",
                "did_driver_contact_you": "One message, then he cancelled.",
                "safety_concern": "No",
            },
            chat=[
                {"t": "2026-09-14T19:06:00+08:00", "sender": "driver", "text": "Arrived."},
                {"t": "2026-09-14T19:07:20+08:00", "sender": "rider", "text": "Coming now, 30 seconds."},
            ],
            profiles=profile("R-6002", "D-3002", driver={"disputes_total": 14, "disputes_upheld": 6}),
        ),
        outcome="ruled",
        action="refund",
        amount=CANCELLATION_FEE,
        rules=["NS-2", "GEN-3"],
        rationale=(
            "The driver was at the pickup point but waited only 1.5 minutes, short of the 3 "
            "minutes NS-2 requires. Under GEN-3 the records must positively support the charge; "
            "here they refute it, so the fee is refunded in full."
        ),
    )

    add(
        no_show_case(
            dispute_id="NS-0203",
            wait_minutes=7.0,
            driver_distance_m=880.0,
            fee=CANCELLATION_FEE,
            driver_marked_no_show=True,
            rider_claims_driver_absent=True,
            claim_text="The driver never came to the pickup point but charged me a no-show.",
            intake={
                "what_went_wrong": "Driver said he arrived but he was never outside my block.",
                "where_were_you": "Standing at the pickup point the whole time.",
                "did_driver_contact_you": "No calls, just the arrival notification.",
                "safety_concern": "No",
            },
            chat=[
                {"t": "2026-09-14T19:06:00+08:00", "sender": "driver", "text": "I have arrived."},
                {"t": "2026-09-14T19:08:00+08:00", "sender": "rider", "text": "I am at the pickup point and you are not here."},
                {"t": "2026-09-14T19:10:00+08:00", "sender": "rider", "text": "I can see the map, you did not arrive."},
            ],
            profiles=profile("R-6003", "D-3003", driver={"disputes_total": 22, "disputes_upheld": 11, "rating": 4.55}),
        ),
        outcome="ruled",
        action="refund",
        amount=CANCELLATION_FEE,
        rules=["NS-3", "GEN-7"],
        rationale=(
            "The driver marked arrival 880 m from the booked pickup point, well beyond the 500 m "
            "limit in NS-3, so the wait never started and the fee is invalid however long the "
            "clock ran. The pattern is flagged under GEN-7 for the platform's own enforcement."
        ),
    )

    add(
        no_show_case(
            dispute_id="NS-0204",
            wait_minutes=0.0,
            driver_distance_m=None,
            driver_arrived=False,
            fee=CANCELLATION_FEE,
            driver_marked_no_show=False,
            rider_claims_driver_absent=True,
            matched_to_cancel_min=22.0,
            claim_text="The driver never arrived and I was charged for cancelling.",
            intake={
                "what_went_wrong": "Waited 20 minutes, driver never moved towards me, so I cancelled.",
                "where_were_you": "At the pickup point from the start.",
                "did_driver_contact_you": "No response to any message.",
                "safety_concern": "No",
            },
            chat=[
                {"t": "2026-09-14T19:08:00+08:00", "sender": "rider", "text": "Are you on the way?"},
                {"t": "2026-09-14T19:15:00+08:00", "sender": "rider", "text": "You have not moved for 10 minutes."},
                {"t": "2026-09-14T19:20:00+08:00", "sender": "rider", "text": "I am cancelling, you never arrived."},
            ],
            profiles=profile("R-6004", "D-3004", driver={"disputes_total": 18, "disputes_upheld": 9}),
        ),
        outcome="ruled",
        action="refund",
        amount=CANCELLATION_FEE,
        rules=["NS-4", "GEN-3"],
        rationale=(
            "No arrival was ever recorded and the driver never marked a no-show. Under NS-4 a "
            "rider whose driver did not arrive owes nothing, and the fee is refunded. The "
            "stationary-and-unresponsive pattern is recorded under GEN-7."
        ),
    )

    add(
        no_show_case(
            dispute_id="NS-0205",
            wait_minutes=4.0,
            driver_distance_m=None,
            fee=CANCELLATION_FEE,
            driver_marked_no_show=True,
            rider_claims_driver_absent=True,
            claim_text="Driver says I did not show up, I say he was not there.",
            intake={
                "what_went_wrong": "I was at the pickup point and the driver was not.",
                "where_were_you": "At the taxi stand as booked.",
                "did_driver_contact_you": "He messaged that he was waiting, I did not see him.",
                "safety_concern": "No",
            },
            chat=[
                {"t": "2026-09-14T19:06:00+08:00", "sender": "driver", "text": "Waiting at the pickup."},
                {"t": "2026-09-14T19:08:00+08:00", "sender": "rider", "text": "I am at the stand, I do not see you."},
                {"t": "2026-09-14T19:09:00+08:00", "sender": "driver", "text": "I am here."},
            ],
            profiles=profile("R-6005", "D-3005"),
        ),
        outcome="escalated",
        action=None,
        amount=None,
        rules=["NS-6", "ESC-3"],
        rationale=(
            "Both parties assert incompatible facts and the driver's position at arrival was "
            "never recorded, so NS-3 cannot settle it. The wait alone clears NS-2, which makes "
            "the charge arguable rather than proven. NS-6 routes it to ESC-3."
        ),
    )

    add(
        no_show_case(
            dispute_id="NS-0206",
            wait_minutes=0.0,
            driver_distance_m=None,
            driver_arrived=False,
            fee=CANCELLATION_FEE,
            driver_marked_no_show=False,
            rider_claims_driver_absent=False,
            matched_to_cancel_min=2.0,
            claim_text="I cancelled within two minutes of booking and was still charged.",
            intake={
                "what_went_wrong": "Cancelled almost straight away because my plans changed.",
                "where_were_you": "At home, the driver had not started coming.",
                "did_driver_contact_you": "No",
                "safety_concern": "No",
            },
            chat=[],
            profiles=profile("R-6006", "D-3006"),
        ),
        outcome="ruled",
        action="refund",
        amount=CANCELLATION_FEE,
        rules=["NS-1", "GEN-3"],
        rationale=(
            "The cancellation came 2 minutes after matching, inside Ryde's published 3-minute "
            "free window, and no arrival was recorded. NS-1 makes the fee unchargeable and it is "
            "refunded in full."
        ),
    )

    add(
        no_show_case(
            dispute_id="NS-0207",
            wait_minutes=6.0,
            driver_distance_m=30.0,
            fee=WAITING_FEE,
            driver_marked_no_show=False,
            rider_claims_driver_absent=False,
            claim_text="I was charged a waiting fee even though the trip went ahead.",
            intake={
                "what_went_wrong": "Extra charge on the receipt for waiting time.",
                "where_were_you": "I came down about 6 minutes after he arrived.",
                "did_driver_contact_you": "Yes, he messaged when he arrived.",
                "safety_concern": "No",
            },
            chat=[
                {"t": "2026-09-14T19:06:00+08:00", "sender": "driver", "text": "I am here at the entrance."},
                {"t": "2026-09-14T19:12:00+08:00", "sender": "rider", "text": "Sorry, coming now."},
                {"t": "2026-09-14T19:13:00+08:00", "sender": "driver", "text": "No problem."},
            ],
            profiles=profile("R-6007", "D-3007"),
        ),
        outcome="ruled",
        action="no action",
        amount=0.0,
        rules=["NS-5", "NS-3"],
        rationale=(
            "The driver was 30 m from the pickup point and waited 6 minutes before the rider "
            "boarded, and the trip completed. NS-5 makes the waiting fee chargeable on exactly "
            "those facts."
        ),
    )

    # -- out of scope -------------------------------------------------------------

    record = no_show_case(
        dispute_id="OS-0301",
        wait_minutes=0.0,
        driver_distance_m=None,
        driver_arrived=False,
        fee=0.0,
        driver_marked_no_show=False,
        rider_claims_driver_absent=False,
        claim_text="The rider left a mess in my car and I want the cleaning fee.",
        intake={
            "what_went_wrong": "Passenger was sick in the back seat and I lost the rest of my shift.",
            "where_were_you": "At the drop-off point.",
            "did_driver_contact_you": "n/a",
            "safety_concern": "No",
        },
        chat=[],
        profiles=profile("R-7001", "D-4001"),
        filed_by="driver",
    )
    record["category"] = "Property Damage / Mess"
    record["claim"]["amount_sgd"] = 120.0
    del record["cancellation"]
    add(
        record,
        outcome="human_review",
        action=None,
        amount=None,
        rules=["GEN-1", "ESC-1"],
        rationale=(
            "Property damage and cleaning are outside the two categories this policy covers. "
            "GEN-1 scopes it out and ESC-1 routes it to the support queue with a neutral "
            "acknowledgement, without an agent ruling."
        ),
    )

    return cases


# ------------------------------------------------------------------------------ write


def write_corpus(target: Path) -> Dict[str, Any]:
    cases = build_cases()
    disputes_dir = target / "disputes"
    disputes_dir.mkdir(parents=True, exist_ok=True)

    for case in cases:
        record = case["record"]
        path = disputes_dir / ("%s.json" % record["dispute_id"])
        path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")

    labels = {
        "_readme": [
            "Ground truth for the synthesised corpus in disputes/.",
            "Deliberately kept OUT of the dispute records: a label inside the input would be",
            "visible to the agents and would make any accuracy measurement worthless.",
            "expected_outcome is one of: ruled | escalated | human_review.",
            "decisive_rule_ids are the rules a correct ruling must rest on, from docs/policy.md.",
        ],
        "policy_version": "1.0",
        "case_count": len(cases),
        "cases": [case["label"] for case in cases],
    }
    (target / "ground-truth.json").write_text(json.dumps(labels, indent=2) + "\n", encoding="utf-8")

    return {"count": len(cases), "dir": str(disputes_dir)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(DATA), help="output directory (default: data/)")
    args = parser.parse_args()

    result = write_corpus(Path(args.out))
    print("wrote %d disputes to %s" % (result["count"], result["dir"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
