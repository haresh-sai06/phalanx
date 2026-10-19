"""LangGraph agent loop for Phalanx.

``run_audit`` drives the *compiled* LangGraph graph (conditional edges, phase
state, stop conditions). The Playwright session is held outside graph state
(LangGraph may copy state between nodes) and looked up by ``run_id``.

Modes
-----
* ``regression`` / ``heuristic`` — seeds targeted at RideLite planted bugs.
  Honest label: this is a **regression suite**, not discovery.
* ``generic`` — non-targeted probes (common paths, form fuzzing, API GETs).
  Used for discovery benchmarks on unseen apps (e.g. Juice Shop).
* ``llm`` — same graph; ``plan`` asks an OpenAI-compatible model for the next
  path. Falls back silently if the endpoint is unreachable.
"""
from __future__ import annotations

import json
import os
import re
import uuid
from typing import Any, TypedDict
from urllib.parse import quote, urlparse

from .browser import BrowserSession
from .detectors import XSS_PAYLOAD, SQLI_PAYLOAD, detect_all
from .models import Finding

try:
    from langgraph.graph import END, StateGraph

    HAS_LANGGRAPH = True
except ImportError:  # pragma: no cover
    HAS_LANGGRAPH = False
    END = "END"

    class StateGraph:  # type: ignore
        def __init__(self, *_a, **_k):
            raise ImportError("langgraph is required")


# Ephemeral session registry — not part of serialisable graph state.
_SESSIONS: dict[str, BrowserSession] = {}


class GraphState(TypedDict, total=False):
    base_url: str
    max_steps: int
    mode: str  # regression | heuristic | generic | llm
    phase: str  # crawl | personas | idor | drain | done
    visited: list[str]
    queue: list[str]
    findings: list[dict]
    step: int
    notes: list[str]
    known_rides: list[int]
    current_user: str | None
    done: bool
    personas_done: int
    idor_done: bool
    run_id: str
    fuzzed_forms: list[str]


SEED_USERS = [
    ("alice", "alice123"),
    ("bob", "bob123"),
]


def _session(state: GraphState) -> BrowserSession:
    return _SESSIONS[state["run_id"]]


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


def _regression_seeds(base: str) -> list[str]:
    """Targeted seeds for the RideLite planted-bug regression suite."""
    return [
        base + "/",
        base + "/login",
        base + "/estimate",
        base + "/search",
        base + "/help",  # B1
        base + "/admin",  # B6/B7
        base + f"/estimate?q={quote(XSS_PAYLOAD)}",  # B8
        base + f"/search?q={quote(SQLI_PAYLOAD)}",  # B9
        base + "/api/rides/1",  # B11
    ]


def _generic_seeds(base: str) -> list[str]:
    """Non-targeted discovery seeds — no knowledge of a specific app's bugs."""
    common = [
        "/",
        "/login",
        "/signin",
        "/admin",
        "/administrator",
        "/api",
        "/api/users",
        "/api/v1",
        "/api/v1/users",
        "/rest",
        "/rest/products/search?q=test",
        "/rest/user/login",
        "/graphql",
        "/swagger.json",
        "/openapi.json",
        "/robots.txt",
        "/ftp",
        "/metrics",
        "/actuator",
        "/.env",
        "/#/",
        "/#/login",
        "/#/search",
        "/#/administration",
        "/#/score-board",
    ]
    return [base + p if not p.startswith("http") else p for p in common]


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
    state.setdefault("personas_done", 0)
    state.setdefault("idor_done", False)
    state.setdefault("fuzzed_forms", [])
    state["phase"] = "crawl"
    base = state["base_url"].rstrip("/")
    mode = state.get("mode") or "heuristic"
    if mode in ("generic",):
        state["queue"] = _generic_seeds(base)
        state["notes"] = list(state.get("notes") or []) + ["seed:generic"]
    elif mode == "llm":
        # LLM mode starts with generic seeds; planner may add more.
        state["queue"] = _generic_seeds(base)
        state["notes"] = list(state.get("notes") or []) + ["seed:generic+llm"]
    else:
        # heuristic / regression
        state["queue"] = _regression_seeds(base)
        state["notes"] = list(state.get("notes") or []) + ["seed:regression"]
    return state


def observe_node(state: GraphState) -> GraphState:
    """Pop next URL, fetch it, run detectors, optionally fuzz forms."""
    session = _session(state)
    if state.get("done") or state["step"] >= state["max_steps"]:
        state["done"] = True
        state["phase"] = "done"
        return state

    url = None
    while state["queue"]:
        cand = state["queue"].pop(0)
        if cand not in state["visited"]:
            url = cand
            break
    if url is None:
        # nothing left to crawl in this phase
        return state

    snap = session.goto(url)
    state["visited"] = list(state["visited"]) + [url]
    state["step"] = state["step"] + 1

    path = urlparse(url).path
    if "/api/" in url or "/rest/" in url:
        status, body = session.request_api(url if url.startswith("http") else path)
        if status == 200 and body:
            low = body.lower()
            # Generic unauthenticated data exposure heuristics
            if any(k in low for k in ('"password"', '"email"', '"owner"', '"creditcard"', '"card"')):
                # Keep stable regression fingerprint for /api/rides/<id>
                if re.match(r"/api/rides/\d+$", path):
                    fp = "idor:api-ride"
                    title = "Unauthenticated JSON IDOR on /api/rides/<id>"
                else:
                    fp = f"idor:api:{path}"
                    title = f"Unauthenticated JSON data exposure on {path}"
                _add(
                    state,
                    [
                        Finding(
                            title=title,
                            category="security",
                            severity="high",
                            url=url,
                            evidence=body[:300],
                            fingerprint=fp,
                            persona=state.get("current_user") or "anon",
                            repro_steps=[f"GET {url} with no/minimal auth"],
                            cvss_hint=7.5,
                        )
                    ],
                )
            # Juice-shop-style SQLi on product search returns unexpected volume / error
            if "sqlite" in low or "sequelize" in low or "syntax error" in low:
                _add(
                    state,
                    [
                        Finding(
                            title=f"SQL error leaked on {path}",
                            category="security",
                            severity="high",
                            url=url,
                            evidence=body[:300],
                            fingerprint=f"sqli:{path}",
                            persona="anon",
                            repro_steps=[f"GET {url}"],
                            cvss_hint=8.0,
                        )
                    ],
                )

    findings = detect_all(
        snap,
        persona=state.get("current_user") or "anon",
        current_user=state.get("current_user"),
    )
    _add(state, findings)

    # Generic form fuzzing (XSS / SQLi) — once per form action
    mode = state.get("mode") or "heuristic"
    if mode in ("generic", "llm") and snap.forms:
        fuzzed = set(state.get("fuzzed_forms") or [])
        for i, form in enumerate(snap.forms):
            action = form.get("action") or snap.url
            if action in fuzzed:
                continue
            fuzzed.add(action)
            # XSS probe
            xss_vals = {
                (f.get("name") or f"f{i}"): XSS_PAYLOAD
                for f in form.get("fields") or []
                if f.get("name") and (f.get("type") or "text") not in ("hidden", "submit", "password", "number")
            }
            if xss_vals:
                session.goto(snap.url)
                try:
                    snap2 = session.fill_and_submit(i, xss_vals)
                    _add(state, detect_all(snap2, persona="fuzz", current_user=state.get("current_user")))
                except Exception as exc:
                    state["notes"] = list(state["notes"]) + [f"fuzz-xss-fail:{exc}"]
            # SQLi probe on first text field
            sqli_vals = {}
            for f in form.get("fields") or []:
                name = f.get("name")
                typ = (f.get("type") or "text").lower()
                if name and typ not in ("hidden", "submit", "button"):
                    sqli_vals[name] = SQLI_PAYLOAD if typ != "password" else SQLI_PAYLOAD
            if sqli_vals:
                session.goto(snap.url)
                try:
                    snap3 = session.fill_and_submit(i, sqli_vals)
                    _add(state, detect_all(snap3, persona="fuzz", current_user=state.get("current_user")))
                except Exception as exc:
                    state["notes"] = list(state["notes"]) + [f"fuzz-sqli-fail:{exc}"]
        state["fuzzed_forms"] = sorted(fuzzed)

    # Also try XSS/SQLi as query params on search-like pages (generic)
    if mode in ("generic", "llm"):
        parsed = urlparse(url)
        if "q=" not in url and any(k in parsed.path.lower() for k in ("search", "estimate", "query", "find")):
            for payload, label in ((XSS_PAYLOAD, "xss"), (SQLI_PAYLOAD, "sqli")):
                probe = url + ("&" if "?" in url else "?") + f"q={quote(payload)}"
                if probe not in state["visited"] and probe not in state["queue"]:
                    state["queue"] = list(state["queue"]) + [probe]

    for link in snap.links:
        if link not in state["visited"] and link not in state["queue"]:
            # cap queue growth
            if len(state["queue"]) < 80:
                state["queue"].append(link)
    return state


def login_persona_node(state: GraphState) -> GraphState:
    """Log in as the next seed user and book a ride so IDOR probes have data."""
    session = _session(state)
    used = {n.split(":", 1)[-1] for n in state["notes"] if n.startswith("logged:")}
    nxt = next(((u, p) for u, p in SEED_USERS if u not in used), None)
    if nxt is None:
        state["phase"] = "idor"
        return state
    user, pw = nxt
    session.goto("/logout")
    snap = session.goto("/login")
    snap = session.fill_and_submit(0, {"username": user, "password": pw})
    state["current_user"] = user
    state["notes"] = list(state["notes"]) + [f"logged:{user}"]
    state["personas_done"] = int(state.get("personas_done") or 0) + 1
    _add(state, detect_all(snap, persona=user, current_user=user))

    # book a ride (RideLite-shaped apps); ignore failures on other apps
    session.goto("/book")
    snap = session.fill_and_submit(0, {"pickup": f"{user}-Pickup", "dropoff": f"{user}-Drop"})
    m = re.search(r"/rides/(\d+)", snap.url)
    if m:
        rid = int(m.group(1))
        state["known_rides"] = list(state["known_rides"]) + [rid]
        base = state["base_url"].rstrip("/")
        state["queue"] = list(state["queue"]) + [
            base + "/rides",
            base + f"/rides/{rid}",
            base + f"/api/rides/{rid}",
        ]
        session.goto(f"/rides/{m.group(1)}")
        try:
            snap = session.fill_and_submit(1, {"amount": "-100"})
            _add(state, detect_all(snap, persona=user, current_user=user))
        except Exception as exc:
            state["notes"] = list(state["notes"]) + [f"tip-failed:{exc}"]

    snap = session.goto("/profile?saved=1&next=https://evil.example/phalanx")
    _add(state, detect_all(snap, persona=user, current_user=user))
    # return to base so later gotos aren't stuck on evil.example
    session.goto("/")
    return state


def cross_persona_idor_node(state: GraphState) -> GraphState:
    """Log in as bob and hit alice's ride IDs (and cancel one)."""
    session = _session(state)
    rides = list(state.get("known_rides") or [])
    state["idor_done"] = True
    state["phase"] = "drain"
    if not rides:
        return state
    session.goto("/logout")
    session.goto("/login")
    session.fill_and_submit(0, {"username": "bob", "password": "bob123"})
    state["current_user"] = "bob"
    state["notes"] = list(state["notes"]) + ["logged:bob-idor"]

    snap = session.goto("/rides")
    _add(state, detect_all(snap, persona="bob", current_user="bob"))

    target = rides[0]
    snap = session.goto(f"/rides/{target}")
    _add(state, detect_all(snap, persona="bob", current_user="bob"))
    try:
        snap = session.click_selector("form[action*='cancel'] button")
        if "cancelled" in snap.text.lower():
            _add(
                state,
                [
                    Finding(
                        title="Any user can cancel another user's ride",
                        category="security",
                        severity="high",
                        url=snap.url,
                        evidence=f"bob cancelled ride #{target}; page now shows status=cancelled",
                        fingerprint="idor:cancel",
                        persona="bob",
                        repro_steps=["Log in as bob", f"POST /rides/{target}/cancel"],
                        cvss_hint=7.1,
                    )
                ],
            )
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
        "to visit (e.g. /admin or /rest/products/search?q=test or /#/search). "
        "Prefer paths that look like admin panels, search, login, API, or file dumps. "
        "Reply with ONLY the path.\n\n"
        f"Visited: {state.get('visited', [])[-12:]}\n"
        f"Findings so far: {[f.get('fingerprint') for f in state.get('findings', [])]}\n"
        f"Notes: {state.get('notes', [])[-5:]}\n"
    )
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=40,
        )
        text = (resp.choices[0].message.content or "").strip().split()[0]
        if text.startswith("/") or text.startswith("http") or text.startswith("#"):
            if text.startswith("#"):
                text = "/" + text
            return text.rstrip(".,;)`\"'")
    except Exception:
        return None
    return None


def advance_phase_node(state: GraphState) -> GraphState:
    """Move crawl → personas → idor → drain → done based on queue / progress."""
    if state.get("done") or state["step"] >= state["max_steps"]:
        state["done"] = True
        state["phase"] = "done"
        return state
    phase = state.get("phase") or "crawl"
    mode = state.get("mode") or "heuristic"
    # Generic/LLM discovery on non-RideLite apps: skip RideLite persona choreography
    # unless we already know rides exist or mode is regression/heuristic.
    skip_personas = mode in ("generic", "llm") and not any(
        n.startswith("seed:regression") for n in state.get("notes") or []
    )
    if phase == "crawl":
        if state.get("queue"):
            return state
        if skip_personas:
            state["phase"] = "done"
            state["done"] = True
        else:
            state["phase"] = "personas"
        return state
    if phase == "personas":
        if int(state.get("personas_done") or 0) < len(SEED_USERS):
            return state
        state["phase"] = "idor"
        return state
    if phase == "idor":
        if not state.get("idor_done"):
            return state
        state["phase"] = "drain"
        return state
    if phase == "drain":
        if state.get("queue") and state["step"] < state["max_steps"]:
            return state
        state["phase"] = "done"
        state["done"] = True
        return state
    state["done"] = True
    state["phase"] = "done"
    return state


def route_after_advance(state: GraphState) -> str:
    if state.get("done") or state.get("phase") == "done" or state["step"] >= state["max_steps"]:
        return "end"
    phase = state.get("phase") or "crawl"
    if phase == "crawl":
        if state.get("queue"):
            return "observe"
        return "advance"  # should have flipped phase; loop once more
    if phase == "personas":
        return "login_persona"
    if phase == "idor":
        return "cross_persona_idor"
    if phase == "drain":
        if state.get("queue"):
            return "observe"
        return "end"
    return "end"


def route_after_observe(state: GraphState) -> str:
    if state.get("done") or state["step"] >= state["max_steps"]:
        return "end"
    return "plan"


def build_graph():
    g = StateGraph(GraphState)
    g.add_node("start", start_node)
    g.add_node("observe", observe_node)
    g.add_node("plan", plan_node)
    g.add_node("advance", advance_phase_node)
    g.add_node("login_persona", login_persona_node)
    g.add_node("cross_persona_idor", cross_persona_idor_node)

    g.set_entry_point("start")
    g.add_edge("start", "observe")
    g.add_conditional_edges("observe", route_after_observe, {"plan": "plan", "end": END})
    g.add_edge("plan", "advance")
    g.add_conditional_edges(
        "advance",
        route_after_advance,
        {
            "observe": "observe",
            "login_persona": "login_persona",
            "cross_persona_idor": "cross_persona_idor",
            "advance": "advance",
            "end": END,
        },
    )
    g.add_edge("login_persona", "advance")
    g.add_edge("cross_persona_idor", "advance")
    return g.compile()


def run_audit(
    base_url: str,
    max_steps: int = 40,
    mode: str = "heuristic",
    headless: bool = True,
) -> dict:
    """Run one full audit via the compiled LangGraph graph."""
    if not HAS_LANGGRAPH:
        raise ImportError("langgraph is required to run Phalanx audits")
    graph = build_graph()
    run_id = uuid.uuid4().hex
    with BrowserSession(base_url, headless=headless) as session:
        _SESSIONS[run_id] = session
        try:
            init: GraphState = {
                "base_url": base_url.rstrip("/"),
                "max_steps": max_steps,
                "mode": mode,
                "phase": "crawl",
                "visited": [],
                "queue": [],
                "findings": [],
                "step": 0,
                "notes": [],
                "known_rides": [],
                "current_user": None,
                "done": False,
                "personas_done": 0,
                "idor_done": False,
                "run_id": run_id,
                "fuzzed_forms": [],
            }
            # Recursion limit: each URL ≈ observe→plan→advance cycle.
            state = graph.invoke(init, config={"recursion_limit": max(100, max_steps * 6)})
        finally:
            _SESSIONS.pop(run_id, None)

    findings = _dedup(state.get("findings") or [])
    return {
        "base_url": base_url,
        "mode": mode,
        "steps": state.get("step", 0),
        "visited": state.get("visited", []),
        "notes": state.get("notes", []),
        "phase": state.get("phase"),
        "findings": findings,
        "summary": {
            "total": len(findings),
            "by_severity": _count(findings, "severity"),
            "by_category": _count(findings, "category"),
            "fingerprints": sorted({f["fingerprint"] for f in findings}),
            "graph_driven": True,
        },
    }


def _count(items: list[dict], key: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for it in items:
        out[it.get(key, "?")] = out.get(it.get(key, "?"), 0) + 1
    return out
