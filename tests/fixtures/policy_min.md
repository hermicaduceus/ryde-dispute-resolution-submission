# TEST FIXTURE — minimal policy for the pipeline tests

**This is not the project policy.** It is a deliberately minimal stand-in so the tests
can exercise rule citation and the fail-loud policy loader without touching the real
policy set. The real policy lands at `docs/policy.md`, is authored in another lane, and
carries its own provenance. Never point the app at this file outside `tests/`.

Provenance: synthesised (test fixture only).

---

### RD-1 — Route deviation threshold

A route deviation is material when the actual distance exceeds the estimated distance by
more than 20 percent, or by more than 1.5 km, whichever is smaller.

Preconditions:
- evidence.route.deviation_pct > 20 OR evidence.route.deviation_km > 1.5

### RD-2 — Remedy for a material, unjustified deviation

Where RD-1 holds and the driver did not record a justification for the route taken, the
rider is entitled to a refund of the fare difference attributable to the deviation.

Preconditions:
- RD-1 is satisfied
- evidence.fare.deviation_fare_delta_sgd > 0
- no recorded driver justification for the route taken

### NS-1 — Minimum driver wait before a no-show fee

A no-show fee may be charged only when the driver waited at least 5 minutes after
marking arrival.

Preconditions:
- evidence.cancellation.driver_wait_minutes >= 5

### NS-2 — Arrival proximity

A driver has not arrived for the purposes of NS-1 when the recorded arrival position is
more than 500 metres from the stated pickup point.

Preconditions:
- evidence.cancellation.driver_distance_from_pickup_m > 500

### GEN-1 — Evidence sufficiency

Where the evidence needed to apply a rule is absent from the Evidence Pack, the case is
not decided on that rule and confidence must reflect the gap.

Preconditions:
- the evidence field a rule depends on is null
