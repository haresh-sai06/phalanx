# Architecture

A detailed walkthrough of the Phalanx system — every stage, every model tier, every efficiency layer, and the design decisions behind them.

See also: [`architecture.svg`](architecture.svg) for the full visual diagram.

---

## Design principles

Three constraints drove every architectural decision:

1. **Zero-config to the developer.** The tool must work with nothing more than a repo URL and a running app URL. Any additional configuration is failure.
2. **Model-agnostic at every seam.** No single-vendor lock-in. Every model role must accept a cloud API, a free-tier API, or a locally-served open-weight model as a first-class option.
3. **Cost defensible under real usage.** A team running 20 audits per day cannot pay $6,000 per run. The efficiency stack is not optional decoration — it is what makes on-prem deployment economical.

---

## Stage 1 — Input

The entry point is a single command:

```bash
phalanx audit <repo-url> <app-url> [--config phalanx.yml]
```

Optional flags cover: seed credentials for authenticated flows, max-runtime budget, model tier overrides, and output directory. Everything else is inferred.

---

## Stage 2 — Pre-flight Analyzer

Before any browser action, the analyzer builds a static understanding of the target:

- **`tree-sitter`** parses the repository AST across every language present (JavaScript, TypeScript, Python, Go, Java, Rust). We chose tree-sitter over language-specific parsers because it handles polyglot repos without a per-language pipeline.
- **Endpoint extraction** walks the AST for framework-specific patterns (Express routes, FastAPI decorators, Django URLconf, Gin handlers) and collects `(method, path, handler, auth-decorator)` tuples.
- **Role extraction** scans middleware, decorators, and RBAC annotations (`@role`, `requiresAuth`, `permission_required`) to surface the user role model.
- **Auth model inference** classifies session handling: JWT, session-cookie, OAuth, API-key. This determines how personas obtain credentials.
- **Code embeddings** — every function and route handler is embedded with `all-MiniLM-L6-v2` (384-dim, runs entirely on CPU, 100MB model, no API cost). Embeddings feed into FAISS for retrieval during the reasoning stage.

Output: a `preflight.json` artifact consumed by the persona planner.

**Why local embeddings.** Sending source code to a cloud embedding API violates the on-prem promise. MiniLM is fast enough (~2000 chunks/second on a laptop CPU) and accurate enough for retrieval; upgrading to a larger encoder is a config flip, not a rewrite.

---

## Stage 3 — Orchestrator (LangGraph 1.0)

The orchestrator is a stateful graph that plans, spawns, and coordinates persona agents. We use LangGraph 1.0 (stable since October 2025) rather than raw agent frameworks because:

- Its graph model handles our need for **dynamic node spawning** — persona count is not known until after pre-flight
- Its checkpointing lets an audit **resume from failure** without re-running the expensive analyzer stage
- The **cross-persona message bus** we need for concurrency fuzzing maps cleanly onto LangGraph's shared state

### Persona Planner sub-graph

The planner takes `preflight.json` and outputs a `PersonaSpec`:

```
n_personas = len(user_roles) + (1 if concurrent_state_detected else 0)
specialization:
  + 1 security-agent (always)
  + 1 UX-agent (if frontend_complexity > threshold)
  + 1 performance-agent (if long_tasks_detected)
```

Each persona receives:
- Its assigned role (`rider`, `driver`, `admin`, `security`, ...)
- Priority test paths (top-K API surfaces relevant to its role via FAISS retrieval)
- Model tier assignment (see Model Layer)
- Budget: max steps, max tokens, max wall-clock

### Cross-persona message bus

Concurrency bugs (IDOR, race conditions, stale-state reads) only surface when personas interact across shared state. The message bus carries events like:

```
{ event: "resource.created", persona: "rider", resource: "ride:47", timestamp: T }
{ event: "resource.modified", persona: "driver", resource: "ride:47", timestamp: T+3s }
```

Personas subscribe to events that affect them, giving each persona a live view of what others have done. This is what lets the `security-agent` immediately test *"can persona A still access resource:47 after persona B revoked their permission?"* — the classic IDOR trigger.

---

## Stage 4 — Persona Swarm

Each persona is an autonomous agent bound to:

- Its own **Playwright browser context** (isolated cookies, storage, cache)
- Its own **model tier** (see Model Layer)
- Its own **observation channel** — accessibility tree, DOM, network requests, console messages

The observation-action loop per persona:

```
1. observe:  a11y_tree = page.accessibility.snapshot()
             diff = compute_diff(a11y_tree, last_tree)
2. plan:     next_action = actor_model(diff, goal, recent_history)
3. act:      execute(next_action)   # click, type, navigate, wait
4. detect:   check(console, network, dom, response_codes) → candidate_bugs
5. update:   record persona state, emit events to bus
6. repeat
```

**Why accessibility trees over screenshots.** A screenshot of a modern web page consumes 4,000–12,000 vision tokens per observation. The accessibility tree is a structured representation of the same interactive elements at ~400 tokens. Over a 50-step persona session, this is the difference between $1.50 and $0.06 per persona. Screenshots are still captured for the report — but for the model's observation channel, we use the a11y tree.

**Set-of-Mark (SoM) prompting** is layered on top: numbered marks are overlaid on interactive elements so the model outputs `"click element 7"` instead of pixel coordinates or fragile selectors. This has become the standard technique for UI agents post-2024 and dramatically reduces action failure rate.

---

## Stage 5 — Detect · Dedup · Report

### Bug Detector

Runs continuously as each persona acts. Watches:

- **Console errors** — unhandled exceptions, React error boundaries, framework warnings
- **HTTP anomalies** — 4xx on flows that should succeed, 5xx anywhere, 200 responses containing error payloads
- **DOM crashes** — blank pages, error toast components, white-screens-of-death
- **Unauthorized data** — persona A receives data belonging to persona B (the IDOR signature)
- **Injection reflections** — payloads sent by the security-agent showing up unescaped in responses
- **Timing anomalies** — actions that succeed when they should be rate-limited

### Bug Fingerprint

Every candidate bug is hashed into a fingerprint:

```
fingerprint = sha256(
    endpoint_normalized +
    bug_class +
    stack_signature +
    key_response_fields
)
```

The normalization step strips volatile fields (session IDs, timestamps, generated UUIDs) so that 500 hits of "the same underlying bug" collapse to one report entry. This is the difference between a report a human can act on and 500-page noise.

### Frontier LLM verifier

For each unique fingerprint, one call to the frontier model (Claude Sonnet 4.5 / Gemini 3 Pro) performs:

- **Root-cause reasoning** — given the candidate + relevant code chunks (via FAISS retrieval), classify the actual defect
- **Severity assignment** — CVSS 3.1 for security bugs, custom rubric for functional/UX
- **Reproduction script generation** — emit a runnable Playwright test that reproduces the finding deterministically

This is the *only* stage that uses frontier tokens. Everything upstream runs on cheap tiers.

### Report Generator

Emits an HTML/PDF report with:

- Executive summary (bug count by severity)
- One page per unique fingerprint
- Screenshot, video clip, a11y-tree snapshot, HTTP trace per bug
- Copy-paste-runnable Playwright script per bug
- Timeline of the persona actions that triggered it

---

## Model Layer (BYOM)

Every model call routes through `phalanx.router.select_model(role, complexity)`. The router is where BYOM lives.

### Tier structure

| Tier | Purpose | Cloud options | Local options | Typical share of calls |
|------|---------|---------------|---------------|------------------------|
| **Frontier** | Bug root-cause reasoning, orchestrator planning under uncertainty | Claude Sonnet 4.5, Gemini 3 Pro, GPT-5 | Qwen 3 32B (NVFP4) | ~5% |
| **Mid** | Persona actors: plan next action, act, observe | Claude Haiku 4.5, Gemini 2.5 Flash, GPT-5 mini | Qwen 3 7B (Q4), Llama 3.1 8B | ~90% |
| **Vision** | Visual bug detection (broken layouts, error toasts) | Gemini 2.5 Flash Vision | LLaVA 7B, Qwen-VL 7B | ~3% |
| **Embed** | Code and text retrieval | OpenAI text-embedding-3 | `all-MiniLM-L6-v2` (default) | ~2% |

### Router design

The router uses feature-vector routing (inspired by UniRoute, 2026) so it can accept models it has never seen before:

```python
def select_model(role, complexity):
    candidates = registry.for_role(role)
    features = extract_features(complexity)  # length, reasoning depth, tool count
    scores = {m: score_by_features(m, features) for m in candidates}
    return max(scores, key=scores.get)
```

Add a new model by editing `models.yml` — no code change. The router evaluates it against known benchmarks on first use.

### Escalation

The router supports **confidence-based cascade**: if the mid-tier model returns low-confidence output or fails to make progress in N consecutive steps, that persona's remaining budget is upgraded to the frontier tier for the next K steps. This is what lets a Qwen 7B persona handle 95% of a session but hand off to Sonnet 4.5 for a particularly gnarly flow.

---

## Efficiency Stack

These are the six techniques that make Phalanx economically viable. Every one is applied by default.

### 1. Prompt Caching (Anthropic / Gemini Context Caching)

The system prompt + persona role prompt + code context are identical across every step of a persona session. Anthropic's Prompt Caching (with 1-hour extended TTL) caches these at 90% discount on subsequent reads. Gemini has an equivalent Context Caching feature. For local models, vLLM's `--enable-prefix-caching` provides the same benefit.

**Impact:** ~90% reduction in tokens billed as input on a per-persona basis.

### 2. Accessibility Tree Observation (already covered above)

**Impact:** ~10× fewer observation tokens per step compared to screenshot-based agents.

### 3. DOM diff between steps

After the initial page load, only *changed* elements are sent to the model on subsequent steps. Static navigation, unchanged sidebars, and stable headers are omitted.

**Impact:** ~80% additional reduction in observation tokens within a session.

### 4. Model Cascade

Small model handles routine actions; frontier model fires only when it earns its keep.

**Impact:** ~10× reduction in overall dollar cost vs a naive frontier-only agent.

### 5. LASER-D compressed reasoning (ICLR 2026)

Replaces verbose Chain-of-Thought with a compressed reasoning representation. Applied to the bug-verifier stage.

**Impact:** ~64% reduction in reasoning-output tokens with matched accuracy.

### 6. Bug fingerprint dedup

Not a token efficiency, but a human efficiency: 500 raw candidate bugs collapse to 1 report entry.

**Impact:** Report becomes actionable rather than overwhelming.

### 7. Semantic action cache

Persona asks: *"What element is the login submit button on this page?"* — the answer is embedded and cached in Redis. Second run of the same audit on the same app: the lookup is a Redis hit rather than an LLM call.

**Impact:** Repeat audits on stable apps run at ~1/3 the cost of the first audit.

---

## Deployment topology

Two supported deployments:

### Cloud + Free-Tier (recommended for teams < 50 devs)

- Orchestrator + reasoning: Anthropic API or Gemini API
- Persona actors: Gemini 2.5 Flash free tier (1M tokens/day free) + paid overflow
- Vision: Gemini Vision
- Compute: any single VM with 4 GB RAM

Cost: ~$0.08 per full audit run.

### Fully On-Prem (recommended for regulated verticals)

- Orchestrator: Qwen 3 32B via vLLM 0.8 with NVFP4 quantization
- Persona actors: Qwen 3 7B (Q4_K_M via Ollama, or NVFP4 via vLLM)
- Vision: Qwen-VL 7B
- Compute: single GPU with 24 GB VRAM (RTX 4090, A5000, RTX 6000 Ada, or Blackwell workstation)
- Zero data leaves the perimeter. DPDP Act / HIPAA / SOC2 compliant by construction.

Cost: ₹0 recurring (electricity only).

---

## What we're not building (explicit non-goals)

To avoid mission creep, Phalanx explicitly does *not*:

- Replace human security review of critical systems
- Perform continuous production monitoring (Datadog, Sentry, Grafana do this well already)
- Fix bugs automatically — a bug report + repro script is the deliverable; the fix is human work
- Test mobile apps in phase 1 (Appium bridge is roadmap phase 6)
- Support decompiled or obfuscated code

We are a pre-ship, dev-loop, source-available-code testing tool. Every other interpretation is out of scope until roadmap phase 7+.
