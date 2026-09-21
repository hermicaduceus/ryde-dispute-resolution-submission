# Dispute Resolution Policy — Ryde (Singapore)

**Version 1.0 · effective 2026-09-21 · applies to on-demand trips in Singapore**

This document is the rule set the Judge agent applies. It is **data, not code**: the pipeline
reads it at a known path, agents cite rules by ID, and a different policy document drops in
with no code change.

---

## PROVENANCE — read this before citing anything here

**This document was synthesised by the project team. It is NOT an official Ryde document and
was not supplied by the organisers.** It is built in three layers, and every rule below is
tagged with which layer it comes from:

| Tag | Meaning |
|---|---|
| **[RYDE-ACTUAL]** | Taken from Ryde's own published policy pages or Terms of Use. The rule states what Ryde actually publishes, with the source URL. |
| **[PEER-DERIVED]** | Ryde publishes no rule here. The rule is modelled on a comparable Singapore operator's published policy (Grab or TADA), cited, and adapted. |
| **[SYNTHESISED]** | Neither Ryde nor its peers publish a usable rule. The team authored it. These are the rules a real Ryde policy would most likely word differently. |

**Why a synthesised policy exists at all.** The challenge statement requires the Judge to apply
"company policy", and no policy document was supplied. Rather than invent one from nothing, the
team researched Ryde's actual published policies first (help centre, Terms of Use, press
statements), used Grab and TADA as peer references for the gaps, and authored only what neither
publishes. The three-layer tagging exists so a reader can always tell which is which.

**The honest limitation.** Ryde's public material covers cancellation and waiting fees in
detail, and covers route deviation and driver no-show barely at all. Section 3 (route deviation)
is therefore mostly **[SYNTHESISED]**, and that is the section carrying the most invention. Ryde's
Terms of Use additionally **disclaim** an adjudication role (Section A Clause 10: "Any complaints
between Partners and Users must be taken up with each other directly"), so an automated Judge is
a design this project proposes, not a process Ryde publishes.

**Fee figures drift.** Ryde's rider-side and driver-side pages currently disagree ($6.61/$5.00
versus $4.50/$4.50) and the cancellation fee has moved $4.30 → $5.30 → $6.50 → $6.61 since 2017.
This document uses the **rider-side current figures**, corroborated by the waiver voucher amount,
retrieved 2026-09-21. Treat every amount in the parameters table as swappable.

**Sources.** Ryde: `help.rydesharing.com` cancellation and waiting fee policy, waiver request
pages, Driver Performance and Community Standards, `rydesharing.com/terms-of-use/`. Peers:
`grab.com/sg/cancellationpolicy/`, Grab Transport Terms of Service, TADA Singapore rider FAQ and
T&C. Regulatory: LTA/PTC joint statement on fare accuracy, CaseTrust-LTA accreditation standards.
Full citations with retrieval dates are in the research reports the team holds.

---

## Parameters

Amounts and thresholds are collected here so they can be changed in one place. Rules reference
them by name.

| Parameter | Value | Layer | Note |
|---|---|---|---|
| Cancellation fee | SGD 6.61 | [RYDE-ACTUAL] | Rider-side published figure |
| Waiting time fee | SGD 5.00 | [RYDE-ACTUAL] | Charged at trip end |
| Free cancellation window | 3 minutes after matching | [RYDE-ACTUAL] | On-demand trips |
| Minimum driver wait before no-show | 3 minutes after "I'm Here" | [RYDE-ACTUAL] | |
| Driver proximity limit at pickup | 500 metres | [PEER-DERIVED] | TADA's published figure |
| Material route deviation | 20% and 1.0 km | [SYNTHESISED] | Both must be met |
| Gross route deviation | 5.0 km | [SYNTHESISED] | Material regardless of percentage |
| De minimis adjustment | SGD 1.00 | [SYNTHESISED] | Below this, no monetary remedy |
| Autonomous decision cap | SGD 50.00 | [SYNTHESISED] | Above this, human review |
| Filing window | 30 days from the trip | [RYDE-ACTUAL] | Waiver request pages |

---

## 1. Scope and general rules

### GEN-1 — What this policy covers [SYNTHESISED]

This policy governs two dispute categories on Singapore on-demand trips: **route deviation /
overcharged fare** (Section 3) and **no-show charge / cancellation fee** (Section 4). Any other
dispute — property damage, cleaning, safety incidents, lost items, promotions, or anything the
filing party selects as "other" — is outside this policy and goes to human review under ESC-1.

RydeTAXI trips are excluded from Section 4 entirely: metered taxi services do not carry Ryde's
cancellation and waiting fee policy ("Cancellation Policy applies to all Service Types in the
Ryde app... All services except RydeTAXI", Ryde help centre) [RYDE-ACTUAL].

### GEN-2 — Every finding must rest on the Evidence Pack [SYNTHESISED]

Quantitative facts come only from the deterministic Evidence Pack, cited by field reference. A
party's assertion is not a fact: it is a claim to be tested against the pack. Where a pack field
needed to decide a rule is `null`, the rule is **not satisfied and not refuted** — it is
undetermined, and ESC-2 applies.

No agent computes its own numbers. A ruling that relies on arithmetic not present in the pack is
invalid regardless of whether the arithmetic is correct.

### GEN-3 — Burden of proof sits with the charge, not the rider [PEER-DERIVED]

Where a fee has been charged to a party, the **records must positively support the charge**. If
the preconditions for the fee cannot be shown from the Evidence Pack, the fee is not valid and is
refunded. Grab states this directly for cancellation fees: "You will not be charged the $4
cancellation fee if any of the above are not fulfilled"
(`grab.com/sg/cancellationpolicy/`). The same principle is applied here to Ryde's fees.

This rule does **not** mean the rider always wins. It means the platform's own logs must show the
fee was earned. Where they do, the fee stands and the claim fails.

### GEN-4 — De minimis [SYNTHESISED]

Where the computed monetary remedy is below the de minimis amount (SGD 1.00), no monetary
adjustment is made. The finding is still recorded and explained to both parties, and the
behavioural consequences in GEN-7 still apply. A fifty-cent refund costs more to administer than
it returns.

### GEN-5 — Form of remedy [SYNTHESISED, grounded in observed practice]

Refunds of **fees** (cancellation, waiting, no-show) are issued as **Ryde wallet credit**. This
follows Ryde's published waiver practice: an eligible waiver request produces "a voucher with a
unique code worth $6.61 as a refund for the incurred Cancellation Charges" (Ryde help centre).

Refunds of **fare overcharges** are issued to the **original payment method** where the trip was
paid by card, and as wallet credit where it was paid by cash or wallet. Ryde's Terms of Use
reserve "absolute discretion to any refunds" and allow either route (Section A Clause 7.2); the
split above is the team's rule, not Ryde's, and is chosen so an overcharge is made whole in the
currency it was taken in.

### GEN-6 — Filing window [RYDE-ACTUAL]

A dispute must be filed within **30 days of the trip**. Ryde's waiver pages are explicit:
"Requests submitted after 30 days of the trip will not be considered for waivers." A dispute
filed outside the window is declined on that ground alone, without reaching the merits.

Where the pack cannot establish the filing date relative to the trip date, do not decline on this
ground — decide the merits instead. Declining a valid claim on an unverified technicality is the
worse error.

### GEN-7 — Findings against a party are recorded, not punished here [RYDE-ACTUAL]

This policy decides money. It does not suspend accounts. Where a ruling finds conduct that Ryde's
Driver Performance and Community Standards treat as a violation — "Remaining stationary and
uncontactable after accepting a ride to trigger cancellation or waiting fees", "Abuse of
Cancellation and Waiting Fee Policy", or overcharging riders — the ruling records the finding and
flags it for the platform's own enforcement process. Suspension thresholds (driver rating below
4.80, cancellation rate above 17.5%) are the platform's to apply, not this policy's.

### GEN-8 — Behavioural history is context, never the deciding factor [SYNTHESISED]

Party profiles (dispute rate, upheld rate, rating, tenure) may be cited as context and may inform
confidence. They must **never** be the reason a claim succeeds or fails. A rider with a high
dispute rate can still be overcharged; a driver with a perfect record can still take a detour. Use
history only to break a tie the evidence leaves genuinely even, and say so explicitly when you do.

### GEN-9 — Chat signals are weak evidence [SYNTHESISED]

The chat lexicon counts in the Evidence Pack are a deterministic keyword heuristic, not a trained
model, and the pack labels them as such. They may corroborate a finding — for example, a rider
questioning the route while it was happening supports that the deviation was unannounced — but a
keyword count alone never establishes a fact and never carries a ruling on its own.

---

## 2. Evidence standards

### EV-1 — What the records must show for a fare finding [SYNTHESISED]

A route-deviation or overcharge finding requires, at minimum: the trip's GPS trace or a recorded
actual distance (`route.actual_distance_km`), the quoted or estimated distance
(`route.estimated_distance_km`), and the fare charged (`fare.charged_sgd`). Without all three,
the deviation cannot be measured and ESC-2 applies.

Where GPS points are present, the actual distance is the haversine sum over consecutive points and
is preferred over any distance asserted in the record.

### EV-2 — What the records must show for a no-show finding [RYDE-ACTUAL + PEER-DERIVED]

A no-show charge requires the platform's own timestamps: when the driver marked arrival
(`cancellation.driver_arrived_at`), when the trip was cancelled (`cancellation.cancelled_at`),
and the resulting wait (`cancellation.driver_wait_minutes`). Where the driver's position at
arrival and the booked pickup point are both recorded, the distance between them
(`cancellation.driver_distance_from_pickup_m`) is decisive under NS-3.

Ryde requires the driver to press "I'm Here" and wait more than 3 minutes before a no-show
cancellation is chargeable [RYDE-ACTUAL]. The GPS proximity requirement is peer-derived: Grab
requires the driver to be "at the pick-up location according to GPS data", and TADA uses a 500
metre radius.

### EV-3 — Fare arithmetic must reconcile [SYNTHESISED]

Where the fare breakdown is present, its components must sum to the amount charged
(`fare.breakdown_consistent`). An inconsistent breakdown is itself evidence of an incorrect
charge and is grounds for a finding under RD-5, independent of any route question.

Tolls, ERP charges and entry fees are legitimately **excluded from the quoted fare and added on
top** ("Surcharges such as toll charges, overtime fees and valet parking fees are excluded from
the base fare", Ryde help centre) [RYDE-ACTUAL]. Their presence in a breakdown is not by itself an
overcharge. Their presence where no such charge could have been incurred is.

---

## 3. Route deviation and overcharged fare

Ryde publishes no route-deviation policy. What it does publish is the fixed-fare principle —
"Fares quoted for our services are generally fixed, except for RydeTAXI" [RYDE-ACTUAL] — and a
fraud rule treating "overcharging riders or manipulating fares" as grounds for suspension
[RYDE-ACTUAL]. Grab's position, the closest peer statement, is that "drivers have the right to
take the fastest or shortest route available as recommended by the GPS for fixed-fare rides"
[PEER-DERIVED]. Everything below builds the actual test from those three anchors.

### RD-1 — When a deviation is material [SYNTHESISED]

A route deviation is **material** when either:

- `route.deviation_pct` is at least 20% **and** `route.deviation_km` is at least 1.0 km; or
- `route.deviation_km` is at least 5.0 km, whatever the percentage.

Both limbs exist because neither works alone. A percentage alone fires on a 2 km trip that went
400 metres wide, which is noise. A distance alone never fires on a short trip, where a 1.5 km
detour is the whole journey again.

A deviation below both limbs is **immaterial**: drivers exercise routing judgement, and a policy
that treats every variance as a breach would make normal driving a violation.

### RD-2 — A material deviation is not automatically a breach [PEER-DERIVED]

A material deviation is justified, and no remedy is due, where any of the following is shown:

- The rider requested or agreed to the route or a change of destination. The intake form answer
  on route agreement and the chat log's agreement markers are the evidence.
- The rider added a stop or changed the drop-off point during the trip. Ryde has adjusted fares on
  exactly this basis: "the drop-off location was changed from the initially booked
  [destination]... the trip fare has been adjusted accordingly" [RYDE-ACTUAL, press statement].
- A road closure, diversion or comparable condition made the expected route unavailable, and the
  driver stated it at the time rather than afterwards.

Congestion alone does **not** justify a material deviation in distance. Traffic is a reason a
route takes longer, not a reason it becomes physically longer. A driver who reroutes around
congestion and thereby drives materially further has made a routing choice the rider did not buy.

### RD-3 — Unjustified material deviation: remedy [SYNTHESISED]

Where a deviation is material under RD-1 and unjustified under RD-2, the rider is refunded the
**fare consequence of the deviation**: `fare.deviation_fare_delta_sgd`, being what the trip as
driven cost minus what the expected route would have cost.

The remedy is the delta, not the whole fare. The rider received the journey and owes its proper
price; what they do not owe is the cost of distance they did not ask for. Where the delta is below
the de minimis amount, GEN-4 applies and no money moves.

Where the delta cannot be computed but an overcharge is otherwise established, the remedy is
`fare.difference_sgd` if positive, and otherwise the dispute escalates under ESC-2 rather than
resolving on a guessed figure.

### RD-4 — Deviation with no fare consequence [SYNTHESISED]

A trip may deviate materially and cost the rider nothing extra, because the fare was genuinely
fixed at booking. Where `fare.deviation_fare_delta_sgd` is zero or negative, or the charged amount
matches the quoted fare, the correct outcome is **no action on the money**, with an explanation
that the fixed fare protected the rider and the routing is recorded under GEN-7.

Do not manufacture a refund to satisfy a complaint. A rider who was not charged more was not
overcharged, and saying so plainly is a better answer than a goodwill payment that implies a
wrong.

### RD-5 — Overcharge independent of routing [RYDE-ACTUAL + SYNTHESISED]

A fare may be wrong without any deviation. Where `fare.breakdown_consistent` is false, or
`fare.difference_sgd` is materially positive against the recomputed fare at the recorded tariff
rates, the rider is refunded the difference regardless of the route taken.

Singapore's regulator has put fare accuracy squarely on the operator: in the 2024 ERP
mis-rating case the LTA and PTC stated that "operators of ride-hail services are responsible for
ensuring that accurate fares are charged to passengers", and directed a full audit and
reimbursement [PEER-DERIVED, regulatory]. A pricing error is the platform's to fix, not the
rider's to absorb and not the driver's to pay for.

### RD-6 — Duration overrun is not, by itself, a fare dispute [SYNTHESISED]

A trip that took longer than estimated without travelling materially further
(`duration.delta_pct` high, `route.deviation_pct` low) is a traffic outcome, not a deviation.
Where the fare includes a time component and the delay was not the driver's doing, the time charge
stands.

The exception is a delay the driver caused — an unnecessary stop, or a detour that also cost time.
There, the time component of the deviation is already inside
`fare.deviation_fare_delta_sgd` and is remedied by RD-3 rather than separately.

---

## 4. No-show charge and cancellation fee

This is the section where Ryde's own published policy is strongest, and most of what follows is
[RYDE-ACTUAL]. The gap Ryde leaves — what a rider is owed when the **driver** fails to appear —
is filled from Grab and TADA.

### NS-1 — When a cancellation fee is chargeable to the rider [RYDE-ACTUAL]

Ryde's published rule, verbatim: "All cancellations made within 3 minutes of matching are not
chargeable. Rider will be charged a Cancellation Fee of $6.61 if: Rider cancels after 3 minutes of
matching OR the driver presses 'I'm Here', waits for > 3 minutes for the rider to arrive at the
pick-up point and cancels the trip (Rider NO SHOW and no trip completion)."

Two distinct routes to the same fee, and they are tested differently. A rider-initiated
cancellation turns on elapsed time from matching. A driver-initiated no-show cancellation turns on
the driver having actually arrived and actually waited, which NS-2 and NS-3 test.

### NS-2 — The wait must be real [RYDE-ACTUAL]

For a driver-initiated no-show charge, `cancellation.driver_wait_minutes` must exceed **3
minutes**, measured from the driver marking arrival. A cancellation inside 3 minutes of arrival
does not earn the fee, and the fee is refunded in full.

Where the wait cannot be established from the timestamps, the fee is not supported and GEN-3
applies: the charge fails for want of proof rather than succeeding by default.

### NS-3 — The driver must have been at the pickup point [PEER-DERIVED]

Where the records show the driver's position at the moment of arrival, that position must be
within **500 metres** of the booked pickup point
(`cancellation.driver_distance_from_pickup_m`). Beyond that, the driver was not at the pickup
point, the "I'm Here" mark does not reflect arrival, and **the no-show fee is invalid and refunded
in full** — regardless of how long the subsequent "wait" ran.

This is the rule that catches the failure mode both Ryde and its peers acknowledge: a driver who
marks arrival from elsewhere and lets the clock run. Ryde's own standards prohibit "Remaining
stationary and uncontactable after accepting a ride to trigger cancellation or waiting fees"
[RYDE-ACTUAL]. Grab requires the driver to be "at the pick-up location according to GPS data" and
TADA uses a 500 metre radius; the figure here is TADA's [PEER-DERIVED].

A driver marking arrival from 650 metres away has not arrived. The distance is not a matter of
degree — the fee either rests on a genuine arrival or it does not.

### NS-4 — Driver no-show: the rider owes nothing [PEER-DERIVED]

Where the driver never arrived, or arrived so late that the rider had already cancelled, the
rider is **not** charged and any fee taken is refunded in full. Ryde publishes no rider-facing
rule for this case; Grab does: "Cancellation fees are waived if your driver does not arrive within
3 minutes after the first-shown estimated time of arrival", and TADA auto-cancels at no charge
where the driver is not on the way.

Where the records additionally suggest the non-arrival was deliberate — the driver stationary and
distant, no contact attempt, a pattern in the profile — the finding is recorded under GEN-7 for
the platform's fraud process. This policy still only decides the money.

### NS-5 — Waiting time fee [RYDE-ACTUAL]

Distinct from cancellation: where the driver pressed "I'm Here", waited more than 3 minutes, **and
the trip went ahead**, a waiting time fee of SGD 5.00 is chargeable at the end of the trip. The
same arrival test in NS-3 applies: a waiting fee earned from the wrong location is not earned.

### NS-6 — Contested no-show with both parties asserting [SYNTHESISED]

Where the driver marked a no-show and the rider asserts the driver was absent
(`cancellation.driver_marked_no_show` true and `cancellation.rider_claims_driver_absent` true),
the platform's own telemetry decides it, in this order: the driver's recorded position at arrival
(NS-3), then the wait duration (NS-2), then the chat log's contemporaneous content.

If the telemetry settles it, rule and explain which field decided. If the position is unrecorded
and the wait is the only evidence, the dispute escalates under ESC-3: a straight word-against-word
conflict on a fee is not something to decide on the balance of personalities.

### NS-7 — Advance bookings [RYDE-ACTUAL]

For advance trips, cancellations more than 15 minutes before the scheduled time are free. Inside
that window the cancellation fee applies, except that a booking accepted less than 15 minutes
before the scheduled time carries a 3-minute grace period from acceptance.

The driver-side tests in NS-2 through NS-4 apply unchanged to advance bookings.

---

## 5. Escalation to human review

Escalation is a correct outcome, not a failure. A wrong ruling delivered confidently costs more
than a slow one.

### ESC-1 — Out of scope [SYNTHESISED]

Any dispute outside the two categories in GEN-1 goes to human review without an agent ruling. The
parties receive a neutral acknowledgement that the matter has been passed to the support team.

### ESC-2 — Missing decisive evidence [SYNTHESISED]

Where a pack field the applicable rule depends on is `null`, and no alternative rule reaches the
question, the dispute escalates. Specifically: a route-deviation claim without the distances
required by EV-1, or a no-show claim without the timestamps required by EV-2.

Do not substitute a plausible figure for a missing one. An estimated deviation is an invented
fact, and a ruling built on it cannot be audited.

### ESC-3 — Irreconcilable accounts [SYNTHESISED]

Where the two sides assert incompatible facts and the telemetry does not settle which is right,
the dispute escalates with both cases and the full Evidence Pack attached. NS-6 is the common
instance.

### ESC-4 — Amount above the autonomous cap [SYNTHESISED]

Where the remedy under consideration exceeds **SGD 50.00**, the ruling is prepared but not issued:
it goes to a human reviewer as a recommendation. Automated systems should not move large sums
without a person in the loop, and the cap is deliberately low relative to the fees in scope.

### ESC-5 — Low confidence [SYNTHESISED]

Where the Judge's own confidence in the ruling falls below the configured threshold, the ruling is
withheld regardless of its content and the case goes to human review with the candidate ruling
attached. The parties see only a neutral notice that the case is still under review.

Confidence is an honest estimate that the ruling is the one the policy and the evidence support.
It is not a measure of how strongly the Judge feels, and it is not to be inflated to clear the
threshold or deflated to avoid deciding. A case that is genuinely clear — the rule fires, the
evidence is complete, neither side's account is in doubt — should carry high confidence and be
decided.

### ESC-6 — What the parties are told on escalation [SYNTHESISED]

An escalated dispute produces a neutral holding message: the case is under review and the party
will be contacted. The parties are **not** told which way the candidate ruling went, what the
confidence score was, or that an automated system was uncertain. A provisional outcome disclosed
and then reversed is worse than a short wait.

### ESC-7 — Target timelines [PEER-DERIVED]

Escalated disputes should be acknowledged within **3 working days** and resolved within **21
working days**. Neither Ryde nor Grab nor TADA publishes a rider-side resolution SLA for fare
disputes; these figures are the CaseTrust-LTA accreditation standard for the car-sharing
industry, which is the nearest published Singapore benchmark ("Operators must acknowledge receipt
of complaints within three working days and address the dispute within 21 working days").

---

## 6. Outcomes

A ruling states one of three actions.

**refund** — money returns to the rider: a fee refunded under Section 4, or a fare overcharge
returned under Section 3. The amount and the form of remedy (GEN-5) are stated.

**compensation** — money moves to the driver. In scope here only where a fee was correctly earned
and had been reversed, or where a rider's conduct cost the driver a fee they were entitled to.

**no action** — the charge stands, or the deviation carried no fare consequence. This is a
ruling like any other and requires the same explanation and the same confidence. A system that
can only find for the complainant is not adjudicating.

Every ruling cites the rule IDs it rests on and the Evidence Pack fields that satisfied them, and
explains the reasoning in language both parties can read.
