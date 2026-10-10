# Demo video script (target 7:25, limit 8:00)

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

## Timeline and slide map (7:25 total, limit 8:00)

| Time | Slide | What happens |
|---|---|---|
| 0:00–0:40 | 1 Title | Overview |
| 0:40–1:30 | 2 Pain point | Verified Ryde figures, then assumptions |
| 1:30–2:10 | 3 Proposal | Three agents, gates in code |
| **2:10–4:50** | **4 Demo marker, then screen recording** | **The live demo (2 min 40). Do not start it earlier or run past 4:50.** |
| 4:50–5:30 | 5 Deploy | Tencent Cloud architecture, webhook, rollout |
| 5:30–6:15 | 6 Cost | S$90k once, S$26k a year |
| 6:15–7:00 | 7 ROI | Payback chart, dispute-rate swing |
| 7:00–7:25 | stays on 7 | Close: next step and the build reflection, spoken over slide 7 (about 25 s) |
| not shown | 8 Reference | Running-cost breakdown, kept for Q&A |
| not shown | 9 Reference | Dispute-rate sensitivity and benchmarks, kept for Q&A |
| not shown | 10 Reference | How it plugs into Ryde (integration contract), kept for Q&A |
| not shown | 11 Reference | Controls and honest limits, kept for Q&A |
| not shown | 12 Reference | System architecture (from docs/architecture.md), kept for Q&A |

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

## 4:50–5:30 | Slide 5: How to deploy it

**[ON SCREEN]** Slide 5: Ryde app → Ryde backend → EdgeOne + API Gateway → TKE workers → ADP; rollout row.

"To deploy, the decision core stays as it is and we move it onto Tencent Cloud. Ryde's backend
sends a signed webhook when a dispute is created. Our workers run on Tencent Kubernetes behind
EdgeOne and an API gateway, read the evidence read-only, and call the three Tencent Cloud ADP
agent apps. A signed callback sends the result back. Ryde keeps the money: we recommend,
Ryde's payments pay. Rollout starts in shadow mode, where the AI rules and customers see
nothing, then assist, then limited autonomy, and only expands on measured data."

---

## 5:30–6:15 | Slide 6: What it costs

**[ON SCREEN]** Cost table, every row tagged ASSUMPTION. Footer: *"Vendor prices not checked."*

"All assumptions, sized lean for a company with a 2 million operating loss. One-off: about 90,000 dollars, two engineers for three months plus review, covering evidence connectors, payments, single sign-on and a privacy check. Running: about 2,200 dollars a month for cloud, model calls and a tenth of an engineer, so about 26,000 a year. Eight months to limited autonomy: build, shadow, assist. The breakdown is on the reference slide."

---

## 6:15–7:00 | Slide 7: Business ROI, honestly

**[ON SCREEN]** Do-nothing vs with-our-system cumulative spend chart and the payback-by-rate table, tagged ASSUMPTION.

"If Ryde does nothing, these disputes cost about 10,000 dollars a month in support time, and that grows with its volume: about 400,000 dollars over three years. With our system, the build, the running cost and the manual work that remains come to about 280,000, so 117,000 saved. The lines cross around month 21, that's the payback.

The swing factor is the dispute rate, and nobody publishes it. Uber's total support contacts, for every topic, are about 1.3 per 100 trips, so our 1 percent is already generous. Break-even is about 0.6 percent. That's why shadow mode measures Ryde's real rate first. Faster answers and one standard aren't priced."

---

## 7:00–7:25 | Close (voiceover over slide 7, no new slide)

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
| One-off build | **[ASSUMPTION]** 2 engineers × 3 months × S$12,000 + S$18,000 | S$90,000 |
| Run cost | infra US$387 (**[VERIFIED]** EdgeOne Basic 57 and TKE cluster fee 15; **[ESTIMATE]** nodes 120, PostgreSQL 150, load balancer 20, API Gateway 5, storage/logs/secrets 20) = S$500; model: DeepSeek-V3.1 at **[VERIFIED]** rates on **[ESTIMATED]** ~50k in / 3.5k out tokens a case = US$342 + US$50 plan = S$507; 0.1 engineer **[ASSUMPTION]** S$1,200 | S$2,207 a month; about S$26,500 a year (the ROI chart keeps S$27,240 a year, slightly conservative) |
| Volume growth | **[ASSUMPTION]** 10% a year in steps (Ryde's verified 1H 2026 revenue growth was +17%, mobility +8%) | in-scope volume 1,333 a month in year 1, 1,467 in year 2, 1,613 in year 3 |
| Year-1 savings | months 1–5 none; months 6–8 assist only 1,333 × 4.375 = S$5,833 × 3; months 9–12 S$8,333 × 4 | S$50,833 |
| Year-1 cost | 90,000 + run cost for 9 months (20,430) | S$110,430; net about −S$59,600 |
| Year 2 and 3, each | 100,000 − 27,240 | +S$72,800 |
| Payback (0% growth case) | 59,600 ÷ (72,800 ÷ 12) after month 12 | about month 22 (month 21 with 10% growth) |
| 2-year / 3-year ROI | net ÷ total cost: 13,200 ÷ 137,700; 85,900 ÷ 164,900 | about 10% / 52% |

**Scenarios (the slide 7 chart uses 1% and 10% growth).** Same model as the deck. Cells are 3-year net saving
(S$k, build included) and payback month; "none" means no payback within 3 years.

| Disputes, % of trips | Growth 0% | Growth 10% | Growth 17% |
|---|---|---|---|
| 0.25% | -102k, none | -94k, none | -89k, none |
| 0.5% | -39k, none | -24k, none | -13k, none |
| **1% (base)** | +86k, month 22 | **+117k, month 21** | +140k, month 20 |
| 1.5% | +211k, month 16 | +258k, month 15 | +292k, month 15 |
| 2% | +337k, month 13 | +399k, month 13 | +445k, month 13 |

Do-nothing 3-year spend at the base case: S$397k (10% growth); with the system S$280k. Break-even dispute rate over 3 years:
about 0.66% of trips at flat volume, 0.59% at 10% growth.

**Dispute-rate references (none is Ryde's):**
- Grab publishes no dispute or contact rate.
- Uber: the engineering blog (Feb 2024) puts 80% of contact volume at "3 million tickets per week" (about 3.75M contacts a week in total); Uber's FY2025 10-K reports 3,751M trips in Q4 2025 (about 288M a week). That is about 1.3 support contacts per 100 trips, for all topics and all products, from figures two years apart: a rough indicator. Disputes are a subset, so 1% disputed is generous.
- A vendor report claims 2-5 contacts per 100 orders (e-commerce, unverified): not used.

Context for scale, from the verified release: annualised total expenses are about S$10.8M
(S$5,410k × 2), so the in-scope support cost at base is roughly 1% of expenses. The deployment
is a small bet either way, which is why it is sized small.

Likely judge questions and short answers:
- *"Where do the numbers come from?"* Revenue and expenses are from Ryde's published 1H 2026 results; trips, disputes and support cost are our assumptions, because Ryde publishes none. Shadow mode replaces them with measured data.
- *"Does it pay back?"* On cost alone, in about 22 months at a 1% dispute rate, and it depends on that rate. The larger value is speed, consistency and retention, which we have not priced.
- *"Is the AI accurate?"* We measured consistency on 17 synthesised cases, not real-world accuracy. Shadow mode produces that figure.
- *"What if the model is wrong or attacked?"* Money gates, the SGD 50 cap and the confidence floor are Python checks; parties never see model text; a kill switch withholds every ruling.
