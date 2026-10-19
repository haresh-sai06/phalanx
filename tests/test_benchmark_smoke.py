"""End-to-end smoke: regression (heuristic) mode must find most planted bugs.

Retries once on Playwright navigation flakes so CI stays green after the
browser-layer stabilisation (wait_for_load_state + retries + re-acquire).
"""
from __future__ import annotations

import pytest

from benchmarks.run_benchmark import run


def _run_once(out_dir: str) -> dict:
    return run(mode="heuristic", max_steps=40, out_dir=out_dir)


def test_heuristic_benchmark_finds_at_least_10_of_12(tmp_path):
    last_err: Exception | None = None
    summary = None
    for attempt in range(2):
        try:
            summary = _run_once(str(tmp_path / f"attempt-{attempt}"))
            break
        except Exception as exc:  # noqa: BLE001 — surface after retry
            last_err = exc
    if summary is None:
        pytest.fail(f"benchmark crashed twice; last error: {last_err}")
    assert summary["planted"] == 12
    assert len(summary["true_positives"]) >= 10, summary
    assert summary["precision"] >= 0.8, summary
    assert summary.get("bugs_found_out_of_planted", "").startswith(("10", "11", "12"))


def test_run_audit_is_graph_driven():
    """Guardrail: run_audit must invoke the compiled LangGraph (not a fixed for-loop)."""
    import socket, subprocess, sys, time, os, urllib.request
    from pathlib import Path
    from phalanx.graph import run_audit, HAS_LANGGRAPH

    assert HAS_LANGGRAPH
    root = Path(__file__).resolve().parents[1]
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = {**os.environ, "PORT": str(port)}
    proc = subprocess.Popen(
        [sys.executable, str(root / "demo_app" / "app.py")],
        cwd=str(root),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.time() + 15
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(base + "/api/health", timeout=1) as r:
                    if r.status == 200:
                        break
            except Exception:
                time.sleep(0.2)
        result = run_audit(base, max_steps=40, mode="heuristic", headless=True)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
    assert result["summary"].get("graph_driven") is True
    assert result["steps"] > 0
    fps = set(result["summary"]["fingerprints"])
    assert "xss:estimate" in fps
    assert "authz:admin-open" in fps
