# Dataset — labelled dispute corpus

**Version 1.0 · 17 cases · generated 2026-09-21 · policy version 1.0**

The corpus the system is evaluated against. Like the policy, it is **data, not code**: the
pipeline reads dispute records from `data/disputes/`, and a real dataset drops in with no code
change.

---

## PROVENANCE — read this first

**Every case in this corpus is synthetic. It was authored by the project team. No real trip,
rider, driver, GPS trace or payment appears anywhere in it.**

The challenge statement promised a sample dataset that was never supplied, and Ryde publishes no
dispute statistics — confirmed against LTA's Point-to-Point Quality of Service releases (which
measure safety, not fare disputes), CASE's annual complaint reports (which have no ride-hailing
category), and Ryde Group's own SEC filings. The absence is documented, not assumed.

So the corpus is built rather than collected. Its **shapes** are grounded: the dispute patterns
are modelled on publicly reported Singapore ride-hailing disputes (a driver marking arrival from
the wrong location and letting the clock run; a fare adjusted after a destination change; a mass
ERP mis-rating corrected on the regulator's direction), and the fee amounts and thresholds come
from Ryde's published policy. The **data** is fabricated.

**What this means for any number measured against it.** An accuracy figure from this corpus
measures whether the system applies *our* policy to *our* cases consistently. It is a measure of
internal consistency and calibration. It is **not** evidence of real-world accuracy, and must
never be presented as one.

---

## Layout

```
data/
├── disputes/           one JSON file per case, named <dispute_id>.json
└── ground-truth.json   the labels, deliberately kept out of the records
```

The labels live in a separate file on purpose. A label inside a dispute record would be visible
to the agents through the intake or trip blocks, and every accuracy number measured against it
would be worthless. `tests/test_corpus.py` enforces this: it scans each record for ground-truth
keys and fails if one leaks.

## The label shape

```json
{
  "dispute_id": "RD-0101",
  "category": "route_deviation",
  "expected_outcome": "ruled",
  "expected_action": "refund",
  "expected_amount_sgd": 5.81,
  "decisive_rule_ids": ["RD-1", "RD-2", "RD-3"],
  "rationale": "50% / 3.2 km deviation clears both limbs of RD-1..."
}
```

`expected_outcome` is one of `ruled`, `escalated`, `human_review`. `decisive_rule_ids` are the
policy rules a correct ruling must rest on — a system that reaches the right answer by citing the
wrong rule got there by luck, and the labels are built so that shows up.

`rationale` exists so a human reviewer can disagree with a label. An unexplained label cannot be
challenged, which makes it an assertion rather than ground truth.

## Coverage

| Cases | | |
|---|---|---|
| Route deviation | 9 | RD-0101 … RD-0109 |
| No-show / cancellation fee | 7 | NS-0201 … NS-0207 |
| Out of scope | 1 | OS-0301 |

| Outcome | Cases |
|---|---|
| `ruled` → refund | 7 |
| `ruled` → no action | 6 |
| `escalated` | 3 |
| `human_review` | 1 |

**The balance is deliberate.** Roughly half the ruled cases find for the complainant and half do
not. A corpus where every claim succeeds cannot demonstrate that the system is capable of saying
no, and a dispute resolver that only ever refunds is not adjudicating — it is processing.
`test_corpus.py` asserts both directions are present.

Three cases escalate rather than resolve, for three different reasons: missing decisive evidence
(RD-0108), an amount above the autonomous cap (RD-0109), and irreconcilable accounts the telemetry
cannot settle (NS-0205). Escalation is a correct outcome under the policy, so it has to be in the
corpus or the escalation path is untested.

## What each case is for

**Route deviation**

| ID | Tests | Expected |
|---|---|---|
| RD-0101 | Plain unjustified detour, both RD-1 limbs cleared | refund 5.81 |
| RD-0102 | Material deviation the rider asked for (added stop) | no action |
| RD-0103 | Deviation below both thresholds — routing judgement, not breach | no action |
| RD-0104 | Long trip where the gross-km limb fires and the percentage barely does | refund 7.70 |
| RD-0105 | Material unjustified deviation, but the rider paid the quoted fixed fare | no action |
| RD-0106 | Fare breakdown does not reconcile — an overcharge with no deviation | refund 3.40 |
| RD-0107 | Big duration overrun, negligible distance variance — traffic, not detour | no action |
| RD-0108 | No estimated distance in the record, so materiality cannot be tested | escalate |
| RD-0109 | Clear-cut deviation whose remedy exceeds the SGD 50 autonomous cap | escalate |

**No-show / cancellation fee**

| ID | Tests | Expected |
|---|---|---|
| NS-0201 | Driver at pickup, waited 5.5 min — the fee was earned | no action |
| NS-0202 | Driver at pickup but cancelled after 1.5 min, short of the minimum wait | refund 6.61 |
| NS-0203 | Driver marked arrival 885 m away — the wait never started | refund 6.61 |
| NS-0204 | Driver never arrived at all; rider charged for cancelling | refund 6.61 |
| NS-0205 | Both sides assert opposite facts and no driver position was recorded | escalate |
| NS-0206 | Cancellation inside the 3-minute free window | refund 6.61 |
| NS-0207 | Waiting fee on a completed trip, driver at pickup | no action |

**Out of scope**

| ID | Tests | Expected |
|---|---|---|
| OS-0301 | A property-damage claim filed by a driver | human review, no agent ruling |

RD-0103 carries a second purpose: its rider profile has a high dispute rate and a low trip count.
The claim fails on RD-1's thresholds and **not** on the rider's history, which is what GEN-8
requires. If a system starts declining claims because of who filed them, this is the case where
that shows.

## How it is generated

`tools/build_corpus.py` writes both `disputes/` and `ground-truth.json`. It is a **non-app tool**:
nothing under `app/` imports from it.

```bash
python3 tools/build_corpus.py
```

The generator exists because every case carries fare arithmetic and a GPS polyline that must agree
with each other. Hand-written JSON drifts: a distance edited without recomputing the fare produces
a record where the Evidence Pack calculates something different from what the case intends, and
the label silently becomes a lie. Here the numbers derive from a handful of per-case parameters
(actual km, quoted km, minutes, tariff), so they cannot come apart.

**GPS traces are generated, not asserted.** Each route is a polyline walked along a bearing in
equal legs, whose haversine length is the intended distance. The Evidence Pack then recomputes the
distance from those points exactly as it would for a real trace — `test_corpus.py` asserts the
pack never fell back to a stated distance. The traces are geometrically valid but they are not
real Singapore roads; they start near Dhoby Ghaut and head northeast in a gentle zigzag.

**Fares are computed with the pack's own formula**, `(base + per_km × km + per_min × min) × surge
− promo`, and the breakdown components are the same terms with surge applied, so they sum to the
charge. RD-0106 deliberately breaks that reconciliation by 3.40 — it is the only case where the
breakdown is inconsistent, and that inconsistency is the thing being tested.

## Verification

`tests/test_corpus.py` (22 tests) is the guard on this artifact. It checks structure (every case
labelled exactly once, no label leaking into a record, every label carrying a rationale), policy
agreement (no label cites a rule that is not in `docs/policy.md`), and — the part that matters
most — **evidence agreement**: every labelled refund amount must match a number the Evidence Pack
actually computes from that record, and the policy's mechanical thresholds applied to the pack
must not contradict the label.

That last check earned its place during authoring. It caught two labels whose amounts were written
by hand and were wrong: RD-0101 was labelled 4.81 against a computed 5.81, and RD-0109 was labelled
below the autonomous cap when its real delta was above it. Both were fixed by correcting the label
and the case, not the test.

Every case also runs end to end through the real pipeline without error.

## Known limitations

- **Seventeen cases is a demonstration corpus, not a benchmark.** It is sized to cover every rule
  path and every outcome, not to support a statistically meaningful accuracy claim. Do not quote a
  percentage from it without the denominator attached.
- **No adversarial or ambiguous-language cases.** Every intake form is coherently written. Real
  filings are terse, contradictory, and sometimes in Singlish. A system tuned on this corpus will
  look better than it is on real text.
- **Chat logs are short and clean.** The lexicon signals in the pack fire predictably here, which
  makes them look more informative than GEN-9 says they are.
- **One trip archetype.** All routes are generated from the same bearing-walk, so their geometry is
  more uniform than a real fleet's.
- **The labels are ours.** Where the policy is `[SYNTHESISED]`, the "correct" answer is a judgement
  the team made. A Ryde operations reviewer might rule differently on RD-0104 or RD-0105, and that
  disagreement would be about policy, not about the system.

## If a real dataset arrives

Drop it in `data/disputes/` in the same record shape (documented in `app/dispute.py`) and point the
pipeline at it. Keep this corpus as the **held-out labelled set**: a real dataset supplied without
ground-truth labels cannot measure accuracy, so the synthesised labelled corpus stays useful even
when it is no longer the primary input.
