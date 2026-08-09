# Cost Analysis

Concrete numbers behind the "$0.08 per audit" claim, and the tradeoffs behind each deployment configuration.

---

## Per-audit token math

A full audit of a small application (BuggyBox scale — ~5 endpoints, 3 personas, 50 steps per persona) works out as follows:

| Item | Value |
|------|-------|
| Personas | 3 |
| Steps per persona | ~50 |
| Input tokens per step (a11y tree + prompt + code context) | ~2,000 |
| Output tokens per step (action decision) | ~300 |
| **Total input tokens (all personas, all steps)** | **~300,000** |
| **Total output tokens** | **~45,000** |
| Bug-verifier reasoning tokens (frontier model, ~10 candidate bugs) | ~15,000 input · ~5,000 output |

The bug-verifier is the only stage that touches the frontier model. Everything else runs on the mid tier.

---

## Configuration A — Fully cloud, no caching (baseline / worst case)

All calls to Claude Sonnet 4.5:

- Input: 315K × $3.00 / 1M = **$0.95**
- Output: 50K × $15.00 / 1M = **$0.75**
- **Total: ≈ $1.70 per audit (~₹145)**

This is what an unoptimized AI-QA tool actually costs. It's the price we're improving on.

---

## Configuration B — Cloud cascade with prompt caching  ·  *default cloud deployment*

Persona actors on Claude Haiku 4.5 (with prompt caching on the ~90% static context), orchestrator + bug verifier on Sonnet 4.5:

| Component | Tokens | Rate | Cost |
|-----------|--------|------|------|
| Haiku 4.5 input (cached, 90% hit) | 270K × 10% billed | $1.00 / 1M | $0.03 |
| Haiku 4.5 input (uncached) | 30K | $1.00 / 1M | $0.03 |
| Haiku 4.5 output | 40K | $5.00 / 1M | $0.20 |
| Sonnet 4.5 verifier input | 15K | $3.00 / 1M | $0.05 |
| Sonnet 4.5 verifier output | 5K | $15.00 / 1M | $0.08 |
| **Total** | | | **≈ $0.39 per audit (~₹33)** |

With LASER-D compressed reasoning applied to the verifier (~64% output-token reduction), verifier output drops to ~1.8K and total falls to **~$0.34**.

---

## Configuration C — Hybrid free-tier + cloud verifier  ·  *recommended for teams < 50 devs*

Persona actors on Gemini 2.5 Flash **free tier** (1M tokens/day free with a Google Cloud project — no card required for the free allotment). Verifier on Sonnet 4.5.

- Gemini Flash (persona actors): **$0** while under free-tier quota
- Sonnet 4.5 verifier: $0.13

**Total: ≈ $0.13 per audit (~₹11) — up to the free-tier daily limit.**

Beyond quota, additional audits fall back to paid Gemini Flash (~$0.20/audit) or paid Haiku 4.5 (~$0.26/audit).

Free-tier ceiling: with 300K input + 45K output per audit, one Google Cloud project handles **~3 audits per day** on the free tier. Multiple projects (or team members) scale linearly.

---

## Configuration D — Fully on-prem  ·  *recommended for regulated verticals*

Persona actors on Qwen 3 7B (Q4_K_M via Ollama or NVFP4 via vLLM). Orchestrator + verifier on Qwen 3 32B (NVFP4).

- **Recurring cost: ₹0**
- Hardware: one GPU with 24 GB VRAM. Options:
  - RTX 4090 (₹2.3 L capex, ~350W under load)
  - RTX 6000 Ada / A5000 (₹4-6 L capex, enterprise support)
  - Blackwell workstation (₹8-15 L capex, native NVFP4 acceleration)
- Electricity: ~₹5 per hour of active audit at ₹8/kWh Indian tariff

**Effective marginal cost: ~₹2 per audit run.**

Break-even vs Configuration B: ~7,000 audits amortizes an RTX 4090. A team running 10 audits/day breaks even in ~2 years — but the real value is regulatory: the ~7,000-audit break-even is meaningless if the alternative (cloud) isn't legally usable at all.

---

## Total-cost-of-ownership comparison

For a team running **20 audits per day for one year (~7,300 audits)**:

| Configuration | Year 1 cost | Notes |
|---------------|-------------|-------|
| Configuration A (naive cloud) | ~$12,400 (~₹10.5 L) | Baseline; no team does this in practice |
| Configuration B (Haiku cascade + caching) | ~$2,850 (~₹2.4 L) | Standard cloud usage |
| Configuration C (free-tier + verifier) | ~$650 (~₹55 K) | Team splits across a few Google Cloud projects |
| Configuration D (on-prem, RTX 4090) | Year 1: ~₹2.4 L capex + ₹15 K electricity. Year 2+: ~₹15 K/year | Compliance-ready |
| **XBOW ($6,000 per pentest)** | **~$43.8 M (~₹372 Cr)** | Not comparable — XBOW is a different product (production bug bounty), included only for scale |

---

## When each configuration wins

| Situation | Choice |
|-----------|--------|
| Solo developer, hobby project | Configuration C (free tier) |
| Startup team < 50 engineers | Configuration C, upgrade to B when quota is a bottleneck |
| Growth-stage company, 50–500 engineers | Configuration B |
| Fintech / healthcare / government / defense | Configuration D — no other option is legally permitted |
| Air-gapped environments (SCIF, on-prem OT networks) | Configuration D |
| Cost-per-audit is the primary metric | Configuration D at scale, C below break-even |
| Speed-of-setup is primary | Configuration C — up in 10 minutes with a Google account |

---

## Cost of *not* using Phalanx

For context, the cost baseline Phalanx competes against:

| Alternative | Typical cost | Notes |
|-------------|--------------|-------|
| One senior QA engineer writing E2E scripts | ~₹1.2–2 L / month per engineer | Doesn't cover multi-persona interaction bugs at all |
| Testim.io Enterprise | ~₹8–40 L / year per team | Single-persona; SaaS-only |
| MABL Enterprise | Similar to Testim | Similar constraints |
| One human pentest engagement | ~₹3–10 L per engagement | Point-in-time; not continuous |
| XBOW autonomous pentest | ~$6,000 (~₹5 L) per audit | Production-only; closed cloud |
| **Not testing pre-ship** (implicit choice for most teams) | Priceless (paid by end users) | ~60% of prod bugs found in the wild |

Phalanx addresses the "not testing pre-ship" gap for the price of a rounding error on the alternatives.

---

## Assumptions and caveats

- **App size scaling.** Costs scale roughly linearly with `endpoints × personas × steps-per-persona`. A 50-endpoint app costs ~10× a 5-endpoint app.
- **API pricing volatility.** Model prices have fallen 5–10× over 2024–2026. Every number above reflects January 2026 published rates. Future price cuts benefit Configurations B and C proportionally.
- **Free-tier changes.** Google's Gemini free tier has changed twice in the past year. Configuration C assumes the January 2026 policy (1M tokens/day per project on Gemini 2.5 Flash). Monitor for changes.
- **Prompt caching cache-hit rates.** The 90% cache-hit rate is achievable only if the system prompt + code context is genuinely stable across a session. Radical persona-instruction changes mid-session invalidate the cache.
- **Quantization accuracy.** NVFP4 and Q4_K_M lose ~2–3 percentage points on standard benchmarks vs full precision. For persona action decisions this is not observed to matter; for bug-verifier reasoning we recommend keeping the verifier on full-precision or Q8 at minimum.
