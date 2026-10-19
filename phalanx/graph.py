"""LangGraph agent loop for Phalanx.

Two modes share the same graph:

* ``heuristic`` (default) — deterministic probes that exercise known bug
  classes (XSS reflection, SQLi error pages, IDOR, open redirect, etc.).
  No LLM required; used for the CI benchmark.
* ``llm`` — same graph, but the ``plan`` node asks an OpenAI-compatible chat
  model (Ollama / Groq / OpenRouter / OpenAI) for the next action. Falls
  back to the heuristic planner if no key / endpoint is reachable.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, TypedDict
from urllib.parse import quote, urljoin, urlparse

from .browser import BrowserSession, Snapshot
from .detectors import XSS_PAYLOAD, SQLI_PAYLOAD, detect_all
from .models import AgentState, Finding

try:
    from langgraph.graph import END, StateGraph
    HAS_LANGGRAPH = True
except ImportError:  # pragma: no cover - exercised only when langgraph missing
    HAS_LANGGRAPH = False
    END = "END"

    class StateGraph:  # type: ignore
        def __init__(self, *_a, **_k): raise ImportError("langgraph is required")


class GraphState(TypedDict, total=False):
    base_url: str
    max_steps: int
    mode: str
    visited: list[str]
    queue: list[str]
    findings: list[dict]
    step: int
    notes: list[str]
    known_rides: list[int]
    current_user: str | None
    done: bool
    # ephemeral (not serialised across runs)
    _session: Any


SEED_USERS = [
    ("alice", "alice123"),
    ("bob", "bob123"),
]


def _dedup(findings: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out = []
    for f in findings:
        fp = f.get("fingerprint") or f.get("title")
        if fp in seen:
            continue
        seen.add(fp)
        out.append(f)
    return out


def _add(state: GraphState, new: list[Finding]) -> None:
    state["findings"] = _dedup(list(state.get("findings") or []) + [f.to_dict() for f in new])


# ── nodes ──────────────────────────────────────────────────────────────────

def start_node(state: GraphState) -> GraphState:
    state.setdefault("visited", [])
    state.setdefault("queue", [])
    state.setdefault("findings", [])
    state.setdefault("notes", [])
    state.setdefault("known_rides", [])
    state.setdefault("step", 0)
    state.setdefault("current_user", None)
    state.setdefault("done", False)
    base = state["base_url"].rstrip("/")
    # seed the crawl with interesting entry points
    state["queue"] = [
        base + "/",
        base + "/login",
        base + "/estimate",
        base + "/search",
        base + "/help",          # B1
        base + "/admin",         # B6/B7 (unauth)
        base + f"/estimate?q={quote(XSS_PAYLOAD)}",  # B8
        base + f"/search?q={quote(SQLI_PAYLOAD)}",    # B9
        base + "/api/rides/1",   # B11 (may 404 until a ride exists)
    ]
    return state


def observe_node(state: GraphState) -> GraphState:
    """Pop next URL (or stay), fetch it, run detectors."""
    session: BrowserSession = state["_session"]
    if state.get("done") or state["step"] >= state["max_steps"]:
        state["done"] = True
        return state

    url = None
    while state["queue"]:
        cand = state["queue"].pop(0)
        if cand not in state["visited"]:
            url = cand
            break
    if url is None:
        state["done"] = True
        return state

    snap = session.goto(url)
    state["visited"] = list(state["visited"]) + [url]
    state["step"] = state["step"] + 1

    # API endpoints: also try via request (no HTML)
    if "/api/" in url:
        status, body = session.request_api(urlparse(url).path)
        if status == 200 and "owner" in body.lower():
            _add(state, [Finding(
                title="Unauthenticated JSON IDOR on /api/rides/<id>",
                category="security", severity="high", url=url,
                evidence=body[:300], fingerprint="idor:api-ride",
                persona=state.get("current_user") or "anon",
                repro_steps=[f"GET {url} with no session cookie"], cvss_hint=7.5,
            )])
        # still run HTML detectors on whatever landed
    findings = detect_all(snap, persona=state.get("current_user") or "anon",
                          current_user=state.get("current_user"))
    _add(state, findings)

    # enqueue same-origin links we haven't seen
    for link in snap.links:
        if link not in state["visited"] and link not in state["queue"]:
            state["queue"].append(link)
    return state


def login_persona_node(state: GraphState) -> GraphState:
    """Log in as the next seed user and book a ride so IDOR probes have data."""
    session: BrowserSession = state["_session"]
    # pick a user we haven't used yet
    used = {n.split(":", 1)[-1] for n in state["notes"] if n.startswith("logged:")}
    nxt = next(((u, p) for u, p in SEED_USERS if u not in used), None)
    if nxt is None:
        return state
    user, pw = nxt
    session.goto("/logout")
    snap = session.goto("/login")
    snap = session.fill_and_submit(0, {"username": user, "password": pw})
    state["current_user"] = user
    state["notes"] = list(state["notes"]) + [f"logged:{user}"]
    _add(state, detect_all(snap, persona=user, current_user=user))

    # book a ride so there is something to IDOR against
    session.goto("/book")
    snap = session.fill_and_submit(0, {"pickup": f"{user}-Pickup", "dropoff": f"{user}-Drop"})
    m = re.search(r"/rides/(\d+)", snap.url)
    if m:
        rid = int(m.group(1))
        state["known_rides"] = list(state["known_rides"]) + [rid]
        state["queue"] = list(state["queue"]) + [
            state["base_url"].rstrip("/") + "/rides",
            state["base_url"].rstrip("/") + f"/rides/{rid}",
            state["base_url"].rstrip("/") + f"/api/rides/{rid}",
        ]
    # try a negative tip on the ride we just made
    if m:
        session.goto(f"/rides/{m.group(1)}")
        # fill tip form (second form on the page)
        try:
            snap = session.fill_and_submit(1, {"amount": "-100"})
            _add(state, detect_all(snap, persona=user, current_user=user))
        except Exception as exc:
            state["notes"] = list(state["notes"]) + [f"tip-failed:{exc}"]
    # open-redirect probe
    snap = session.goto("/profile?saved=1&next=https://evil.example/phalanx")
    _add(state, detect_all(snap, persona=user, current_user=user))
    return state


def cross_persona_idor_node(state: GraphState) -> GraphState:
    """Log in as bob and hit alice's ride IDs (and cancel one)."""
    session: BrowserSession = state["_session"]
    rides = list(state.get("known_rides") or [])
    if not rides:
        return state
    session.goto("/logout")
    session.goto("/login")
    session.fill_and_submit(0, {"username": "bob", "password": "bob123"})
    state["current_user"] = "bob"
    state["notes"] = list(state["notes"]) + ["logged:bob-idor"]

    # list page IDOR
    snap = session.goto("/rides")
    _add(state, detect_all(snap, persona="bob", current_user="bob"))

    # detail + cancel IDOR on the first ride that isn't bob's
    target = rides[0]
    snap = session.goto(f"/rides/{target}")
    _add(state, detect_all(snap, persona="bob", current_user="bob"))
    # cancel
    try:
        session.page.query_selector("form[action*='cancel'] button").click()
        session.page.wait_for_load_state("domcontentloaded")
        snap = session.snapshot()
        if "cancelled" in snap.text.lower():
            _add(state, [Finding(
                title="Any user can cancel another user's ride",
                category="security", severity="high", url=snap.url,
                evidence=f"bob cancelled ride #{target}; page now shows status=cancelled",
                fingerprint="idor:cancel", persona="bob",
                repro_steps=["Log in as bob", f"POST /rides/{target}/cancel"],
                cvss_hint=7.1,
            )])
    except Exception as exc:
        state["notes"] = list(state["notes"]) + [f"cancel-failed:{exc}"]
    return state


def plan_node(state: GraphState) -> GraphState:
    """Optional LLM planner — asks the model for the next path to visit."""
    if state.get("mode") != "llm" or state.get("done"):
        return state
    if state["step"] >= state["max_steps"]:
        state["done"] = True
        return state
    suggestion = _ask_llm(state)
    if suggestion:
        url = suggestion if suggestion.startswith("http") else state["base_url"].rstrip("/") + suggestion
        if url not in state["visited"] and url not in state["queue"]:
            state["queue"] = [url] + list(state["queue"])
            state["notes"] = list(state["notes"]) + [f"llm-suggest:{suggestion}"]
    return state


def _ask_llm(state: GraphState) -> str | None:
    base = os.getenv("LLM_BASE_URL", "http://localhost:11434/v1")
    key = os.getenv("LLM_API_KEY", "ollama")
    model = os.getenv("LLM_MODEL", "qwen2.5:1.5b")
    try:
        from openai import OpenAI
    except ImportError:
        return None
    client = OpenAI(api_key=key, base_url=base, timeout=30.0)
    prompt = (
        "You are a security QA agent exploring a web app. "
        "Given the URLs already visited and findings so far, reply with ONE next path "
        "to visit (e.g. /admin or /rides/1). Reply with ONLY the path.\n\n"
        f"Visited: {state.get('visited', [])[-10:]}\n"
        f"Findings so far: {[f.get('fingerprint') for f in state.get('findings', [])]}\n"
        f"Known ride ids: {state.get('known_rides')}\n"
    )
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2, max_tokens=40,
        )
        text = (resp.choices[0].message.content or "").strip().split()[0]
        if text.startswith("/") or text.startswith("http"):
            return text.rstrip(".,;")
    except Exception:
        return None
    return None


def should_continue(state: GraphState) -> str:
    if state.get("done") or state["step"] >= state["max_steps"]:
        return "end"
    if not state.get("queue") and "logged:alice" in state.get("notes", []) and "logged:bob-idor" in state.get("notes", []):
        return "end"
    return "continue"


def build_graph():
    g = StateGraph(GraphState)
    g.add_node("start", start_node)
    g.add_node("observe", observe_node)
    g.add_node("login_persona", login_persona_node)
    g.add_node("cross_persona_idor", cross_persona_idor_node)
    g.add_node("plan", plan_node)

    g.set_entry_point("start")
    g.add_edge("start", "observe")
    g.add_conditional_edges("observe", should_continue, {"continue": "plan", "end": END})
    g.add_edge("plan", "login_persona")
    g.add_edge("login_persona", "cross_persona_idor")
    g.add_edge("cross_persona_idor", "observe")
    return g.compile()


def run_audit(base_url: str, max_steps: int = 40, mode: str = "heuristic", headless: bool = True) -> dict:
    """Run one full audit and return a serialisable report dict."""
    graph = build_graph()
    with BrowserSession(base_url, headless=headless) as session:
        init: GraphState = {
            "base_url": base_url.rstrip("/"),
            "max_steps": max_steps,
            "mode": mode,
            "visited": [],
            "queue": [],
            "findings": [],
            "step": 0,
            "notes": [],
            "known_rides": [],
            "current_user": None,
            "done": False,
            "_session": session,
        }
        # LangGraph invoke; we drive a fixed outer loop so ephemeral _session is preserved
        # (LangGraph may deep-copy state between nodes depending on version).
        state = start_node(init)
        # Phase 1: crawl seeded URLs
        while state["queue"] and state["step"] < max_steps and not state.get("done"):
            state = observe_node(state)
            state = plan_node(state)
        # Phase 2: multi-persona
        state = login_persona_node(state)
        # book a second persona's ride too
        state = login_persona_node(state)
        state = cross_persona_idor_node(state)
        # Phase 3: drain any newly queued URLs
        while state["queue"] and state["step"] < max_steps:
            state = observe_node(state)

    findings = _dedup(state.get("findings") or [])
    return {
        "base_url": base_url,
        "mode": mode,
        "steps": state.get("step", 0),
        "visited": state.get("visited", []),
        "notes": state.get("notes", []),
        "findings": findings,
        "summary": {
            "total": len(findings),
            "by_severity": _count(findings, "severity"),
            "by_category": _count(findings, "category"),
            "fingerprints": sorted({f["fingerprint"] for f in findings}),
        },
    }


def _count(items: list[dict], key: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for it in items:
        out[it.get(key, "?")] = out.get(it.get(key, "?"), 0) + 1
    return out
