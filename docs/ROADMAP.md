# Roadmap

Seven phases, ~24 months to product-market fit. Each phase has concrete deliverables, dependencies, and success criteria.

---

## Phase 1 — Prototype  ·  August 2026  ·  HackFusion 24-hour build

**Goal:** end-to-end working system on a controlled testbench.

**Deliverables**
- Two personas running in parallel via LangGraph 1.0 orchestrator
- BuggyBox target application with 10 planted bug categories
- Pre-flight analyzer (tree-sitter + endpoint extraction, single-language: Node/Express)
- Bug detector for functional + one class of security bugs (IDOR)
- HTML report with severity ranking + Playwright reproduction scripts
- Live persona dashboard (Next.js) showing exploration in real time

**Success criteria**
- Finds ≥ 6 of 10 planted bugs in BuggyBox
- Report generation ≤ 30 minutes wall-clock on cloud tier
- Zero-config launch: `phalanx audit <buggybox-url>` requires no flags

**Explicit non-goals for Phase 1**
- Multi-language repo support (Node only)
- Auto-fix suggestions
- CI/CD integration
- Compliance evidence bundle
- Mobile support

---

## Phase 2 — Tool Synthesis  ·  Q4 2026

**Goal:** personas learn app-specific browser tools rather than re-discovering them each session.

Inspired by [WALT (Web Agents that Learn Tools)](https://arxiv.org/abs/2510.01524), Oct 2025.

**Deliverables**
- Persona-side tool library (per-app, versioned)
- Tool synthesis pipeline: observe repeated action patterns → extract as callable tool → store
- Tool retrieval at persona planning time (reduces exploration overhead by ~40%)

**Dependencies**
- Phase 1 core loop stable
- Persistent app-state storage (PostgreSQL schema)

**Success criteria**
- On second audit of same app, mean actions-per-bug drops by ≥ 30%
- Synthesized tools transfer across personas within one app

---

## Phase 3 — LoRA per Persona  ·  Q1 2027

**Goal:** app-specific fine-tuning without full model retraining.

**Deliverables**
- Nightly LoRA training pipeline: collects successful persona traces → distills into a LoRA adapter per persona-role
- Adapter swap at persona spawn (one base model, many adapters)
- Adapter marketplace concept (share adapters across teams for common frameworks: Next.js SaaS, Django admin, etc.)

**Dependencies**
- Phase 2 tool synthesis (traces are richer with tools)
- On-prem serving stack (vLLM 0.8+ with LoRA support)

**Success criteria**
- LoRA'd persona catches ≥ 20% more bugs than base persona on same app
- Adapter file < 100 MB per persona-role

---

## Phase 4 — CI/CD Native  ·  Q2 2027

**Goal:** every pull request triggers a targeted audit.

**Deliverables**
- GitHub Action + GitLab CI + generic webhook receiver
- Diff-aware auditing: only re-test flows touching changed files
- PR-comment reporter with severity gate (fail CI if new critical bug introduced)
- Baseline tracking: which bugs are new-in-this-PR vs pre-existing

**Dependencies**
- Phase 1 core
- Bug fingerprinting stable enough to compare across runs

**Success criteria**
- Median PR audit ≤ 8 minutes
- False-positive rate on regressions ≤ 5%
- One design partner running Phalanx in CI on their main branch

---

## Phase 5 — Compliance Mode  ·  Q3 2027

**Goal:** enterprise sale to regulated verticals.

**Deliverables**
- Signed audit trail (every persona action, every model call, every finding logged and signed)
- Evidence bundle export for SOC2 CC7.1/CC7.2, ISO 27001 A.14.2.8, and PCI-DSS 6.5
- Redaction rules for PII in reports (regex + configurable extractors)
- On-prem-only mode enforcement (refuses to start if cloud endpoints configured)

**Dependencies**
- On-prem stack production-hardened
- Legal review of evidence-bundle format with a compliance advisor

**Success criteria**
- One fintech pilot successfully uses Phalanx evidence bundles in their annual SOC2 audit
- Third-party auditor validates evidence-bundle authenticity

---

## Phase 6 — Mobile  ·  Q4 2027

**Goal:** extend the multi-persona model to native mobile apps.

**Deliverables**
- Appium bridge (replacing the Playwright layer for mobile targets)
- iOS + Android persona actors
- Deep-link handling, biometric prompts, push-notification interactions
- Emulator + device-farm integration

**Dependencies**
- Phase 4 CI/CD (mobile is most valuable in CI)
- Access to at least one iOS + Android device farm

**Success criteria**
- Successful full audit of a mobile-first sample app (BuggyBox-Mobile)
- Report parity with web reports (screenshot, video, repro-script equivalents)

---

## Phase 7 — Benchmark Leadership  ·  2028

**Goal:** publish external validation.

**Deliverables**
- Formal submission to [WebArena-Verified](https://github.com/ServiceNow/webarena-verified) leaderboard
- Public performance report vs XBOW (on scopes both tools can address), vs Testim.io, vs baseline scripted tests
- Academic paper on multi-persona coverage advantages (target: NeurIPS 2028 Datasets & Benchmarks track)

**Success criteria**
- Top-5 finish on WebArena-Verified as of publication date
- Paper accepted at NeurIPS or ICLR

---

## Cross-phase engineering priorities

Independent of the phase schedule, these workstreams run continuously:

- **Efficiency stack refinement.** Each new caching / compression / routing technique published in the AI-serving literature is evaluated for inclusion.
- **Model catalog expansion.** New open-weight releases (Qwen 4, Llama 4, DeepSeek future releases) added to the router as they clear the tool-use reliability threshold.
- **BYOM router improvements.** Cold-start handling for user-brought models, better latency prediction.
- **Reporting UX.** The report is the artifact users actually see — polish never stops.

---

## Risk register

Top risks to the roadmap, ranked by likelihood × impact:

| Risk | Mitigation |
|------|-----------|
| Frontier model API cost outpaces revenue | On-prem stack must stay on the critical path; cannot degrade to a "cloud-only in practice" tool |
| Multi-persona coverage claims fail to hold on real apps beyond BuggyBox | Publish honest failure-mode analysis with each major release; do not overclaim |
| Regulatory environment forces telemetry off (fine) or on (bad) | Compliance Mode designed for zero-telemetry on-prem operation from the start |
| Adversarial disclosure — Phalanx used offensively against apps its owners did not consent to | ToS + technical rate-limiting + refuse-to-attack-non-authorized-origins by default |
| Bugs found by Phalanx are noise (low precision) | Aggressive dedup + severity gating + human-in-the-loop review before reporting to any external tracker |
