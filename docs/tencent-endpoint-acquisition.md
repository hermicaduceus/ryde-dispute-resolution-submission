# Tencent LLM endpoint — acquisition note

**Status: BLOCKED on an API key. This is a the operator task, not a build task.**
Written 2026-09-22 after session two. Every URL below is from vendor documentation read on that
date and is **UNVERIFIED against a live call** — nothing here has been exercised.

## Why this is the longest pole

Every ruling the system produces today carries a literal `MOCK` prefix. The pipeline, the
agents, the evidence layer, the gates and the UI are all real; the reasoning is not. Until a
key exists:

- No demo shows the Judge actually reasoning.
- **W4, the evaluation harness, cannot start.** Scoring mock output against
  `data/ground-truth.json` reports a meaningless number.

It is also the only open item with an external dependency, which is why it should be resolved
early rather than in October.

## The good news: four of the five TODOs look already correct

`app/llm/tencent.py` assumes an OpenAI-shaped request, `Authorization: Bearer <key>`, and
`choices[0].message.content` on the way back. Tencent's documented LLM endpoints are
**OpenAI-compatible and use exactly that shape.** If that holds, pinning the endpoint is
configuration, not a rewrite:

```
TENCENT_LLM_API_KEY=...
TENCENT_LLM_ENDPOINT=<base>/chat/completions
TENCENT_LLM_MODEL=<model id>
```

Treat that as a strong prior, not a fact. It is confirmed only by a real call.

## Two candidate paths

**TokenHub (the international gateway) — the likely correct path for a Singapore account.**
One OpenAI-compatible key reaching Hunyuan, DeepSeek, GLM, Kimi and others; Singapore region;
vendor pages advertise free tokens for new users. **The documented base URL differs between
vendor pages** (`tokenhub-intl.tencentcloudmaas.com/v1` on the product page,
`tokenhub-intl.tencentmaas.com` on a third-party guide). Do not pin either from this file —
read it off the console once the account exists.

**Hunyuan direct** — `https://api.hunyuan.cloud.tencent.com/v1/chat/completions`, documented on
the mainland console (`cloud.tencent.com`). The concern is account provenance: our CodeBuddy
account is deliberately on the **International Site**, and vendor material describes the direct
Hunyuan path as assuming a mainland account and mainland payment. Prefer the international
gateway unless the hackathon organisers say otherwise.

## What the operator needs to do

1. Sign in to the Tencent Cloud **international** site with the same account used for CodeBuddy.
2. Find TokenHub (or the equivalent LLM offering) in the console, create an API key.
3. Copy the **exact** base URL and the **exact** model id from the console — case-sensitive, and
   the region-specific host. Do not reuse the URLs in this file.
4. Put all three in `.env` (never committed; `.env.example` shows the shape).

Then the build lane runs the documented check in `app/llm/tencent.py`:

```bash
python3 -m app.cli --llm tencent --dispute data/disputes/RD-0101.json --out runs/
```

A real response means the ruling loses its `MOCK` prefix. That single command is what closes
W3, and W4 unblocks the moment it passes.

## Ask the organisers first — it may be free

The hackathon promises credits per person and markets Tencent Cloud LLM access as part of the
package. **Before paying for anything, ask whether participants get LLM API access and how to
redeem it.** This question is worth adding to the one organiser item still open (`OPEN-ITEMS.md`
§A6, Demo Day format), so both travel in the same message.
