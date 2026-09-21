"""Driver Advocate — represents the driver's perspective.

Gathers driver-side evidence from the Evidence Pack, articulates the driver's defence and
argues for the outcome the evidence and policy support. Runs before the Judge and does
not see the Rider Advocate's case.
"""

from __future__ import annotations

from .base import AdvocateAgent


class DriverAdvocate(AdvocateAgent):
    name = "driver_advocate"
    role_title = "Driver Advocate"
    party = "driver"
    role_blurb = (
        "Represent the driver's perspective. Read the driver's side out of the Evidence Pack "
        "and the intake form, articulate the driver's defence, and argue for the outcome that "
        "the evidence and company policy support. The driver is not on trial: a fare that was "
        "computed correctly, a deviation with a recorded justification, or a wait that met "
        "policy are all legitimate defences and should be argued as such."
    )
