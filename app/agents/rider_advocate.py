"""Rider Advocate — represents the rider's perspective.

Gathers rider-side evidence from the Evidence Pack, articulates the rider's claim and
argues for the outcome the evidence and policy support. Runs before the Judge and does
not see the Driver Advocate's case.
"""

from __future__ import annotations

from .base import AdvocateAgent


class RiderAdvocate(AdvocateAgent):
    name = "rider_advocate"
    role_title = "Rider Advocate"
    party = "rider"
    role_blurb = (
        "Represent the rider's perspective. Read the rider's side out of the Evidence Pack "
        "and the intake form, articulate the rider's claim, and argue for the outcome that "
        "the evidence and company policy support. Argue the rider's case firmly, but do not "
        "overstate it: the Judge sees the same pack, and a claim the evidence does not carry "
        "weakens the rider's case rather than strengthening it."
    )
