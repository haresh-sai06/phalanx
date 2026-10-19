"""Discovery benchmark against an unseen vulnerable app (OWASP Juice Shop).

Scores generic / LLM modes against the OFFICIAL Juice Shop challenge list in
benchmarks/juice_shop/official_challenges.json (scoped to black-box, unauth,
single-step challenges). Generic mode uses ONLY the app-agnostic wordlist in
benchmarks/wordlists/common_paths.txt plus generic SQLi/XSS payload families —
no target-specific paths.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from phalanx.graph import run_audit  # noqa: E402
from phalanx.report import write_report  # noqa: E402

OFFICIAL = ROOT / "benchmarks" / "juice_shop" / "official_challenges.json"


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


def score(findings: list[dict], challenges: list[dict]) -> dict:
    found_fps = {f["fingerprint"] for f in findings}
    tp_keys, fn_keys = [], []
    matched_fps: set[str] = set()
    for ch in challenges:
        mapped = set(ch.get("map_fingerprints") or [])
        hit = mapped & found_fps
        if hit:
            tp_keys.append(ch["key"])
            matched_fps |= hit
        else:
            fn_keys.append(ch["key"])
    # Findings that matched no scoped challenge are false positives.
    fp_fps = sorted(found_fps - matched_fps)
    tp, fn, fp = len(tp_keys), len(fn_keys), len(fp_fps)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {
        "scoped_challenges": len(challenges),
        "true_positives": sorted(tp_keys),
        "false_negatives": sorted(fn_keys),
        "false_positives": fp_fps,
        "challenges_found": f"{tp}/{len(challenges)}",
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
    }


def run(base_url: str, mode: str = "generic", max_steps: int = 60,
        out_dir: str | Path = "benchmarks/results-juice") -> dict:
    spec = json.loads(OFFICIAL.read_text(encoding="utf-8"))
    challenges = spec["challenges"]
    _wait_http(base_url.rstrip("/") + "/")
    result = run_audit(base_url, max_steps=max_steps, mode=mode, headless=True)
    summary = score(result["findings"], challenges)
    summary.update({
        "mode": mode,
        "base_url": base_url,
        "steps": result["steps"],
        "visited_count": len(result["visited"]),
        "all_fingerprints": sorted({f["fingerprint"] for f in result["findings"]}),
        "notes": result.get("notes", [])[:20],
        "target": spec["target"],
        "official_list": str(OFFICIAL.relative_to(ROOT)),
        "wordlist": "benchmarks/wordlists/common_paths.txt",
    })
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    write_report(result, out)
    (out / "discovery.json").write_text(
        json.dumps({"summary": summary, "audit": result}, indent=2), encoding="utf-8")
    by_key = {c["key"]: c for c in challenges}
    md = [
        f"# Phalanx discovery — Juice Shop ({mode})",
        "",
        f"- Target: `{base_url}` — {spec['target']}",
        f"- Mode: `{mode}` — app-agnostic wordlist `{summary['wordlist']}` + generic SQLi/XSS; no target-specific paths",
        f"- Official scoped challenges: **{summary['challenges_found']}** found",
        f"- Precision: {summary['precision']} · Recall: {summary['recall']} · F1: {summary['f1']}",
        f"- Steps: {summary['steps']} · URLs visited: {summary['visited_count']}",
        "",
        "## Found (true positives)",
        "",
    ]
    for k in summary["true_positives"]:
        c = by_key[k]
        md.append(f"- `{k}` — {c['name']} ({c['category']})")
    md += ["", "## Missed (false negatives)", ""]
    for k in summary["false_negatives"]:
        c = by_key[k]
        md.append(f"- `{k}` — {c['name']} ({c['category']}) — {c['reach']}")
    md += ["", "## Unmapped findings (false positives)", ""]
    md += ([f"- `{fp}`" for fp in summary["false_positives"]] or ["_None._"])
    (out / "discovery.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return summary


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--url", default=os.getenv("JUICE_SHOP_URL", "http://127.0.0.1:3000"))
    p.add_argument("--mode", choices=["generic", "llm"], default="generic")
    p.add_argument("--max-steps", type=int, default=60)
    p.add_argument("--out", default="benchmarks/results-juice")
    a = p.parse_args(argv)
    print(json.dumps(run(a.url, mode=a.mode, max_steps=a.max_steps, out_dir=a.out), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
