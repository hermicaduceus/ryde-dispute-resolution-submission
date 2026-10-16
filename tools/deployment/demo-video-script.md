# Demo video script (target 7:30, limit 8:00)

**Historical draft, not current filming instructions.** Kept as presentation source, not the accepted recording script. Its local `start.bat` instruction launches the mock and must not be filmed as real AI; its replay date is historical. See [the recording handoff boundary](../../docs/live-copy.md#rehearsal-handoff).

Format: **[ON SCREEN]** is what the viewer sees; plain text is spoken. About 140 words a
minute. Challenge case study to name in the first line: **Digital Native track, Ryde:
Multi-Agent Autonomous Dispute Resolution.**

## How every number is tagged

Every figure on screen carries one tag, so nothing assumed can pass for fact:

- **[VERIFIED]** appears in Ryde's published results, "Ryde Reports First Half 2026 Results"
  (investor.rydesharing.com, dated 8 October 2026, unaudited, SGD). Only the figures in the
  first table below are verified.
- **[DERIVED]** simple arithmetic on a verified figure plus a stated assumption.
- **[ASSUMPTION]** our estimate. Ryde does not publish trips, GMV, users, headcount,
  customer-service cost or dispute volumes (the release gives none of these).

| Verified figure (1H 2026, six months to 30 June 2026) | Value |
|---|---|
| Revenue | S$6,735k (up 17% from S$5,748k) |
| Mobility revenue | S$4.5M, up 8%, "on higher gross transaction value" (no GMV figure given) |
| Total expenses, net | S$5,410k |
| Operational loss | S$2,227k |
| Net loss | S$13,421k, of which S$11,392k is share-based compensation |
| Adjusted EBITDA | S$(1,901)k, narrowed 37% |
| Total assets / equity (30 June 2026) | S$57,271k / S$51,599k |

Other honesty rules: state which model produced the demo run (real Tencent ADP, or the replay
with its recording date); a mock run is never presented as a real ruling; "17 cases" is a
consistency check on synthesised data, not accuracy.

## Timeline and slide map (7:30 total, limit 8:00)

| Time | Slide | What happens |
|---|---|---|
| 0:00–0:40 | 1 Title | Overview |
| 0:40–1:30 | 2 Pain point | Verified Ryde figures, then assumptions |
| 1:30–2:10 | 3 Proposal | Three agents, gates in code |
| **2:10–4:50** | **4 Demo marker, then screen recording** | **The live demo (2 min 40). Do not start it earlier or run past 4:50.** |
| 4:50–5:30 | 5 Embed in Ryde | Existing CS tool, decision service in Ryde's cluster, rollout |
| 5:30–6:15 | 6 Cost | S$120k of staff time once, S$14 a month in tokens |
| 6:15–7:05 | 7 ROI | Do-nothing vs with-system, payback, dispute-rate swing |
| 7:05–7:30 | stays on 7 | Close: next step and the build reflection, spoken over slide 7 (about 25 s) |
| not shown | 8 Reference | Cost breakdown (staff time, tokens by model), kept for Q&A |
| not shown | 9 Reference | Dispute-rate sensitivity and benchmarks, kept for Q&A |
| not shown | 10 Reference | How it plugs into Ryde (integration contract), kept for Q&A |
| not shown | 11 Reference | Controls and honest limits, kept for Q&A |
| not shown | 12 Reference | System architecture (from docs/architecture.md), kept for Q&A |
| not shown | 13 Reference | Deployment options compared (embedded, hosted, no AI), kept for Q&A |

The deck is [ryde-dispute-pitch.pptx](ryde-dispute-pitch.pptx); each slide carries its timing and
talking points in the speaker notes. Record the demo segment on its own, so it can be trimmed to fit
2:10 to 4:50 without re-recording the rest.

---

## 0:00–0:40 | Slide 1: Project overview

**[ON SCREEN]** Title slide: *Ryde: Multi-Agent Autonomous Dispute Resolution.* Track and team name.

"We chose the Digital Native track: Ryde's multi-agent dispute resolution challenge.

Riders and drivers argue over fares and fees every day: a longer route, a no-show charge. Today a person reads the GPS, the chat and the policy, and decides.

We built three AI agents that do that work. A Rider Advocate and a Driver Advocate argue their sides, and a Judge applies policy and rules, with a confidence score. The AI never does the maths, and never gets the last word on money."

---

## 0:40–1:30 | Slide 2: The pain point

**[ON SCREEN]** Left: the verified table, tagged VERIFIED. Right: the derived chain, tagged
ASSUMPTION or DERIVED.

"First, which numbers are real. Ryde's first-half 2026 results are public: revenue 6.7 million Singapore dollars, up 17 percent, and an operating loss of 2.2 million. Every cost line matters. These are verified.

Ryde doesn't publish trips, support cost or disputes, so the rest are assumptions. From its mobility revenue we estimate about 4 million trips a year, one percent disputed (generous: Uber's total support contacts are about 1.3 per 100 trips), and 1,300 disputes a month in our two categories. At 12 minutes each, that's about 120,000 dollars a year, two people's work.

The bigger cost is felt by riders: 24 to 72 hours to resolve, and inconsistent answers."

---

## 1:30–2:10 | Slide 3: What we are proposing

**[ON SCREEN]** Slide 3: Evidence Pack → Rider Advocate → Driver Advocate → Judge → Gates in code.

"Our answer is a small team of AI agents with strict limits. Python computes the evidence
first. A Rider Advocate and a Driver Advocate each argue their side. A Judge weighs both,
applies policy by rule ID, and rules with a confidence score. Then gates written in code decide
whether that ruling is delivered at all: the confidence floor, a SGD 50 cap, and the money
rules. If a gate holds it, a person decides and the rider just sees 'still under review'.
Three guarantees: the AI never does arithmetic, the rules live in code, and every step is
observable. Let me show you."

---

## 2:10–4:50 | Slide 4, then LIVE DEMO (about 2 min 40)

**[ON SCREEN]** Slide 4 for 5 seconds (the five demo beats), then switch to the screen recording.

### 3a. Filing (about 20 s)
**[ON SCREEN]** Double-click `start.bat`. Browser opens the start page, then the rider form.

"Setup is one double-click. A rider files through a standard form: pick the trip, pick
'route deviation', describe what happened. No chatting with bots. The agents work behind
the form."

### 3b. Three agents and the evidence (about 50 s)
**[ON SCREEN]** Operator console, case file for RD-0109 (above-cap detour). Show claim, evidence, both
advocate cases.

"Before any AI runs, Python computes the evidence: the route deviation in kilometres and
percent, the fare recomputed, the cancellation timestamps. This Evidence Pack is the only source of numbers.
The agents cite fields from it. They are forbidden from doing arithmetic.

Here the Rider Advocate argues for a refund, and the Driver Advocate argues the other
side. Neither sees the other's case. Then the Judge reads both, applies the policy by rule
ID, and rules."

### 3c. Observable communication (included in 3b's 50 s: do not repeat the explanation)
**[ON SCREEN]** Event strip: `case.assigned`, `advocate.case_submitted`, `judge.deliberation_started`,
`judge.ruling_withheld`. Expand one payload.

"Every step is a timestamped event. A judge, or a Ryde reviewer, sees exactly who sent what
to whom, and one click opens the full payload. That's the observability the challenge asks
for."

### 3d. Safe by construction: gates in code (about 40 s)
**[ON SCREEN]** The `ruling_withheld` event on RD-0109, then the neutral party message.

"This refund is SGD 55. Our autonomous cap is SGD 50. The Judge proposed it with high
confidence, and the system still held it. That rule is enforced in Python, not asked of the
model in a prompt, because a prompt is a request and code is a guarantee. The same goes for
low confidence, an unmeasured deviation, and the no-show refund ceilings.

The rider sees only: 'your case is still under review.' No amount, no confidence. A person
decides next."

### 3e. Human decision (about 30 s) and a straightforward win (about 20 s)
**[ON SCREEN]** Review queue, approve RD-0109, party status page. Then NS-0202 ruled alone.

"A reviewer opens the case, sees the AI's proposal, and approves or changes it. Their
decision is recorded; their name never reaches the rider. And a clear case, like this
no-show where the driver cancelled after 90 seconds, is decided automatically, refund
SGD 6.61, explained in plain language."

**[ON SCREEN]** Corner label: *"Replay recorded 2026-10-06"* if using the replay link.

---
## 4:50–5:30 | Slide 5: Embed it in Ryde's existing system

**[ON SCREEN]** Slide 5: Ryde app → Ryde CS tool → decision service in Ryde's cluster → Tencent Cloud ADP; payments and CS agents on the return path.

"We propose embedding this in what Ryde already runs, not building new infrastructure. A rider's report becomes a ticket in Ryde's existing customer-service tool. That ticket publishes a dispute event to our decision service, running in Ryde's own cluster. It reads the evidence from Ryde's services, calls the three Tencent Cloud agent apps on DeepSeek V4 Flash, and returns a ruling or a withheld case to the same tool. Ryde's payments apply any refund, and its agents review withheld cases where they already work. Rollout starts in shadow mode: customers see nothing while we measure."

---
## 5:30–6:15 | Slide 6: What it costs

**[ON SCREEN]** Slide 6: S$120k staff time, S$14 a month, 9 months; every figure tagged ASSUMPTION except the verified token rates.

"Because it's embedded, the cost is Ryde's own people and the model tokens. One-off: about 120,000 dollars of staff time, two engineers for four months plus product, QA and security review. That's an opportunity cost, not new cash. Running: only API tokens on DeepSeek V4 Flash, about 14 dollars a month at our assumed volume, since it runs on infrastructure Ryde already has. Nine months to limited autonomy. Token rates are verified; staff cost and volume are our assumptions."

---
## 6:15–7:05 | Slide 7: Business ROI, honestly

**[ON SCREEN]** Do-nothing vs with-our-system cumulative spend chart and the payback-by-rate table, tagged ASSUMPTION.

"If Ryde does nothing, these disputes cost about 10,000 dollars a month in support time, growing with volume: about 400,000 over three years. With our system: about 244,000, the staff time to embed it, a few hundred dollars of tokens, and the manual work that remains. The lines cross around month 21. That's about 153,000 saved, a 127 percent return on the staff time, and it's cash only if Ryde avoids hiring as volume grows. The swing factor is the dispute rate, and nobody publishes it. Uber's total support contacts are about 1.3 per 100 trips, so our 1 percent is generous. Break-even is about 0.4 to 0.5 percent. Shadow mode measures Ryde's real rate."

---

## 7:05–7:30 | Close (voiceover over slide 7, no new slide)

**[ON SCREEN]** Stay on slide 7. For the build reflection, cut to one screenshot from `evidence/` (the CodeBuddy
session banner) for about 10 seconds, then return to slide 7 for the last line.

"The next step is shadow mode: the AI rules on real tickets while customers see nothing, so Ryde's real numbers replace our assumptions.

We built this in Tencent Cloud CodeBuddy: a planning step wrote each brief and the failing tests first, CodeBuddy built until they passed, and a second model family reviewed. Tests decided 'done', and safety rules live in code, not prompts. Thank you."

---
## Appendix: how the numbers were computed (keep for Q&A)

| Item | Basis | Value |
|---|---|---|
| Mobility revenue, annualised | **[VERIFIED]** S$4.5M for 1H 2026, doubled **[DERIVED]**, assumes 2H equals 1H | S$9M a year |
| Take rate | **[ASSUMPTION]** 15% of fare | GMV about S$60M a year |
| Average fare | **[ASSUMPTION]** S$15 | about 4.0M trips a year; 333k a month |
| Dispute rate | **[ASSUMPTION]** 1% of trips | about 3,333 disputes a month |
| In-scope share | **[ASSUMPTION]** 40% (route deviation, no-show) | about 1,333 a month |
| Agent cost | **[ASSUMPTION]** S$4,500 a month; 120 productive hours; 12 min a dispute | S$37.50 an hour; S$7.50 a dispute |
| Current in-scope cost | **[DERIVED]** 1,333 × 7.50 | S$10,000 a month; S$120,000 a year; about 2.2 full-time people (267 hours) |
| All-category cost | **[DERIVED]** 3,333 × 7.50 × 12 | about S$300,000 a year |
| Auto-decided | **[ASSUMPTION]** 60% = 800 cases | 800 × 7.50 = S$6,000 a month |
| Assisted review | **[ASSUMPTION]** 533 cases, 12 min down to 5 (saves S$4.375 each) | S$2,333 a month |
| Steady-state saving | **[DERIVED]** 6,000 + 2,333 | S$8,333 a month; S$100,000 a year |
| One-off (embedded) | **[ASSUMPTION]** Ryde staff time: 2 engineers × 4 months × S$12,000 = S$96k, plus PM, QA and security review S$24k | S$120,000 (an opportunity cost, not cash) |
| Run cost (embedded) | **[VERIFIED]** DeepSeek V4 Flash US$0.00014 in / US$0.00028 out per 1k tokens (Tencent Cloud ADP); **[ESTIMATED]** about 50k in + 3.5k out tokens a case = US$0.008 = S$0.0103; × 1,333 cases a month | about S$14 a month, tokens only (no new infrastructure or support staff assumed; excludes any ADP platform plan) |
| Timeline (embedded) | 4 months build, shadow from month 5 (tokens start), assist months 7–9, limited autonomy from month 10 | 9 months to limited autonomy |
| Volume growth | **[ASSUMPTION]** 10% a year in steps (Ryde's verified 1H 2026 revenue growth was +17%, mobility +8%) | in-scope volume 1,333 a month in year 1, 1,467 in year 2, 1,613 in year 3 |
| 3-year result (1% disputed, 10% growth) | do nothing S$397k; with the system S$244k = staff time 120 + tokens about 0.5 + remaining manual work | S$153k saved; 127% return on the staff time; payback month 21 |

**Scenarios (the slide 7 chart uses 1% and 10% growth).** Same model as the deck. Cells are the 3-year net saving
(S$k, staff time included) and the payback month; "none" means no payback within 3 years.

| Disputes, % of trips | Growth 0% | Growth 10% | Growth 17% |
|---|---|---|---|
| 0.25% | -59k, none | -52k, none | -46k, none |
| 0.5% | +1k, month 36 | +17k, month 33 | +28k, month 32 |
| **1% (base)** | +122k, month 22 | +153k, month 21 | +176k, month 20 |
| 1.5% | +243k, month 17 | +290k, month 17 | +324k, month 16 |
| 2% | +364k, month 15 | +426k, month 14 | +472k, month 14 |

Break-even dispute rate over 3 years: about 0.50% of trips at flat volume, 0.44% at 10% growth.

**Deployment options (slide 13, base case, DeepSeek V4 Flash in both).**

| | A. Embedded in Ryde (proposed) | B. Hosted service | C. No AI |
|---|---|---|---|
| One-off | S$120k of Ryde staff time | S$90k, paid to build it | none |
| Running / month | about S$14 (tokens only) | about S$1.7k (cloud S$0.5k, tokens S$14, 0.1 engineer S$1.2k) | none, but cost grows with volume |
| 3-year spend | S$244k | S$262k | S$397k |
| Payback | month 21 | month 20 | n/a |

Caveats: staff time is salaried, so the saving (and the cost) is an opportunity cost; it is cash only if Ryde avoids hiring,
overtime or outsourcing as volume grows. DeepSeek V4 Flash is unproven on this task: score it with the evaluation harness
before go-live; V4 Pro (about S$171 a month) is the fallback.

**Dispute-rate references (none is Ryde's):**
- Grab publishes no dispute or contact rate.
- Uber: the engineering blog (Feb 2024) puts 80% of contact volume at "3 million tickets per week" (about 3.75M contacts a week in total); Uber's FY2025 10-K reports 3,751M trips in Q4 2025 (about 288M a week). That is about 1.3 support contacts per 100 trips, for all topics and all products, from figures two years apart: a rough indicator. Disputes are a subset, so 1% disputed is generous.
- A vendor report claims 2-5 contacts per 100 orders (e-commerce, unverified): not used.

Context for scale, from the verified release: annualised total expenses are about S$10.8M
(S$5,410k × 2), so the in-scope support cost at base is roughly 1% of expenses. The deployment
is a small bet either way, which is why it is sized small.

Likely judge questions and short answers:
- *"Where do the numbers come from?"* Revenue and expenses are from Ryde's published 1H 2026 results; trips, disputes and support cost are our assumptions, because Ryde publishes none. Shadow mode replaces them with measured data.
- *"Does it pay back?"* On cost alone, in about 21 months at a 1% dispute rate, and it depends on that rate. The larger value is speed, consistency and retention, which we have not priced.
- *"Is the AI accurate?"* We measured consistency on 17 synthesised cases, not real-world accuracy. Shadow mode produces that figure.
- *"What if the model is wrong or attacked?"* Money gates, the SGD 50 cap and the confidence floor are Python checks; parties never see model text. Before go-live we would add a kill switch that pauses every ruling.
