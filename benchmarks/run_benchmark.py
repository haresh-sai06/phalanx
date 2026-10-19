"""Score Phalanx against the planted bugs in demo_app/planted_bugs.json."""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from phalanx.graph import run_audit  # noqa: E402
from phalanx.report import write_report  # noqa: E402


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_http(url: str, timeout: float = 15.0) -> None:
    import urllib.request
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as r:
                if r.status == 200:
                    return
        except Exception:
            time.sleep(0.2)
    raise RuntimeError(f"demo app did not become ready at {url}")


def run(mode: str = "heuristic", max_steps: int = 40, out_dir: str | Path = "benchmarks/results") -> dict:
    planted = json.loads((ROOT / "demo_app" / "planted_bugs.json").read_text(encoding="utf-8"))
    planted_fps = {b["fingerprint"] for b in planted}

    port = _free_port()
    env = {**os.environ, "PORT": str(port)}
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "demo_app" / "app.py")],
        cwd=str(ROOT), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        _wait_http(base + "/api/health")
        result = run_audit(base, max_steps=max_steps, mode=mode, headless=True)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

    found_fps = {f["fingerprint"] for f in result["findings"]}
    tp = sorted(planted_fps & found_fps)
    fn = sorted(planted_fps - found_fps)
    fp = sorted(found_fps - planted_fps)
    precision = len(tp) / len(found_fps) if found_fps else 0.0
    recall = len(tp) / len(planted_fps) if planted_fps else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0

    summary = {
        "mode": mode,
        "planted": len(planted_fps),
        "found": len(found_fps),
        "true_positives": tp,
        "false_negatives": fn,
        "false_positives": fp,
        "bugs_found_out_of_planted": f"{len(tp)}/{len(planted_fps)}",
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "steps": result["steps"],
        "visited_count": len(result["visited"]),
    }
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    write_report(result, out)
    (out / "benchmark.json").write_text(json.dumps({"summary": summary, "audit": result}, indent=2), encoding="utf-8")
    (out / "benchmark.md").write_text(_md(summary, planted), encoding="utf-8")
    return summary


def _md(summary: dict, planted: list) -> str:
    lines = [
        "# Phalanx benchmark",
        "",
        f"- Mode: `{summary['mode']}`",
        f"- Bugs found: **{summary['bugs_found_out_of_planted']}**",
        f"- Precision: {summary['precision']} · Recall: {summary['recall']} · F1: {summary['f1']}",
        f"- Steps: {summary['steps']} · URLs visited: {summary['visited_count']}",
        "",
        "## True positives",
        "",
    ]
    by_fp = {b["fingerprint"]: b for b in planted}
    for fp in summary["true_positives"]:
        b = by_fp[fp]
        lines.append(f"- `{fp}` — {b['title']} ({b['severity']}/{b['severity']})")
    lines += ["", "## False negatives (missed)", ""]
    for fp in summary["false_negatives"]:
        b = by_fp[fp]
        lines.append(f"- `{fp}` — {b['title']}")
    lines += ["", "## False positives", ""]
    if summary["false_positives"]:
        for fp in summary["false_positives"]:
            lines.append(f"- `{fp}`")
    else:
        lines.append("_None._")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
