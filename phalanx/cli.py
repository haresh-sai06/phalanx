"""CLI entry points: `python -m phalanx.cli audit|benchmark`."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .graph import run_audit
from .report import write_report


def cmd_audit(args: argparse.Namespace) -> int:
    result = run_audit(args.url, max_steps=args.max_steps, mode=args.mode, headless=not args.headed)
    out = write_report(result, args.out)
    print(json.dumps(result["summary"], indent=2))
    print(f"report -> {out}", file=sys.stderr)
    return 0


def cmd_benchmark(args: argparse.Namespace) -> int:
    from benchmarks.run_benchmark import run as run_bench
    summary = run_bench(mode=args.mode, max_steps=args.max_steps, out_dir=args.out)
    print(json.dumps(summary, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="phalanx", description="Phalanx multi-persona QA / security swarm")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("audit", help="audit a running app")
    a.add_argument("url")
    a.add_argument("--mode", choices=["heuristic", "regression", "generic", "llm"], default="heuristic")
    a.add_argument("--max-steps", type=int, default=40)
    a.add_argument("--out", default="reports/latest")
    a.add_argument("--headed", action="store_true")
    a.set_defaults(func=cmd_audit)

    b = sub.add_parser("benchmark", help="run against the planted-bug demo app")
    b.add_argument("--mode", choices=["heuristic", "regression", "generic", "llm"], default="heuristic")
    b.add_argument("--max-steps", type=int, default=40)
    b.add_argument("--out", default="benchmarks/results")
    b.set_defaults(func=cmd_benchmark)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
