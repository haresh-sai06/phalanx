"""Discovery benchmark against an unseen vulnerable app (OWASP Juice Shop).

Scores generic / LLM modes against benchmarks/juice_shop/ground_truth.json.
Does NOT use RideLite planted-bug seeds.
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from phalanx.graph import run_audit  # noqa: E402
from phalanx.report import write_report  # noqa: E402

GT_PATH = ROOT / "benchmarks" / "juice_shop" / "ground_truth.json"


def _wait_http(url: str, timeout: float = 60.0) -> None:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status == 200:
                    return
        except Exception as exc:
            last = exc
            time.sleep(0.5)
    raise RuntimeError(f"target not ready at {url}: {last}")


def score(findings: list[dict], planted: list[dict]) -> dict:
    planted_fps = {b["fingerprint"] for b in planted if b.get("in_scope", True)}
    found_fps = {f["fingerprint"] for f in findings}
    # Also accept prefix / alias matches listed on GT entries
    tp = sorted(planted_fps & found_fps)
    fn = sorted(planted_fps - found_fps)
    fp = sorted(found_fps - planted_fps)
    precision = len(tp) / len(found_fps) if found_fps else 0.0
    recall = len(tp) / len(planted_fps) if planted_fps else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "planted": len(planted_fps),
        "found": len(found_fps),
        "true_positives": tp,
        "false_negatives": fn,
        "false_positives": fp,
        "bugs_found_out_of_planted": f"{len(tp)}/{len(planted_fps)}",
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
    }


def run(
    base_url: str,
    mode: str = "generic",
    max_steps: int = 50,
    out_dir: str | Path = "benchmarks/results-juice",
) -> dict:
    planted = json.loads(GT_PATH.read_text(encoding="utf-8"))
    _wait_http(base_url.rstrip("/") + "/")
    result = run_audit(base_url, max_steps=max_steps, mode=mode, headless=True)
    summary = score(result["findings"], planted)
    summary.update({
        "mode": mode,
        "base_url": base_url,
        "steps": result["steps"],
        "visited_count": len(result["visited"]),
        "notes": result.get("notes", []),
        "all_fingerprints": sorted({f["fingerprint"] for f in result["findings"]}),
        "target": "owasp-juice-shop",
        "ground_truth": str(GT_PATH.relative_to(ROOT)),
    })
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    write_report(result, out)
    (out / "discovery.json").write_text(
        json.dumps({"summary": summary, "audit": result, "ground_truth": planted}, indent=2),
        encoding="utf-8",
    )
    md = [
        f"# Phalanx discovery — Juice Shop ({mode})",
        "",
        f"- Target: `{base_url}`",
        f"- Mode: `{mode}` (generic probes; NOT RideLite regression seeds)",
        f"- In-scope GT bugs found: **{summary['bugs_found_out_of_planted']}**",
        f"- Precision: {summary['precision']} · Recall: {summary['recall']} · F1: {summary['f1']}",
        f"- Steps: {summary['steps']} · URLs visited: {summary['visited_count']}",
        "",
        "## True positives",
        "",
    ]
    by_fp = {b["fingerprint"]: b for b in planted}
    for fp in summary["true_positives"]:
        b = by_fp[fp]
        md.append(f"- `{fp}` — {b['title']} ({b.get('challenge_key') or 'n/a'})")
    md += ["", "## False negatives (missed)", ""]
    for fp in summary["false_negatives"]:
        b = by_fp[fp]
        md.append(f"- `{fp}` — {b['title']}")
    md += ["", "## False positives (extra findings vs GT)", ""]
    if summary["false_positives"]:
        for fp in summary["false_positives"]:
            md.append(f"- `{fp}`")
    else:
        md.append("_None._")
    (out / "discovery.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--url", default=os.getenv("JUICE_SHOP_URL", "http://127.0.0.1:3000"))
    p.add_argument("--mode", choices=["generic", "llm"], default="generic")
    p.add_argument("--max-steps", type=int, default=50)
    p.add_argument("--out", default="benchmarks/results-juice")
    args = p.parse_args(argv)
    summary = run(args.url, mode=args.mode, max_steps=args.max_steps, out_dir=args.out)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
