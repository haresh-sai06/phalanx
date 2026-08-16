<div align="center">

# Phalanx

### Autonomous Multi-Persona QA & Security Testing Swarm

*Point it at your repo. Get a full audit report in ~30 minutes.*

![Status](https://img.shields.io/badge/status-concept-blue)
![Round](https://img.shields.io/badge/HackFusion%202026-Round%201-purple)
![License](https://img.shields.io/badge/license-MIT-green)
![Made with](https://img.shields.io/badge/built%20with-LangGraph%201.0%20·%20Playwright%20·%20MCP-cyan)

</div>

---

## Overview

**Phalanx** is an autonomous, multi-persona QA and security testing agent that spawns a dynamic fleet of synthetic users (rider, driver, admin, security-agent — auto-sized to your app's complexity), runs them in parallel against your running application, and delivers a deduplicated, reproducible bug report covering **functional, security, and UX** defects — with an executable Playwright script attached to every finding.

Built for the **pre-ship developer loop** — the gap left open by production pentest tools like XBOW and by scripted-QA tools that require humans to write "test this flow."

---

## The Problem

Pre-ship QA + security testing is broken:

- **Scripted E2E testing** (Playwright, Cypress) costs **500+ dev-hours per quarter** to write and maintain.
- **AI-QA SaaS** (Testim.io, MABL) is single-user, closed-cloud, and expensive.
- **Multi-user interaction bugs** — IDOR, race conditions, permission leaks — require simulating multiple simultaneous users. **No mainstream tool does this today.**
- **AI pentest tools** (XBOW #1 on HackerOne US, Nov 2025; PentestGPT; Antigravity) are closed-cloud and cannot be deployed on-prem — barring their use in fintech / healthcare / government where source code cannot leave the perimeter.

Result: ~60% of production bugs are found by end users, not QA.

---

## The Solution

Phalanx closes the gap with three architectural pillars no existing tool combines:

### 1. Multi-Persona Parallel Swarm
2 to N synthetic users run **simultaneously**, each with its own Playwright browser context. Cross-persona state fuzzing (persona A creates → persona B modifies → persona A reads) catches concurrency + permission bugs no single-agent tool can find.

### 2. BYOM — Bring Your Own Model
Cloud (Claude Sonnet 4.5, Gemini 3 Pro, GPT-5), free-tier (Gemini 2.5 Flash), or fully local (Qwen 3 7B/32B via Ollama or vLLM with NVFP4 quantization). Cost-tiered routing pushes 95% of steps to cheap models; frontier models fire only for bug root-cause reasoning. **On-prem deployment is a first-class use case, not a bolt-on.**

### 3. Code-Aware, Zero-Config
Tree-sitter + embedding-based code retrieval auto-maps your API surface, user roles, auth model, and DB schema. Persona spec is generated automatically — no scripts to write, no configs to tune.

---

## Key Features

| # | Feature | Detail |
|---|---------|--------|
| 1 | **Multi-Persona Parallel Swarm** | Dynamic 2–N synthetic users exploring simultaneously; auto-sized to codebase complexity |
| 2 | **Code-Aware Zero-Config** | Tree-sitter + MiniLM embeddings map endpoints, roles, auth without user input |
| 3 | **BYOM Cost-Tiered Orchestration** | ~$0.08 per audit (cloud cascade) or ₹0 (fully local) |
| 4 | **On-Prem / Air-Gapped Deployment** | Full local stack fits on a single 24 GB GPU; usable in DPDP / HIPAA / SOC2 environments |
| 5 | **Unified Functional + Security + UX Report** | Crashes, layout bugs, XSS, IDOR, auth bypass, race conditions — one tool, CVSS-ranked |
| 6 | **Deterministic Reproduction Scripts** | Every bug ships with executable Playwright script + video + a11y-tree snapshot |

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│  INPUT:  phalanx audit <repo-url> <app-url>                          │
└─────────────────────────────────┬────────────────────────────────────┘
                                  ▼
┌──────────────────────────────────────────────────────────────────────┐
│  PRE-FLIGHT ANALYZER                                                 │
│  tree-sitter AST · MiniLM embeddings · FAISS · API+roles+auth map    │
└─────────────────────────────────┬────────────────────────────────────┘
                                  ▼
┌──────────────────────────────────────────────────────────────────────┐
│  ORCHESTRATOR — LangGraph 1.0                                        │
│  Persona Planner · MCP tool bus · Memory Tool + Context Editing      │
└──────┬──────────────┬──────────────┬──────────────┬──────────────────┘
       ▼              ▼              ▼              ▼
   ┌───────┐      ┌───────┐      ┌───────┐      ┌────────┐
   │ Rider │      │Driver │      │ Admin │      │Security│  ← Persona Swarm
   │ ctx#1 │      │ ctx#2 │      │ ctx#3 │      │ ctx#4  │    (Playwright
   └───┬───┘      └───┬───┘      └───┬───┘      └────┬───┘     parallel)
       │              │              │               │
       ▼              ▼              ▼               ▼
       observe (a11y tree) → plan → act → observe → repeat
                                  │
                                  ▼
┌──────────────────────────────────────────────────────────────────────┐
│  DETECT · DEDUP · REPORT                                             │
│  Bug Detector · Fingerprint hash · CVSS ranking · HTML/PDF export    │
└─────────────────────────────────┬────────────────────────────────────┘
                                  ▼
        Audit Report · Playwright Repro Scripts · Video Evidence
```

Full architecture diagram: [`docs/architecture.svg`](docs/architecture.svg)

Deep-dive documents:
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — every stage, every model tier, every efficiency layer
- [`docs/ROADMAP.md`](docs/ROADMAP.md) — 7-phase plan through 2028
- [`docs/COST-ANALYSIS.md`](docs/COST-ANALYSIS.md) — token math, deployment configurations, TCO comparison

---

## Tech Stack

**Agent Orchestration**
- [LangGraph 1.0](https://blog.langchain.com/langgraph-1-0/) — stateful multi-agent graph
- [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) — tool bus
- Anthropic Skills API + Memory Tool + Context Editing

**Browser Automation**
- [Playwright](https://playwright.dev/) — parallel browser contexts, a11y-tree observation
- Set-of-Mark (SoM) visual prompting

**Code Understanding**
- [Tree-sitter](https://tree-sitter.github.io/) — multi-language AST parsing
- SentenceTransformer `all-MiniLM-L6-v2` — code embeddings
- FAISS — vector retrieval

**LLM Layer (BYOM)**
- **Cloud:** Claude Sonnet 4.5, Claude Haiku 4.5, Gemini 3 Pro, Gemini 2.5 Flash, GPT-5, GPT-5 mini
- **Local:** Qwen 3 7B / 32B via Ollama or vLLM 0.8 with NVFP4 quantization
- **Router:** UniRoute-inspired feature-vector cascade with cold-start support

**Efficiency Stack**
- Anthropic Prompt Caching (90% cost reduction on static context)
- TurboRAG-style prefix caching (vLLM `--enable-prefix-caching`)
- LASER-D compressed reasoning (ICLR 2026) — 64% reasoning-token reduction
- Accessibility tree over screenshots — 10× observation-token reduction
- Bug fingerprint dedup, semantic action cache (Redis)

**Serving & Backend**
- vLLM 0.8, Ollama, SGLang
- FastAPI + PostgreSQL + Redis
- Docker Compose (dev) / Kubernetes (prod)

**Frontend**
- Next.js 15 + Tailwind CSS
- Live persona swarm dashboard with real-time exploration visualization

---

## Cost per Audit (BuggyBox testbench)

| Configuration | Cost per Run |
|---|---|
| Cloud cascade + Anthropic Prompt Caching | **≈ $0.08 (₹7)** |
| Gemini 2.5 Flash free tier | **₹0** |
| Fully local (Ollama Qwen 3 7B) | **₹0 (electricity only)** |

Compare: XBOW pentest ≈ $6,000/audit. Testim.io ≈ $50/run.

---

## Roadmap

- **Phase 1 (HackFusion 2026 · Aug 28–29):** Working prototype with 2 personas, BuggyBox testbench, full report pipeline, live dashboard
- **Phase 2 (Q4 2026):** WALT-style tool synthesis — personas learn reusable browser tools per app
- **Phase 3 (Q1 2027):** LoRA-per-persona fine-tuning on app-specific bug patterns
- **Phase 4 (Q2 2027):** Native CI/CD integration — auto-audit on every GitHub PR
- **Phase 5 (Q3 2027):** Compliance Mode — signed SOC2 / ISO-27001 evidence bundle export
- **Phase 6 (Q4 2027):** Mobile app testing via Appium bridge
- **Phase 7:** Publish [WebArena-Verified](https://github.com/ServiceNow/webarena-verified) benchmark leaderboard entry

---

## Positioning

|  | Playwright | Testim | Antigravity | XBOW | PentestGPT | **Phalanx** |
|---|:-:|:-:|:-:|:-:|:-:|:-:|
| Zero-config | ✗ | Partial | ✓ | ✓ | Partial | **✓** |
| Multi-persona parallel | ✗ | ✗ | ✗ | Partial | ✗ | **✓** |
| Functional + Security unified | ✗ | ✗ | Partial | Security only | Security only | **✓** |
| BYOM | N/A | ✗ | ✗ | ✗ | Partial | **✓** |
| On-prem / air-gapped | ✓ | ✗ | ✗ | ✗ | Partial | **✓** |
| Cost-tiered routing | N/A | ✗ | ✗ | ✗ | ✗ | **✓** |
| Cost per audit | Free* | ~$50 | ~$5 | $6,000 | ~$2 | **~$0.08** |

*Free per run, but ~500 dev-hours/quarter in script maintenance.

> **XBOW proved offensive AI pentest works at HackerOne scale — in production, closed-cloud, security-only.**
> **Phalanx solves the pre-ship dev loop — multi-persona, on-prem, model-agnostic, unified QA + security.**

---

## Status

> **Round 1 concept submission for HackFusion 2026.** Full working prototype targeted for Round 2 (24-hour offline hackathon, Aug 28–29, 2026 · Chennai Institute of Technology). This repository will progressively fill in with the core orchestrator, persona actors, BuggyBox testbench, and live dashboard during the 24-hour build. Watch this space.

---

## Team — GravitySurfers

- Haresh Sainaath S
- Shyam Prasath S
- Navika G
- Maithra Rajaram

**Institution:** Sri Krishna College of Technology, Coimbatore

Prototype under /prototype - Kindly check

---

## HackFusion 2026

Submitted to **HackFusion 2026** — National-Level 24-Hour Offline Hackathon organized by the Department of Computer Science & Engineering, [Chennai Institute of Technology](https://citchennai.edu.in/).

- **Round 1 (Online PPT):** Aug 3–17, 2026
- **Round 2 (Offline Hackathon):** Aug 28–29, 2026 · Chennai
- **Prize Pool:** ₹1,00,000

---

## License

MIT © 2026 GravitySurfers (proposed — finalize before public release)

---

## References & Prior Art

- [XBOW hits #1 on HackerOne US](https://www.businesswire.com/news/home/20251112470912/en/) (Nov 2025)
- [LangGraph 1.0 release](https://blog.langchain.com/langgraph-1-0/) (Oct 2025)
- [Anthropic Context Management](https://claude.com/blog/context-management) — Memory Tool + Context Editing
- [TurboRAG paper](https://arxiv.org/abs/2410.07590) — precomputed KV cache reuse
- [LASER-D (ICLR 2026)](https://openreview.net/) — compressed chain-of-thought reasoning
- [WebArena-Verified](https://github.com/ServiceNow/webarena-verified) — target benchmark
- [Model Context Protocol](https://modelcontextprotocol.io/) — tool interoperability standard

---

<div align="center">
<sub>Built with ambition, shipped with rigor · GravitySurfers · HackFusion 2026</sub>
</div>
